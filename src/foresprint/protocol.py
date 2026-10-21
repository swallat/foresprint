# SPDX-License-Identifier: EUPL-1.2
"""Minutes of the sprint meetings (PO pre-planning, Planning, Review).

Every save creates a Markdown file
``protokolle/<sprint>-<termin>-<Datum>-<Zeit>.md`` in the team's folder (which can also be the
root of the data folder); older versions stay readable. If a meeting becomes obsolete (e.g.
when the freeze is lifted), the old minutes are afterwards named
``…_obsolet_<Datum>-<Zeit>.md``."""

from __future__ import annotations

import contextlib
import dataclasses
import errno
import getpass
import hashlib
import os
import re
import stat
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO

from foresprint.config import config_dir
from foresprint.git import invalidate_status
from foresprint.i18n import t
from foresprint.model import Sprint
from foresprint.products import Distribution, by_po, measure_label
from foresprint.report import fmt
from foresprint.storage import (
    FileAccessError,
    Repository,
    _not_readable,
    _not_saved,
    dump_yaml,
    sprint_to_dict,
    write_text,
)

PROTOCOL_DIR = "protokolle"
STAMP = "%Y%m%d-%H%M%S"
PREPLANNING, PLANNING, REVIEW = "vorplanung", "planning", "review"
KINDS = (PREPLANNING, PLANNING, REVIEW)
# Columns of the product table per meeting.
KIND_MEASURES = {
    PREPLANNING: ("standard", "preplanned"),
    PLANNING: ("standard", "preplanned", "planned"),
    REVIEW: ("planned", "done"),
}
_NAME = re.compile(
    r"^(?P<sprint>.+)-(?P<kind>vorplanung|planning|review)-(?P<at>\d{8}-\d{6})"
    r"(?:-[0-9a-f]{4})?"  # start of the fingerprint, see write_protocol_new
    r"(?:_obsolet_(?P<obsolete>\d{8}-\d{6}))?\.md$"
)


def _cell(text: str | None) -> str:
    """Text for a Markdown cell or line (neutralizes pipes and line breaks)."""
    return " ".join((text or "").replace("|", "\\|").split())


def kind_title(kind: str) -> str:
    return {
        PREPLANNING: t("PO pre-planning"),
        PLANNING: t("Sprint Planning"),
        REVIEW: t("Sprint Review"),
    }[kind]


def _distribution_lines(
    d: Distribution, measures: tuple[str, ...], show_po: bool, heading: str = "##"
) -> list[str]:
    """Tables "Per product" (and "Per PO") as Markdown lines; empty without product rows."""
    lines: list[str] = []
    if not d.rows:
        return lines
    header = [t("Product"), *(["PO"] if show_po else [])]
    header += [measure_label(m) for m in measures]
    lines += ["", f"{heading} {t('Per product')}", ""]
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in d.rows:
        if not (r.active or any(r.value(m) is not None for m in measures)):
            continue
        cells = [_cell(r.product.name), *([_cell(r.product.po)] if show_po else [])]
        cells += [fmt(r.value(m), 2) for m in measures]
        lines.append("| " + " | ".join(cells) + " |")
    if show_po and (po_rows := by_po(d)):
        header = ["PO", *(measure_label(m) for m in measures)]
        lines += ["", f"{heading} {t('Per PO')}", "", "| " + " | ".join(header) + " |"]
        lines.append("|" + "---|" * len(header))
        for po, totals in po_rows:
            cells = [_cell(po), *(fmt(totals[m], 2) for m in measures)]
            lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_protocol(
    kind: str,
    team: str,
    sprint_id: str,
    *,
    now: datetime,
    facts: list[tuple[str, str]],
    d: Distribution | None = None,
    notes: list[tuple[str, list[str]]] | None = None,
    comment: str = "",
    show_po: bool = True,
) -> str:
    """Markdown text of a meeting: header, key figures (``facts``), sections (``notes``) and,
    with ``d``, the distribution per product (and per PO)."""
    lines = [
        f"# {kind_title(kind)} {_cell(team)} – {t('Sprint {id}', id=sprint_id)}",
        "",
        t("As of: {at}", at=f"{now:%d.%m.%Y %H:%M}"),
        "",
    ]
    lines += [f"- {label}: {_cell(value)}" for label, value in facts]
    if comment.strip():
        lines += ["", f"**{t('Comment')}:** {_cell(comment)}"]
    for title, items in notes or []:
        if items:
            lines += ["", f"## {title}", ""] + [f"- {_cell(i)}" for i in items]
    if d is not None:
        lines += _distribution_lines(d, KIND_MEASURES[kind], show_po)
    return "\n".join(lines) + "\n"


