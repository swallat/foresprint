# SPDX-License-Identifier: EUPL-1.2
"""Kleine Git-Helfer für Commit und Sprint-Tag."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
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
    # Pfade sind nie Suchmuster: Dateinamen mit *, ? oder [ bleiben wörtlich gemeint.
    env = {**os.environ, "LC_ALL": "C", "LANGUAGE": "C", "GIT_LITERAL_PATHSPECS": "1"}
    if network:
        env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git_result(
    cwd: Path, *args: str, network: bool = False, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Führt ``git`` aus und liefert das Ergebnis samt Rückgabecode (ohne Fehlerprüfung); nur
    „git fehlt“ und Zeitüberschreitung kommen als :class:`GitError`."""
    try:
        return subprocess.run(
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
    proc = _git_result(cwd, *args, network=network, timeout=timeout)
    if proc.returncode != 0:
        if not check:
            return ""
        raise classify(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip() if strip else proc.stdout


def split_z(out: str) -> list[str]:
    """Zerlegt NUL-getrennte Git-Ausgabe (``-z``) in ihre Einträge. Nur so bleiben Pfade mit
    Umlauten, Anführungszeichen oder Tabulatoren unverändert (ohne ``-z`` setzt Git sie in
    Anführungszeichen und maskiert Sonderzeichen)."""
    return [item for item in out.split("\0") if item]


def check_name(name: str) -> str:
    """Prüft einen Tag-Namen, der an Git übergeben wird: er darf nicht mit ``-`` beginnen (Git
    läse ihn sonst als Option), nicht ``HEAD`` oder ``@`` heißen (für Git mehrdeutig) und keine
    Leerzeichen am Anfang oder Ende haben (sie werden nicht still entfernt, sonst entstünde ein
    anderer Name als der eingegebene). Gibt den Namen unverändert zurück."""
    if not name.strip() or name != name.strip() or name.startswith("-") or name in {"HEAD", "@"}:
        raise GitError(t("Ungültiger Tag-Name: {name}", name=name))
    return name


def valid_tag_name(root: Path, name: str) -> str:
    """Wie :func:`check_name`, prüft aber zusätzlich mit Git, ob der Referenzname gültig ist."""
    name = check_name(name)
    if _git_result(root, "check-ref-format", f"refs/tags/{name}").returncode != 0:
        raise GitError(t("Ungültiger Tag-Name: {name}", name=name))
    return name


def tag_commit(root: Path, name: str) -> str:
    """Voller Hash des Commits, auf den der lokale Tag zeigt (leer = es gibt ihn nicht)."""
    return _git(
        root, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{commit}}", check=False
    )


def check_new_tags(root: Path, tags: list[str] | None) -> list[str]:
    """Prüft Tag-Namen VOR einem Commit: gültig und lokal noch nicht vergeben (ein vorhandener
    Tag zeigt nie auf den neuen Commit). Bei einem Konflikt :class:`GitError`; dann ist noch
    nichts verändert. Gibt die Namen ohne Doppelte zurück."""
    names = list(dict.fromkeys(valid_tag_name(root, tag) for tag in tags or []))
    for name in names:
        if existing := tag_commit(root, name):
            raise GitError(
                t(
                    "Der Tag {name} gibt es auf diesem Rechner schon (er zeigt auf {rev}). "
                    "Es wurde nichts committet.",
                    name=name,
                    rev=existing[:7],
                ),
                "tag_exists",
                hint_for("tag_exists"),
            )
    return names


def ensure_tags(root: Path, tags: list[str] | None, message: str) -> tuple[list[str], list[str]]:
    """Setzt fehlende Tags auf den aktuellen Stand (HEAD), ohne neuen Commit – etwa wenn ein
    früherer Versuch den Commit schrieb, den Tag aber nicht. Liefert (neu gesetzte Tags, Tags,
    die schon auf einem anderen Stand liegen und unverändert bleiben)."""
    names = list(dict.fromkeys(valid_tag_name(root, tag) for tag in tags or []))
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
    created: list[str] = []
    elsewhere: list[str] = []
    if not head:
        return created, elsewhere
    try:
        for name in names:
            existing = tag_commit(root, name)
            if not existing:
                _git(root, "tag", "-a", "-m", message, "--", name)
                created.append(name)
            elif existing != head:
                elsewhere.append(name)
    finally:
        invalidate_status()
    return created, elsewhere


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
        "unrelated_histories": t("Server hat eine andere Historie"),
        "tag_exists": t("Tag-Name ist schon vergeben"),
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
        "unrelated_histories": t(
            "Der Server enthält eine andere Historie als dieser Datenordner – vermutlich ist "
            "ein falsches Repository verbunden (z. B. ein Code-Repository). Es wurde nichts "
            "zusammengeführt und nichts hochgeladen; deine Änderungen sind lokal gesichert. "
            "Ist das Daten-Repository auf dem Server richtig, muss das Zusammenführen "
            "ausdrücklich bestätigt werden."
        ),
        "tag_exists": t(
            "Einen anderen Namen wählen oder den vorhandenen Tag zuerst entfernen. Die "
            "Änderungen sind unverändert und noch nicht gespeichert."
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


def forget_roots(path: Path) -> None:
    """Vergisst zwischengespeicherte Wurzeln für ``path``, darunter und darüber (nach
    ``git init`` oder ``git clone`` – sonst gälte „kein Repository“ noch bis zu 30 Sekunden)."""
    path = path.resolve()
    for key in [k for k in _ROOT_CACHE if k == path or path in k.parents or k in path.parents]:
        del _ROOT_CACHE[key]


@dataclass(frozen=True)
class Change:
    """Eine nicht committete Änderung. ``status``: M geändert, D gelöscht, A neu (vorgemerkt),
    R umbenannt, ?? neu (nicht vorgemerkt) – auch kombiniert (AM, RM, AD …). ``orig`` ist bei
    Umbenennungen und Kopien der bisherige Pfad."""

    status: str
    file: str  # relativ zur Repository-Wurzel
    orig: str = ""


def changes_in(path: Path) -> list[Change]:
    """Nicht committete Änderungen unterhalb von ``path``, bei Umbenennungen mit dem bisherigen
    Pfad."""
    root = repo_root(path)
    if root is None:
        raise GitError(t("{path} liegt in keinem Git-Repository", path=path))
    # Nicht strippen: Die Statusspalte beginnt ggf. mit einem Leerzeichen (" M datei").
    out = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        str(path.resolve()),
        strip=False,
    )
    entries = out.split("\0")
    changes = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, file, orig = entry[:2], entry[3:], ""
        if ("R" in xy or "C" in xy) and i < len(entries):  # der bisherige Pfad folgt
            orig = entries[i]
            i += 1
        changes.append(Change(xy.strip(), file, orig))
    return changes


def pending_changes(path: Path) -> list[tuple[str, str]]:
    """Nicht committete Änderungen unterhalb von ``path`` als (Status, Pfad relativ zur Wurzel);
    bei Umbenennungen der neue Pfad (den bisherigen liefert :func:`changes_in`)."""
    return [(c.status, c.file) for c in changes_in(path)]


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
    for key in [k for k, (_, root) in _ROOT_CACHE.items() if root is None]:
        del _ROOT_CACHE[key]  # „kein Repository“ ist nicht von Dauer
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
    names = check_new_tags(root, tags)  # vor dem Commit: bei einem Konflikt bleibt alles offen
    target = str(path.resolve())
    try:
        _git(root, "add", "--all", "--", target)
        _git(root, "commit", "-m", message, "--", target)
        for name in names:
            _git(root, "tag", "-a", "-m", message, "--", name)
    finally:
        invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


def commit(paths: list[Path], message: str, tag: str | None = None) -> str:
    """Committet ``paths`` und setzt optional einen Tag. Gibt den Commit-Hash zurück."""
    cwd = paths[0].resolve().parent
    root = Path(_git(cwd, "rev-parse", "--show-toplevel"))
    names = check_new_tags(root, [tag] if tag else None)
    try:
        _git(root, "add", "--", *(str(p.resolve()) for p in paths))
        _git(root, "commit", "-m", message, "--", *(str(p.resolve()) for p in paths))
        for name in names:
            _git(root, "tag", "-a", "-m", message, "--", name)
    finally:
        invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


GITIGNORE = """\
# Tabellenkalkulationen nie committen – sie können echte Team-Daten enthalten.
*.xlsx
*.xlsm
*.xls
# Übrig gebliebene Zwischendateien des Speicherns.
*.tmp
"""


def init_data_repository(path: Path, teams_folder: bool = True) -> Path:
    """Legt ein Daten-Repository an (git init, .gitignore, optional Ordner ``teams``) und
    liefert den Ordner für die Teams."""
    path.mkdir(parents=True, exist_ok=True)
    if repo_root(path) is None:
        _git(path, "init", "-q")
        forget_roots(path)
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
    url = url.strip()
    if not url or url.startswith("-"):  # Git läse die Adresse sonst als Option
        raise GitError(t("Ungültige Adresse: {url}", url=url))
    if path.exists() and any(path.iterdir()):
        raise GitError(t("{path} ist nicht leer", path=path))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(path.parent, "clone", "--", url, str(path), network=True, timeout=timeout)
    except GitError as e:
        if e.kind == "auth":
            e.hint = auth_help(url)
        raise
    finally:
        forget_roots(path)
