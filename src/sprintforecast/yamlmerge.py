# SPDX-License-Identifier: EUPL-1.2
"""Dreiwege-Zusammenführen auf Schlüsselebene für YAML-Daten.

Verschiedene Schlüssel derselben Datei werden vereinigt; nur wenn beide Seiten denselben Wert
unterschiedlich geändert haben, entsteht ein :class:`KeyConflict`, den ein Mensch entscheidet
(„meine“ oder „andere“ Änderung). Listen von Objekten mit ``id`` (Personen, Produkte) werden
je Eintrag zusammengeführt, alle anderen Listen als ein Wert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class _Missing:
    def __repr__(self) -> str:
        return "<fehlt>"


MISSING = _Missing()

OURS = "ours"
THEIRS = "theirs"

Path = tuple[str, ...]


@dataclass(frozen=True)
class KeyConflict:
    """Beide Seiten haben den Wert unter ``path`` unterschiedlich geändert."""

    path: Path
    ours: Any  # MISSING = von mir entfernt
    theirs: Any  # MISSING = von anderen entfernt

    @property
    def label(self) -> str:
        return ".".join(self.path) or "."


def _keyed(items: Any) -> dict[str, dict] | None:
    """Liste von Objekten mit eindeutiger ``id`` als Abbildung, sonst None."""
    if not isinstance(items, list) or not items:
        return None
    ids = []
    for item in items:
        if not isinstance(item, dict) or "id" not in item:
            return None
        ids.append(str(item["id"]))
    return dict(zip(ids, items, strict=True)) if len(set(ids)) == len(ids) else None


def merge3(
    base: Any, ours: Any, theirs: Any, choices: dict[Path, str] | None = None
) -> tuple[Any, list[KeyConflict]]:
    """Führt ``ours`` und ``theirs`` auf Basis von ``base`` zusammen (``MISSING`` = nicht
    vorhanden). Für Konflikte gilt ``choices[path]`` ("ours" oder "theirs"); ohne Wahl bleibt
    die eigene Seite im Ergebnis und der Konflikt wird gemeldet."""
    conflicts: list[KeyConflict] = []
    merged = _merge(base, ours, theirs, (), choices or {}, conflicts)
    return merged, conflicts


def same(a: Any, b: Any) -> bool:
    """Gleicher Wert und gleiche Art: ``True`` ist nicht ``1`` (Python setzt beide gleich, in
    YAML sind es aber verschiedene Werte), auch nicht innerhalb von Listen und Objekten."""
    if a is MISSING or b is MISSING:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _merge(base: Any, ours: Any, theirs: Any, path: Path, choices, conflicts) -> Any:
    if same(ours, theirs):
        return ours
    if same(ours, base):
        return theirs
    if same(theirs, base):
        return ours
    # Beide haben geändert, unterschiedlich.
    if isinstance(ours, dict) and isinstance(theirs, dict):
        return _merge_dicts(
            base if isinstance(base, dict) else {}, ours, theirs, path, choices, conflicts
        )
    keyed_o, keyed_t = _keyed(ours), _keyed(theirs)
    if keyed_o is not None and keyed_t is not None and (base is MISSING or isinstance(base, list)):
        keyed_b = {} if base is MISSING or base == [] else _keyed(base)
        if keyed_b is not None:
            merged = _merge_dicts(keyed_b, keyed_o, keyed_t, path, choices, conflicts, item=True)
            return list(merged.values())
    choice = choices.get(path)
    if choice == THEIRS:
        return theirs
    if choice == OURS:
        return ours
    conflicts.append(KeyConflict(path, ours, theirs))
    return ours


def _merge_dicts(base, ours, theirs, path, choices, conflicts, item: bool = False) -> dict:
    keys = list(ours) + [k for k in theirs if k not in ours]
    merged = {}
    for key in keys:
        sub = (*path, f"[{key}]" if item else str(key))
        value = _merge(
            base.get(key, MISSING), ours.get(key, MISSING), theirs.get(key, MISSING), sub,
            choices, conflicts,
        )  # fmt: skip
        if value is not MISSING:
            merged[key] = value
    return merged


def header_of(text: str) -> str:
    """Führender Kommentarblock einer Datei (bleibt beim Zusammenführen erhalten)."""
    lines = []
    for line in text.splitlines(keepends=True):
        if line.startswith("#") or not line.strip():
            lines.append(line)
        else:
            break
    return "".join(lines)
