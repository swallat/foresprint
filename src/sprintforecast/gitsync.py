# SPDX-License-Identifier: EUPL-1.2
"""Stand und „Speichern und teilen“ für gemeinsam genutzte Daten-Repositories.

Das Modell ist bewusst einfach: ein Branch, immer synchron halten. Die Funktionen rufen das
Programm ``git`` auf (siehe :mod:`sprintforecast.git`) und liefern Fehler als
:class:`~sprintforecast.git.GitError` mit Art und nächstem Schritt. Eigene Änderungen werden vor
jedem Abgleich committet, damit sie nie verloren gehen können; scheitert das Zusammenführen,
wird es abgebrochen und der Stand bleibt wie zuvor.
"""

from __future__ import annotations

import io
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from sprintforecast import git as gitmod
from sprintforecast.git import GitError, _git, hint_for, pending_changes, repo_root
from sprintforecast.i18n import t
from sprintforecast.yamlmerge import (
    MISSING,
    OURS,
    KeyConflict,
    header_of,
    merge3,
)

# Wie oft ein Push nach "inzwischen hat jemand anderes hochgeladen" neu versucht wird.
MAX_ATTEMPTS = 3

_SEP = "\x1f"


@dataclass(frozen=True)
class Commit:
    rev: str
    author: str
    day: str
    subject: str


@dataclass(frozen=True)
class SyncState:
    """Stand des Datenordners gegenüber dem Server (ohne Netzwerkzugriff ermittelt; ``behind``
    gilt für den Stand beim letzten Abgleich, siehe :func:`fetch`)."""

    root: Path
    branch: str | None  # None = detached HEAD
    upstream: str | None  # z. B. "origin/main"
    remote: str | None  # Name des Servers, None = keiner eingerichtet
    url: str = ""
    ahead: int = 0
    behind: int = 0
    unfinished: str | None = None  # "merge" oder "rebase"
    conflicts: tuple[str, ...] = ()
    fetch_error: GitError | None = None  # Ergebnis des letzten Abgleichs, None = ok/unbekannt
    fetched_at: float | None = None

    @property
    def detached(self) -> bool:
        return self.branch is None

    @property
    def offline(self) -> bool:
        return self.fetch_error is not None and self.fetch_error.kind == "offline"

    @property
    def can_share(self) -> bool:
        return self.remote is not None and not self.detached and self.unfinished is None


@dataclass(frozen=True)
class ConflictFile:
    """Eine Datei, die beim Zusammenführen nicht von selbst zusammenpasst."""

    file: str  # relativ zur Repository-Wurzel
    keys: tuple[KeyConflict, ...] = ()  # echte Wertkonflikte (nur bei Zusammenführen je Schlüssel)
    whole: bool = False  # nur als Ganzes entscheidbar (kein YAML, gelöscht auf einer Seite)
    ours_deleted: bool = False
    theirs_deleted: bool = False

    @property
    def open(self) -> bool:
        """Braucht eine Entscheidung (sonst wird die Datei automatisch zusammengeführt)."""
        return self.whole or bool(self.keys)


@dataclass
class SyncResult:
    """Ergebnis von :func:`sync`: was getan wurde, was von anderen kam und woran es ggf. hakt."""

    committed: str | None = None  # Kurz-Hash des eigenen Commits
    pulled: list[Commit] = field(default_factory=list)  # neu von anderen
    pulled_files: list[tuple[str, str]] = field(default_factory=list)
    pushed: bool = False
    merged: bool = False  # fremde Änderungen wurden zusammengeführt
    conflicts: list[ConflictFile] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)  # neue Fehler nach dem Zusammenführen
    error: GitError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# Zuletzt bekannter Abgleich je Repository: (Zeit, Fehler oder None).
_FETCHED: dict[Path, tuple[float, GitError | None]] = {}
_STATE_CACHE: dict[Path, tuple[float, SyncState]] = {}
_STATE_TTL = 5.0
gitmod.on_invalidate(_STATE_CACHE.clear)


def git_available() -> bool:
    return shutil.which("git") is not None


