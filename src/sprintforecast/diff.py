# SPDX-License-Identifier: EUPL-1.2
"""Änderungen an den YAML-Daten als Wertänderungen (nur lesend).

:func:`diff_values` vergleicht zwei geladene YAML-Werte und liefert je geänderten Wert einen
:class:`ValueChange` mit Pfad, altem und neuem Wert. Listen von Objekten mit ``id`` (Personen,
Produkte) werden je Eintrag verglichen, alle anderen Listen als ein Wert – wie beim Zusammenführen
(:mod:`sprintforecast.yamlmerge`). :func:`file_changes` vergleicht den Arbeitsstand mit dem
letzten Commit.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sprintforecast import git as gitmod
from sprintforecast.git import Change, GitError, changes_in
from sprintforecast.gitsync import _parse
from sprintforecast.yamlmerge import MISSING, keyed, same

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"

_YAML_SUFFIXES = {".yaml", ".yml"}
# Größere Dateien gelten als nicht lesbar: Sie kommen ggf. aus einem fremden Repository.
_MAX_BYTES = 5 * 1024 * 1024
_EVAL_LIMIT = 100  # so viele Dateien werden ausgewertet (die Oberfläche zeigt weniger)
# Probleme von Git selbst (nicht der einen Datei) sehen Aufrufer, statt als „nicht lesbar“ zu
# erscheinen.
_GIT_PROBLEMS = {"git_missing", "unsafe_directory", "offline"}


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
    orig: str = ""  # bisheriger Pfad bei Umbenennungen und Kopien, relativ zur Wurzel


def diff_values(old: Any, new: Any, path: tuple[str, ...] = ()) -> list[ValueChange]:
    """Alle Unterschiede zwischen ``old`` und ``new`` in der Reihenfolge der Schlüssel.

    Ändert sich bei Listen mit ``id`` nur die Reihenfolge der Einträge, steht dafür eine
    Änderung unter dem Pfad der Liste mit den ``id`` davor und danach."""
    if same(old, new):
        return []
    if isinstance(old, dict) and isinstance(new, dict):
        return _diff_mapping(old, new, path, item=False)
    keyed_old, keyed_new = keyed(old), keyed(new)
    # Eine leere Liste ist die leere Abbildung, wenn die andere Seite Objekte mit id enthält
    # (erstes Objekt hinzugefügt, letztes entfernt): So bleibt der Pfad [id] erhalten.
    if keyed_old is None and old == [] and keyed_new is not None:
        keyed_old = {}
    if keyed_new is None and new == [] and keyed_old is not None:
        keyed_new = {}
    if keyed_old is not None and keyed_new is not None:
        changes = _diff_mapping(keyed_old, keyed_new, path, item=True)
        order_old = [k for k in keyed_old if k in keyed_new]
        order_new = [k for k in keyed_new if k in keyed_old]
        if order_old != order_new:
            changes.append(ValueChange(path, list(keyed_old), list(keyed_new)))
        return changes
    return [ValueChange(path, old, new)]


def _diff_mapping(
    old: dict[Any, Any], new: dict[Any, Any], path: tuple[str, ...], item: bool
) -> list[ValueChange]:
    changes: list[ValueChange] = []
    for key in [*old, *(k for k in new if k not in old)]:
        sub = (*path, f"[{key}]" if item else str(key))
        changes.extend(diff_values(old.get(key, MISSING), new.get(key, MISSING), sub))
    return changes


def _head_text(root: Path, file: str) -> str:
    if int(gitmod._git(root, "cat-file", "-s", f"HEAD:{file}")) > _MAX_BYTES:
        raise ValueError(file)
    return gitmod._git_bytes(root, "show", f"HEAD:{file}").decode("utf-8")


def _work_text(root: Path, file: str) -> str:
    """Inhalt im Arbeitsbaum; ``FileNotFoundError``, wenn die Datei fehlt. Symlinks werden nicht
    gefolgt: Das Ziel kann außerhalb des Repositorys liegen."""
    path = root / file
    if path.is_symlink() or path.stat().st_size > _MAX_BYTES:
        raise ValueError(file)
    return path.read_text(encoding="utf-8")


def _file_change(root: Path, change: Change) -> FileChange:
    file, status = change.file, change.status
    orig = change.orig
    unreadable = FileChange(file, status, readable=False, orig=orig)
    if any(Path(f).suffix.lower() not in _YAML_SUFFIXES for f in (file, change.orig or file)):
        return unreadable
    old: Any = MISSING
    new: Any = MISSING
    try:
        if "A" not in status and status != "??":
            old = _parse(_head_text(root, change.orig or file))
        with contextlib.suppress(FileNotFoundError):  # gelöscht, auch „von ihnen gelöscht“
            new = _parse(_work_text(root, file))
        if old is MISSING or new is MISSING:
            return FileChange(file, status, orig=orig)
        return FileChange(file, status, tuple(diff_values(old, new)), orig=orig)
    except GitError as e:
        if e.kind in _GIT_PROBLEMS:
            raise
        return unreadable
    except yaml.YAMLError, ValueError, OSError, RecursionError:  # ValueError: auch Unicode
        return unreadable


def file_changes(path: Path) -> list[FileChange]:
    """Nicht committete Änderungen unterhalb von ``path`` als Wertänderungen je Datei."""
    root = gitmod.require_root(path)
    # Nur die ersten Dateien werden ausgewertet; die übrigen kommen ohne Werte (lesbar).
    return [
        _file_change(root, c) if i < _EVAL_LIMIT else FileChange(c.file, c.status, orig=c.orig)
        for i, c in enumerate(changes_in(path))
    ]


_CACHE: dict[Path, tuple[tuple[Any, ...], list[FileChange]]] = {}


def _signature(root: Path, pending: list[tuple[str, str]]) -> tuple[Any, ...]:
    """Status, Datei, Änderungszeit (ns) und Größe der Arbeitsdatei (``None``, wenn sie fehlt)."""
    parts: list[tuple[Any, ...]] = []
    for status, file in pending:
        try:
            stat = (root / file).lstat()
            parts.append((status, file, stat.st_mtime_ns, stat.st_size))
        except OSError:
            parts.append((status, file, None, None))
    return tuple(parts)


def cached_file_changes(path: Path, pending: list[tuple[str, str]]) -> list[FileChange]:
    """Wie :func:`file_changes`, aber nur neu berechnet, wenn sich ``pending`` (die Liste aus
    :func:`sprintforecast.git.cached_pending_changes`) oder eine Arbeitsdatei geändert hat (für
    die Oberfläche, die bei jeder Eingabe neu zeichnet). Wird mit
    :func:`sprintforecast.git.invalidate_status` geleert."""
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
