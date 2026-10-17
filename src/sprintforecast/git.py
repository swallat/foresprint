# SPDX-License-Identifier: EUPL-1.2
"""Kleine Git-Helfer für Commit und Sprint-Tag."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from sprintforecast.i18n import t


class GitError(Exception):
    """Fehler eines Git-Aufrufs. ``kind`` benennt die Art (siehe :func:`classify`), ``hint`` ist
    der nächste Schritt in Alltagssprache; ``str(error)`` bleibt die kurze Meldung."""

    def __init__(self, message: str, kind: str = "error", hint: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.hint = hint

    def full(self) -> str:
        """Meldung samt nächstem Schritt."""
        return f"{self} {self.hint}".strip()


# Tabellenkalkulationen dürfen nie committet werden (können echte Team-Daten enthalten).
FORBIDDEN = re.compile(r"\.xls[xm]?$", re.IGNORECASE)


# Windows: keine Konsolenfenster für Hilfsprozesse (sonst blitzt bei jedem Aufruf eines auf).
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

_ROOT_CACHE: dict[Path, tuple[float, Path | None]] = {}
_ROOT_TTL = 30.0


# Netzwerkaufrufe (fetch, push, clone) dürfen nie ewig hängen oder im Hintergrund nach einem
# Kennwort fragen: Es gibt kein Terminal, in dem man antworten könnte.
NETWORK_TIMEOUT = 90.0


def _env(network: bool) -> dict[str, str]:
    """Umgebung für Git: englische Meldungen (damit sie sich erkennen lassen) und bei
    Netzwerkaufrufen keine Rückfrage im Terminal. Anmeldehelfer (Credential Manager) laufen
    weiter."""
    env = {**os.environ, "LC_ALL": "C", "LANGUAGE": "C"}
    if network:
        env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(
    cwd: Path,
    *args: str,
    strip: bool = True,
    network: bool = False,
    check: bool = True,
    timeout: float | None = None,
) -> str:
    """Führt ``git`` aus. Bei Fehlern :class:`GitError` mit erkannter Art und nächstem Schritt;
    mit ``check=False`` wird bei Fehlern statt einer Ausnahme ein leerer Text geliefert."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=_env(network),
            timeout=timeout or (NETWORK_TIMEOUT if network else 120),
            **NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise classify("", missing=True) from e
    except subprocess.TimeoutExpired as e:
        raise classify("", timeout=True) from e
    if proc.returncode != 0:
        if not check:
            return ""
        raise classify(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip() if strip else proc.stdout


def _git_bytes(cwd: Path, *args: str) -> bytes:
    """Wie :func:`_git`, liefert aber die rohe Ausgabe (z. B. ein Archiv)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=_env(False),
            timeout=120,
            **NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise classify("", missing=True) from e
    except subprocess.TimeoutExpired as e:
        raise classify("", timeout=True) from e
    if proc.returncode != 0:
        raise classify(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


# Erkennungsmuster in der Reihenfolge der Prüfung (englische Git-Meldungen, siehe _env).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "identity",
        re.compile(
            r"tell me who you are|unable to auto-detect email|empty ident|"
            r"auto-detection is disabled",
            re.I,
        ),
    ),
    (
        "locked",
        re.compile(
            r"index\.lock|\.lock'?: File exists|unable to unlink|Device or resource busy|"
            r"being used by another process|Unable to create '.*\.lock'",
            re.I,
        ),
    ),
    (
        "auth",
        re.compile(
            r"Authentication failed|could not read Username|could not read Password|"
            r"terminal prompts disabled|Permission denied \(publickey|"
            r"Invalid username or password|The requested URL returned error: 40[13]|"
            r"HTTP Basic: Access denied|Host key verification failed|"
            r"Support for password authentication was removed",
            re.I,
        ),
    ),
    (
        "offline",
        re.compile(
            r"Could not resolve host|Failed to connect|Connection (timed out|refused|reset)|"
            r"Network is unreachable|unable to access|Operation timed out|Temporary failure in "
            r"name resolution|Could not read from remote repository|ssh: connect to host|"
            r"Connection closed by|SSL certificate problem",
            re.I,
        ),
    ),
    (
        "denied",
        re.compile(
            r"remote rejected|hook declined|protected branch|pre-receive hook|"
            r"Permission to .* denied",
            re.I,
        ),
    ),
    (
        "rejected",
        re.compile(
            r"\[rejected\]|non-fast-forward|failed to push some refs|fetch first|"
            r"Updates were rejected",
            re.I,
        ),
    ),
    (
        "merge_in_progress",
        re.compile(
            r"You have not concluded your merge|MERGE_HEAD exists|"
            r"Exiting because of an unresolved conflict|Pulling is not possible because you "
            r"have unmerged",
            re.I,
        ),
    ),
    ("conflict", re.compile(r"CONFLICT|Automatic merge failed|fix conflicts", re.I)),
    (
        "dirty",
        re.compile(
            r"would be overwritten by (merge|checkout|revert)|"
            r"Please commit your changes or stash them",
            re.I,
        ),
    ),
    ("detached", re.compile(r"You are not currently on a branch|detached HEAD", re.I)),
    (
        "no_upstream",
        re.compile(r"no tracking information|has no upstream branch|no upstream configured", re.I),
    ),
    (
        "no_remote",
        re.compile(
            r"No configured push destination|No remote repository specified|No such remote", re.I
        ),
    ),
    ("not_found", re.compile(r"Repository not found|remote: Not Found", re.I)),
]


def classify(message: str, missing: bool = False, timeout: bool = False) -> GitError:
    """Macht aus einer Git-Fehlermeldung eine :class:`GitError` mit Art und nächstem Schritt."""
    if missing:
        return GitError(
            t("git ist nicht installiert oder nicht im PATH"),
            "git_missing",
            t(
                "Git installieren (Windows: https://git-scm.com/download/win, macOS: "
                "`xcode-select --install`, Linux: Paketverwaltung) und die App neu starten."
            ),
        )
    if timeout:
        return GitError(
            t("Der Server antwortet nicht rechtzeitig."),
            "offline",
            t("Internetverbindung und VPN prüfen und später noch einmal versuchen."),
        )
    for kind, pattern in _PATTERNS:
        if pattern.search(message):
            return GitError(message or kind, kind, hint_for(kind))
    return GitError(message or t("Unbekannter Git-Fehler"), "error")


def title_for(kind: str) -> str:
    """Kurze Überschrift zu einer Fehlerart."""
    titles = {
        "git_missing": t("Git ist nicht installiert"),
        "identity": t("Name und E-Mail-Adresse fehlen"),
        "locked": t("Eine Datei ist gesperrt"),
        "auth": t("Anmeldung fehlt oder wurde abgelehnt"),
        "offline": t("Server nicht erreichbar"),
        "denied": t("Server lehnt das Hochladen ab"),
        "rejected": t("Hochladen abgelehnt, weil inzwischen etwas Neues da ist"),
        "merge_in_progress": t("Zusammenführen ist unvollständig"),
        "conflict": t("Konflikt beim Zusammenführen"),
        "invalid": t("Zusammengeführte Daten sind nicht gültig"),
        "dirty": t("Offene Änderungen außerhalb des Datenordners"),
        "detached": t("Kein Branch ausgewählt (detached HEAD)"),
        "no_upstream": t("Branch ist nicht mit dem Server verbunden"),
        "no_remote": t("Kein Server eingerichtet"),
        "not_found": t("Repository nicht gefunden"),
    }
    return titles.get(kind, t("Git-Fehler"))


def hint_for(kind: str, url: str = "") -> str:
    """Nächster Schritt in Alltagssprache zu einer Fehlerart (leer, wenn es keinen gibt)."""
    if kind == "auth":
        return auth_help(url)
    hints = {
        "identity": t(
            "Git kennt deinen Namen noch nicht. Bitte in der Seitenleiste Name und "
            "E-Mail-Adresse eintragen."
        ),
        "locked": t(
            "Eine Datei ist gesperrt, weil ein anderes Programm (Git-Client, Editor, "
            "Virenscanner, Synchronisationsdienst) sie benutzt. Andere Programme schließen und "
            "noch einmal versuchen."
        ),
        "offline": t(
            "Der Server ist nicht erreichbar. Deine Änderungen bleiben lokal gesichert; "
            "Internetverbindung bzw. VPN prüfen und später erneut „Speichern und teilen“ wählen."
        ),
        "denied": t(
            "Der Server hat das Hochladen abgelehnt, etwa wegen eines geschützten Branches "
            "oder fehlender Schreibrechte. Deine Änderungen sind lokal gesichert; bitte "
            "bei der Betreuung des Repositorys nachfragen."
        ),
        "rejected": t(
            "Jemand anderes hat inzwischen Änderungen hochgeladen. Noch einmal "
            "„Speichern und teilen“ wählen, dann werden sie zuerst übernommen."
        ),
        "merge_in_progress": t(
            "Ein Zusammenführen ist unvollständig. Es kann abgebrochen werden; die eigenen "
            "Änderungen bleiben dabei erhalten."
        ),
        "conflict": t(
            "Dieselbe Stelle wurde von zwei Personen geändert. Auf der Seite „Konflikte "
            "lösen“ je Eintrag „meine“ oder „andere“ Änderung wählen, oder das "
            "Zusammenführen abbrechen. Es ist nichts verloren."
        ),
        "invalid": t(
            "Die Zusammenführung war technisch möglich, aber die Daten sind nun fachlich "
            "ungültig (siehe Liste). Nichts wurde hochgeladen. Bitte die Werte korrigieren und "
            "erneut „Speichern und teilen“ wählen – oder bewusst „Trotzdem teilen“."
        ),
        "dirty": t(
            "Es gibt nicht gesicherte Änderungen außerhalb des Datenordners, die mit den "
            "neuen Änderungen kollidieren. Diese bitte zuerst committen oder verwerfen."
        ),
        "detached": t(
            "Das Repository steht auf keinem Branch (detached HEAD). In der Seitenleiste "
            "„Zurück auf den Branch“ wählen."
        ),
        "no_upstream": t(
            "Der Branch ist noch nicht mit dem Server verbunden. „Speichern und teilen“ "
            "richtet das beim ersten Mal ein."
        ),
        "no_remote": t(
            "Zu diesem Repository gibt es keinen Server (Remote). Unter „Datenordner“ ein "
            "bestehendes Repository klonen oder einmalig im Terminal "
            "`git remote add origin ADRESSE` ausführen."
        ),
        "not_found": t(
            "Das Repository wurde nicht gefunden oder du hast keinen Zugriff. Adresse und "
            "Berechtigung prüfen."
        ),
    }
    return hints.get(kind, "")


def auth_help(url: str = "") -> str:
    """Anmelde-Hilfe passend zur Adresse des Servers (https oder SSH)."""
    if url.startswith(("git@", "ssh://")):
        return t(
            "Die Anmeldung per SSH fehlt oder wurde abgelehnt. Einen SSH-Schlüssel anlegen "
            "(`ssh-keygen -t ed25519`), den öffentlichen Teil (Datei `.pub`) beim Server "
            "(GitHub, GitLab …) unter „SSH-Schlüssel“ hinterlegen und den Schlüssel im "
            "ssh-agent ohne Kennwortabfrage verfügbar machen; danach noch einmal versuchen."
        )
    return t(
        "Die Anmeldung fehlt oder wurde abgelehnt. Bei https braucht der Server meist einen "
        "Zugangstoken statt des Kennworts (GitHub: Settings › Developer settings › Personal "
        "access tokens; GitLab: Zugriffstoken mit dem Recht „write_repository“). Den Token im "
        "Anmeldedienst des Rechners hinterlegen (Windows: Anmeldeinformationsverwaltung, macOS: "
        "Schlüsselbund, Linux: `git config --global credential.helper store`) bzw. beim "
        "nächsten Anmeldefenster als Kennwort eingeben; danach noch einmal versuchen."
    )


def repo_root(path: Path) -> Path | None:
    """Wurzel des Git-Repositorys, in dem ``path`` liegt – oder None."""
    path = path.resolve()
    cached = _ROOT_CACHE.get(path)
    if cached and time.monotonic() - cached[0] < _ROOT_TTL:
        return cached[1]
    start = path
    while not start.exists():
        start = start.parent
    try:
        root = Path(_git(start if start.is_dir() else start.parent, "rev-parse", "--show-toplevel"))
    except GitError:
        root = None
    _ROOT_CACHE[path] = (time.monotonic(), root)
    return root


def pending_changes(path: Path) -> list[tuple[str, str]]:
    """Nicht committete Änderungen unterhalb von ``path`` als (Status, Pfad relativ zur Wurzel)."""
    root = repo_root(path)
    if root is None:
        raise GitError(t("{path} liegt in keinem Git-Repository", path=path))
    # Nicht strippen: Die Statusspalte beginnt ggf. mit einem Leerzeichen (" M datei").
    out = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        str(path.resolve()),
        strip=False,
    )
    changes = []
    for line in out.splitlines():
        status, file = line[:2].strip(), line[3:]
        if " -> " in file:  # Umbenennung
            file = file.split(" -> ", 1)[1]
        changes.append((status, file.strip('"')))
    return changes


_STATUS_CACHE: dict[Path, tuple[float, list[tuple[str, str]]]] = {}
_STATUS_TTL = 5.0


def cached_pending_changes(path: Path) -> list[tuple[str, str]]:
    """Wie :func:`pending_changes`, aber höchstens alle paar Sekunden neu abgefragt (für die
    Oberfläche, die bei jeder Eingabe neu zeichnet). Nach Speichern, Commit und Wechsel des
    Datenordners mit :func:`invalidate_status` ungültig machen."""
    key = path.resolve()
    cached = _STATUS_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATUS_TTL:
        return list(cached[1])
    changes = pending_changes(path)
    _STATUS_CACHE[key] = (time.monotonic(), changes)
    return list(changes)


_INVALIDATE_HOOKS: list[Callable[[], object]] = []


def on_invalidate(hook: Callable[[], object]) -> None:
    """Meldet einen weiteren Zwischenspeicher an, der mit :func:`invalidate_status` geleert wird."""
    _INVALIDATE_HOOKS.append(hook)


def invalidate_status() -> None:
    """Verwirft zwischengespeicherte Git-Stände (nach Speichern, Commit, Synchronisation)."""
    _STATUS_CACHE.clear()
    for hook in _INVALIDATE_HOOKS:
        hook()


def commit_directory(path: Path, message: str, tags: list[str] | None = None) -> str:
    """Committet alle Änderungen unterhalb von ``path`` (nur dort) und setzt optional Tags."""
    root = repo_root(path)
    if root is None:
        raise GitError(t("{path} liegt in keinem Git-Repository", path=path))
    changes = pending_changes(path)
    if not changes:
        raise GitError(t("Keine Änderungen zum Committen"))
    if blocked := [f for _, f in changes if FORBIDDEN.search(f)]:
        raise GitError(
            t(
                "Tabellenkalkulationen werden nicht committet – bitte entfernen oder in "
                ".gitignore aufnehmen: {files}",
                files=", ".join(blocked),
            )
        )
    target = str(path.resolve())
    _git(root, "add", "--all", "--", target)
    _git(root, "commit", "-m", message, "--", target)
    for tag in tags or []:
        _git(root, "tag", "-a", tag, "-m", message)
    invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


def commit(paths: list[Path], message: str, tag: str | None = None) -> str:
    """Committet ``paths`` und setzt optional einen Tag. Gibt den Commit-Hash zurück."""
    cwd = paths[0].resolve().parent
    root = Path(_git(cwd, "rev-parse", "--show-toplevel"))
    _git(root, "add", "--", *(str(p.resolve()) for p in paths))
    _git(root, "commit", "-m", message, "--", *(str(p.resolve()) for p in paths))
    if tag:
        _git(root, "tag", "-a", tag, "-m", message)
    invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


GITIGNORE = """\
# Tabellenkalkulationen nie committen – sie können echte Team-Daten enthalten.
*.xlsx
*.xlsm
*.xls
"""


def init_data_repository(path: Path, teams_folder: bool = True) -> Path:
    """Legt ein Daten-Repository an (git init, .gitignore, optional Ordner ``teams``) und
    liefert den Ordner für die Teams."""
    path.mkdir(parents=True, exist_ok=True)
    if repo_root(path) is None:
        _git(path, "init", "-q")
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE, encoding="utf-8")
    if not teams_folder:
        return path
    teams = path / "teams"
    teams.mkdir(exist_ok=True)
    return teams


def clone_repository(url: str, path: Path, timeout: float = 300) -> None:
    """Klont ein bestehendes Daten-Repository nach ``path``. Fehler (Anmeldung, Server nicht
    erreichbar, Zeitüberschreitung) kommen als :class:`GitError` mit nächstem Schritt."""
    if path.exists() and any(path.iterdir()):
        raise GitError(t("{path} ist nicht leer", path=path))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(path.parent, "clone", url, str(path), network=True, timeout=timeout)
    except GitError as e:
        if e.kind == "auth":
            e.hint = auth_help(url)
        raise
