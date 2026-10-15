# SPDX-License-Identifier: EUPL-1.2
"""Umwandlung zwischen Web-Tabellen und Datenmodell – ohne Streamlit, damit testbar."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from sprintforecast.calendar import following_sprint
from sprintforecast.forecast import Forecast
from sprintforecast.model import Membership, Person, Sprint, new_person_id
from sprintforecast.storage import TeamData


def is_blank(value: Any) -> bool:
    """None, leerer Text oder NaN/NaT aus pandas."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return str(value) in {"NaT", "nan", "None"}


def as_date(value: Any) -> date | None:
    if is_blank(value):
        return None
    if hasattr(value, "date") and callable(value.date):  # pandas.Timestamp, datetime
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def with_sprints(data: TeamData, sprints: list[Sprint]) -> TeamData:
    """Kopie von ``data``, in der die genannten Sprints ersetzt bzw. ergänzt sind."""
    result = copy.deepcopy(data)
    by_id = {s.id: s for s in result.sprints}
    for s in sprints:
        by_id[s.id] = copy.deepcopy(s)
    result.sprints = sorted(by_id.values(), key=lambda s: s.start)
    return result


def with_people(data: TeamData, people: list[Person]) -> TeamData:
    result = copy.deepcopy(data)
    result.people = copy.deepcopy(people)
    return result


# --- Fehltage-Matrix ------------------------------------------------------------------


def absence_sprints(data: TeamData, fc: Forecast, count: int) -> list[Sprint]:
    """Laufender Sprint und die folgenden – erfasst oder aus dem Kalender erzeugt."""
    start = fc.current or fc.default_entry("next")
    if start is None:
        return []
    result = []
    sprint: Sprint | None = data.sprint(start.sprint.id) or copy.deepcopy(start.sprint)
    while sprint is not None and len(result) < count:
        result.append(copy.deepcopy(sprint))
        following = following_sprint(data.team, sprint)
        sprint = data.sprint(following.id) or following
    return result


def absence_matrix(people: list[Person], sprints: list[Sprint]) -> list[dict[str, Any]]:
    """Eine Zeile pro Person, eine Spalte pro Sprint (Fehltage); inaktive Zellen sind None."""
    rows = []
    for p in people:
        if not any(p.active_between(s.start, s.end) for s in sprints):
            continue
        row: dict[str, Any] = {"id": p.id, "Person": p.name}
        for s in sprints:
            row[s.id] = s.absences.get(p.id, 0.0) if p.active_between(s.start, s.end) else None
        rows.append(row)
    return rows


def edit_absences(
    people: list[Person], sprints: list[Sprint], rows: list[dict[str, Any]]
) -> list[Sprint]:
    """Überträgt die bearbeitete Matrix auf Kopien aller Sprints (gleiche Reihenfolge)."""
    by_id = {p.id: p for p in people}
    result = []
    for original in sprints:
        sprint = copy.deepcopy(original)
        for row in rows:
            person = by_id.get(str(row["id"]))
            if person is None or not person.active_between(sprint.start, sprint.end):
                continue
            value = row.get(sprint.id)
            days = 0.0 if is_blank(value) else float(value)
            if days:
                sprint.absences[person.id] = days
            else:
                sprint.absences.pop(person.id, None)
        result.append(sprint)
    return result


def sprints_to_save(data: TeamData, originals: list[Sprint], edited: list[Sprint]) -> list[Sprint]:
    """Geänderte Sprints plus Sprints ohne Datei – Speichern bestätigt deren Fehltage."""
    return [
        new
        for old, new in zip(originals, edited, strict=True)
        if new.absences != old.absences or data.sprint(new.id) is None
    ]


# --- Personen -------------------------------------------------------------------------

# Auswahlwert für „Bundesland wie im Team eingestellt“.
TEAM_REGION = "(Team)"
PEOPLE_COLUMNS = ["_id", "Name", "Bundesland", "ab", "bis", "FTE"]