def _root(path: Path) -> Path:
    if not git_available():
        raise gitmod.classify("", missing=True)
    root = repo_root(path)
    if root is None:
        raise GitError(t("{path} liegt in keinem Git-Repository", path=path))
    return root


def _git_dir(root: Path) -> Path:
    inner = root / ".git"
    if inner.is_dir():
        return inner
    return Path(_git(root, "rev-parse", "--absolute-git-dir"))


def state(path: Path) -> SyncState:
    """Stand des Datenordners (lokal ermittelt, ohne Netzwerk)."""
    root = _root(path)
    out = _git(root, "status", "--porcelain=v2", "--branch", "--untracked-files=no", strip=False)
    branch: str | None = None
    upstream: str | None = None
    ahead = behind = 0
    conflicts: list[str] = []
    for line in out.splitlines():
        if line.startswith("# branch.head "):
            head = line.split(" ", 2)[2]
            branch = None if head == "(detached)" else head
        elif line.startswith("# branch.upstream "):
            upstream = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            plus, minus = line.split(" ")[2:4]
            ahead, behind = int(plus.lstrip("+")), abs(int(minus))
        elif line.startswith("u "):  # nicht zusammengeführte Datei
            conflicts.append(line.split(" ", 10)[-1].strip('"'))
    remote = upstream.split("/", 1)[0] if upstream else None
    if remote is None:
        remotes = _git(root, "remote", check=False).split()
        remote = "origin" if "origin" in remotes else (remotes[0] if remotes else None)
    url = _git(root, "config", "--get", f"remote.{remote}.url", check=False) if remote else ""
    gdir = _git_dir(root)
    unfinished = None
    if (gdir / "MERGE_HEAD").exists():
        unfinished = "merge"
    elif (gdir / "rebase-merge").exists() or (gdir / "rebase-apply").exists():
        unfinished = "rebase"
    fetched = _FETCHED.get(root)
    return SyncState(
        root=root,
        branch=branch,
        upstream=upstream,
        remote=remote,
        url=url,
        ahead=ahead,
        behind=behind,
        unfinished=unfinished,
        conflicts=tuple(conflicts),
        fetch_error=fetched[1] if fetched else None,
        fetched_at=fetched[0] if fetched else None,
    )


def cached_state(path: Path) -> SyncState:
    """Wie :func:`state`, aber kurz zwischengespeichert (für die Oberfläche); wird mit
    :func:`sprintforecast.git.invalidate_status` ungültig."""
    key = path.resolve()
    cached = _STATE_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATE_TTL:
        return cached[1]
    current = state(path)
    _STATE_CACHE[key] = (time.monotonic(), current)
    return current


def fetch(path: Path) -> SyncState:
    """Holt den Stand vom Server (nur herunterladen, nichts ändern) und merkt sich, ob der
    Server erreichbar war. Fehler werden nicht ausgelöst, sondern im Stand vermerkt."""
    root = _root(path)
    current = state(path)
    error: GitError | None = None
    if current.remote is None:
        error = GitError(t("Kein Server eingerichtet."), "no_remote", hint_for("no_remote"))
    else:
        try:
            _git(root, "fetch", "--prune", current.remote, network=True)
        except GitError as e:
            error = e
            if e.kind == "auth":
                e.hint = gitmod.auth_help(current.url)
    _FETCHED[root] = (time.time(), error)
    gitmod.invalidate_status()
    return state(path)


def incoming(path: Path, limit: int = 50) -> tuple[list[Commit], list[tuple[str, str]]]:
    """Was andere seit dem eigenen Stand geändert haben (nach dem letzten Abgleich): Commits
    und geänderte Dateien (Status, Pfad) unterhalb von ``path``."""
    root = _root(path)
    current = state(path)
    if not current.upstream or current.behind == 0:
        return [], []
    target = str(path.resolve())
    log = _git(
        root,
        "log",
        f"-{limit}",
        f"--format=%h{_SEP}%an{_SEP}%as{_SEP}%s",
        f"HEAD..{current.upstream}",
        "--",
        target,
        check=False,
    )
    commits = [Commit(*line.split(_SEP, 3)) for line in log.splitlines() if _SEP in line]
    diff = _git(
        root, "diff", "--name-status", f"HEAD...{current.upstream}", "--", target, check=False
    )
    files = []
    for line in diff.splitlines():
        status, _, name = line.partition("\t")
        files.append((status[:1], name.split("\t")[-1]))
    return commits, files


