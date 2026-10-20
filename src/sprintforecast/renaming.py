# SPDX-License-Identifier: EUPL-1.2
"""Change sprint IDs after the fact.

A sprint gets a new ID; all saved sprints after it continue counting from it
(the team's numbering) so that the following IDs can still be derived. The sprint files
and the sprint's minutes are renamed; their contents stay unchanged.
"""

from __future__ import annotations

import contextlib
import copy
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from sprintforecast.calendar import expected_id_form, id_fits_numbering, next_id
from sprintforecast.i18n import t
from sprintforecast.model import Sprint
from sprintforecast.storage import (
    DataError,
    FileAccessError,
    Repository,
    TeamData,
    clear_team_cache,
    file_name_problem,
    not_readable,
)


@dataclass(frozen=True)
class Rename:
    old: str
    new: str


def plan_renames(data: TeamData, sprint_id: str, new_id: str) -> list[Rename]:
    """Renames that follow from "``sprint_id`` is now called ``new_id``": the sprint itself
    and all saved sprints after it, counted on by the team's numbering. Sprints whose ID stays
    the same are missing from the list. Raises DataError for an unknown sprint, an invalid ID,
    or if a new ID would collide with an earlier sprint."""
    new_id = new_id.strip()
    sprint = data.sprint(sprint_id)
    if sprint is None:
        raise DataError(
            t(
                "Sprint {id} is not saved (existing: {known}).",
                id=repr(sprint_id),
                known=", ".join(s.id for s in data.sprints) or t("none"),
            )
        )
    if not new_id:
        raise DataError(t("Please enter a new sprint ID."))
    if problem := file_name_problem(new_id, portable=False):
        raise DataError(t("ID not allowed as a file name ({problem}).", problem=problem))
    numbering = data.team.sprint.numbering
    if not id_fits_numbering(new_id, sprint.end, numbering):
        raise DataError(
            t(
                "Sprint ID {id} does not match the numbering (expected {expected}).",
                id=repr(new_id),
                expected=expected_id_form(numbering),
            )
        )
    position = data.sprints.index(sprint)
    untouched = {s.id for s in data.sprints[:position]}
    renames: list[Rename] = []
    previous = new_id
    for i, s in enumerate(data.sprints[position:]):
        target = new_id if i == 0 else next_id(previous, s.start, numbering)
        if target in untouched:
            raise DataError(
                t(
                    "Sprint ID {id} is already taken (by an earlier sprint).",
                    id=repr(target),
                )
            )
        if target != s.id:
            renames.append(Rename(s.id, target))
        previous = target
    return renames


@dataclass(frozen=True)
class Applied:
    """Result of ``apply_renames``: the new sprint files and all touched paths (old
    and new names of sprint files and minutes, for committing)."""

    files: list[Path]
    touched: list[Path]


def apply_renames(repo: Repository, data: TeamData, renames: list[Rename]) -> Applied:
    """Rename sprint files and minutes; all or nothing."""
    from sprintforecast.protocol import protocol_renames

    if not renames:
        return Applied([], [])
    key = data.team.key
    moves: list[tuple[Path, Path, Sprint]] = []
    for r in renames:
        sprint = data.sprint(r.old)
        assert sprint is not None
        renamed = copy.deepcopy(sprint)
        renamed.id = r.new
        moves.append((repo.sprint_path(key, r.old), repo.sprint_path(key, r.new), renamed))
    # Collect minutes before the first rename: otherwise a later sprint would find the
    # just-renamed files of its predecessor.
    protocols = protocol_renames(repo, key, [(r.old, r.new) for r in renames])
    sources = {old for old, _, _ in moves} | {src for src, _ in protocols}
    for new in [new for _, new, _ in moves] + [dst for _, dst in protocols]:
        if new.exists() and new not in sources:
            raise DataError(t("{path} already exists.", path=new))
    backup: dict[Path, bytes] = {}
    for old, _, _ in moves:
        try:
            backup[old] = old.read_bytes()
        except OSError as e:
            raise not_readable(old, e) from e
    written: list[Path] = []
    # Minutes in two steps: first all to an intermediate name, then to the new name.
    # If the chain overlaps (2026.20 → 2026.21, 2026.21 → 2026.22), a direct rename would
    # otherwise overwrite the successor's minutes.
    stamp = uuid.uuid4().hex[:8]
    staged = [(src, src.with_name(f"{src.name}.renaming-{stamp}"), dst) for src, dst in protocols]
    done: list[tuple[Path, Path]] = []  # (from, to) in execution order
    try:
        for old, _, _ in moves:
            _unlink(old)
        for _, _, sprint in moves:
            written.append(repo.save_sprint(key, sprint))
        for src, tmp, _ in staged:
            _replace(src, tmp)
            done.append((src, tmp))
        for _, tmp, dst in staged:
            _replace(tmp, dst)
            done.append((tmp, dst))
    except BaseException:
        for path in written:
            with contextlib.suppress(OSError):  # the original error is what matters
                path.unlink(missing_ok=True)
        for old, text in backup.items():
            with contextlib.suppress(OSError):
                old.write_bytes(text)
        for src, dst in reversed(done):
            with contextlib.suppress(OSError):
                os.replace(dst, src)
        clear_team_cache()
        raise
    clear_team_cache()
    touched = [old for old, _, _ in moves] + written
    touched += [src for src, _ in protocols] + [dst for _, dst in protocols]
    return Applied(written, list(dict.fromkeys(touched)))


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError as e:
        raise FileAccessError(
            t(
                (
                    "{path}: not deleted ({reason}). Is the file read-only or open in another "
                    "program?"
                ),
                path=path,
                reason=e.strerror or str(e),
            )
        ) from e


def _replace(src: Path, dst: Path) -> None:
    try:
        os.replace(src, dst)
    except OSError as e:
        raise FileAccessError(
            t("{path}: not renamed ({reason})", path=src, reason=e.strerror or str(e))
        ) from e
