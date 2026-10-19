# SPDX-License-Identifier: EUPL-1.2
"""Dreiwege-Zusammenführen auf Schlüsselebene für YAML-Daten.

Verschiedene Schlüssel derselben Datei werden vereinigt; nur wenn beide Seiten denselben Wert
unterschiedlich geändert haben, entsteht ein :class:`KeyConflict`, den ein Mensch entscheidet
(„meine“ oder „andere“ Änderung). Listen von Objekten mit ``id`` (Personen, Produkte) werden
je Eintrag zusammengeführt. Die Prognosen eines Sprints (Liste ``prognoses``, ohne ``id``) werden
über ihren Zeitpunkt ``at`` vereinigt und danach aufsteigend nach ``at`` sortiert: Hängen zwei
Personen je eine Prognose an, bleiben beide. Alle anderen Listen gelten als ein Wert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class _Missing:
    def __repr__(self) -> str:
        return "<fehlt>"


MISSING = _Missing()

OURS = "ours"
THEIRS = "theirs"

Path = tuple[str, ...]

PROGNOSES = "prognoses"  # Liste ohne ``id``, die über den Zeitpunkt ``at`` vereinigt wird


@dataclass(frozen=True)
class KeyConflict:
    """Beide Seiten haben den Wert unter ``path`` unterschiedlich geändert."""

    path: Path
    ours: Any  # MISSING = von mir entfernt
    theirs: Any  # MISSING = von anderen entfernt

    @property
    def label(self) -> str:
        return ".".join(self.path) or "."


def keyed(items: Any) -> dict[str, dict] | None:
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
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True  # ``.nan`` ist in YAML ein Wert; nan == nan ist in Python falsch
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
    if path and path[-1] == PROGNOSES:
        union = _merge_prognoses(base, ours, theirs, path, choices, conflicts)
        if union is not None:
            return union
    keyed_o, keyed_t = keyed(ours), keyed(theirs)
    if keyed_o is not None and keyed_t is not None and (base is MISSING or isinstance(base, list)):
        keyed_b = {} if base is MISSING or base == [] else keyed(base)
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


def _stamp(value: Any) -> datetime | None:
    """Zeitpunkt eines Prognose-Eintrags (``datetime`` oder ISO-Text) auf Sekunden genau."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    return value.replace(microsecond=0) if isinstance(value, datetime) else None


def _order(stamp: datetime) -> datetime:
    """Zeitpunkt als Instant: mit Zeitzone nach UTC gerechnet und ohne Zone, damit sich
    verschiedene Schreibweisen (``+00:00`` und ``+01:00``) und Zeitpunkte ohne Zone vergleichen
    und sortieren lassen."""
    if stamp.tzinfo is None:
        return stamp
    return stamp.astimezone(UTC).replace(tzinfo=None)


def _key(stamp: datetime) -> str:
    """Schlüssel eines Zeitpunkts: der Instant, nicht die Schreibweise."""
    return _order(stamp).isoformat()


def _by_stamp(items: Any) -> dict[str, tuple[datetime, dict]] | None:
    """Prognosen als Abbildung Zeitpunkt (normiert) → (Zeitpunkt, Eintrag); ``None``, wenn ein
    Eintrag keinen lesbaren ``at`` hat oder ein ``at`` doppelt vorkommt."""
    if not isinstance(items, list):
        return None
    out: dict[str, tuple[datetime, dict]] = {}
    for item in items:
        stamp = _stamp(item.get("at")) if isinstance(item, dict) else None
        if stamp is None or _key(stamp) in out:
            return None
        out[_key(stamp)] = (stamp, item)
    return out


def _merge_prognoses(base, ours, theirs, path, choices, conflicts) -> list | None:
    """Vereinigt Prognosen über ihren Zeitpunkt ``at`` (Einträge tragen keine ``id``): Beide
    Seiten dürfen anhängen, ohne dass eine verloren geht. Ein Eintrag gilt als Ganzes; nur bei
    gleichem ``at`` mit verschiedenem Inhalt entsteht ein Konflikt (Pfad ``…[<at>]``). Das
    Ergebnis ist nach ``at`` aufsteigend sortiert. Eine Basis ohne Prognosen (fehlender oder
    leerer Schlüssel ``prognoses:``, also ``None``) zählt als leere Liste. ``None`` = nicht
    anwendbar (kein ``at``, doppeltes ``at``, keine Liste): dann gilt die Liste wie sonst als
    ein Wert."""
    if not isinstance(ours, list) or not isinstance(theirs, list):
        return None
    empty_base = base is MISSING or base is None
    if not (empty_base or isinstance(base, list)):
        return None
    keyed_b = {} if empty_base else _by_stamp(base)
    keyed_o, keyed_t = _by_stamp(ours), _by_stamp(theirs)
    if keyed_b is None or keyed_o is None or keyed_t is None:
        return None

    def content(entry: tuple[datetime, dict] | None) -> Any:
        # ``at`` normiert, damit datetime und Text sowie verschiedene Zeitzonen-Schreibweisen
        # mit gleichem Zeitpunkt gleich sind
        if entry is None:
            return MISSING
        return {**entry[1], "at": _key(entry[0])}

    merged: list[tuple[datetime, dict]] = []
    for key in [*keyed_o, *(k for k in keyed_t if k not in keyed_o)]:
        b, o, t = keyed_b.get(key), keyed_o.get(key), keyed_t.get(key)
        sub = (*path, f"[{key}]")
        if same(content(o), content(t)):
            chosen = o
        elif same(content(o), content(b)):
            chosen = t
        elif same(content(t), content(b)):
            chosen = o
        else:
            choice = choices.get(sub)
            if choice is None:
                conflicts.append(KeyConflict(sub, o[1] if o else MISSING, t[1] if t else MISSING))
            chosen = t if choice == THEIRS else o
        if chosen is not None:
            merged.append(chosen)
    merged.sort(key=lambda entry: _order(entry[0]))  # stabil: gleiche Zeitpunkte bleiben
    return [entry for _, entry in merged]


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