def _parse(text: str) -> Any:
    from sprintforecast.storage import _YAML_LOADER

    content = yaml.load(text, Loader=_YAML_LOADER)
    return {} if content is None else content


def _stages(root: Path) -> dict[str, set[int]]:
    """Nicht zusammengeführte Dateien mit den vorhandenen Ständen (1 = Basis, 2 = meine,
    3 = andere)."""
    out = _git(root, "ls-files", "-u", "-z", strip=False, check=False)
    stages: dict[str, set[int]] = {}
    for entry in filter(None, out.split("\0")):
        info, _, name = entry.partition("\t")
        stages.setdefault(name, set()).add(int(info.split()[2]))
    return stages


def _stage_text(root: Path, stage: int, file: str) -> str:
    return _git(root, "show", f":{stage}:{file}", strip=False)


def _analyse(
    root: Path, file: str, stages: set[int], choices: dict[tuple[str, ...], str]
) -> tuple[ConflictFile, str | None]:
    """Prüft eine Datei: lässt sie sich auf Schlüsselebene zusammenführen? Liefert die offenen
    Wertkonflikte und – wenn keine bleiben – den zusammengeführten Text."""
    whole = ConflictFile(
        file, whole=True, ours_deleted=2 not in stages, theirs_deleted=3 not in stages
    )
    if not file.endswith((".yaml", ".yml")) or not {2, 3} <= stages:
        return whole, None
    try:
        ours_text, theirs_text = _stage_text(root, 2, file), _stage_text(root, 3, file)
        base = _parse(_stage_text(root, 1, file)) if 1 in stages else MISSING
        ours, theirs = _parse(ours_text), _parse(theirs_text)
        if not isinstance(ours, dict) or not isinstance(theirs, dict):
            return whole, None
        merged, conflicts = merge3(base, ours, theirs, choices)
    except yaml.YAMLError, GitError:
        return whole, None
    if conflicts:
        return ConflictFile(file, keys=tuple(conflicts)), None
    from sprintforecast.storage import dump_yaml

    return ConflictFile(file), header_of(ours_text or theirs_text) + dump_yaml(merged)


def pending_conflicts(path: Path) -> list[ConflictFile]:
    """Dateien eines unvollständigen Zusammenführens: mit ihren echten Wertkonflikten (leer =
    lässt sich automatisch zusammenführen) bzw. als Ganzes zu entscheiden."""
    root = _root(path)
    return [_analyse(root, f, st, {})[0] for f, st in sorted(_stages(root).items())]


def resolve_conflicts(
    path: Path, choices: dict[str, dict[tuple[str, ...], str]] | None = None
) -> list[ConflictFile]:
    """Löst alles, was sich lösen lässt: Dateien ohne Wertkonflikt automatisch, die übrigen
    nach ``choices`` (Datei → Pfad → "ours"/"theirs"; Pfad ``()`` = ganze Datei). Liefert die
    verbleibenden Konflikte. Das Zusammenführen wird erst von :func:`sync` abgeschlossen."""
    root = _root(path)
    for file, stages in sorted(_stages(root).items()):
        wanted = (choices or {}).get(file, {})
        info, merged = _analyse(root, file, stages, wanted)
        if info.whole:
            choice = wanted.get(())
            if choice is None:
                continue
            keep = 2 if choice == OURS else 3
            if keep in stages:
                _git(root, "checkout", "--ours" if choice == OURS else "--theirs", "--", file)
                _git(root, "add", "--", file)
            else:  # auf dieser Seite gelöscht
                _git(root, "rm", "-q", "--", file)
        elif merged is not None:
            (root / file).write_text(merged, encoding="utf-8", newline="\n")
            _git(root, "add", "--", file)
    gitmod.invalidate_status()
    return pending_conflicts(path)