def people_table(
    people: list[Person], today: date, show_former: bool
) -> tuple[list[dict[str, Any]], list[Person]]:
    """Eine Zeile je Zugehörigkeit. Liefert (Zeilen, ausgeblendete Personen)."""
    visible = [p for p in people if show_former or p.is_current(today)]
    hidden = [p for p in people if p not in visible]
    rows = [
        {
            "_id": p.id,
            "Name": p.name,
            "Bundesland": p.region or TEAM_REGION,
            "ab": m.start,
            "bis": m.end,
            "FTE": m.fte,
        }
        for p in sorted(visible, key=lambda p: p.name.lower())
        for m in p.memberships
    ]
    return rows, hidden


@dataclass
class PeopleResult:
    people: list[Person]
    errors: list[str]
    # Namen der Personen bzw. Zeiträume, die gegenüber dem Ausgangsstand fehlen.
    deleted: list[str]


def people_from_table(
    rows: list[dict[str, Any]], original: list[Person], hidden: list[Person]
) -> PeopleResult:
    """Baut die Personenliste aus der Tabelle. Neue Zeilen ohne ID gehören zur Person mit
    gleichem Namen (z. B. FTE-Änderung) oder bekommen eine neue ID."""
    errors: list[str] = []
    kept: dict[str, Person] = {p.id: copy.deepcopy(p) for p in hidden}
    original_by_id = {p.id: p for p in original}
    name_to_id = {p.name.strip().lower(): p.id for p in original}
    used = {p.id for p in original}
    visible_people: dict[str, Person] = {}

    for i, row in enumerate(rows, start=1):
        if all(is_blank(row.get(c)) for c in PEOPLE_COLUMNS if c != "_id"):
            continue
        name = "" if is_blank(row.get("Name")) else str(row["Name"]).strip()
        if not name:
            errors.append(f"Zeile {i}: Name fehlt")
            continue
        pid = None if is_blank(row.get("_id")) else str(row["_id"])
        if pid is None:
            pid = name_to_id.get(name.lower())
        if pid is None:
            pid = new_person_id(name, used)
            used.add(pid)
            name_to_id[name.lower()] = pid
        raw_region = row.get("Bundesland")
        region = None if is_blank(raw_region) or raw_region == TEAM_REGION else str(raw_region)
        person = visible_people.get(pid)
        if person is None:
            person = visible_people[pid] = Person(id=pid, name=name, region=region)
        elif person.name != name or person.region != region:
            errors.append(
                f"Zeile {i}: Für {person.name} stehen in mehreren Zeilen unterschiedliche Namen "
                "oder Bundesländer – bitte einheitlich eintragen."
            )
            continue
        try:
            start, end = as_date(row.get("ab")), as_date(row.get("bis"))
        except ValueError:
            errors.append(f"Zeile {i} ({name}): ungültiges Datum")
            continue
        if start is None:
            errors.append(f"Zeile {i} ({name}): 'ab' fehlt")
            continue
        fte = 1.0 if is_blank(row.get("FTE")) else float(row["FTE"])
        person.memberships.append(Membership(start=start, end=end, fte=fte))

    deleted = []
    for pid, before in original_by_id.items():
        if pid in kept:
            continue
        after = visible_people.get(pid)
        if after is None:
            deleted.append(before.name)
        elif len(after.memberships) < len(before.memberships):
            deleted.append(f"{before.name} (Zeitraum)")

    people = [*visible_people.values(), *kept.values()]
    for p in people:
        p.memberships.sort(key=lambda m: m.start)
    order = {p.id: n for n, p in enumerate(original)}
    people.sort(key=lambda p: (order.get(p.id, len(order)), p.name.lower()))
    return PeopleResult(people=people, errors=errors, deleted=deleted)


def parse_numbers(raw: str) -> list[float]:
    """„4,25 4.5“ → [4.25, 4.5]; wirft ValueError bei ungültigen Einträgen."""
    return [float(x.replace(",", ".")) for x in raw.replace(";", " ").split()]
