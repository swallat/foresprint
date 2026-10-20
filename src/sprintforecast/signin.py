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
                "GitLab: in the project (or in your own settings) under “Access tokens” "
                "create a token with the role “Developer” or higher and the permission "
                "“write_repository”. Copy the token once."
            ),
        )
    if kind == "github":
        return HostGuide(
            kind,
            "x-access-token",
            t(
                "GitHub: under Settings › Developer settings › Personal access tokens "
                "create a fine-grained token for this repository with the permission "
                "“Contents: Read and write”. Copy the token once."
            ),
        )
    if kind == "forgejo":
        return HostGuide(
            kind,
            "",
            t(
                "Forgejo/Gitea/Codeberg: under Settings › Applications create an access "
                "token with the permission “write:repository”. The user name is your own "
                "account name."
            ),
        )
    return HostGuide(
        kind,
        "",
        t(
            "Create an access token (personal access token) with read and write permission "
            "on the repository at the server and enter the user name the server expects "
            "for it."
        ),
    )


def https_parts(url: str) -> tuple[str, str]:
    """``(host, pfad)`` einer https-Adresse für den Anmeldedienst. Andere Adressen (SSH, Ordner,
    http) sind hier nicht gemeint: :class:`GitError`."""
    problem = GitError(
        t("Token sign-in applies only to https addresses without credentials in the address.")
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
        raise GitError(t("Please enter {what} (without a line break).", what=what))
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
        raise GitError(t("The app does not set up this credential helper."))
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
    username = _clean(username, t("the user name"))
    token = _clean(token, t("the token"))
    if len(token) > MAX_TOKEN_LENGTH:
        raise GitError(t("The token is too long."))
    state = helper_state(root)
    if state == "plain":
        raise GitError(
            t("Git stores sign-ins here in plain text (`credential.helper store`)."),
            "auth",
            t(
                "The app does not use that for tokens. Please set up a credential helper "
                "of the computer (see above) and remove `store`."
            ),
        )
    if state == "none":
        raise GitError(
            t("No Git credential helper is configured on this computer yet."),
            "auth",
            t("Please switch on the credential helper first (see above)."),
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
            t("The Git credential helper did not accept the token."),
            "auth",
            t(
                "Check the credential helper and the permissions of the user account, then "
                "try again."
            ),
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
        username = _clean(username, t("the user name"))
    if token:
        token = _clean(token, t("the token"))
    proc = _git_result(
        root,
        "credential",
        "reject",
        timeout=HELPER_TIMEOUT,
        stdin_text=_credential_input(url, username, token),
    )
    if proc.returncode != 0:
        raise GitError(t("The Git credential helper did not delete the sign-in."))


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
        SetupItem("git", git_ok, t("Git is installed.") if git_ok else t("Git is missing."), "help")
    )
    top = gitmod.repo_root(root) if git_ok and root is not None else None
    items.append(
        SetupItem(
            "folder",
            top is not None,
            t("The data folder is a Git repository.")
            if top
            else t("The data folder is not a Git repository yet."),
            "data_dir",
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
            t("A server is configured.") if info.name else t("No server is configured yet."),
            "data_dir",
        )
    )
    if info.name:
        if is_https(info.url):
            state = helper_state(top)
            ok = state == "ok"
            detail = (
                t("A credential helper is configured.")
                if ok
                else t("Token sign-in for the server is still missing.")
            )
        else:
            ok, detail = True, t("The address needs no token sign-in.")
        items.append(SetupItem("login", ok, detail, "data_dir"))
    name = _git(top, "config", "--get", "user.name", check=False)
    email = _git(top, "config", "--get", "user.email", check=False)
    items.append(
        SetupItem(
            "identity",
            bool(name and email),
            t("Name and email address for changes are set.")
            if name and email
            else t("Name and email address for changes are missing."),
            "data_dir",
        )
    )
    return items
