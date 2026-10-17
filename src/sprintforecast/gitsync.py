# SPDX-License-Identifier: EUPL-1.2
"""Stand und „Speichern und teilen“ für gemeinsam genutzte Daten-Repositories.

Das Modell ist bewusst einfach: ein Branch, immer synchron halten. Die Funktionen rufen das
Programm ``git`` auf (siehe :mod:`sprintforecast.git`) und liefern Fehler als
:class:`~sprintforecast.git.GitError` mit Art und nächstem Schritt. Eigene Änderungen werden vor
jedem Abgleich committet, damit sie nie verloren gehen können; scheitert das Zusammenführen,
wird es abgebrochen und der Stand bleibt wie zuvor.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from sprintforecast import git as gitmod
from sprintforecast.git import GitError, _git, hint_for, pending_changes, repo_root
from sprintforecast.i18n import t

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


@dataclass
class SyncResult:
    """Ergebnis von :func:`sync`: was getan wurde, was von anderen kam und woran es ggf. hakt."""

    committed: str | None = None  # Kurz-Hash des eigenen Commits
    pulled: list[Commit] = field(default_factory=list)  # neu von anderen
    pulled_files: list[tuple[str, str]] = field(default_factory=list)
    pushed: bool = False
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


def _merge(root: Path, upstream: str) -> None:
    """Führt den Server-Stand ein. Bei Konflikten wird abgebrochen (nichts geht verloren, die
    eigenen Änderungen sind bereits committet)."""
    try:
        _git(root, "merge", "--no-edit", upstream)
    except GitError as e:
        if e.kind in {"conflict", "error"}:
            files = _git(root, "diff", "--name-only", "--diff-filter=U", check=False).split()
            _git(root, "merge", "--abort", check=False)
            if files:
                raise GitError(
                    t(
                        "Zusammenführen nicht möglich, Konflikt in: {files}",
                        files=", ".join(files),
                    ),
                    "conflict",
                    hint_for("conflict"),
                ) from e
        raise


def sync(path: Path, message: str, tags: list[str] | None = None) -> SyncResult:
    """„Speichern und teilen“: eigene Änderungen committen, die der anderen holen und
    zusammenführen, hochladen. Erwartbare Fehler (offline, abgelehnt, Anmeldung …) stehen in
    ``result.error``; was bis dahin gelang (z. B. der eigene Commit), bleibt erhalten."""
    result = SyncResult()
    try:
        root = _root(path)
        current = state(path)
        if current.unfinished or current.conflicts:
            raise GitError(
                t("Ein früheres Zusammenführen ist noch nicht abgeschlossen."),
                "merge_in_progress",
                hint_for("merge_in_progress"),
            )
        if current.detached:
            raise GitError(t("Kein Branch ausgewählt."), "detached", hint_for("detached"))
        # 1. Eigenes sichern: erst als Commit, dann ist nichts mehr in Gefahr.
        if pending_changes(path):
            result.committed = gitmod.commit_directory(path, message, tags)
        if current.remote is None:
            raise GitError(t("Kein Server eingerichtet."), "no_remote", hint_for("no_remote"))
        # 2. Server-Stand holen, 3. zusammenführen, 4. hochladen (bei Wettlauf erneut).
        for attempt in range(MAX_ATTEMPTS):
            current = fetch(path)
            if current.fetch_error is not None:
                raise current.fetch_error
            commits, files = incoming(path)
            result.pulled += [c for c in commits if c not in result.pulled]
            result.pulled_files += [f for f in files if f not in result.pulled_files]
            if current.upstream and current.behind:
                _merge(root, current.upstream)
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
