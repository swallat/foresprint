# SPDX-License-Identifier: EUPL-1.2
"""Changes to the YAML data as value changes (read-only).

:func:`diff_values` compares two loaded YAML values and returns a :class:`ValueChange` with
path, old and new value for each changed value. Lists of objects with ``id`` (people,
products) are compared per entry, all other lists as one value, as in merging
(:mod:`sprintforecast.yamlmerge`); unlike there, where the ``prognoses`` are united via
``at``, this list also counts as one value here. :func:`file_changes` compares the working
state with the last commit.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from stat import S_ISREG
from typing import Any

import yaml

from sprintforecast import git as gitmod
from sprintforecast.git import Change, GitError, changes_in
from sprintforecast.gitsync import _parse, unified_diff
from sprintforecast.yamlmerge import MISSING, keyed

# Upper limit for compared nodes per file: two separately loaded trees made of YAML aliases
# (small file, huge tree) would otherwise compute for an arbitrarily long time.
MAX_NODES = 200_000


class TooComplex(ValueError):
    """The file is too nested or too large to compare."""


class _Budget:
    def __init__(self, left: int = MAX_NODES) -> None:
        self.left = left

    def spend(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise TooComplex("too many nodes")


def _same(a: Any, b: Any, budget: _Budget) -> bool:
    """Like :func:`sprintforecast.yamlmerge.same`, but with a shortcut for the same object and
    with an upper limit (only for this view; merging stays unchanged)."""
    # Count first, then shortcut: singletons (null, true, small numbers) are often the same
    # object in separately loaded trees, and otherwise a file with very many entries would
    # bypass the limit.
    budget.spend()
    if a is b:
        return True
    if a is MISSING or b is MISSING:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], budget) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y, budget) for x, y in zip(a, b, strict=True))
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True
    return a == b


ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"

_YAML_SUFFIXES = {".yaml", ".yml"}
# Larger files count as unreadable: they may come from a foreign repository.
_MAX_BYTES = 1024 * 1024  # per file (team data is small; parsing costs about 1 s per MiB)
_BYTES_BUDGET = 4 * 1024 * 1024  # sum of the sizes read (HEAD and working state) per computation
_EVAL_LIMIT = 25  # this many files are evaluated: the ones the UI shows
MAX_VALUES = 30  # this many value changes per file are kept (the rest is counted)
# Kept values are shortened to an excerpt slightly above the display limits (``web.ui``: 1000
# items and characters, 5000 nodes, depth 8): it then shows the same as the whole value would,
# and the cache holds no large subtrees of the documents.
_SLIM_ITEMS = 1001
_SLIM_NODES = 6000
_SLIM_DEPTH = 9


def _slim(value: Any, left: list[int], depth: int = 0) -> Any:
    left[0] -= 1
    if left[0] < 0 or depth > _SLIM_DEPTH:
        return "…"
    if isinstance(value, str):
        return value[:_SLIM_ITEMS]
    if isinstance(value, dict):
        return {
            (k[:_SLIM_ITEMS] if isinstance(k, str) else k): _slim(v, left, depth + 1)
            for k, v in islice(value.items(), _SLIM_ITEMS)
        }
    if isinstance(value, list):
        return [_slim(v, left, depth + 1) for v in value[:_SLIM_ITEMS]]
    if isinstance(value, (set, frozenset)):
        return set(islice(value, _SLIM_ITEMS))
    return value


# Problems of Git itself (not of the one file) are seen by callers instead of appearing as
# "not readable".
_GIT_PROBLEMS = {"git_missing", "unsafe_directory", "offline"}


@dataclass(frozen=True)
class ValueChange:
    """A value under ``path``; ``MISSING`` means "not present"."""

    path: tuple[str, ...]
    old: Any
    new: Any

    @property
    def kind(self) -> str:
        if self.old is MISSING:
            return ADDED
        if self.new is MISSING:
            return REMOVED
        return CHANGED

    @property
    def label(self) -> str:
        return ".".join(self.path) or "."


@dataclass(frozen=True)
class FileChange:
    """The changes of a file. ``values`` is empty if the file is not readable YAML
    (``readable`` False) or only the file as a whole is new, deleted or renamed."""

    file: str  # relative to the repository root
    status: str  # wie :attr:`sprintforecast.git.Change.status`
    values: tuple[ValueChange, ...] = ()
    readable: bool = True
    orig: str = ""  # previous path for renames and copies, relative to the root
    skipped: bool = False  # not evaluated: total budget of file sizes used up
    omitted: int = 0  # more value changes beyond :data:`MAX_VALUES` (not kept)


def diff_values(
    old: Any, new: Any, path: tuple[str, ...] = (), _budget: _Budget | None = None
) -> list[ValueChange]:
    """All differences between ``old`` and ``new`` in key order.

    If only the order of the entries changes in lists with ``id``, one change is reported
    under the path of the list, with the ``id`` values before and after. Trees with more than
    :data:`MAX_NODES` nodes to compare raise :class:`TooComplex`."""
    budget = _budget if _budget is not None else _Budget()
    if _same(old, new, budget):
        return []
    if isinstance(old, dict) and isinstance(new, dict):
        return _diff_mapping(old, new, path, False, budget)
    keyed_old, keyed_new = keyed(old), keyed(new)
    # An empty list is the empty mapping if the other side contains objects with id (first
    # object added, last removed): that keeps the path [id].
    if keyed_old is None and old == [] and keyed_new is not None:
        keyed_old = {}
    if keyed_new is None and new == [] and keyed_old is not None:
        keyed_new = {}
    if keyed_old is not None and keyed_new is not None:
        changes = _diff_mapping(keyed_old, keyed_new, path, True, budget)
        order_old = [k for k in keyed_old if k in keyed_new]
        order_new = [k for k in keyed_new if k in keyed_old]
        if order_old != order_new:
            changes.append(ValueChange(path, list(keyed_old), list(keyed_new)))
        return changes
    return [ValueChange(path, old, new)]


def _key_text(key: Any) -> str:
    """Key in the file's spelling (``null``, ``true``), not Python's."""
    if key is None:
        return "null"
    if isinstance(key, bool):
        return "true" if key else "false"
    return str(key)


def _diff_mapping(
    old: dict[Any, Any], new: dict[Any, Any], path: tuple[str, ...], item: bool, budget: _Budget
) -> list[ValueChange]:
    changes: list[ValueChange] = []
    for key in [*old, *(k for k in new if k not in old)]:
        text = _key_text(key)
        sub = (*path, f"[{text}]" if item else text)
        changes.extend(diff_values(old.get(key, MISSING), new.get(key, MISSING), sub, budget))
    return changes


class _Skipped(Exception):
    """The total budget of file sizes is used up: the file is not evaluated."""


class _Sizes:
    """Sum of the file sizes read in one computation."""

    def __init__(self, left: int) -> None:
        self.left = left

    def charge(self, size: int) -> None:
        self.left -= size
        if self.left < 0:
            raise _Skipped


def _load(text: str) -> Any:
    """Loads YAML once a cheap estimate of the nodes (lines, colons, commas) is within the
    limit: otherwise parsing is not worth it, the comparison refuses."""
    if text.count("\n") + text.count(":") + text.count(",") > MAX_NODES:
        raise TooComplex("too large")
    return _parse(text)


def _head_text(root: Path, file: str, sizes: _Sizes | None = None) -> str:
    size = int(gitmod._git(root, "cat-file", "-s", f"HEAD:{file}"))
    if size > _MAX_BYTES:
        raise ValueError(file)
    if sizes:
        sizes.charge(size)
    return gitmod._git_bytes(root, "show", f"HEAD:{file}").decode("utf-8")


def _work_text(root: Path, file: str, sizes: _Sizes | None = None) -> str:
    """Content in the working tree; ``FileNotFoundError`` if the file is missing. Symlinks are
    not followed: the target may lie outside the repository. Ordinary files only."""
    path = root / file
    if path.is_symlink():
        raise ValueError(file)
    stat = path.stat()
    if stat.st_size > _MAX_BYTES or not S_ISREG(stat.st_mode):
        raise ValueError(file)
    if sizes:
        sizes.charge(stat.st_size)
    return path.read_text(encoding="utf-8")


def _file_change(root: Path, change: Change, sizes: _Sizes | None = None) -> FileChange:
    file, status = change.file, change.status
    orig = change.orig
    unreadable = FileChange(file, status, readable=False, orig=orig)
    if any(Path(f).suffix.lower() not in _YAML_SUFFIXES for f in (file, change.orig or file)):
        return unreadable
    old: Any = MISSING
    new: Any = MISSING
    try:
        if "A" not in status and status != "??":
            old = _load(_head_text(root, change.orig or file, sizes))
        with contextlib.suppress(FileNotFoundError):  # deleted, also "deleted by them"
            new = _load(_work_text(root, file, sizes))
        if old is MISSING or new is MISSING:
            return FileChange(file, status, orig=orig)
        found = diff_values(old, new)
        kept = tuple(
            ValueChange(v.path, _slim(v.old, [_SLIM_NODES]), _slim(v.new, [_SLIM_NODES]))
            for v in found[:MAX_VALUES]
        )
        return FileChange(file, status, kept, orig=orig, omitted=max(0, len(found) - MAX_VALUES))
    except GitError as e:
        if e.kind in _GIT_PROBLEMS:
            raise
        return unreadable
    except _Skipped:
        return FileChange(file, status, orig=orig, skipped=True)
    except yaml.YAMLError, ValueError, OSError, RecursionError:  # ValueError: also Unicode
        return unreadable


def text_diff(path: Path, change: Change) -> str:
    """Difference of an uncommitted file from the last commit as text (``diff -u``), also
    for files without a value view such as the logs. Empty if the file is too large, not
    text or not readable."""
    root = gitmod.require_root(path)
    file, status = change.file, change.status
    old = new = ""
    try:
        if "A" not in status and status != "??":
            old = _head_text(root, change.orig or file)
        with contextlib.suppress(FileNotFoundError):  # deleted
            new = _work_text(root, file)
    except GitError as e:
        if e.kind in _GIT_PROBLEMS:
            raise
        return ""
    except ValueError, OSError:  # too large, not text, symlink
        return ""
    return unified_diff(old, new, f"a/{change.orig or file}", f"b/{file}")


def file_changes(path: Path) -> list[FileChange]:
    """Uncommitted changes below ``path`` as value changes per file."""
    root = gitmod.require_root(path)
    sizes = _Sizes(_BYTES_BUDGET)
    # Only the first files are evaluated; the rest come without values (readable).
    return [
        _file_change(root, c, sizes)
        if i < _EVAL_LIMIT
        else FileChange(c.file, c.status, orig=c.orig)
        for i, c in enumerate(changes_in(path))
    ]


_CACHE: dict[Path, tuple[tuple[Any, ...], list[FileChange]]] = {}


def _head_state(root: Path) -> tuple[str | None, ...]:
    """State of HEAD without a Git call: ``.git/HEAD`` and the reference it points to (loose
    file or ``packed-refs``). A new commit from outside changes it."""
    try:
        git_dir = root / ".git"
        if git_dir.is_file():  # worktree or submodule: "gitdir: <path>"
            target = git_dir.read_text(encoding="utf-8").strip().removeprefix("gitdir:").strip()
            git_dir = (root / target).resolve()
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        common = git_dir
        link = git_dir / "commondir"
        if link.is_file():
            common = (git_dir / link.read_text(encoding="utf-8").strip()).resolve()
        if not head.startswith("ref:"):
            return (head, None, None)
        ref = head.removeprefix("ref:").strip()
        loose = common / ref
        if loose.is_file():
            return (head, loose.read_text(encoding="utf-8").strip(), None)
        packed = common / "packed-refs"
        stat = packed.stat() if packed.is_file() else None
        return (head, None, f"{stat.st_mtime_ns}:{stat.st_size}" if stat else None)
    except OSError, UnicodeDecodeError:
        return ("?", None, None)


def _signature(root: Path, pending: list[tuple[str, str]]) -> tuple[Any, ...]:
    """HEAD, plus per file status, name, modification time (ns), size, inode number and inode
    time of the working file (``None`` if it is missing). The inode time (``st_ctime_ns``)
    cannot be reset, unlike the modification time (coarse timestamps, tools that preserve
    it). On Windows ``st_ctime`` is the creation time: there modification time and size
    still carry the main load; content is not checked, for performance."""
    parts: list[tuple[Any, ...]] = [_head_state(root)]
    for i, (status, file) in enumerate(pending):
        if i >= _EVAL_LIMIT:  # check only the evaluated files (network drives are slow)
            parts.append((status, file))
            continue
        try:
            stat = (root / file).lstat()
            parts.append(
                (status, file, stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)
            )
        except OSError:
            parts.append((status, file, None, None, None, None))
    return tuple(parts)


def cached_file_changes(path: Path, pending: list[tuple[str, str]]) -> list[FileChange]:
    """Like :func:`file_changes`, but recomputed only if ``pending`` (the list from
    :func:`sprintforecast.git.cached_pending_changes`) or a working file has changed (for
    the UI, which redraws on every input). Cleared by
    :func:`sprintforecast.git.invalidate_status`."""
    root = gitmod.require_root(path)
    key = path.resolve()
    signature = _signature(root, pending)
    cached = _CACHE.get(key)
    if cached and cached[0] == signature:
        return list(cached[1])
    result = file_changes(path)
    _CACHE[key] = (signature, result)
    return list(result)


gitmod.on_invalidate(_CACHE.clear)
