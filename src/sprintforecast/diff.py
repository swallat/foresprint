# SPDX-License-Identifier: EUPL-1.2
"""Änderungen an den YAML-Daten als Wertänderungen (nur lesend).

:func:`diff_values` vergleicht zwei geladene YAML-Werte und liefert je geänderten Wert einen
:class:`ValueChange` mit Pfad, altem und neuem Wert. Listen von Objekten mit ``id`` (Personen,
Produkte) werden je Eintrag verglichen, alle anderen Listen als ein Wert – wie beim Zusammenführen
(:mod:`sprintforecast.yamlmerge`). :func:`file_changes` vergleicht den Arbeitsstand mit dem
letzten Commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sprintforecast import git as gitmod
from sprintforecast.git import Change, changes_in
from sprintforecast.yamlmerge import MISSING, _keyed, same

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"

_YAML_SUFFIXES = {".yaml", ".yml"}


@dataclass(frozen=True)
class ValueChange:
    """Ein Wert unter ``path``; ``MISSING`` bedeutet „nicht vorhanden“."""

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
    """Die Änderungen einer Datei. ``values`` ist leer, wenn die Datei kein lesbares YAML ist
    (``readable`` False) oder nur die Datei als Ganzes neu, gelöscht oder umbenannt ist."""

    file: str  # relativ zur Repository-Wurzel
    status: str  # wie :attr:`sprintforecast.git.Change.status`
    values: tuple[ValueChange, ...] = ()
    readable: bool = True


def diff_values(old: Any, new: Any, path: tuple[str, ...] = ()) -> list[ValueChange]:
    """Alle Unterschiede zwischen ``old`` und ``new`` in der Reihenfolge der Schlüssel."""
    if same(old, new):
        return []
    if isinstance(old, dict) and isinstance(new, dict):
        return _diff_mapping(old, new, path, item=False)
    keyed_old, keyed_new = _keyed(old), _keyed(new)
    if keyed_old is not None and keyed_new is not None:
        return _diff_mapping(keyed_old, keyed_new, path, item=True)
    return [ValueChange(path, old, new)]


def _diff_mapping(
    old: dict[Any, Any], new: dict[Any, Any], path: tuple[str, ...], item: bool
) -> list[ValueChange]:
    changes: list[ValueChange] = []
    for key in [*old, *(k for k in new if k not in old)]:
        sub = (*path, f"[{key}]" if item else str(key))
        before, after = old.get(key, MISSING), new.get(key, MISSING)
        if before is MISSING or after is MISSING:
            if not same(before, after):
                changes.append(ValueChange(sub, before, after))
        else:
            changes.extend(diff_values(before, after, sub))
    return changes


def _parse(text: str) -> Any:
    from sprintforecast.gitsync import _parse as parse

    return parse(text)


def _head_text(root: Path, file: str) -> str:
    return gitmod._git_bytes(root, "show", f"HEAD:{file}").decode("utf-8")


def _file_change(root: Path, change: Change) -> FileChange:
    file = change.file
    if Path(file).suffix.lower() not in _YAML_SUFFIXES:
        return FileChange(file, change.status, readable=False)
    old: Any = MISSING
    new: Any = MISSING
    try:
        if "A" not in change.status and change.status != "??":
            old = _parse(_head_text(root, change.orig or file))
        if "D" not in change.status:
            new = _parse((root / file).read_text(encoding="utf-8"))
    except Exception:  # GitError, OSError, Unicode- und YAML-Fehler
        return FileChange(file, change.status, readable=False)
    if old is MISSING or new is MISSING:
        return FileChange(file, change.status)
    return FileChange(file, change.status, tuple(diff_values(old, new)))


def file_changes(path: Path) -> list[FileChange]:
    """Nicht committete Änderungen unterhalb von ``path`` als Wertänderungen je Datei."""
    root = gitmod.require_root(path)
    return [_file_change(root, c) for c in changes_in(path)]