def _merge(root: Path, upstream: str, path: Path) -> list[ConflictFile]:
    """Führt den Server-Stand ein. Bei Konflikten bleibt das Zusammenführen offen, alles
    automatisch Lösbare ist erledigt; zurück kommen die Konflikte für den Menschen (leer =
    fertig). Die eigenen Änderungen sind bereits committet."""
    try:
        _git(root, "merge", "--no-edit", upstream)
        return []
    except GitError as e:
        if e.kind not in {"conflict", "error"} or not (_git_dir(root) / "MERGE_HEAD").exists():
            raise
    remaining = resolve_conflicts(path)
    if not remaining:
        _git(root, "commit", "--no-edit")
    return remaining


def _conflict_error() -> GitError:
    return GitError(
        t("Zusammenführen: Konflikte warten auf deine Entscheidung."),
        "conflict",
        hint_for("conflict"),
    )


def _error_set(repo_dir: Path, today: date) -> set[tuple[str, str, str]]:
    from sprintforecast.storage import Repository
    from sprintforecast.validate import Level, check_all

    return {
        (key, i.where, i.message)
        for key, issues in check_all(Repository(repo_dir), today).items()
        for i in issues
        if i.level is Level.ERROR
    }


def _errors_at(root: Path, path: Path, rev: str, today: date) -> set[tuple[str, str, str]]:
    """Fehler der Gesamtvalidierung für den Stand eines Commits (ohne ihn auszuchecken)."""
    rel = path.resolve().relative_to(root).as_posix()
    tree = rev if rel == "." else f"{rev}:{rel}"
    try:
        data = gitmod._git_bytes(root, "archive", "--format=tar", tree)
    except GitError:
        return set()
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(tmp, filter="data")
        return _error_set(Path(tmp), today)


def new_errors(path: Path, baseline: str, today: date | None = None) -> list[str]:
    """Fehler der Gesamtvalidierung im Arbeitsstand, die im Stand ``baseline`` (Commit) noch
    nicht vorhanden waren – als lesbare Zeilen."""
    root = _root(path)
    today = today or date.today()
    found = _error_set(path, today) - _errors_at(root, path, baseline, today)
    return [f"{key}: {where}: {message}" for key, where, message in sorted(found)]


def _unpushed_merges(root: Path, current: SyncState) -> bool:
    if not current.upstream:
        return False
    count = _git(root, "rev-list", "--merges", "--count", f"{current.upstream}..HEAD")
    return count.isdigit() and int(count) > 0


def sync(
    path: Path,
    message: str,
    tags: list[str] | None = None,
    today: date | None = None,
    allow_invalid: bool = False,
) -> SyncResult:
    """„Speichern und teilen“: eigene Änderungen committen, die der anderen holen und
    zusammenführen, prüfen, hochladen. Erwartbare Fehler (offline, abgelehnt, Anmeldung,
    Konflikt …) stehen in ``result.error``; was bis dahin gelang (z. B. der eigene Commit),
    bleibt erhalten. Bei Konflikten bleibt das Zusammenführen offen (``result.conflicts``);
    nach der Entscheidung (:func:`resolve_conflicts`) setzt ein erneuter Aufruf fort. Nach
    einem Zusammenführen läuft die Gesamtvalidierung: Neue Fehler verhindern das Hochladen,
    außer mit ``allow_invalid``."""
    result = SyncResult()
    try:
        root = _root(path)
        current = state(path)
        if current.unfinished == "rebase":
            raise GitError(
                t("Ein früherer Vorgang ist noch nicht abgeschlossen."),
                "merge_in_progress",
                hint_for("merge_in_progress"),
            )
        if current.detached:
            raise GitError(t("Kein Branch ausgewählt."), "detached", hint_for("detached"))
        # 0. Wiederaufnahme: ein offenes Zusammenführen zuerst abschließen.
        if current.unfinished == "merge":
            result.conflicts = resolve_conflicts(path)
            if result.conflicts:
                raise _conflict_error()
            _git(root, "commit", "--no-edit")
            result.merged = True
        elif current.conflicts:
            raise GitError(
                t("Ein früherer Vorgang ist noch nicht abgeschlossen."),
                "merge_in_progress",
                hint_for("merge_in_progress"),
            )
        # 1. Eigenes sichern: erst als Commit, dann ist nichts mehr in Gefahr.
        if pending_changes(path):
            result.committed = gitmod.commit_directory(path, message, tags)
        current = state(path)
        if current.remote is None:
            raise GitError(t("Kein Server eingerichtet."), "no_remote", hint_for("no_remote"))
        # 2. Server-Stand holen, 3. zusammenführen, 4. prüfen, 5. hochladen (bei Wettlauf neu).
        for attempt in range(MAX_ATTEMPTS):
            current = fetch(path)
            if current.fetch_error is not None:
                raise current.fetch_error
            commits, files = incoming(path)
            result.pulled += [c for c in commits if c not in result.pulled]
            result.pulled_files += [f for f in files if f not in result.pulled_files]
            if current.upstream and current.behind:
                result.conflicts = _merge(root, current.upstream, path)
                if result.conflicts:
                    raise _conflict_error()
                result.merged = True
                current = state(path)
            if not allow_invalid and _unpushed_merges(root, current):
                found = new_errors(path, current.upstream or "HEAD", today)
                if found:
                    result.validation = found
                    raise GitError(
                        t("Die zusammengeführten Daten sind nicht gültig."),
                        "invalid",
                        hint_for("invalid"),
                    )
            try:
                _push(root, current)
            except GitError as e:
                if e.kind == "rejected" and attempt + 1 < MAX_ATTEMPTS:
                    continue
                raise
            result.pushed = True
            break
    except GitError as e:
        result.error = e
    finally:
        gitmod.invalidate_status()
    return result


