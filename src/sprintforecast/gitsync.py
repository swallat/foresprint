# SPDX-License-Identifier: EUPL-1.2
"""State and "Save and share" for shared data repositories.

The model is deliberately simple: one branch, always kept in sync. The functions call the
``git`` program (see :mod:`sprintforecast.git`) and report errors as
:class:`~sprintforecast.git.GitError` with a kind and the next step. Own changes are committed
before every sync so that they can never get lost; if merging fails, it is aborted and the
state stays as it was.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import io
import os
import re
import tarfile
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from sprintforecast import git as gitmod
from sprintforecast.git import (
    GitError,
    _git,
    hint_for,
    pending_changes,
    require_root,
    split_record,
)
from sprintforecast.i18n import t
from sprintforecast.yamlmerge import (
    MISSING,
    OURS,
    KeyConflict,
    header_of,
    merge3,
)

# How own changes reach the server: directly onto the branch or (server with a protected
# main branch, e.g. GitLab) via a merge request. The choice applies per data repository and
# is stored in its local Git configuration.
SHARE_KEY = "sprintforecast.share"
AUTO_MERGE_KEY = "sprintforecast.mrautomerge"  # "false" turns auto-merge off (default: on)
SHARE_DIRECT, SHARE_MERGE_REQUEST = "direct", "merge_request"
_PR_URL = re.compile(
    r"https?://\S+/(?:pulls?/(?:\d+|new/\S+)|merge_requests/(?:\d+|new\b\S*)|compare/\S+)"
)
# Which server hosts the data repository? That determines how a merge/pull request is
# created. ``HOST_KEY`` overrides the detection from the address (default: automatic).
HOST_KEY = "sprintforecast.host"
HOST_GITLAB, HOST_GITHUB, HOST_FORGEJO, HOST_GENERIC = "gitlab", "github", "forgejo", "generic"
HOSTS = (HOST_GITLAB, HOST_GITHUB, HOST_FORGEJO, HOST_GENERIC)

# How often a push is retried after "someone else has uploaded in the meantime".
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
    """State of the data folder relative to the server (determined without network access;
    ``behind`` applies to the state at the last fetch, see :func:`fetch`)."""

    root: Path
    branch: str | None  # None = detached HEAD
    upstream: str | None  # e.g. "origin/main"
    remote: str | None  # name of the server, None = none set up
    # Raw, may contain credentials (legacy data): never display, not even via ``repr``.
    url: str = field(default="", repr=False)
    ahead: int = 0
    behind: int = 0
    unfinished: str | None = None  # "merge" or "rebase"
    conflicts: tuple[str, ...] = ()
    fetch_error: GitError | None = None  # result of the last fetch, None = ok/unknown
    fetched_at: float | None = None
    unborn: bool = False  # no commit yet (freshly created repository)

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
    """A file that does not merge on its own."""

    file: str  # relative to the repository root
    keys: tuple[KeyConflict, ...] = ()  # real value conflicts (only when merging per key)
    whole: bool = False  # can only be decided as a whole (not YAML, deleted on one side)
    ours_deleted: bool = False
    theirs_deleted: bool = False

    @property
    def open(self) -> bool:
        """Needs a decision (otherwise the file is merged automatically)."""
        return self.whole or bool(self.keys)


@dataclass
class SyncResult:
    """Result of :func:`sync`: what was done, what came from others and what got stuck."""

    committed: str | None = None  # short hash of the own commit
    pulled: list[Commit] = field(default_factory=list)  # new from others
    pulled_files: list[tuple[str, str]] = field(default_factory=list)
    pushed: bool = False
    merge_request_url: str | None = None  # sharing via merge request: address, if reported
    merge_request_branch: str | None = None  # branch that was uploaded
    pull_only: bool = False  # "Pull from server": upload nothing, not even when resuming
    merged: bool = False  # changes from others were merged
    conflicts: list[ConflictFile] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)  # new errors after merging
    notes: list[str] = field(default_factory=list)  # notes even though everything worked
    error: GitError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# Last known fetch per repository: (time, error or None).
_FETCHED: dict[Path, tuple[float, GitError | None]] = {}
_STATE_CACHE: dict[Path, tuple[float, SyncState]] = {}
_STATE_TTL = 5.0
gitmod.on_invalidate(_STATE_CACHE.clear)


def git_available() -> bool:
    return gitmod.find_git() is not None


def _root(path: Path) -> Path:
    if not git_available():
        raise gitmod.classify("", missing=True, broken=gitmod.broken_git())
    return require_root(path)


def _git_dir(root: Path) -> Path:
    inner = root / ".git"
    if inner.is_dir():
        return inner
    return Path(_git(root, "rev-parse", "--absolute-git-dir"))


def state(path: Path) -> SyncState:
    """State of the data folder (determined locally, without network)."""
    root = _root(path)
    out = _git(
        root, "status", "--porcelain=v2", "-z", "--branch", "--untracked-files=no", strip=False
    )
    branch: str | None = None
    upstream: str | None = None
    unborn = False
    ahead = behind = 0
    conflicts: list[str] = []
    entries = out.split("\0")
    skip = 0
    for line in entries:
        if skip:  # previous path of a rename
            skip -= 1
            continue
        if line.startswith("2 "):
            skip = 1
        elif line.startswith("# branch.oid "):
            unborn = line.split(" ", 2)[2] == "(initial)"  # no commit yet
        elif line.startswith("# branch.head "):
            head = line.split(" ", 2)[2]
            branch = None if head == "(detached)" else head
        elif line.startswith("# branch.upstream "):
            upstream = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            plus, minus = line.split(" ")[2:4]
            ahead, behind = int(plus.lstrip("+")), abs(int(minus))
        elif line.startswith("u "):  # unmerged file
            conflicts.append(line.split(" ", 10)[-1])
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
        unborn=unborn,
    )


def cached_state(path: Path) -> SyncState:
    """Like :func:`state`, but cached briefly (for the UI); invalidated by
    :func:`sprintforecast.git.invalidate_status`."""
    key = path.resolve()
    cached = _STATE_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATE_TTL:
        return cached[1]
    current = state(path)
    _STATE_CACHE[key] = (time.monotonic(), current)
    return current


# In the background: short timeout (the whole process tree is terminated) and never a login
# window or prompt (Credential Manager, GIT_ASKPASS/SSH_ASKPASS, SSH passphrase). If the login
# is missing or the server is unreachable, the state stays unchanged; the "Check state"
# button then explains the next step.
BACKGROUND_FETCH_SECONDS = 30 * 60
BACKGROUND_TIMEOUT = 20.0
BACKGROUND_OFF_ENV = "SPRINTFORECAST_NO_BACKGROUND_FETCH"  # set: no background fetch
_QUIET_ENV = {
    "GCM_INTERACTIVE": "never",
    "SSH_ASKPASS_REQUIRE": "never",
    "GIT_ASKPASS": "",  # empty (not missing): Git asks neither core.askPass nor SSH_ASKPASS
}
_BACKGROUND_LOCK = threading.Lock()
_BACKGROUND_ACTIVE: set[Path] = set()
_BACKGROUND_LAST: dict[Path, float] = {}  # last attempt per data folder (without a Git call)
_SYNC_LOCKS: dict[Path, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    """One lock per data folder: sync and fetch never run at the same time (otherwise Git locks
    ``packed-refs`` and the index, and "Save and share" would fail because of a background
    fetch). Reentrant, because the sync calls :func:`fetch` itself."""
    key = path.resolve()
    with _BACKGROUND_LOCK:
        return _SYNC_LOCKS.setdefault(key, threading.RLock())


LOCK_WARN_SECONDS = 60.0  # a call waits this long for a running sync, then a notice
_LOCK_POLL_SECONDS = 1.0
_HELD: dict[Path, tuple[float, int]] = {}  # data folder → (start, depth) of the running sync


def _busy_error(since: float) -> GitError:
    seconds = int(max(0.0, time.time() - since))
    return GitError(
        t(
            "Another sync of this data folder has been running for {seconds} seconds.",
            seconds=seconds,
        ),
        "sync_busy",
        hint_for("sync_busy"),
    )


@contextlib.contextmanager
def _locked(path: Path, wait: float | None = None) -> Iterator[None]:
    """Holds the lock of the data folder. Whoever would have to wait longer than ``wait``
    (default: ``LOCK_WARN_SECONDS``) gets a :class:`GitError` of kind ``sync_busy`` instead of
    waiting forever. The running sync is never ended by this; that only happens with
    :func:`abort_running_sync`."""
    lock = _lock_for(path)
    key = path.resolve()
    limit = LOCK_WARN_SECONDS if wait is None else wait
    deadline = time.monotonic() + limit
    while not lock.acquire(timeout=min(_LOCK_POLL_SECONDS, max(0.0, limit))):
        if time.monotonic() >= deadline:
            with _BACKGROUND_LOCK:
                since = _HELD.get(key, (time.time(), 0))[0]
            raise _busy_error(since)
    with _BACKGROUND_LOCK:
        since, depth = _HELD.get(key, (time.time(), 0))
        _HELD[key] = (since, depth + 1)
    root: Path | None = None
    if depth == 0:
        with contextlib.suppress(GitError):
            root = _root(path)
            gitmod.begin_sync(root)
    try:
        yield
    finally:
        if root is not None:  # an abort applies only to this sync
            gitmod.end_sync(root)
        with _BACKGROUND_LOCK:
            since, depth = _HELD[key]
            if depth <= 1:
                del _HELD[key]
            else:
                _HELD[key] = (since, depth - 1)
        lock.release()


def sync_running_seconds(path: Path) -> float | None:
    """For how many seconds has a sync held the lock of this data folder (``None``: none)?"""
    with _BACKGROUND_LOCK:
        held = _HELD.get(path.resolve())
    return None if held is None else max(0.0, time.time() - held[0])


def abort_running_sync(path: Path) -> bool:
    """Terminates the running Git calls of the sync of this data folder (explicit request).
    The sync then ends with an error; changes saved before stay, lock files such as
    ``index.lock`` are not touched. ``True`` if something was running."""
    try:
        return gitmod.abort_running(_root(path))
    except GitError:
        return False


def _quiet_env(root: Path) -> dict[str, str]:
    """Environment for the background fetch; SSH runs without prompts (``BatchMode``) unless
    someone set their own SSH command (environment or ``core.sshCommand``)."""
    env = dict(_QUIET_ENV)
    if not (
        os.environ.get("GIT_SSH_COMMAND")
        or os.environ.get("GIT_SSH")
        or _git(root, "config", "--get", "core.sshCommand", check=False)
    ):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
    return env


def _fetch_in_background(root: Path, current: SyncState) -> None:
    """A ``git fetch --prune`` with a timeout; only a success is stored (a failure without
    prompting says nothing about the server and must not overwrite the last good state). If
    the server has changed in the meantime, the result is discarded."""
    run = gitmod._probe_run(
        root,
        ("fetch", "--prune", "--no-tags", current.remote or "origin"),
        BACKGROUND_TIMEOUT,
        _quiet_env(root),
    )
    if run.code != 0:
        return
    if gitmod.remote_url(root, current.remote or "origin") != current.url:
        return
    _FETCHED[root] = (time.time(), None)
    gitmod.invalidate_status()


def fetch(path: Path) -> SyncState:
    """Fetches the state from the server (download only, change nothing) and remembers whether
    the server was reachable. Errors are not raised but recorded in the state."""
    try:
        with _locked(path):
            return _fetch_locked(path)
    except GitError as e:
        if e.kind not in {"sync_busy", "aborted"}:
            raise
        cached = _STATE_CACHE.get(path.resolve())  # no Git call alongside the running sync
        return cached[1] if cached else state(path)


def _fetch_locked(path: Path) -> SyncState:
    root = _root(path)
    current = state(path)
    error: GitError | None = None
    if current.remote is None:
        error = GitError(t("No server set up."), "no_remote", hint_for("no_remote"))
    else:
        try:
            _git(root, "fetch", "--prune", current.remote, network=True, url=current.url)
        except GitError as e:
            if e.kind == "aborted":  # no finding about the server: record nothing
                raise
            error = e
    _FETCHED[root] = (time.time(), error)
    gitmod.invalidate_status()
    return state(path)


def background_fetch_due(path: Path, now: float | None = None) -> bool:
    """Is the last fetch (background attempt or manual fetch) more than 30 minutes ago, or has
    there been none in this program run, and does the data folder have a server? The time
    check comes first and needs no Git call: the sidebar asks on every redraw."""
    now = now or time.time()
    key = path.resolve()
    # Some leeway: the UI calls exactly every 30 minutes, but the last fetch ended a few
    # seconds after it started.
    due_after = BACKGROUND_FETCH_SECONDS - 60
    last = _BACKGROUND_LAST.get(key)
    if last is not None and now - last < due_after:
        return False
    if cached_state(path).remote is None:
        _BACKGROUND_LAST[key] = now  # without a server, do not ask again on every redraw
        return False
    fetched = _FETCHED.get(_root(path))
    return fetched is None or now - fetched[0] >= due_after


def start_background_fetch(path: Path) -> bool:
    """Starts a background fetch of the server state (``git fetch --prune``) if needed and
    returns whether one was started. Never more than one runs per data folder, never at the
    same time as a sync, and there is no endless loop: it is only called from a connected
    session (at startup and every 30 minutes), the thread is a daemon thread and does not
    hold up ``idle.py``."""
    if os.environ.get(BACKGROUND_OFF_ENV):
        return False
    key = path.resolve()
    try:
        if not background_fetch_due(path) or sync_running_seconds(path) is not None:
            return False  # a sync is running: no Git call alongside it
        root = _root(path)
        current = state(path)
    except GitError:
        return False
    with _BACKGROUND_LOCK:
        if key in _BACKGROUND_ACTIVE:
            return False
        _BACKGROUND_ACTIVE.add(key)
        _BACKGROUND_LAST[key] = time.time()

    def run() -> None:
        try:
            try:
                with _locked(path, wait=0):  # a sync is running: try again next time
                    _fetch_in_background(root, current)
            except GitError:
                pass
        except Exception:  # a background fetch must never end anything
            pass
        finally:
            with _BACKGROUND_LOCK:
                _BACKGROUND_ACTIVE.discard(key)

    threading.Thread(target=run, name="sprintforecast-fetch", daemon=True).start()
    return True


def incoming(path: Path, limit: int = 50) -> tuple[list[Commit], list[tuple[str, str]]]:
    """What others have changed since the own state (as of the last fetch): commits and
    changed files (status, path) below ``path``."""
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
    commits = [Commit(*split_record(line, 4, _SEP)) for line in log.split("\n") if _SEP in line]
    related = bool(_git(root, "merge-base", "HEAD", current.upstream, check=False))
    span = f"HEAD...{current.upstream}" if related else f"HEAD..{current.upstream}"
    diff = _git(
        root, "diff", "--name-status", "-z", span, "--", target,
        check=False, strip=False,
    )  # fmt: skip
    files = []
    entries = diff.split("\0")
    i = 0
    while i < len(entries) and entries[i]:
        status = entries[i]
        i += 1
        names = 2 if status[:1] in {"R", "C"} else 1  # for renames: old, new
        if i + names > len(entries):
            break
        files.append((status[:1], entries[i + names - 1]))
        i += names
    return commits, files


def _parse(text: str) -> Any:
    from sprintforecast.storage import _YAML_LOADER

    content = yaml.load(text, Loader=_YAML_LOADER)
    return {} if content is None else content


def _stages(root: Path) -> dict[str, set[int]]:
    """Unmerged files with the stages present (1 = base, 2 = mine, 3 = theirs)."""
    out = _git(root, "ls-files", "-u", "-z", strip=False, check=False)
    stages: dict[str, set[int]] = {}
    for entry in filter(None, out.split("\0")):
        info, _, name = entry.partition("\t")
        stages.setdefault(name, set()).add(int(info.split()[2]))
    return stages


def _stage_text(root: Path, stage: int, file: str) -> str:
    return _git(root, "show", f":{stage}:{file}", strip=False)


# Upper limits of the text view (lines and characters per line), so that a large file does
# not blow up the page.
MAX_DIFF_LINES = 300
MAX_DIFF_COLUMNS = 400


def unified_diff(old: str, new: str, old_name: str, new_name: str) -> str:
    """Line-by-line difference (``diff -u``) of two texts, truncated; empty if equal."""
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), old_name, new_name, lineterm="", n=2
    )
    kept = [line[:MAX_DIFF_COLUMNS] for line in lines]
    if len(kept) > MAX_DIFF_LINES:
        kept = [*kept[:MAX_DIFF_LINES], f"… (+{len(kept) - MAX_DIFF_LINES})"]
    return "\n".join(kept)


def conflict_text_diffs(path: Path, file: str) -> tuple[str, str]:
    """How the file changed on both sides compared to the common state during an open merge,
    as text (``diff -u``): (my side, other side). Empty if that stage does not exist, the
    file is too large or not text."""
    root = _root(path)
    stages = _stages(root).get(file, set())

    def text(stage: int) -> str | None:
        if stage not in stages:
            return None
        size = _git(root, "cat-file", "-s", f":{stage}:{file}", check=False)
        if not size.isdigit() or int(size) > 1_000_000:
            raise ValueError(file)
        return gitmod._git_bytes(root, "show", f":{stage}:{file}").decode("utf-8")

    try:
        base, mine, theirs = text(1), text(2), text(3)
    except ValueError, GitError:
        return "", ""
    shown = base or ""

    def one(side: str | None, label: str) -> str:
        return unified_diff(shown, side or "", f"{file} ({t('common state')})", f"{file} ({label})")

    return one(mine, t("my change")), one(theirs, t("other change"))


def _analyse(
    root: Path, file: str, stages: set[int], choices: dict[tuple[str, ...], str]
) -> tuple[ConflictFile, str | None]:
    """Checks a file: can it be merged at key level? Returns the open value conflicts and,
    if none remain, the merged text."""
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
    except yaml.YAMLError, GitError, ValueError:
        return whole, None
    if conflicts:
        return ConflictFile(file, keys=tuple(conflicts)), None
    from sprintforecast.storage import dump_yaml

    return ConflictFile(file), header_of(ours_text or theirs_text) + dump_yaml(merged)


def pending_conflicts(path: Path) -> list[ConflictFile]:
    """Files of an unfinished merge: with their real value conflicts (empty = can be merged
    automatically) or to be decided as a whole."""
    root = _root(path)
    return [_analyse(root, f, st, {})[0] for f, st in sorted(_stages(root).items())]


def resolve_conflicts(
    path: Path, choices: dict[str, dict[tuple[str, ...], str]] | None = None
) -> list[ConflictFile]:
    """Resolves everything that can be resolved: files without a value conflict automatically,
    the rest according to ``choices`` (file → path → "ours"/"theirs"; path ``()`` = whole
    file). Returns the remaining conflicts. The merge is only completed by :func:`sync`."""
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
            else:  # deleted on this side
                _git(root, "rm", "-q", "--", file)
        elif merged is not None:
            try:
                (root / file).write_text(merged, encoding="utf-8", newline="\n")
            except OSError as e:  # locked or read-only: the merge stays open
                # The kind stays ``locked`` ("A file is locked"): Windows reports a file held
                # by another program as "Permission denied", like a read-only one, and the
                # error number does not reliably tell them apart. Unlike with Git's
                # ``index.lock``, only the hint about the file fits here.
                raise GitError(
                    t(
                        "{file} could not be written ({reason}).",
                        file=file,
                        reason=e.strerror or str(e),
                    ),
                    "locked",
                    gitmod.unwritable_file_hint(),
                ) from e
            _git(root, "add", "--", file)
    gitmod.invalidate_status()
    return pending_conflicts(path)


def _unrelated(root: Path, remote: str | None, upstream: str) -> bool:
    """Do the own state and ``upstream`` lack a common origin? Distinguishes "no common
    ancestor" (return code 1) from real errors (which are raised) and from a shallow clone
    whose truncated history only looks that way: there the full history is fetched first.
    Without an own commit there is nothing that could get mixed up."""
    if not _ref_exists(root, "HEAD"):
        return False
    for attempt in range(2):
        proc = gitmod._git_result(root, "merge-base", "HEAD", upstream)
        if proc.returncode == 0 and proc.stdout.strip():
            return False
        if proc.returncode not in {0, 1}:
            raise gitmod.classify(proc.stderr.strip() or proc.stdout.strip())
        shallow = _git(root, "rev-parse", "--is-shallow-repository", check=False) == "true"
        if attempt == 0 and shallow and remote:
            _git(
                root,
                "fetch",
                "--unshallow",
                "--prune",
                remote,
                network=True,
                url=gitmod.remote_url(root, remote),
            )
            continue
        break
    return True


def _unrelated_error(current: SyncState, target: str) -> GitError:
    return gitmod.UnrelatedHistoriesError(
        gitmod.public_url(current.url) or current.remote or "?", target.split("/", 1)[-1]
    )


def _merge(
    root: Path, upstream: str, path: Path, allow_unrelated: bool = False
) -> list[ConflictFile]:
    """Brings in the server state. On conflicts the merge stays open, everything that can be
    resolved automatically is done; the conflicts for the human are returned (empty = done).
    The own changes are already committed. Unrelated histories are only merged with
    ``allow_unrelated`` (the caller has checked them beforehand)."""
    args = ["merge", "--no-edit"]
    if allow_unrelated:
        args.append("--allow-unrelated-histories")
    try:
        _git(root, *args, upstream)
        return []
    except GitError as e:
        if e.kind not in {"conflict", "error"} or not (_git_dir(root) / "MERGE_HEAD").exists():
            raise
    remaining = resolve_conflicts(path)
    if not remaining:
        gitmod.refuse_staged_conflict_markers(root)
        _git(root, "commit", "--no-edit")
    return remaining


def _conflict_error() -> GitError:
    return GitError(
        t("Merge: conflicts are waiting for your decision."),
        "conflict",
        hint_for("conflict"),
    )


def _error_set(repo_dir: Path, today: date) -> set[tuple[str, str, str]]:
    from sprintforecast.storage import Repository
    from sprintforecast.validate import Level, check_all

    # Without the folder in the text: the comparison of working state against commit runs in
    # different folders, and load errors name the file path.
    prefix = str(repo_dir)

    def relative(text: str) -> str:
        return text.replace(prefix + os.sep, "").replace(prefix, "")

    return {
        (key, relative(i.where), relative(i.message))
        for key, issues in check_all(Repository(repo_dir), today).items()
        for i in issues
        if i.level is Level.ERROR
    }


def _errors_at(root: Path, path: Path, rev: str, today: date) -> set[tuple[str, str, str]]:
    """Errors of the full validation for the state of a commit (without checking it out)."""
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
    """Errors of the full validation in the working state that were not yet present in the
    state ``baseline`` (commit), as readable lines."""
    root = _root(path)
    today = today or date.today()
    found = _error_set(path, today) - _errors_at(root, path, baseline, today)
    return [f"{key}: {where}: {message}" for key, where, message in sorted(found)]


def _ref_exists(root: Path, ref: str) -> bool:
    return bool(_git(root, "rev-parse", "--verify", "--quiet", ref, check=False))


def _unpushed_merges(root: Path, current: SyncState) -> bool:
    # Without a counterpart (never uploaded or removed from the server) there is nothing to
    # compare.
    if not current.upstream or not _ref_exists(root, f"refs/remotes/{current.upstream}"):
        return False
    count = _git(root, "rev-list", "--merges", "--count", f"{current.upstream}..HEAD")
    return count.isdigit() and int(count) > 0


def _sync(
    path: Path,
    message: str,
    tags: list[str] | None = None,
    today: date | None = None,
    allow_invalid: bool = False,
    allow_unrelated: bool = False,
    push: bool = True,
) -> SyncResult:
    """Save and share: commit own changes, fetch and merge those of others, validate,
    upload. Expected errors (offline, rejected, login, conflict …) are in ``result.error``;
    whatever succeeded up to then (e.g. the own commit) is kept. On conflicts the merge stays
    open (``result.conflicts``); after the decision (:func:`resolve_conflicts`) a new call
    resumes. After a merge the full validation runs: new errors prevent the upload, unless
    ``allow_invalid`` is set. If the server has a foreign history without a common origin
    (usually the wrong repository), the function aborts before merging with the error kind
    ``unrelated_histories``; only with ``allow_unrelated`` (explicit confirmation) is it
    merged anyway, after which the usual conflict handling applies. Tags (``tags``) are
    checked before the commit: if a name is invalid or already taken locally, the function
    aborts without committing; missing tags are also created without a new commit. If the
    data folder still has no commit after saving (freshly created, no files), there is
    nothing to share: error kind ``nothing_to_share``. With ``push=False`` ("Pull from
    server") the process ends after the merge: own changes are saved and the server state is
    taken over, but nothing is uploaded or validated."""
    result = SyncResult(pull_only=not push)
    try:
        root = _root(path)
        current = state(path)
        if current.unfinished == "rebase":
            raise GitError(
                t("An earlier operation has not been completed."),
                "merge_in_progress",
                hint_for("merge_in_progress"),
            )
        if current.detached:
            raise GitError(t("No branch selected."), "detached", hint_for("detached"))
        # 0. Resumption: finish an open merge first.
        if current.unfinished == "merge":
            result.conflicts = resolve_conflicts(path)
            if result.conflicts:
                raise _conflict_error()
            gitmod.refuse_staged_conflict_markers(root)
            _git(root, "commit", "--no-edit")
            result.merged = True
        elif current.conflicts:
            raise GitError(
                t("An earlier operation has not been completed."),
                "merge_in_progress",
                hint_for("merge_in_progress"),
            )
        # 1. Secure own changes: first as a commit, then nothing is in danger anymore.
        if pending_changes(path):
            result.committed = gitmod.commit_directory(path, message, tags)
        elif tags:
            _, elsewhere = gitmod.ensure_tags(root, tags, message)
            result.notes += [
                t(
                    (
                        "The tag {tag} points to a different commit than the current version "
                        "and was not moved."
                    ),
                    tag=tag,
                )
                for tag in elsewhere
            ]
        current = state(path)
        if current.remote is None:
            raise GitError(t("No server set up."), "no_remote", hint_for("no_remote"))
        if not _ref_exists(root, "HEAD"):
            # Fresh repository without own data: there is nothing to upload, and a branch
            # without a commit can neither be connected to the server nor pushed (Git would
            # otherwise report "failed to push some refs", which looks like a race).
            raise gitmod.nothing_to_share_error()
        # 2. Fetch server state, 3. merge, 4. validate, 5. upload (retry on a race).
        for attempt in range(MAX_ATTEMPTS):
            current = fetch(path)
            if current.fetch_error is not None:
                raise current.fetch_error
            unrelated = False
            if target := _server_branch(root, current):
                unrelated = _unrelated(root, current.remote, target)
                if unrelated and not allow_unrelated:
                    raise _unrelated_error(current, target)
            if not current.upstream and current.branch:
                current = _adopt_remote_branch(root, current)
            commits, files = incoming(path)
            result.pulled += [c for c in commits if c not in result.pulled]
            result.pulled_files += [f for f in files if f not in result.pulled_files]
            if current.upstream and current.behind:
                result.conflicts = _merge(root, current.upstream, path, unrelated)
                if result.conflicts:
                    raise _conflict_error()
                result.merged = True
                current = state(path)
            if not push:
                if share_mode(root) == SHARE_MERGE_REQUEST:
                    result.notes += _open_merge_request_note(root, path, current)
                break
            if not allow_invalid and _unpushed_merges(root, current):
                found = new_errors(path, current.upstream or "HEAD", today)
                if found:
                    result.validation = found
                    raise GitError(
                        t("The merged data is not valid."),
                        "invalid",
                        hint_for("invalid"),
                    )
            via_mr = share_mode(root) == SHARE_MERGE_REQUEST
            if via_mr and current.upstream and current.ahead:
                current = _drop_merged_commits(root, current)  # e.g. after "squash" in the merge
            if via_mr and tags:
                result.notes.append(
                    t(
                        "Tags are not uploaded with merge requests; share them in the "
                        "“Tags” section after the merge."
                    )
                )
            if via_mr and current.upstream and not current.ahead:
                break  # nothing of our own that would need a merge request
            try:
                if via_mr:
                    result.merge_request_branch, result.merge_request_url = _push_merge_request(
                        root, current, message
                    )
                else:
                    _push(root, current)
            except GitError as e:
                if e.kind == "rejected" and not via_mr and attempt + 1 < MAX_ATTEMPTS:
                    continue
                raise
            result.pushed = True
            result.notes += _tag_notes(root, current, tags or [])
            break
    except GitError as e:
        result.error = e
    finally:
        gitmod.invalidate_status()
    return result


def sync(path: Path, *args: Any, **kwargs: Any) -> SyncResult:
    """Save and share (see :func:`_sync`); never runs at the same time as a fetch."""
    try:
        with _locked(path):
            return _sync(path, *args, **kwargs)
    except GitError as e:
        if e.kind != "sync_busy":
            raise
        return SyncResult(error=e)


def _server_branch(root: Path, current: SyncState) -> str | None:
    """The server state for the current branch (e.g. ``origin/main``), if there is one: the
    connected upstream or, before the first connection, the branch of the same name."""
    candidate = current.upstream or (
        f"{current.remote}/{current.branch}" if current.remote and current.branch else None
    )
    if candidate and _ref_exists(root, f"refs/remotes/{candidate}"):
        return candidate
    return None


def _adopt_remote_branch(root: Path, current: SyncState) -> SyncState:
    """If the server already has the branch but this computer has not yet connected it to the
    server (e.g. a repository started separately), it is connected now. Afterwards the server
    state is merged as usual."""
    candidate = f"{current.remote}/{current.branch}"
    if current.remote and _ref_exists(root, f"refs/remotes/{candidate}"):
        _git(root, "branch", f"--set-upstream-to={candidate}")
        return state(root)
    return current


def _git_ok(root: Path, *args: str) -> bool:
    return gitmod._git_result(root, *args).returncode == 0


def _tag_notes(root: Path, current: SyncState, tags: list[str]) -> list[str]:
    """Notes on tags that ``push --follow-tags`` did not publish: the name is already used on
    the server for a different state (two people tagged the same sprint); the tag stays
    unchanged there, locally it points to the own state."""
    notes: list[str] = []
    if not tags or not current.remote:
        return notes
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
    for tag in tags:
        local = gitmod.tag_commit(root, tag)
        if not local:
            continue
        if local != head and not _git_ok(root, "merge-base", "--is-ancestor", local, "HEAD"):
            notes.append(
                t(
                    (
                        "The tag {tag} points to a different commit that is not part of the "
                        "current version; it was not moved."
                    ),
                    tag=tag,
                )
            )
            continue
        try:
            out = _git(root, "ls-remote", "--tags", current.remote, f"refs/tags/{tag}",
                       f"refs/tags/{tag}^{{}}", network=True, url=current.url)  # fmt: skip
        except GitError:
            continue  # without an answer from the server nothing can be said
        refs = {}
        for line in out.splitlines():
            sha, _, ref = line.partition("\t")
            refs[ref] = sha
        remote = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
        if remote and remote != local:
            notes.append(
                t(
                    (
                        "The tag {tag} is already used on the server for a different version "
                        "and was not overwritten. On this computer it points to your own "
                        "version."
                    ),
                    tag=tag,
                )
            )
        elif not remote:
            notes.append(t("The tag {tag} could not be transferred to the server.", tag=tag))
    return notes


def _drop_merged_commits(root: Path, current: SyncState) -> SyncState:
    """If the own state has the same content as the server (the merge request is merged, e.g.
    as a "squash" with a new commit), this resets the branch to the server state: otherwise it
    would stay "ahead" forever and every share would create an empty merge request. ``--keep``
    aborts where something would be lost."""
    if _git_ok(root, "diff", "--quiet", current.upstream or "HEAD", "HEAD", "--") and _git_ok(
        root, "diff", "--quiet", "--cached"
    ):
        _git(root, "reset", "--keep", current.upstream or "HEAD", check=False)
        return state(root)
    return current


def share_mode(path: Path) -> str:
    """``"direct"`` (default) or ``"merge_request"``: where "Save and share" uploads to."""
    root = _root(path)
    value = _git(root, "config", "--local", "--get", SHARE_KEY, check=False)
    return value if value == SHARE_MERGE_REQUEST else SHARE_DIRECT


def _open_merge_request_note(root: Path, path: Path, current: SyncState) -> list[str]:
    """Note for "Pull from server" in merge request mode: if own changes are not yet in the
    main branch, it says whether they are in an open merge request (the own branch is on the
    server and contains the state) or have not been shared at all. Content that is already in
    the main branch (merged, e.g. as a "squash") does not count."""
    if current.upstream and current.ahead:
        current = _drop_merged_commits(root, current)
    if not (current.upstream and current.ahead):
        return []
    branch = (current.upstream).partition("/")[2] or "main"
    mr_ref = f"refs/remotes/{current.remote or 'origin'}/{merge_request_branch(root)}"
    if _ref_exists(root, mr_ref) and _git_ok(root, "merge-base", "--is-ancestor", "HEAD", mr_ref):
        return [
            t(
                (
                    "Your merge request is still open: your changes are not in {branch} on the "
                    "server yet. Pull again after the merge."
                ),
                branch=branch,
            )
        ]
    if host_kind(root) == HOST_FORGEJO:
        # The pull request is not on a branch of its own that could be seen here.
        return [
            t(
                (
                    "Your changes are not in {branch} on the server yet. If they are in an "
                    "open pull request, fetch them again after the merge."
                ),
                branch=branch,
            )
        ]
    return [
        t(
            (
                "Your changes are not shared yet (not in {branch}, no merge request on the "
                "server). “Save and share” creates it."
            ),
            branch=branch,
        )
    ]


def auto_merge(path: Path) -> bool:
    """Should the merge request merge automatically once the pipeline is green? Default: yes."""
    root = _root(path)
    return _git(root, "config", "--local", "--get", AUTO_MERGE_KEY, check=False) != "false"


def set_auto_merge(path: Path, enabled: bool) -> None:
    root = _root(path)
    if enabled:
        _git(root, "config", "--local", "--unset-all", AUTO_MERGE_KEY, check=False)
    else:
        _git(root, "config", "--local", AUTO_MERGE_KEY, "false")


def set_share_mode(path: Path, mode: str) -> None:
    root = _root(path)
    if mode == SHARE_MERGE_REQUEST:
        _git(root, "config", "--local", SHARE_KEY, mode)
    else:
        _git(root, "config", "--local", "--unset-all", SHARE_KEY, check=False)


def detect_host(url: str) -> str:
    """Which kind of server is behind the address, as far as the name reveals it (GitHub,
    GitLab, Forgejo/Gitea/Codeberg); everything else is ``generic``."""
    name = (_web_location(url) or ("", ""))[0].lower()
    if name == "github.com" or name.startswith("github."):
        return HOST_GITHUB
    if "gitlab" in name:
        return HOST_GITLAB
    if name == "codeberg.org" or any(word in name for word in ("forgejo", "gitea")):
        return HOST_FORGEJO
    return HOST_GENERIC


def _web_location(url: str) -> tuple[str, str] | None:
    """Host name and path without ``.git`` from a server address (https, ssh or scp form);
    ``None`` for a folder path."""
    found = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url)
    if not found:
        found = re.match(r"^(?:[^@/\s]+@)?([^/:\s]+):(?!//)(.+?)(?:\.git)?/?$", url)
    return (found.group(1), found.group(2)) if found else None


def host_setting(path: Path) -> str | None:
    """The explicitly chosen server kind (``None``: detect automatically from the address)."""
    value = _git(_root(path), "config", "--local", "--get", HOST_KEY, check=False)
    return value if value in HOSTS else None


def set_host(path: Path, host: str | None) -> None:
    root = _root(path)
    if host in HOSTS:
        _git(root, "config", "--local", HOST_KEY, host)
    else:
        _git(root, "config", "--local", "--unset-all", HOST_KEY, check=False)


def host_kind(path: Path) -> str:
    """The kind of server: the chosen one or, as long as none is chosen, the detected one."""
    return host_setting(path) or detected_host(path)


def detected_host(path: Path) -> str:
    """The kind detected from the server's address, regardless of any choice."""
    root = _root(path)
    return detect_host(gitmod.remote_url(root, state(root).remote or "origin"))


def compare_url(url: str, target: str, branch: str) -> str | None:
    """The web address where a pull request is opened from the branch on GitHub."""
    where = _web_location(url)
    if not where or len(where[0]) == 1:  # drive letter like ``C:\\x``, not a host
        return None
    host, repo = where
    return f"https://{host}/{repo}/compare/{target}...{branch}?expand=1"


def merge_request_branch(root: Path) -> str:
    """The branch this person uploads to for merge requests: a fixed name per person
    (``sprintforecast/<name>-<short hash of the address>``), so that another share updates the
    same merge request and two people with the same name prefix do not collide."""
    email = _git(root, "config", "--get", "user.email", check=False).strip().lower()
    who = email.partition("@")[0] or _git(root, "config", "--get", "user.name", check=False)
    slug = re.sub(r"[^a-z0-9_-]+", "-", who.lower()).strip("-_") or "user"
    tag = hashlib.sha1((email or who).encode("utf-8")).hexdigest()[:6]
    return f"sprintforecast/{slug}-{tag}"


def _push_merge_request(root: Path, current: SyncState, title: str) -> tuple[str, str | None]:
    """Uploads the state for review by others, depending on the server:

    - GitLab (and unknown servers): to the own branch, with push options so that the server
      creates or updates the merge request (and merges by itself on request).
    - Forgejo/Gitea/Codeberg: AGit flow (``refs/for/<target>``), the pull request is created
      on push; if that does not work, the branch stays.
    - GitHub: the own branch; the app has no access token, it names the address where the
      pull request can be opened.

    The branch belongs to this person: if it has diverged after a rebase in the merge request
    or a merged state, it is overwritten with ``--force-with-lease``. Tags are not pushed
    (otherwise they would point to commits that never reach the main branch).
    Returns the branch and, if known, the address of the merge/pull request."""
    branch = merge_request_branch(root)
    host = host_kind(root)
    ref = f"refs/heads/{branch}"
    remote = current.remote or "origin"
    target = (current.upstream or "").partition("/")[2] or current.branch or "main"
    subject = (title.strip().splitlines() or [t("Changes")])[0]
    if host == HOST_FORGEJO:
        proc = gitmod._git_result(
            root,
            "push",
            "-o", f"topic={branch}",
            "-o", f"title={subject}",
            "-o", "force-push=true",
            remote,
            f"HEAD:refs/for/{target}",
            network=True,
        )  # fmt: skip
        if proc.returncode == 0:
            found = _PR_URL.search(proc.stderr + proc.stdout)
            return branch, found.group(0).rstrip(".,)") if found else None
    listed = _git(root, "ls-remote", remote, ref, network=True, url=current.url, check=False)
    lease = (
        f"--force-with-lease={ref}:{listed.split()[0]}" if listed else f"--force-with-lease={ref}:"
    )
    options: list[str] = []
    if host in (HOST_GITLAB, HOST_GENERIC):
        options = [
            "-o", "merge_request.create",
            "-o", f"merge_request.target={target}",
            "-o", f"merge_request.title={subject}",
            "-o", "merge_request.remove_source_branch",
            # Newer GitLab versions also know ``merge_request.auto_merge`` (same effect).
            *(["-o", "merge_request.merge_when_pipeline_succeeds"] if auto_merge(root) else []),
        ]  # fmt: skip
    proc = gitmod._git_result(root, "push", lease, *options, remote, f"HEAD:{ref}", network=True)
    message = proc.stderr.strip() or proc.stdout.strip()
    if proc.returncode != 0 and options and "does not support push options" in message:
        if host == HOST_GITLAB:
            raise GitError(
                t(
                    "The server does not support push options, so sharing via merge "
                    "request is not possible. Please switch the setting off on the “Data "
                    "folder” page."
                )
            )
        # Not GitLab: only upload the branch, the pull request is opened on the server.
        proc = gitmod._git_result(root, "push", lease, remote, f"HEAD:{ref}", network=True)
        message = proc.stderr.strip() or proc.stdout.strip()
    if proc.returncode != 0:
        raise gitmod.classify(message, url=current.url, cwd=root)
    found = _PR_URL.search(proc.stderr + proc.stdout)
    if found:
        return branch, found.group(0).rstrip(".,)")
    if host == HOST_GITHUB:
        return branch, compare_url(current.url, target, branch)
    return branch, None


def _push(root: Path, current: SyncState) -> None:
    if current.upstream:
        _git(root, "push", "--follow-tags", network=True, url=current.url)
        return
    # First push: connect the branch to the server.
    _git(
        root,
        "push",
        "--follow-tags",
        "-u",
        current.remote or "origin",
        current.branch or "HEAD",
        network=True,
        url=current.url,
    )


def restore_file(path: Path, file: Path) -> None:
    """Restores a file to the last saved (committed) state."""
    root = _root(path)
    _git(root, "checkout", "HEAD", "--", str(file.resolve()))
    gitmod.invalidate_status()


def abort_unfinished(path: Path) -> None:
    """Aborts an unfinished merge (or rebase); own committed changes stay unchanged."""
    root = _root(path)
    current = state(path)
    if current.unfinished == "merge" or (current.conflicts and current.unfinished is None):
        _git(root, "merge", "--abort")
    elif current.unfinished == "rebase":
        _git(root, "rebase", "--abort")
    gitmod.invalidate_status()


class Reattached(NamedTuple):
    """Result of :func:`reattach`: the branch the data folder is now on, and the rescue branch
    holding saved work (``None`` = nothing was saved). ``commits``: the commits of the
    detached state are there; ``changes``: the open changes in the data folder are there too
    (as a commit of their own)."""

    branch: str
    rescue: str | None = None
    commits: bool = False
    changes: bool = False


def _reattach_hint(saved: str | None = None) -> str:
    """Next step when switching back to the branch fails because of open changes. Those in
    the data folder are saved by :func:`reattach` itself; what remains are changes outside it,
    which the app does not touch. Never gives instructions on settings. ``saved`` is the
    rescue branch that already holds the changes in the data folder."""
    text = t(
        "Switching back to the branch would overwrite open changes that lie outside the "
        "data folder. The app only touches the data folder. The way out: save or discard "
        "the changes in Git outside the data folder (Git client or terminal; ask whoever "
        "looks after the computer if needed) and then choose “Back to the branch” again. "
        "The files are named in the message from Git under “Technical message”."
    )
    if saved:
        text = _saved_note(saved) + " " + text
    return text


def _saved_note(rescue: str) -> str:
    """Sentence naming the rescue branch that holds the changes in the data folder."""
    return t(
        "The open changes in the data folder are already saved on the rescue branch {rescue}.",
        rescue=rescue,
    )


_SAVE_SUBJECT = "Open changes saved before the switch"
_LEGACY_SAVE_SUBJECT = "Offene Änderungen vor dem Wechsel gesichert"  # commits of older versions
_SAVE_SUBJECTS = (_SAVE_SUBJECT, _LEGACY_SAVE_SUBJECT)
_RESCUE_PREFIX = "rescue-"
_RESCUE_PREFIXES = (_RESCUE_PREFIX, "rettung-")  # older versions named the branches "rettung-"


def _save_open_changes(root: Path, path: Path, rescue: str | None) -> str:
    """Commits the open changes in the data folder on a rescue branch and returns its name.
    ``rescue`` is an existing rescue branch at this point (``None`` = create a new one). If
    committing fails (identity, spreadsheets, conflict markers …), the repository is back in
    the detached state as before."""
    start = _git(root, "rev-parse", "HEAD")
    index = _git(root, "write-tree")  # the user's staged state, for the rollback
    name = rescue or f"{_RESCUE_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}"
    if rescue:
        _git(root, "switch", rescue)
    else:
        _git(root, "switch", "-c", name)
    try:
        gitmod.commit_directory(path, _SAVE_SUBJECT)
    except GitError, OSError:
        try:
            # Restore the index exactly as before (``git add`` changed it; the working tree
            # stays untouched) and go back to the detached state; HEAD never stays on the new
            # rescue branch.
            _git(root, "read-tree", index, check=False)
            _git(root, "switch", "--detach", start)
            if rescue is None:
                _git(root, "branch", "-D", name)
        finally:
            gitmod.invalidate_status()
        raise
    return name


def _saved_before(root: Path, holders: list[str]) -> bool | None:
    """Is HEAD on the backup of an earlier attempt of :func:`reattach` (commit
    ``Open changes saved before the switch``, only on rescue branches)? If so: were
    there commits on no branch before it (``True``) or not (``False``)? Otherwise ``None``."""
    if not holders or not all(b.startswith(_RESCUE_PREFIXES) for b in holders):
        return None
    if _git(root, "log", "-1", "--format=%s", "HEAD", check=False) not in _SAVE_SUBJECTS:
        return None
    # Go back through the whole chain of backups (several attempts): only the first other
    # commit shows whether the detached state had commits of its own.
    depth = 1
    while _git(root, "log", "-1", "--format=%s", f"HEAD~{depth}", check=False) in _SAVE_SUBJECTS:
        depth += 1
    parent = _git(
        root, "branch", "--contains", f"HEAD~{depth}", "--format=%(refname:short)", check=False
    )
    return all(b.startswith(_RESCUE_PREFIXES) for b in parent.splitlines() if not b.startswith("("))


def reattach(path: Path) -> Reattached:
    """Goes from "detached HEAD" back to the main branch. If commits are on no branch, they
    are saved on a rescue branch first, as are the open changes in the data folder (as a
    commit of their own there). If the switch fails because of changes outside the data
    folder, the rescue branch remains and is named again on the next attempt."""
    root = _root(path)
    if state(path).branch is not None:
        raise GitError(t("The repository is already on a branch."))
    default = _git(root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", check=False)
    candidates = [default.split("/", 1)[-1]] if default else []
    candidates += ["main", "master"]
    local = set(_git(root, "branch", "--format=%(refname:short)").split())
    target = next((c for c in candidates if c in local), None)
    if target is None:
        raise GitError(
            t("No main branch found (main or master)."),
            "detached",
            t("Please use a Git client or a terminal."),
        )
    contains = _git(root, "branch", "--contains", "HEAD", "--format=%(refname:short)", check=False)
    holders = [b for b in contains.splitlines() if not b.startswith("(")]
    rescue = None
    commits = False
    if not holders:
        commits = True
        rescue = f"{_RESCUE_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}"
    elif all(b.startswith(_RESCUE_PREFIXES) for b in holders):  # saved by an earlier attempt
        commits = True
        rescue = holders[0]
    new_changes = bool(gitmod.changes_in(path))
    earlier = _saved_before(root, holders)  # backup from an earlier attempt
    if earlier is not None:
        commits = earlier
    if new_changes:
        # Commit on the rescue branch (an existing one at this point, otherwise a new one).
        rescue = _save_open_changes(root, path, rescue if holders else None)
        saved_at = _git(root, "rev-parse", "HEAD")
    elif rescue and not holders:
        _git(root, "branch", rescue)
    changes = new_changes or earlier is not None
    try:
        _git(root, "switch", target)
    except GitError as e:
        if new_changes:  # detached again on the backup: the next attempt finds it
            _git(root, "switch", "--detach", saved_at)
        gitmod.invalidate_status()
        saved = rescue if changes else None
        if e.kind != "dirty":
            if saved:  # do not hide where the changes were saved
                e.hint = _saved_note(saved) + (" " + e.hint if e.hint else "")
            raise
        raise GitError(str(e), "detached", _reattach_hint(saved), e.raw) from e
    gitmod.invalidate_status()
    return Reattached(target, rescue, commits, changes)


class Branch(NamedTuple):
    """A branch that can be switched to: ``local`` = exists in the data folder, ``remote`` =
    the server has it too (a remote-only branch is created as a local one when switching)."""

    name: str
    local: bool
    remote: bool
    current: bool = False


def branches(path: Path) -> list[Branch]:
    """Local and remote branches (as known since the last fetch), the current one first,
    then alphabetically."""
    root = _root(path)
    current = state(path)
    local = {
        n
        for n in _git(root, "branch", "--format=%(refname:short)").splitlines()
        if n and not n.startswith("(")  # "(HEAD detached at …)"
    }
    remote: set[str] = set()
    if current.remote:
        prefix = f"{current.remote}/"
        refs = _git(root, "branch", "-r", "--format=%(refname:short)", check=False).split()
        remote = {r[len(prefix) :] for r in refs if r.startswith(prefix)} - {"HEAD"}
    found = [Branch(n, n in local, n in remote, n == current.branch) for n in local | remote]
    return sorted(found, key=lambda b: (not b.current, b.name))


def switch_branch(path: Path, name: str) -> str:
    """Switches the data folder to branch ``name`` (a remote-only one is created locally and
    follows the server). Refuses while the data folder has open changes: nothing is saved or
    discarded implicitly. Returns the name of the branch."""
    root = _root(path)
    current = state(path)
    if current.unfinished or current.conflicts:
        raise GitError(hint_for("conflict"), "conflict")
    if gitmod.changes_in(path):
        raise GitError(
            t("There are open changes. Commit or discard them before switching the branch.")
        )
    found = {b.name: b for b in branches(path)}
    if name not in found:
        raise GitError(t("Branch {name} not found.", name=name))
    with _locked(path):
        if found[name].local:
            _git(root, "switch", name)
        else:  # explicit remote: git's guessing fails with several servers having the name
            _git(root, "switch", "-c", name, "--track", f"{current.remote}/{name}")
    gitmod.invalidate_status()
    return name


def set_identity(name: str, email: str) -> None:
    """Stores name and email address for commits (global for the user)."""
    if not name.strip() or "@" not in email:
        raise GitError(t("Please enter a name and a valid email address."))
    _git(Path.home(), "config", "--global", "user.name", name.strip())
    _git(Path.home(), "config", "--global", "user.email", email.strip())


# --- Set up the server (remote) ------------------------------------------------------------

# Valid name of a server (remote); only then is it touched.
_REMOTE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class RemoteInfo:
    """The server set up for a data folder (determined locally, without network).

    ``url`` is the display version (without credentials), ``has_secret`` says that the stored
    address contains some. ``others`` are further servers, which are never changed.
    ``special`` names settings the app does not touch: ``multi_url`` (several addresses),
    ``pushurl`` (own upload address) or ``name`` (unusual name). ``branch`` is the local
    branch (``None`` = detached HEAD), ``unborn`` says that there is no commit yet (a freshly
    created repository)."""

    root: Path
    name: str | None
    url: str
    has_secret: bool
    others: tuple[str, ...]
    special: str
    branch: str | None
    unborn: bool = False


def remote_info(path: Path) -> RemoteInfo:
    """Server of the data folder including special cases (see :class:`RemoteInfo`)."""
    root = _root(path)
    current = state(path)
    name = current.remote
    remotes = _git(root, "remote", check=False).split()
    urls: list[str] = []
    special = ""
    if name is not None:
        if not _REMOTE_NAME.fullmatch(name):
            special = "name"
        else:
            urls = _git(root, "config", "--get-all", f"remote.{name}.url", check=False).splitlines()
            if len(urls) > 1:
                special = "multi_url"
            elif _git(root, "config", "--get-all", f"remote.{name}.pushurl", check=False):
                special = "pushurl"
    return RemoteInfo(
        root=root,
        name=name,
        url=gitmod.public_url(current.url) if name else "",
        has_secret=any(gitmod.has_credentials(u) for u in urls or [current.url]),
        others=tuple(r for r in remotes if r != name),
        special=special,
        branch=current.branch,
        unborn=current.unborn,
    )


_INFO_CACHE: dict[Path, tuple[float, RemoteInfo]] = {}
gitmod.on_invalidate(_INFO_CACHE.clear)


def cached_remote_info(path: Path) -> RemoteInfo:
    """Like :func:`remote_info`, but cached briefly (for the UI, which redraws on every
    input); invalidated by :func:`sprintforecast.git.invalidate_status`."""
    key = path.resolve()
    cached = _INFO_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATE_TTL:
        return cached[1]
    info = remote_info(path)
    _INFO_CACHE[key] = (time.monotonic(), info)
    return info


@dataclass(frozen=True)
class RemoteCheck:
    """Result of the connection check: checked address, branches of the server (all that fit
    the query limit, see :func:`~sprintforecast.git.probe_remote`; truncated only when
    displayed) and local branch (``None`` = detached HEAD). ``unborn``: the data folder has
    no commit yet."""

    address: gitmod.RemoteAddress
    heads: tuple[str, ...]
    branch: str | None
    unborn: bool = False

    @property
    def empty(self) -> bool:
        """The server is reachable but has no branch yet."""
        return not self.heads

    @property
    def branch_missing(self) -> bool:
        """The server has branches, but not the local one: the first upload creates it."""
        return bool(self.heads) and self.branch is not None and self.branch not in self.heads


def check_remote(
    path: Path,
    raw: str,
    *,
    allow_insecure: bool = False,
    timeout: float = gitmod.PROBE_TIMEOUT,
) -> RemoteCheck:
    """Checks a server address (format and connection, ``git ls-remote``) and writes nothing.
    Raises only :class:`GitError`."""
    root = _root(path)
    address = gitmod.parse_remote_url(raw, allow_insecure=allow_insecure)
    info = remote_info(root)
    heads = gitmod.probe_remote(root, address, timeout, info.branch)
    return RemoteCheck(address, heads, info.branch, info.unborn)


@dataclass(frozen=True)
class RemoteSaved:
    """Result of :func:`set_remote`: name of the server, display version of the address and
    whether the connection could be checked (``False`` = explicitly saved unchecked)."""

    name: str
    url: str
    verified: bool


def set_remote(
    path: Path,
    raw: str,
    *,
    allow_insecure: bool = False,
    accept_new_branch: bool = False,
    allow_offline: bool = False,
    timeout: float = gitmod.PROBE_TIMEOUT,
) -> RemoteSaved:
    """Sets the address of the server (name as before, otherwise ``origin``), after a renewed
    check in the backend, since the UI is not considered trustworthy. It is saved only after
    a passed check; two exceptions apply only with explicit confirmation: ``allow_offline``
    (server unreachable) and ``accept_new_branch`` (the server has branches, but not the
    local one). On login problems, repository not found and other errors nothing is ever
    saved. Blocked are an open merge, several addresses, an own upload address and an unusual
    server name; nothing is cleaned up. No fetch, no credentials, nothing global."""
    root = _root(path)
    address = gitmod.parse_remote_url(raw, allow_insecure=allow_insecure)
    if state(path).unfinished:
        raise GitError(
            t("The server cannot be changed while a merge is open."),
            "merge_in_progress",
        )
    info = remote_info(root)
    if info.special:
        raise gitmod.remote_special_error()
    verified = True
    try:
        check = check_remote(root, address.url, allow_insecure=allow_insecure, timeout=timeout)
    except GitError as e:
        if e.kind != "offline" or not allow_offline:
            raise
        verified = False
    else:
        if check.branch_missing and not accept_new_branch:
            raise gitmod.new_branch_error(check.branch or "", check.heads, check.unborn)
    name = info.name or "origin"
    try:
        if info.name is None:
            _git(root, "remote", "add", "--", name, address.url)
        else:
            _git(root, "remote", "set-url", name, "--", address.url)
    finally:
        _FETCHED.pop(root, None)  # the state of the old server no longer applies
        gitmod.invalidate_status()
    return RemoteSaved(name, gitmod.public_url(address.url), verified)
