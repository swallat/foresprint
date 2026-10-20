# SPDX-License-Identifier: EUPL-1.2
"""Anmeldung am Git-Server per Zugriffstoken (https), geführt von der App.

Die App speichert den Token nie selbst: Sie reicht ihn einmal mit ``git credential approve`` an
den Anmeldedienst von Git weiter (Credential Manager, Schlüsselbund, libsecret …), schreibt ihn
in keine Datei und kein Protokoll und zeigt ihn nie wieder an. Ein Klartext-Speicher
(``credential.helper store``) wird weder gesetzt noch zum Ablegen benutzt. SSH-Schlüssel erzeugt
die App nicht.
"""

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import git as gitmod
from .git import GitError, _git, _git_result, credential_helpers, parse_remote_url, probe_remote
from .gitsync import cached_remote_info, git_available
from .i18n import t

# Anmeldedienste, bei denen ``git credential approve`` ein Geheimnis verschlüsselt ablegt.
# Alles Unbekannte („custom“) ist erlaubt (Sache des Rechners), ``store`` nie.
_PLAIN_TEXT = {"store"}
# Mehr Zeit als ein Anmeldedienst braucht (Windows startet ihn kalt).
HELPER_TIMEOUT = 30.0
MAX_TOKEN_LENGTH = 4096


@dataclass(frozen=True)
class HostGuide:
    """Wie man bei einem Hoster einen Token anlegt; ``username`` ist die Vorgabe für das Feld
    (leer = die Person trägt ihren Benutzernamen ein)."""

    kind: str
    username: str
    steps: str


def host_guide(kind: str) -> HostGuide:
    """Anleitung je Art des Servers (``gitsync.HOST_*``); Unbekanntes bekommt die allgemeine."""
    if kind == "gitlab":
        return HostGuide(
            kind,
            "oauth2",
            t(
                "GitLab: Im Projekt (oder in den eigenen Einstellungen) unter „Zugriffstoken“ "
                "einen Token anlegen, Rolle „Developer“ oder höher und das Recht "
                "„write_repository“. Den Token einmal kopieren."
            ),
        )
    if kind == "github":
        return HostGuide(
            kind,
            "x-access-token",
            t(
                "GitHub: Unter Settings › Developer settings › Personal access tokens einen "
                "fine-grained Token für dieses Repository anlegen, Recht „Contents: Read and "
                "write“. Den Token einmal kopieren."
            ),
        )
    if kind == "forgejo":
        return HostGuide(
            kind,
            "",
            t(
                "Forgejo/Gitea/Codeberg: Unter Einstellungen › Anwendungen einen Zugangstoken "
                "mit dem Recht „write:repository“ anlegen. Benutzername ist der eigene "
                "Kontoname."
            ),
        )
    return HostGuide(
        kind,
        "",
        t(
            "Beim Server einen Zugangstoken (Personal Access Token) mit Lese- und "
            "Schreibrecht auf das Repository anlegen und den Benutzernamen eintragen, den der "
            "Server dafür vorsieht."
        ),
    )


def https_parts(url: str) -> tuple[str, str]:
    """``(host, pfad)`` einer https-Adresse für den Anmeldedienst. Andere Adressen (SSH, Ordner,
    http) sind hier nicht gemeint: :class:`GitError`."""
    problem = GitError(
        t("Die Token-Anmeldung gilt nur für https-Adressen ohne Zugangsdaten in der Adresse.")
    )
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise problem
        parts.port  # noqa: B018  (wirft ValueError bei einem ungültigen Port)
    except ValueError as e:
        raise problem from e
    return parts.netloc, parts.path.lstrip("/")


def is_https(url: str) -> bool:
    try:
        https_parts(url)
    except GitError:
        return False
    return True


def _credential_input(url: str, username: str = "", token: str = "") -> str:
    """Eingabe für ``git credential``: Zeilen ``schlüssel=wert``, am Ende eine Leerzeile."""
    host, path = https_parts(url)
    lines = ["protocol=https", f"host={host}"]
    if path:
        lines.append(f"path={path}")
    if username:
        lines.append(f"username={username}")
    if token:
        lines.append(f"password={token}")
    return "\n".join(lines) + "\n\n"


def _clean(value: str, what: str) -> str:
    value = value.strip()
    if not value or any(ch in value for ch in "\r\n\0"):
        raise GitError(t("Bitte {what} eintragen (ohne Zeilenumbruch).", what=what))
    return value


# --- Anmeldedienst -------------------------------------------------------------------------


def _helper_exists(name: str) -> bool:
    """Gibt es ``git-credential-<name>`` im PATH oder im Ordner der Git-Programme?"""
    command = f"git-credential-{name}"
    if shutil.which(command):
        return True
    try:
        out = _git_result(Path.home(), "--exec-path", timeout=10).stdout.strip()
    except GitError, OSError:
        return False
    folder = Path(out) if out else None
    return bool(folder and any((folder / (command + ext)).exists() for ext in ("", ".exe", ".cmd")))


def suggested_helper() -> str | None:
    """Der Anmeldedienst, den die App für diesen Rechner anbieten darf, oder ``None`` (dann nur
    Hinweise). Windows: ``manager`` (Git Credential Manager), macOS: ``osxkeychain``, Linux:
    ``libsecret`` bzw. ``manager``, wenn der Helfer vorhanden ist. Nie ``store``."""
    if sys.platform == "win32":
        candidates = ["manager", "wincred"]
    elif sys.platform == "darwin":
        candidates = ["osxkeychain", "manager"]
    else:
        candidates = ["libsecret", "manager"]
    return next((name for name in candidates if _helper_exists(name)), None)