SECTION_MARKER = "<!-- sprintforecast-section: "


@dataclasses.dataclass
class PlanningSection:
    """A section of the Planning minutes (absences, scheduling, Commitment). ``lines`` are
    the Markdown lines below it; without ``recorded`` it says "not yet recorded"."""

    key: str
    title: str
    lines: list[str]
    recorded: bool = True


def _section_parts(text: str) -> dict[str, tuple[str, list[str]]]:
    """Sections of Planning minutes: key → (as-of text, lines without the as-of line)."""
    parts: dict[str, tuple[str, list[str]]] = {}
    key: str | None = None
    body: list[str] = []

    def close() -> None:
        if key is None:
            return
        stand = ""
        if body and body[0].startswith("_") and body[0].endswith("_"):
            stand, rest = body[0][1:-1], body[1:]
        else:
            rest = body
        parts[key] = (stand, [ln for ln in rest if ln.strip()])

    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith(SECTION_MARKER):
            close()
            key = line[len(SECTION_MARKER) :].removesuffix(" -->").strip()
            body = []
        elif line.startswith(STATE_MARKER):
            close()
            key = None
        elif key is not None and line.strip() and not line.startswith("## "):
            body.append(line)  # the heading of the next section is not part of this one
    close()
    return parts


def latest_planning_sections(
    repo: Repository, team: str, sprint_id: str
) -> dict[str, tuple[str, list[str]]]:
    """The sections of the latest valid Planning minutes (empty if there are none or they
    are not readable)."""
    for _, kind, obsolete, path in list_protocols(repo, team, sprint_id):
        if kind == PLANNING and not obsolete:
            try:
                return _section_parts(path.read_text(encoding="utf-8"))
            except OSError, UnicodeDecodeError:
                return {}
    return {}


def render_planning_protocol(
    team: str,
    sprint_id: str,
    *,
    now: datetime,
    facts: list[tuple[str, str]],
    sections: list[PlanningSection],
    previous: dict[str, tuple[str, list[str]]],
) -> str:
    """Complete Planning minutes with all sections. Each recorded section carries its own
    as-of time: if unchanged compared to ``previous`` (the latest minutes), the old as-of time
    stays, otherwise ``now`` applies. So each set of minutes shows when each step was last
    changed, and an unchanged state still does not create further minutes."""
    lines = [
        f"# {kind_title(PLANNING)} {_cell(team)} – {t('Sprint {id}', id=sprint_id)}",
        "",
        t("As of: {at}", at=f"{now:%d.%m.%Y %H:%M}"),
        "",
    ]
    lines += [f"- {label}: {_cell(value)}" for label, value in facts]
    for section in sections:
        lines += ["", f"## {section.title}", f"{SECTION_MARKER}{section.key} -->", ""]
        if not section.recorded:
            lines.append(f"_{t('not yet recorded')}_")
            continue
        old_stand, old_lines = previous.get(section.key, ("", []))
        if old_stand == t("not yet recorded"):  # the placeholder is not an as-of time
            old_stand = ""
        body = [ln for ln in section.lines if ln.strip()]
        stand = (
            old_stand
            if old_stand and old_lines == body
            else t("As of: {at}", at=f"{now:%d.%m.%Y %H:%M}")
        )
        lines += [f"_{stand}_", "", *section.lines]
    return "\n".join(lines) + "\n"


def planning_distribution_lines(d: Distribution, show_po: bool) -> list[str]:
    """Product tables of the Planning minutes (headings one level below the section)."""
    return _distribution_lines(d, KIND_MEASURES[PLANNING], show_po, heading="###")


def md_item(text: str) -> str:
    """A bullet line with neutralized pipes and line breaks."""
    return f"- {_cell(text)}"


def _folder(repo: Repository, team: str) -> Path:
    return repo.team_dir(team) / PROTOCOL_DIR


def _body_of(text: str) -> list[str]:
    """The text without the "As of: …" line (third line, with the timestamp)."""
    lines = text.replace("\r\n", "\n").split("\n")
    return lines[:2] + lines[3:]