def _push(root: Path, current: SyncState) -> None:
    if current.upstream:
        _git(root, "push", "--follow-tags", network=True)
        return
    # Erster Push: Branch mit dem Server verbinden.
    _git(
        root,
        "push",
        "--follow-tags",
        "-u",
        current.remote or "origin",
        current.branch or "HEAD",
        network=True,
    )


def restore_file(path: Path, file: Path) -> None:
    """Stellt eine Datei auf den letzten gespeicherten (committeten) Stand zurück."""
    root = _root(path)
    _git(root, "checkout", "HEAD", "--", str(file.resolve()))
    gitmod.invalidate_status()


def abort_unfinished(path: Path) -> None:
    """Bricht ein unvollständiges Zusammenführen (oder einen Rebase) ab; eigene committete
    Änderungen bleiben unverändert."""
    root = _root(path)
    current = state(path)
    if current.unfinished == "merge" or (current.conflicts and current.unfinished is None):
        _git(root, "merge", "--abort")
    elif current.unfinished == "rebase":
        _git(root, "rebase", "--abort")
    gitmod.invalidate_status()


def reattach(path: Path) -> str:
    """Geht von „detached HEAD“ zurück auf den Hauptbranch. Hängen Commits an keinem Branch,
    werden sie vorher auf einem Rettungsbranch gesichert. Gibt den Namen des Branches zurück."""
    root = _root(path)
    if state(path).branch is not None:
        raise GitError(t("Das Repository steht bereits auf einem Branch."))
    default = _git(root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", check=False)
    candidates = [default.split("/", 1)[-1]] if default else []
    candidates += ["main", "master"]
    local = set(_git(root, "branch", "--format=%(refname:short)").split())
    target = next((c for c in candidates if c in local), None)
    if target is None:
        raise GitError(
            t("Kein Hauptbranch gefunden (main oder master)."),
            "detached",
            t("Bitte einen Git-Client oder ein Terminal verwenden."),
        )
    holders = _git(root, "branch", "--contains", "HEAD", "--format=%(refname:short)", check=False)
    if not [b for b in holders.splitlines() if not b.startswith("(")]:
        rescue = f"rettung-{time.strftime('%Y%m%d-%H%M%S')}"
        _git(root, "branch", rescue)
    _git(root, "switch", target)
    gitmod.invalidate_status()
    return target


def set_identity(name: str, email: str) -> None:
    """Hinterlegt Name und E-Mail-Adresse für Commits (global für den Benutzer)."""
    if not name.strip() or "@" not in email:
        raise GitError(t("Bitte Name und eine gültige E-Mail-Adresse eintragen."))
    _git(Path.home(), "config", "--global", "user.name", name.strip())
    _git(Path.home(), "config", "--global", "user.email", email.strip())