def enable_helper(name: str) -> None:
    """Trägt den Anmeldedienst für den Benutzer ein (``git config --global``, nie im
    Repository). Nur die Namen aus :func:`suggested_helper`; ``store`` ist ausgeschlossen."""
    if name != suggested_helper():
        raise GitError(t("Dieser Anmeldedienst wird von der App nicht eingerichtet."))
    _git(Path.home(), "config", "--global", "credential.helper", name)


def helper_state(root: Path) -> str:
    """``"none"`` (kein Dienst), ``"plain"`` (Klartext-Speicher) oder ``"ok"``."""
    names = credential_helpers(root)
    if any(name in _PLAIN_TEXT for name in names):
        return "plain"
    return "ok" if names else "none"


# --- Token speichern, prüfen, löschen ------------------------------------------------------


def store_token(root: Path, url: str, username: str, token: str) -> None:
    """Reicht den Token an den Anmeldedienst weiter (``git credential approve``). Fehlt ein
    Dienst oder ist es ein Klartext-Speicher, passiert nichts und es kommt eine
    :class:`GitError`. Der Token erscheint in keiner Meldung."""
    username = _clean(username, t("den Benutzernamen"))
    token = _clean(token, t("den Token"))
    if len(token) > MAX_TOKEN_LENGTH:
        raise GitError(t("Der Token ist zu lang."))
    state = helper_state(root)
    if state == "plain":
        raise GitError(
            t("Git legt Anmeldungen hier im Klartext ab (`credential.helper store`)."),
            "auth",
            t(
                "Das benutzt die App nicht für Token. Bitte einen Anmeldedienst des Rechners "
                "einrichten (siehe oben) und `store` entfernen."
            ),
        )
    if state == "none":
        raise GitError(
            t("Auf diesem Rechner ist noch kein Anmeldedienst von Git eingetragen."),
            "auth",
            t("Bitte zuerst den Anmeldedienst einschalten (siehe oben)."),
        )
    proc = _git_result(
        root,
        "credential",
        "approve",
        timeout=HELPER_TIMEOUT,
        stdin_text=_credential_input(url, username, token),
    )
    if proc.returncode != 0:
        # Die Ausgabe des Dienstes kann den Token nennen: nur der Rückgabecode zählt.
        raise GitError(
            t("Der Anmeldedienst von Git hat den Token nicht angenommen."),
            "auth",
            t("Anmeldedienst und Rechte des Benutzerkontos prüfen und noch einmal versuchen."),
        )


def verify(root: Path, url: str) -> tuple[str, ...]:
    """Prüft die Anmeldung mit ``git ls-remote`` (ändert nichts) und liefert die Branches.
    Fehler (abgelehnt, abgelaufen, falsches Recht) kommen mit Hinweis als :class:`GitError`."""
    return probe_remote(root, parse_remote_url(url))


def forget_token(root: Path, url: str, username: str = "", token: str = "") -> None:
    """Entfernt die gespeicherte Anmeldung aus dem Anmeldedienst (``git credential reject``).
    Mit ``username`` und ``token`` trifft es genau diesen Eintrag; ohne beides alle Anmeldungen
    dieses Servers (der Pfad der Adresse zählt bei den meisten Diensten nicht)."""
    if username:
        username = _clean(username, t("den Benutzernamen"))
    if token:
        token = _clean(token, t("den Token"))
    proc = _git_result(
        root,
        "credential",
        "reject",
        timeout=HELPER_TIMEOUT,
        stdin_text=_credential_input(url, username, token),
    )
    if proc.returncode != 0:
        raise GitError(t("Der Anmeldedienst von Git hat die Anmeldung nicht gelöscht."))


# --- Einrichtungs-Checkliste ---------------------------------------------------------------


@dataclass(frozen=True)
class SetupItem:
    key: str
    ok: bool
    detail: str
    page: str  # Seite, auf der man es erledigt ("" = keine)


def setup_items(root: Path | None) -> list[SetupItem]:
    """Lesende Prüfungen für die Checkliste auf der Startseite (ohne Netzwerk, ohne
    Rückfragen). ``root`` ist der Datenordner oder ``None``."""
    items: list[SetupItem] = []
    git_ok = git_available()
    items.append(
        SetupItem("git", git_ok, t("Git ist installiert.") if git_ok else t("Git fehlt."), "hilfe")
    )
    top = gitmod.repo_root(root) if git_ok and root is not None else None
    items.append(
        SetupItem(
            "folder",
            top is not None,
            t("Der Datenordner ist ein Git-Repository.")
            if top
            else t("Der Datenordner ist noch kein Git-Repository."),
            "datenordner",
        )
    )
    if top is None:
        return items
    try:
        info = cached_remote_info(top)
    except GitError:
        return items
    items.append(
        SetupItem(
            "server",
            info.name is not None,
            t("Ein Server ist eingetragen.")
            if info.name
            else t("Es ist noch kein Server eingetragen."),
            "datenordner",
        )
    )
    if info.name:
        if is_https(info.url):
            state = helper_state(top)
            ok = state == "ok"
            detail = (
                t("Ein Anmeldedienst ist eingetragen.")
                if ok
                else t("Für den Server fehlt noch die Anmeldung per Token.")
            )
        else:
            ok, detail = True, t("Die Adresse braucht keine Token-Anmeldung.")
        items.append(SetupItem("login", ok, detail, "datenordner"))
    name = _git(top, "config", "--get", "user.name", check=False)
    email = _git(top, "config", "--get", "user.email", check=False)
    items.append(
        SetupItem(
            "identity",
            bool(name and email),
            t("Name und E-Mail-Adresse für Änderungen sind eingetragen.")
            if name and email
            else t("Name und E-Mail-Adresse für Änderungen fehlen."),
            "datenordner",
        )
    )
    return items