def _body(path: Path) -> list[str] | None:
    try:
        return _body_of(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError:
        return None


STATE_MARKER = "<!-- sprintforecast-state: "


def fingerprint(text: str, *documents: dict) -> str:
    """Short fingerprint of the saved state: the text without the "As of: …" line and all
    saved fields of the sprint files (including those the minutes do not show)."""
    digest = hashlib.sha256("\n".join(_body_of(text)).encode("utf-8"))
    for document in documents:
        digest.update(dump_yaml(document).encode("utf-8"))
    return digest.hexdigest()[:16]


def _state_of(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError, UnicodeDecodeError:
        return None
    for line in reversed(lines):
        if line.startswith(STATE_MARKER):
            return line[len(STATE_MARKER) :].removesuffix(" -->").strip()
    return None


# Lock per sprint and meeting: finding the latest minutes, checking for no change and writing
# run in one go, so that two sessions with the same state do not create two sets of minutes.
LOCK_WAIT_SECONDS = 10.0


def _private_dir(path: Path) -> None:
    """Creates the folder; on POSIX readable and writable only by the user themselves."""
    if sys.platform == "win32":
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)


def _fallback_lock_dir() -> Path:
    """Per-user folder in the temp directory, used when the settings folder does not work. In
    a shared ``/tmp`` a fixed name must not be used: the account that creates it first would
    otherwise lock out all the others. On POSIX the folder must belong to the user."""
    if sys.platform == "win32":
        try:
            user = getpass.getuser()
        except OSError:
            user = "unknown"
    else:
        user = str(os.getuid())
    name = re.sub(r"\W", "_", user)  # only characters that are valid in a folder name
    root = Path(tempfile.gettempdir()) / f"sprintforecast-sperren-{name}"
    try:
        _private_dir(root)
    except OSError as e:
        raise _not_saved(root, e) from e
    if sys.platform != "win32":
        info = root.lstat()  # a link or foreign folder is not a safe place
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise FileAccessError(
                t(
                    (
                        "The folder {path} for the locks belongs to another user. Please have "
                        "it removed or make the settings folder writable."
                    ),
                    path=root,
                )
            )
    return root


# Permanent errors when creating/opening in the settings folder: only then is the temp folder
# used. Transient ones (e.g. ``EMFILE``, ``ENOSPC``, ``EIO``, ``EINTR``) are raised as errors
# instead of silently spreading sessions across different lock files.
_PERMANENT_OPEN_ERRNOS = frozenset(
    getattr(errno, name)
    for name in ("ENOENT", "EROFS", "EACCES", "EPERM", "EISDIR", "ENOTDIR", "EEXIST")
    if hasattr(errno, name)
)


def _is_permanent(e: OSError) -> bool:
    return e.errno in _PERMANENT_OPEN_ERRNOS


def _lock_dir() -> Path:
    """Folder of the lock files: ``sperren`` in the user's settings folder (never in the Git
    working directory); if it cannot be created, a per-user folder in the temp directory."""
    root = config_dir() / "sperren"
    try:
        _private_dir(root)
    except OSError as e:
        if not _is_permanent(e):
            raise _not_saved(root, e) from e
        return _fallback_lock_dir()
    # An existing, non-writable folder (``exist_ok`` succeeds anyway) is no good.
    # On Windows ``access`` says nothing about permissions; :func:`_open_lock` covers that.
    if not os.access(root, os.W_OK | os.X_OK):
        return _fallback_lock_dir()
    return root


def _lock_file(folder: Path, sprint_id: str, kind: str) -> Path:
    """Lock file outside the data folder (never in the Git working directory): one per
    minutes folder, sprint and meeting."""
    key = hashlib.sha256(f"{folder.resolve()}|{sprint_id}|{kind}".encode()).hexdigest()[:24]
    return _lock_dir() / f"{key}.lock"


def _open_lock(path: Path) -> tuple[IO[bytes], Path]:
    """Opens the lock file. If that fails (e.g. settings folder without write permission), the
    same file in the per-user temp folder is used; all sessions with the same permissions thus
    end up at the same lock file. Returns the handle and the path that was actually opened.
    If that fails too, a :class:`FileAccessError` is raised."""
    try:
        return path.open("a+b"), path
    except OSError as e:
        first = e
    if not _is_permanent(first):
        raise _not_saved(path, first) from first
    fallback_dir = _fallback_lock_dir()
    if fallback_dir == path.parent:  # that was already the fallback folder
        raise _not_saved(path, first) from first
    fallback = fallback_dir / path.name
    try:
        return fallback.open("a+b"), fallback
    except OSError as e:
        raise _not_saved(fallback, e) from e


class _LockUnsupported(Exception):
    """Locking the file fails permanently (not just because another session holds it),
    e.g. on a file system without file locks."""


# Only genuine contention means "busy": POSIX ``EWOULDBLOCK``/``EAGAIN`` (some ``flock``
# variants report ``EACCES``), Windows ``EACCES`` and ``EDEADLOCK`` from ``msvcrt.locking``,
# and the Windows errors 32 (sharing violation) and 33 (lock violation).
_BUSY_ERRNOS = frozenset(
    getattr(errno, name)
    for name in ("EACCES", "EAGAIN", "EWOULDBLOCK", "EDEADLK", "EDEADLOCK")
    if hasattr(errno, name)
)
_BUSY_WINERRORS = frozenset({32, 33})


def _try_lock(handle: IO[bytes]) -> bool:
    """Tries to lock the file without waiting (operating system lock). ``False`` means:
    another session holds it. Any other error (e.g. ``ENOLCK``, ``ENOSYS``, ``EINVAL``,
    ``EIO`` on network drives without file locks) is permanent and raised as
    :class:`_LockUnsupported`."""
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        if e.errno in _BUSY_ERRNOS or getattr(e, "winerror", None) in _BUSY_WINERRORS:
            return False
        raise _LockUnsupported(str(e)) from e
    return True


def _acquire(handle: IO[bytes]) -> None:
    """Locks the file; on contention it waits up to ``LOCK_WAIT_SECONDS``. A permanent error
    (:class:`_LockUnsupported`) is raised immediately, without waiting."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while not _try_lock(handle):
        if time.monotonic() >= deadline:
            raise FileAccessError(
                t(
                    "Another session is currently writing minutes for this sprint. Please "
                    "save again in a moment."
                )
            )
        time.sleep(0.05)


def _acquire_in_fallback(used: Path) -> IO[bytes]:
    """One-time second attempt when locking the file ``used`` fails permanently: the same
    file in the per-user temp folder. Without success (or if ``used`` was already there) a
    :class:`FileAccessError` is raised, never a wait."""
    unsupported = FileAccessError(
        t(
            (
                "File locks are not supported on the drive of {path}. Please move the settings "
                "folder to a local drive."
            ),
            path=used.parent,
        )
    )
    fallback_dir = _fallback_lock_dir()
    if fallback_dir == used.parent:
        raise unsupported
    try:
        handle = (fallback_dir / used.name).open("a+b")
    except OSError as e:
        raise unsupported from e
    try:
        _acquire(handle)
    except _LockUnsupported as e:
        handle.close()
        raise unsupported from e
    except BaseException:
        handle.close()
        raise
    return handle


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _locked(folder: Path, sprint_id: str, kind: str) -> Iterator[None]:
    """Locks the minutes of a sprint and meeting against other sessions on this machine. The
    lock is an operating system lock on a file (``flock``/``msvcrt.locking``): it ends with
    the process by itself and needs neither detection of orphaned locks nor a clock. Whoever
    waits, waits up to ``LOCK_WAIT_SECONDS``. It has no effect between clones on different
    machines; there the file name derived from the content protects. If locking fails
    permanently (file system without file locks), the same file in the temp folder is tried
    once; otherwise an error is raised."""
    handle, used = _open_lock(_lock_file(folder, sprint_id, kind))
    try:
        try:
            _acquire(handle)
        except _LockUnsupported:
            handle.close()
            handle = _acquire_in_fallback(used)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                _unlock(handle)
    finally:
        handle.close()


Clock = datetime | Callable[[], datetime] | None


def _resolve_now(now: Clock) -> datetime:
    """The timestamp for the file name. A ``datetime`` is used as passed; ``None`` or a
    function (e.g. ``datetime.now``) is only read here, i.e. after acquiring the lock: whoever
    waits longer for the lock thus never gets an earlier timestamp than the predecessor."""
    if isinstance(now, datetime):
        return now
    return (now() if now is not None else datetime.now()).replace(microsecond=0)


def write_protocol_new(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    text: str,
    now: Clock,
    state: str | None = None,
) -> tuple[Path, bool]:
    """Writes the minutes (LF line endings, via a temporary file) and reports whether they
    are new. With ``state`` (see :func:`fingerprint`) no further minutes are created if the
    state is unchanged; without ``state`` the text decides. If the name already exists (two
    saves in the same second), the second is counted up: nothing is lost. Searching and
    writing run under a lock per sprint and meeting (:func:`_locked`). ``now`` may be a
    ``datetime``, a function or ``None`` (then the clock is read only under the lock). Write
    errors are raised as :class:`FileAccessError`."""
    folder = _make_folder(repo, team)
    with _locked(folder, sprint_id, kind):
        return _write_locked(repo, team, sprint_id, kind, text, now, state)


def _make_folder(repo: Repository, team: str) -> Path:
    """Creates the minutes folder (errors as :class:`FileAccessError`)."""
    folder = _folder(repo, team)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise _not_saved(folder, e) from e
    return folder


def _write_locked(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    text: str,
    now: Clock,
    state: str | None,
) -> tuple[Path, bool]:
    """Body of :func:`write_protocol_new`. The caller holds the lock (:func:`_locked`); the
    operating system lock is not reentrant, so it must not be entered again here."""
    folder = _folder(repo, team)
    latest = next(
        (
            p
            for _, k, obsolete, p in list_protocols(repo, team, sprint_id)
            if k == kind and not obsolete
        ),
        None,
    )
    if latest is not None:
        same = _state_of(latest) == state if state is not None else _body(latest) == _body_of(text)
        if same:
            return latest, False  # nothing changed: no further identical minutes
    if state is not None:
        text = text.rstrip("\n") + f"\n\n{STATE_MARKER}{state} -->\n"
    # Part of the name derived from the content: two clones that save different things in
    # the same second thus never produce the same file name (otherwise a conflict when
    # merging).
    tag = (state or hashlib.sha256(text.encode("utf-8")).hexdigest())[:4]
    stamp = _resolve_now(now)
    while (path := folder / f"{sprint_id}-{kind}-{stamp:{STAMP}}-{tag}.md").exists():
        stamp += timedelta(seconds=1)
    write_text(path, text, newline="\n")  # temporary file, then replace: never read half-written
    invalidate_status()  # a new file is an open change, even without changed YAML
    return path, True


def write_protocol(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    text: str,
    now: Clock,
    state: str | None = None,
) -> Path:
    """Like :func:`write_protocol_new`, but returns only the file."""
    return write_protocol_new(repo, team, sprint_id, kind, text, now, state)[0]


def _persisted(repo: Repository, team: str, sprint: Sprint) -> dict:
    """The sprint file as ``save_sprint`` writes it, with the absence state pinned
    (``save_sprint`` pins it when saving; otherwise fingerprint and file would differ)."""
    copy = dataclasses.replace(sprint)
    if copy.absence_state is None:
        copy.absence_state = repo._pinned_absence_state(repo.sprint_path(team, sprint.id), copy)
    return sprint_to_dict(copy)


def save_with_protocol(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    text: str,
    now: Clock,
    sprints: list[Sprint],
    save: Callable[[], list[Path]],
) -> list[Path]:
    """Writes the minutes first, then ``save`` (the sprint files). If the minutes cannot be
    written, the sprint file stays unchanged; if ``save`` fails, the minutes just written are
    removed again: both succeed or neither. The lock (:func:`_locked`) covers the minutes,
    ``save`` and the rollback: a second session with the same state only adopts the minutes
    once the first has saved, and never minutes that the first deletes again right away.
    So ``save`` runs under the lock and must not enter it itself (it is not reentrant)."""
    state = fingerprint(text, *(_persisted(repo, team, s) for s in sprints))
    folder = _make_folder(repo, team)
    with _locked(folder, sprint_id, kind):
        path, created = _write_locked(repo, team, sprint_id, kind, text, now, state)
        try:
            return save()
        except BaseException as primary:
            if created:
                # If the rollback fails too (e.g. locked file), the original error counts;
                # the rollback error is attached to it as a note.
                try:
                    path.unlink(missing_ok=True)
                except OSError as e:
                    _note_rollback_failure(primary, path, e)
                invalidate_status()
            raise


def list_protocols(
    repo: Repository, team: str, sprint_id: str
) -> list[tuple[datetime, str, bool, Path]]:
    """The minutes of a sprint as (timestamp, meeting, obsolete, file), newest first."""
    folder = _folder(repo, team)
    found: list[tuple[datetime, str, bool, Path]] = []
    try:
        entries = list(folder.iterdir()) if folder.is_dir() else []
    except OSError as e:
        raise _not_readable(folder, e) from e
    for p in entries:
        m = _NAME.match(p.name)
        if m and m["sprint"] == sprint_id and p.is_file():
            try:
                at = datetime.strptime(m["at"], STAMP)
            except ValueError:  # renamed by hand or by sync: impossible timestamp
                continue
            found.append((at, m["kind"], m["obsolete"] is not None, p))
    return sorted(found, key=lambda f: (f[0], f[3].name), reverse=True)


def protocol_renames(
    repo: Repository, team: str, pairs: list[tuple[str, str]]
) -> list[tuple[Path, Path]]:
    """File renames by which the minutes of the sprints ``alt`` (old) are kept under ``neu``
    (new) from now on (obsolete ones too); only the sprint in the file name changes, not the
    content. Nothing is renamed here; the list is complete before a caller works through it."""
    found: list[tuple[Path, Path]] = []
    for old, new in pairs:
        for _, _, _, path in list_protocols(repo, team, old):
            found.append((path, path.with_name(new + path.name.removeprefix(old))))
    return found


def _note_rollback_failure(primary: BaseException, path: Path, error: OSError) -> None:
    """Attaches a failed rollback as a note to the original error (which stays the main
    error), so that it does not go unnoticed."""
    primary.add_note(t("{path}: not rolled back ({reason})", path=path, reason=str(error)))


def _undo(renamed: list[Path], primary: BaseException) -> None:
    """Undoes ``mark_obsolete`` as far as possible; if a rename back fails, that is attached
    as a note to the original error ``primary``."""
    for target in renamed:
        original = re.sub(r"_obsolet_\d{8}-\d{6}(?=\.md$)", "", target.name)
        try:
            target.replace(target.with_name(original))
        except OSError as e:
            _note_rollback_failure(primary, target, e)
    if renamed:
        invalidate_status()


def mark_obsolete(repo: Repository, team: str, sprint_id: str, kind: str, now: Clock) -> list[Path]:
    """Renames the valid minutes of the meeting to ``…_obsolet_<Datum>-<Zeit>.md`` (e.g. when
    the freeze of the sprint is lifted). Returns the new files. If a rename fails, those
    already renamed are renamed back (all or nothing). The lock is taken even if the folder
    does not exist yet (it is created; an empty folder is harmless): another session may
    create it at the same time and write minutes."""
    folder = _make_folder(repo, team)
    with _locked(folder, sprint_id, kind):
        return _mark_obsolete(repo, team, sprint_id, kind, now)


def _mark_obsolete(
    repo: Repository, team: str, sprint_id: str, kind: str, now: Clock
) -> list[Path]:
    renamed: list[Path] = []
    moment = _resolve_now(now)
    for _, found_kind, obsolete, path in list_protocols(repo, team, sprint_id):
        if found_kind != kind or obsolete:
            continue
        stamp = moment
        target = path.with_name(f"{path.stem}_obsolet_{stamp:{STAMP}}.md")
        while target.exists():  # two lifts in the same second
            stamp += timedelta(seconds=1)
            target = path.with_name(f"{path.stem}_obsolet_{stamp:{STAMP}}.md")
        try:
            path.replace(target)
        except OSError as e:
            error = FileAccessError(t("{path}: not renamed ({reason})", path=path, reason=str(e)))
            _undo(renamed, error)
            raise error from e
        renamed.append(target)
    if renamed:
        invalidate_status()
    return renamed


def obsolete_with_save(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    now: Clock,
    save: Callable[[], list[Path]],
) -> list[Path]:
    """Renames the minutes first and then writes the sprint file with ``save``; if saving
    fails, the minutes are renamed back: both succeed or neither. The lock (:func:`_locked`)
    covers renaming, ``save`` and renaming back, so that another session never sees an
    intermediate state (``save`` must not enter it itself). The lock also applies if the
    minutes folder does not exist yet (it is created): otherwise another session could save a
    Planning with minutes at the same time, and those would stay valid afterwards."""
    folder = _make_folder(repo, team)
    with _locked(folder, sprint_id, kind):
        renamed = _mark_obsolete(repo, team, sprint_id, kind, now)
        try:
            return save()
        except BaseException as primary:
            _undo(renamed, primary)
            raise
