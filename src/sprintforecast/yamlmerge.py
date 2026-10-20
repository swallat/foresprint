# SPDX-License-Identifier: EUPL-1.2
"""Three-way merge at key level for YAML data.

Different keys of the same file are combined; only if both sides changed the same value in
different ways does a :class:`KeyConflict` arise, which a human decides ("mine" or "theirs"
change). Lists of objects with an ``id`` (people, products) are merged entry by entry. The
forecasts of a sprint (list ``prognoses``, without ``id``) are combined by their timestamp
``at`` and then sorted ascending by ``at``: if two people each append a forecast, both stay.
All other lists count as a single value.
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

PROGNOSES = "prognoses"  # list without ``id``, combined by the timestamp ``at``


@dataclass(frozen=True)
class KeyConflict:
    """Both sides changed the value at ``path`` in different ways."""

    path: Path
    ours: Any  # MISSING = removed by me
    theirs: Any  # MISSING = removed by others

    @property
    def label(self) -> str:
        return ".".join(self.path) or "."


def keyed(items: Any) -> dict[str, dict] | None:
    """List of objects with a unique ``id`` as a mapping, else None."""
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
    """Merges ``ours`` and ``theirs`` on the basis of ``base`` (``MISSING`` = not present).
    Conflicts are resolved by ``choices[path]`` ("ours" or "theirs"); without a choice, our
    side stays in the result and the conflict is reported."""
    conflicts: list[KeyConflict] = []
    merged = _merge(base, ours, theirs, (), choices or {}, conflicts)
    return merged, conflicts


def same(a: Any, b: Any) -> bool:
    """Same value and same type: ``True`` is not ``1`` (Python treats them as equal, but in
    YAML they are different values), also not inside lists and objects."""
    if a is MISSING or b is MISSING:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True  # ``.nan`` is a value in YAML; nan == nan is false in Python
    return a == b


def _merge(base: Any, ours: Any, theirs: Any, path: Path, choices, conflicts) -> Any:
    if same(ours, theirs):
        return ours
    if same(ours, base):
        return theirs
    if same(theirs, base):
        return ours
    # Both changed it, in different ways.
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
    """Timestamp of a forecast entry (``datetime`` or ISO text), to the second."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    return value.replace(microsecond=0) if isinstance(value, datetime) else None


def _order(stamp: datetime) -> datetime:
    """Timestamp as an instant: converted to UTC if it has a time zone, and returned without
    a zone, so that different notations (``+00:00`` and ``+01:00``) and timestamps without a
    zone can be compared and sorted."""
    if stamp.tzinfo is None:
        return stamp
    return stamp.astimezone(UTC).replace(tzinfo=None)


def _key(stamp: datetime) -> str:
    """Key of a timestamp: the instant, not the notation."""
    return _order(stamp).isoformat()


def _by_stamp(items: Any) -> dict[str, tuple[datetime, dict]] | None:
    """Forecasts as a mapping timestamp (normalized) → (timestamp, entry); ``None`` if an
    entry has no readable ``at`` or an ``at`` occurs twice."""
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
    """Combines forecasts by their timestamp ``at`` (entries carry no ``id``): both sides may
    append without one getting lost. An entry counts as a whole; only the same ``at`` with
    different content causes a conflict (path ``…[<at>]``). The result is sorted ascending by
    ``at``. A base without forecasts (missing or empty key ``prognoses:``, i.e. ``None``)
    counts as an empty list. ``None`` = not applicable (no ``at``, duplicate ``at``, not a
    list): then the list counts as a single value, as with other lists."""
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
        # ``at`` normalized, so that datetime and text as well as different time zone
        # notations of the same instant compare equal
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
    merged.sort(key=lambda entry: _order(entry[0]))  # stable: equal timestamps keep their order
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
    """Leading comment block of a file (kept when merging)."""
    lines = []
    for line in text.splitlines(keepends=True):
        if line.startswith("#") or not line.strip():
            lines.append(line)
        else:
            break
    return "".join(lines)
