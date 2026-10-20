# SPDX-License-Identifier: EUPL-1.2
"""Everyday operations without a terminal: discard changes, history, restore an earlier
state and manage tags.

Everything runs through the ``git`` program (see :mod:`sprintforecast.git`). Discarding first
backs up the affected files to a trash folder under ``.git``; restoring is itself a commit
and can be undone with :func:`revert_commit`. We always read paths from NUL-separated output
(``-z``): only that keeps names with umlauts or quotation marks intact.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sprintforecast import git as gitmod
from sprintforecast.git import (
    Change,
    GitError,
    _git,
    changes_in,
    split_record,
    split_z,
)
from sprintforecast.gitsync import _git_dir, _root, state
from sprintforecast.i18n import t

_SEP = "\x1f"
_REC = "\x1e"

# At most this many characters of paths per Git call (Windows allows about 32,000 per line).
_CHUNK_CHARS = 16000


@dataclass(frozen=True)
class Lost:
    """What is lost when discarding."""

    status: str  # M modified, D deleted, A/?? new, R renamed
    file: str  # relative to the repository root
    added: int = 0
    removed: int = 0
    orig: str = ""  # previous path for renames


@dataclass(frozen=True)
class Entry:
    rev: str
    short: str
    author: str
    day: str
    subject: str
    files: tuple[str, ...] = ()
    merge: bool = False


@dataclass(frozen=True)
class Tag:
    """A tag. ``local``: present on this computer; ``on_server``: present on the server
    (None = unknown, because not queried or server not reachable); ``differs``: locally and
    on the server the tag points to different states."""

    name: str
    target: str  # short hash of the tagged commit
    day: str
    subject: str
    local: bool = True
    on_server: bool | None = None
    differs: bool = False


def _no_unfinished(path: Path) -> None:
    current = state(path)
    if current.unfinished or current.conflicts:
        raise GitError(
            t("A merge has not been completed yet."),
            "merge_in_progress",
            gitmod.hint_for("merge_in_progress"),
        )


def _chunks(paths: list[str]) -> Iterator[list[str]]:
    """Splits a long path list so that every line stays short enough for Git."""
    chunk: list[str] = []
    size = 0
    for p in paths:
        if chunk and size + len(p) + 1 > _CHUNK_CHARS:
            yield chunk
            chunk, size = [], 0
        chunk.append(p)
        size += len(p) + 1
    if chunk:
        yield chunk


def _inside(file: str, rel: str) -> bool:
    """Is ``file`` (path relative to the root) inside ``rel``? ``.`` is the root itself."""
    if rel in {"", "."}:
        return True
    return file == rel or file.startswith(rel.rstrip("/") + "/")


# --- Discarding changes -------------------------------------------------------------------


def _selected(path: Path, files: list[str] | None) -> list[Change]:
    return [c for c in changes_in(path) if files is None or c.file in files]


def _numstat(root: Path, path: Path) -> dict[str, tuple[int, int]]:
    """Added/removed lines per file (key: new path)."""
    out = _git(
        root, "diff", "HEAD", "-M", "--numstat", "-z", "--", str(path.resolve()),
        check=False, strip=False,
    )  # fmt: skip
    stats: dict[str, tuple[int, int]] = {}
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        parts = entries[i].split("\t", 2)
        i += 1
        if len(parts) != 3:
            continue
        added, removed, name = parts
        if not name:  # rename: previous and new path follow
            if i + 1 >= len(entries):
                break
            name = entries[i + 1]
            i += 2
        if added.isdigit() and removed.isdigit():
            stats[name] = (int(added), int(removed))
    return stats


def discard_preview(path: Path, files: list[str] | None = None) -> list[Lost]:
    """Shows what a discard costs (``files`` relative to the root; None = everything in the
    data folder): status and number of added/removed lines."""
    root = _root(path)
    changes = _selected(path, files)
    stats = _numstat(root, path)
    lost = []
    for change in changes:
        added, removed = stats.get(change.file, (0, 0))
        if change.status in {"??", "A"} and not added:
            with contextlib.suppress(OSError):
                added = len(
                    (root / change.file).read_text(encoding="utf-8", errors="replace").splitlines()
                )
        lost.append(Lost(change.status, change.file, added, removed, change.orig))
    return lost


def _new_trash(root: Path) -> Path:
    """A new, not yet existing trash folder (also for several operations in the same
    second)."""
    base = _git_dir(root) / "sprintforecast-verworfen"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    n = 0
    while True:
        trash = base / (stamp if n == 0 else f"{stamp}-{n}")
        try:
            trash.mkdir(parents=True)
        except FileExistsError:
            n += 1
            continue
        return trash


def _paths_of(changes: list[Change]) -> list[str]:
    """All paths touched by the changes (new and previous name), without duplicates."""
    return list(dict.fromkeys(p for c in changes for p in (c.file, c.orig) if p))


def _backup(root: Path, trash: Path, changes: list[Change]) -> None:
    for name in _paths_of(changes):
        source = root / name
        if source.is_file():
            (trash / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, trash / name)


@dataclass(frozen=True)
class _Snapshot:
    """State before discarding, so that everything can be put back after a partial failure:
    which files existed (content is in the trash), which did not (e.g. deleted or before a
    rename) and the staging (index)."""

    present: tuple[str, ...]
    absent: tuple[str, ...]
    index: bytes | None


def _snapshot(root: Path, changes: list[Change]) -> _Snapshot:
    paths = _paths_of(changes)
    try:
        index = (_git_dir(root) / "index").read_bytes()
    except OSError:
        index = None
    return _Snapshot(
        tuple(p for p in paths if (root / p).is_file()),
        tuple(p for p in paths if not (root / p).exists()),
        index,
    )


def _write_index(root: Path, data: bytes) -> None:
    index = _git_dir(root) / "index"
    tmp = index.with_name("index.sprintforecast-rollback")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, index)
    finally:
        tmp.unlink(missing_ok=True)


def _put_back(root: Path, trash: Path, snap: _Snapshot) -> list[str]:
    """Restores the state before discarding (after a partial failure): copy backed-up files
    back, remove re-created (previously deleted) files, write the staging back. Returns what
    could not be restored (empty = everything)."""
    failed: list[str] = []
    for name in snap.present:
        try:
            saved = trash / name
            if not saved.is_file():
                raise OSError(name)
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, root / name)
        except OSError:
            failed.append(name)
    for name in snap.absent:
        try:
            (root / name).unlink(missing_ok=True)
        except OSError:
            failed.append(name)
    if snap.index is not None:
        try:
            _write_index(root, snap.index)
        except OSError:
            failed.append(t("the staging area (index)"))
    return failed


def _rollback_hint(failed: list[str], trash: Path, quote: Callable[[str], str] = str) -> str:
    if not failed:
        return t(
            ("The original state (files and staging) was restored. Backup of the changes: {trash}"),
            trash=quote(str(trash)),
        )
    return t(
        (
            "The original state could not be fully restored. Not restored: {files}. The backup "
            "of the changes is in {trash}; please copy the files back from there."
        ),
        files=quote(", ".join(failed)),
        trash=quote(str(trash)),
    )


def discard(path: Path, files: list[str] | None = None) -> Path | None:
    """Discards open changes (single files or everything in the data folder). The files are
    first copied to a trash folder under ``.git``; its folder is returned. If something
    fails, the state before is restored from the backup (files, deleted files, staging); the
    error message names what could not be restored and where the backup is."""
    root = _root(path)
    _no_unfinished(path)
    changes = _selected(path, files)
    if not changes:
        raise GitError(t("No changes to discard"))
    trash = _new_trash(root)
    try:
        _backup(root, trash, changes)
        snap = _snapshot(root, changes)
    except OSError as e:
        shutil.rmtree(trash, ignore_errors=True)
        raise GitError(
            t("The changes cannot be backed up: {error}", error=e),
            "error",
            t("Nothing was discarded."),
        ) from e
    try:
        _apply_discard(root, changes)
    except (GitError, OSError) as e:
        failed = _put_back(root, trash, snap)
        gitmod.invalidate_status()
        raise GitError(
            t("Discarding did not fully succeed: {error}", error=e),
            getattr(e, "kind", "error"),
            _rollback_hint(failed, trash),
            hint_md=_rollback_hint(failed, trash, gitmod.md_plain),
        ) from e
    gitmod.invalidate_status()
    if not any(trash.iterdir()):
        trash.rmdir()
        return None
    return trash


def _apply_discard(root: Path, changes: list[Change]) -> None:
    """Resets the paths to the state of HEAD: known files are restored (also the previous
    name of a rename), files that do not exist in HEAD (new, target of a rename) are removed
    from the staging and deleted."""
    paths = list(dict.fromkeys(p for c in changes for p in (c.file, c.orig) if p))
    in_head: set[str] = set()
    for chunk in _chunks(paths):
        out = _git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", *chunk,
                   check=False, strip=False)  # fmt: skip
        in_head.update(split_z(out))
    restore = [p for p in paths if p in in_head]
    remove = [p for p in paths if p not in in_head]
    for chunk in _chunks(remove):
        _git(root, "rm", "-q", "-f", "--cached", "--ignore-unmatch", "--", *chunk)
    for chunk in _chunks(restore):
        _git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", *chunk)
    for p in remove:
        (root / p).unlink(missing_ok=True)


# --- History --------------------------------------------------------------------------------


def history(path: Path, scope: Path | None = None, limit: int = 40) -> list[Entry]:
    """Commits that affect ``scope`` (file or folder; default: the data folder): who changed
    what and when, newest first."""
    root = _root(path)
    target = str((scope or path).resolve())
    fmt = f"{_REC}%H{_SEP}%h{_SEP}%an{_SEP}%ad{_SEP}%P{_SEP}%s"
    out = _git(
        root,
        "log",
        "-z",
        f"-{limit}",
        f"--format={fmt}",
        "--date=format:%Y-%m-%d %H:%M",
        "--name-only",
        "--no-renames",
        "--",
        target,
        check=False,
        strip=False,
    )
    entries = []
    for record in filter(None, out.split(_REC)):
        head, _, names = record.partition("\0")
        rev, short, author, day, parents, subject = head.split(_SEP, 5)
        files = tuple(split_z(names.removeprefix("\n")))
        entries.append(Entry(rev, short, author, day, subject, files, len(parents.split()) > 1))
    return entries


def _check_rev(rev: str) -> str:
    rev = rev.strip()
    if not rev or rev.startswith("-"):
        raise GitError(t("Invalid version: {rev}", rev=rev))
    return rev


def _rollback_restore(
    root: Path, rel: str, added: set[str], saved: dict[str, Path] | None = None
) -> list[str]:
    """Undoes a half-executed restore (there were no open changes in this area before, so
    HEAD is the right state). ``saved``: ignored files backed up beforehand (path → backup)
    that go back to their place. Returns what could not be reset (empty = everything)."""
    saved = saved or {}
    failed: list[str] = []
    for args in (("reset", "-q", "HEAD", "--", rel), ("checkout", "HEAD", "--", rel)):
        try:
            _git(root, *args)
        except GitError:
            failed.append(rel)
    for file in sorted(added - saved.keys()):
        try:
            (root / file).unlink(missing_ok=True)
        except OSError:
            failed.append(file)
    for file, backup in sorted(saved.items()):
        try:
            shutil.copy2(backup, root / file)
        except OSError:
            failed.append(file)
    left = _git(
        root, "status", "--porcelain", "-z", "--untracked-files=no", "--", rel,
        check=False, strip=False,
    )  # fmt: skip
    if left and rel not in failed:
        failed.append(rel)
    return list(dict.fromkeys(failed))


def _save_ignored(root: Path, trash: Path, files: list[str]) -> dict[str, Path]:
    """Backs up ignored, untracked files that a restore would overwrite (path → backup in the
    trash)."""
    saved: dict[str, Path] = {}
    for file in files:
        (trash / file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / file, trash / file)
        saved[file] = trash / file
    return saved


def restore_version(path: Path, scope: Path, rev: str, message: str | None = None) -> str:
    """Resets ``scope`` (file or folder) to the state of ``rev``, as a new commit that can be
    undone with :func:`revert_commit`. Returns the short hash. Refused if there are open
    changes in the area (they would otherwise be overwritten). Ignored, untracked files (e.g.
    ``*.tmp``) that the old state would overwrite are first backed up to the trash under
    ``.git/sprintforecast-verworfen``."""
    root = _root(path)
    _no_unfinished(path)
    rev = _check_rev(rev)
    target = scope.resolve()
    rel = target.relative_to(root).as_posix()  # "." = the root itself
    if any(_inside(c.file, rel) or (c.orig and _inside(c.orig, rel)) for c in changes_in(path)):
        raise GitError(
            t("There are open changes in this area."),
            "dirty",
            t("Please save (commit) or discard them first, then restore."),
        )
    where = [] if rel == "." else ["--", rel]
    then = set(split_z(_git(root, "ls-tree", "-r", "-z", "--name-only", rev, *where, strip=False)))
    now = set(split_z(_git(root, "ls-files", "-z", *where, strip=False)))
    gone = sorted(now - then)
    listing = _git(
        root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", *where,
        check=False, strip=False,
    )  # fmt: skip
    ignored = split_z(listing)
    clash = sorted(set(ignored) & then)
    saved: dict[str, Path] = {}
    trash: Path | None = None
    if clash:
        trash = _new_trash(root)
        try:
            saved = _save_ignored(root, trash, clash)
        except OSError as e:
            shutil.rmtree(trash, ignore_errors=True)
            raise GitError(
                t("Backing up ignored files is not possible: {error}", error=e),
                "error",
                t("Nothing was changed."),
            ) from e
    try:
        for chunk in _chunks(sorted(then)):
            _git(root, "checkout", rev, "--", *chunk)
        for chunk in _chunks(gone):
            _git(root, "rm", "-q", "--", *chunk)
        if not _git(root, "status", "--porcelain", "-z", "--", rel, strip=False):
            raise GitError(t("This area already has exactly this state."))
        short = _git(root, "rev-parse", "--short", rev)
        text = message or t("State of {rev} restored ({scope})", rev=short, scope=rel)
        _git(root, "add", "--all", "--", rel)
        gitmod.refuse_staged_conflict_markers(root)  # an earlier shared faulty state
        _git(root, "commit", "-m", text, "--", rel)
    except GitError as e:
        failed = _rollback_restore(root, rel, then - now, saved)
        gitmod.invalidate_status()
        if failed:
            where_saved = trash if trash else _git_dir(root) / "sprintforecast-verworfen"
            raise GitError(
                str(e),
                e.kind,
                t(
                    (
                        "The original version could not be fully restored (affected: {files}). "
                        "Saved ignored files are in {trash}."
                    ),
                    files=", ".join(failed),
                    trash=where_saved,
                ),
            ) from e
        raise
    gitmod.invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


def revert_commit(path: Path, rev: str) -> str:
    """Reverts a commit with a new commit (e.g. undoes a restore). Merges cannot be reverted
    this way."""
    root = _root(path)
    _no_unfinished(path)
    rev = _check_rev(rev)
    parents = _git(root, "rev-list", "--parents", "-n", "1", rev).split()
    if len(parents) > 2:
        raise GitError(t("A merge cannot be taken back."))
    if changes_in(root):  # the whole repository, not only the data folder
        raise GitError(
            t("There are open changes."),
            "dirty",
            t("Please save (commit) or discard them first, then take back."),
        )
    try:
        _git(root, "revert", "--no-edit", rev)
    except GitError as e:
        _git(root, "revert", "--abort", check=False)
        if e.kind == "conflict":
            raise GitError(
                t("Taking back is not possible without a conflict: {error}", error=e),
                "conflict",
                t("Later changes affect the same places. Nothing was changed."),
            ) from e
        if "now empty" in str(e) or "nothing to commit" in str(e):
            raise GitError(
                t("This commit changes nothing (any more); there is nothing to take back."),
                "error",
                t("Nothing was changed."),
            ) from e
        raise
    changed = gitmod.split_z(
        _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD", strip=False)
    )
    try:  # no state with conflict markers (e.g. reverting a repair)
        gitmod.refuse_conflict_markers(root, (root / name for name in changed))
    except GitError:
        _git(root, "reset", "--hard", "HEAD~1")  # our own commit from just now, all clean before
        gitmod.invalidate_status()
        raise
    gitmod.invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


# --- Tags -----------------------------------------------------------------------------------


def _remote(root: Path) -> str | None:
    remotes = _git(root, "remote", check=False).split()
    return "origin" if "origin" in remotes else (remotes[0] if remotes else None)


def _server_tags(root: Path, remote: str) -> dict[str, str]:
    """Tags on the server: name → commit they point to (queries the server)."""
    out = _git(
        root, "ls-remote", "--tags", remote, network=True, url=gitmod.remote_url(root, remote)
    )
    objects: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if not ref.startswith("refs/tags/"):
            continue
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name.removesuffix("^{}")] = sha
        else:
            objects[name] = sha
    return {name: peeled.get(name, sha) for name, sha in objects.items()}


def server_reachable(path: Path) -> bool:
    """Whether the server of the tags can be queried (network). False also without a server."""
    root = _root(path)
    remote = _remote(root)
    if not remote:
        return False
    try:
        _server_tags(root, remote)
    except GitError:
        return False
    return True


def list_tags(path: Path, check_server: bool = False) -> list[Tag]:
    """The tags of this repository, newest first. With ``check_server`` the server is
    queried (network): ``on_server`` and ``differs`` then show differences, and tags that
    exist only on the server come last with ``local=False``. If the server is not reachable,
    ``on_server`` stays None."""
    root = _root(path)
    fmt = _SEP.join(
        [
            "%(refname:strip=2)",
            "%(*objectname)",
            "%(objectname)",
            "%(*objectname:short)",
            "%(objectname:short)",
            "%(creatordate:short)",
            "%(contents:subject)",
        ]
    )
    out = _git(
        root, "for-each-ref", "--sort=-creatordate", f"--format={fmt}", "refs/tags", check=False
    )
    local: list[tuple[Tag, str]] = []
    # not splitlines: U+2028, \x0c … would split the subject into several entries
    for line in filter(None, out.split("\n")):
        name, deref_full, obj_full, deref, obj, day, subject = split_record(line, 7, _SEP)
        local.append((Tag(name, deref or obj, day, subject), deref_full or obj_full))
    server: dict[str, str] | None = None
    remote = _remote(root) if check_server else None
    if remote:
        try:
            server = _server_tags(root, remote)
        except GitError:
            server = None
    if server is None:
        return [tag for tag, _ in local]
    tags = [
        Tag(
            tag.name,
            tag.target,
            tag.day,
            tag.subject,
            True,
            tag.name in server,
            tag.name in server and server[tag.name] != full,
        )
        for tag, full in local
    ]
    known = {tag.name for tag in tags}
    tags += [
        Tag(name, sha[:7], "", "", local=False, on_server=True)
        for name, sha in sorted(server.items())
        if name not in known
    ]
    return tags


def _valid_name(root: Path, name: str) -> str:
    """Checks a tag name (see :func:`sprintforecast.git.valid_tag_name`)."""
    return gitmod.valid_tag_name(root, name)


def _commit_of(root: Path, ref: str) -> str:
    return _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)


def _tag_exists(root: Path, name: str) -> bool:
    return bool(_git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}", check=False))


def set_tag(
    path: Path, name: str, rev: str = "HEAD", message: str | None = None
) -> GitError | None:
    """Sets a tag (also retroactively) and uploads it. Returns a warning if the upload
    failed (the tag then stays local; a new call uploads it). If the tag already exists
    locally at the same state, it is only uploaded; at a different state the function
    refuses. If the server is reachable and already has the name for a different state, the
    tag is not created (error ``tag_exists``); if it has it for the same state, it is
    adopted."""
    root = _root(path)
    name = _valid_name(root, name)
    rev = _check_rev(rev)
    existing = _commit_of(root, f"refs/tags/{name}")
    target = _commit_of(root, rev)
    if existing and existing != target:
        raise GitError(t("The tag {name} already exists.", name=name))
    if not existing:
        if _adopt_server_tag(root, name, target):
            return None
        _git(root, "tag", "-a", "-m", message or name, "--", name, rev)
        gitmod.invalidate_status()
    return _push_tag(root, name)


def _adopt_server_tag(root: Path, name: str, target: str) -> bool:
    """Asks the server (if reachable): if the name is taken there for a different state,
    error. If it points to the same state, that tag is fetched (True) instead of creating a
    second one that the server would reject as differing."""
    if not (remote := _remote(root)):
        return False
    try:
        on_server = _server_tags(root, remote).get(name)
    except GitError:
        return False  # without an answer from the server nothing can be said
    if not on_server or not target:
        return False
    if on_server != target:
        raise GitError(
            t(
                (
                    "The tag {name} is already used on the server for a different version "
                    "({rev}). It was not created."
                ),
                name=name,
                rev=on_server[:7],
            ),
            "tag_exists",
            t("Choose a different name or delete the tag on the server first."),
        )
    try:
        _git(
            root,
            "fetch",
            remote,
            f"refs/tags/{name}:refs/tags/{name}",
            network=True,
            url=gitmod.remote_url(root, remote),
        )
    except GitError:
        return False
    gitmod.invalidate_status()
    return True


def _push_tag(root: Path, name: str) -> GitError | None:
    if not (remote := _remote(root)):
        return None
    try:
        _git(
            root,
            "push",
            remote,
            f"refs/tags/{name}",
            network=True,
            url=gitmod.remote_url(root, remote),
        )
    except GitError as e:
        return e
    return None


def upload_tag(path: Path, name: str) -> None:
    """Uploads an existing local tag to the server (e.g. after the upload failed when
    setting it). Errors (no local tag, no server, server not reachable, tag with a different
    state already there) come as :class:`GitError`."""
    root = _root(path)
    name = _valid_name(root, name)
    if not _tag_exists(root, name):
        raise GitError(t("The tag {name} does not exist on this computer.", name=name))
    if _remote(root) is None:
        raise GitError(t("No server set up."), "no_remote", gitmod.hint_for("no_remote"))
    if error := _push_tag(root, name):
        raise error


def delete_tag(path: Path, name: str) -> GitError | None:
    """Deletes a tag locally and on the server (also one that exists on only one of the two
    sides; calling repeatedly does no harm). Warning if the server was not reachable (the
    tag stays there; a new call deletes it there)."""
    root = _root(path)
    name = _valid_name(root, name)
    if _tag_exists(root, name):
        _git(root, "tag", "-d", "--", name)
        gitmod.invalidate_status()
    if remote := _remote(root):
        try:
            _git(
                root,
                "push",
                remote,
                f":refs/tags/{name}",
                network=True,
                url=gitmod.remote_url(root, remote),
            )
        except GitError as e:
            if "remote ref does not exist" in str(e):
                return None
            return e
    return None
