# SPDX-License-Identifier: EUPL-1.2
"""Sprint-IDs nachträglich ändern.

Ein Sprint bekommt eine neue ID; alle gespeicherten Sprints danach zählen von ihr aus weiter
(Nummerierung des Teams), damit die Folge-IDs weiterhin bildbar bleiben. Umbenannt werden die
Sprintdateien und die Protokolle des Sprints; die Inhalte bleiben unverändert.
"""

from __future__ import annotations

import contextlib
import copy
import os
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
    """Umbenennungen, die aus „``sprint_id`` heißt künftig ``new_id``“ folgen: der Sprint selbst
    und alle gespeicherten Sprints danach, fortgezählt nach der Nummerierung des Teams. Sprints,
    deren ID dabei gleich bleibt, fehlen in der Liste. Wirft DataError bei unbekanntem Sprint,
    unzulässiger ID oder wenn eine neue ID mit einem früheren Sprint zusammenfiele."""
    new_id = new_id.strip()
    sprint = data.sprint(sprint_id)
    if sprint is None:
        raise DataError(
            t(
                "Sprint {id} ist nicht gespeichert (vorhanden: {known}).",
                id=repr(sprint_id),
                known=", ".join(s.id for s in data.sprints) or t("keine"),
            )
        )
    if not new_id:
        raise DataError(t("Bitte eine neue Sprint-ID eingeben."))
    if problem := file_name_problem(new_id, portable=False):
        raise DataError(t("ID nicht zulässig als Dateiname ({problem}).", problem=problem))
    numbering = data.team.sprint.numbering
    if not id_fits_numbering(new_id, sprint.end, numbering):
        raise DataError(
            t(
                "Sprint-ID {id} passt nicht zur Nummerierung (erwartet {expected}).",
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
                    "Sprint-ID {id} ist schon vergeben (an einen früheren Sprint).",
                    id=repr(target),
                )
            )
        if target != s.id:
            renames.append(Rename(s.id, target))
        previous = target
    return renames


def apply_renames(repo: Repository, data: TeamData, renames: list[Rename]) -> list[Path]:
    """Benennt Sprintdateien und Protokolle um; ganz oder gar nicht. Liefert die neuen
    Sprintdateien (zum Prüfen und Committen; die alten Pfade dazu nennt ``old_paths``)."""
    from sprintforecast.protocol import protocol_renames

    if not renames:
        return []
    key = data.team.key
    moves: list[tuple[Path, Path, Sprint]] = []
    for r in renames:
        sprint = data.sprint(r.old)
        assert sprint is not None
        renamed = copy.deepcopy(sprint)
        renamed.id = r.new
        moves.append((repo.sprint_path(key, r.old), repo.sprint_path(key, r.new), renamed))
    # Protokolle vor dem ersten Umbenennen sammeln: Sonst fände ein späterer Sprint die gerade
    # umbenannten Dateien seines Vorgängers.
    protocols = protocol_renames(repo, key, [(r.old, r.new) for r in renames])
    sources = {old for old, _, _ in moves}
    for _, new, _ in moves:
        if new.exists() and new not in sources:
            raise DataError(t("{path} existiert bereits.", path=new))
    backup: dict[Path, bytes] = {}
    for old, _, _ in moves:
        try:
            backup[old] = old.read_bytes()
        except OSError as e:
            raise not_readable(old, e) from e
    written: list[Path] = []
    done_protocols: list[tuple[Path, Path]] = []
    try:
        for old, _, _ in moves:
            _unlink(old)
        for _, _, sprint in moves:
            written.append(repo.save_sprint(key, sprint))
        for src, dst in protocols:
            _replace(src, dst)
            done_protocols.append((src, dst))
    except BaseException:
        for path in written:
            with contextlib.suppress(OSError):  # der ursprüngliche Fehler zählt
                path.unlink(missing_ok=True)
        for old, text in backup.items():
            with contextlib.suppress(OSError):
                old.write_bytes(text)
        for src, dst in done_protocols:
            with contextlib.suppress(OSError):
                os.replace(dst, src)
        clear_team_cache()
        raise
    clear_team_cache()
    return written


def old_paths(repo: Repository, data: TeamData, renames: list[Rename]) -> list[Path]:
    return [repo.sprint_path(data.team.key, r.old) for r in renames]


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError as e:
        raise FileAccessError(
            t(
                "{path}: nicht gelöscht ({reason}). Ist die Datei schreibgeschützt oder in "
                "einem anderen Programm geöffnet?",
                path=path,
                reason=e.strerror or str(e),
            )
        ) from e


def _replace(src: Path, dst: Path) -> None:
    try:
        os.replace(src, dst)
    except OSError as e:
        raise FileAccessError(
            t("{path}: nicht umbenannt ({reason})", path=src, reason=e.strerror or str(e))
        ) from e
