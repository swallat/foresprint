# SPDX-License-Identifier: EUPL-1.2
"""Umwandlung zwischen Web-Tabellen und Datenmodell – ohne Streamlit, damit testbar."""

from __future__ import annotations

import copy
import math
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sprintforecast import config
from sprintforecast.calendar import (
    following_sprint,
    next_id,
    team_workdays,
    weekend_from_workweek,
)
from sprintforecast.forecast import Forecast, build_forecast, find_sprint
from sprintforecast.i18n import t
from sprintforecast.model import (
    AbsenceState,
    Membership,
    Person,
    Product,
    ProductValues,
    Prognosis,
    Sprint,
    absence_status,
    new_person_id,
)
from sprintforecast.products import MEASURES, PRODUCTION_MEASURES, Distribution
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


def open_velocity_sprints(fc: Forecast, count: int = 2) -> list[Sprint]:
    """Laufende bzw. abgelaufene Sprints ohne erfasste Velocity (die letzten ``count``) –
    für sie lässt sich eine erwartete Velocity annehmen."""
    open_ = [
        e.sprint for e in fc.entries if e.sprint.start <= fc.today and e.sprint.velocity is None
    ]
    return open_[-count:]


@dataclass(frozen=True)
class Assumption:
    """Prognose des Teams für einen offenen Sprint."""

    forecast_ist: float
    not_done: float | None = None
    additional_done: float | None = None

    @property
    def expected(self) -> float:
        """Erwartete erledigte Menge (Velocity)."""
        return max(self.forecast_ist - (self.not_done or 0.0) + (self.additional_done or 0.0), 0.0)


def record_prognoses(
    data: TeamData,
    target: Sprint,
    assumed: dict[str, Assumption],
    plan: float | None,
    comment: str,
    now: datetime | None = None,
) -> list[Sprint]:
    """Hängt die Annahmen als Prognose an die betroffenen Sprints (Kopien) und liefert alle zu
    speichernden Sprints samt ``target`` (der Zielsprint der Vorplanung)."""
    now = (now or datetime.now()).replace(microsecond=0)
    result = {target.id: target}
    preplanned = {
        pid: v.preplanned for pid, v in target.products.items() if v.preplanned is not None
    }
    for sprint_id, a in assumed.items():
        sprint = result.get(sprint_id)
        if sprint is None:
            found = find_sprint(data, sprint_id)
            if found is None:
                continue
            sprint = result[sprint_id] = copy.deepcopy(found)
        sprint.prognoses.append(
            Prognosis(
                at=now,
                comment=comment.strip() or None,
                forecast_ist=a.forecast_ist,
                not_done=a.not_done,
                additional_done=a.additional_done,
                expected_done=a.expected,
                target=target.id,
                plan=plan,
                preplanned=preplanned,
            )
        )
    return list(result.values())


def default_forecast_ist(fc: Forecast, sprint: Sprint) -> float | None:
    """Vorbelegung des Commitments im Was-wäre-wenn: der erfasste Wert des Sprints, sonst der
    des nächstfrüheren Sprints, für den einer erfasst ist."""
    if sprint.forecast_ist is not None:
        return sprint.forecast_ist
    earlier = [e.sprint for e in fc.entries if e.sprint.start < sprint.start]
    return next((s.forecast_ist for s in reversed(earlier) if s.forecast_ist is not None), None)


def whatif_forecast(fc: Forecast, velocities: dict[str, float] | dict[str, Assumption]) -> Forecast:
    """Forecast unter der Annahme, dass die genannten Sprints die Velocity erreichen.
    Nichts wird gespeichert; ``fc`` bleibt unverändert."""
    changed = []
    for sprint_id, velocity in velocities.items():
        sprint = find_sprint(fc.data, sprint_id)
        if sprint is None:
            continue
        sprint = copy.deepcopy(sprint)
        sprint.velocity = velocity.expected if isinstance(velocity, Assumption) else velocity
        changed.append(sprint)
    return build_forecast(with_sprints(fc.data, changed), fc.today)


def with_people(data: TeamData, people: list[Person]) -> TeamData:
    result = copy.deepcopy(data)
    result.people = copy.deepcopy(people)
    return result


# --- Fehltage-Matrix ------------------------------------------------------------------


def absence_sprints(data: TeamData, fc: Forecast, count: int, past: int = 0) -> list[Sprint]:
    """Laufender Sprint und die folgenden – erfasst oder aus dem Kalender erzeugt –, davor
    optional die letzten ``past`` abgeschlossenen Sprints (zum Nachtragen von Fehltagen)."""
    start = fc.current or fc.default_entry("next")
    if start is None:
        return []
    result: list[Sprint] = []
    if past > 0:
        earlier = [e.sprint.id for e in fc.history()][-past:]
        result += [copy.deepcopy(s) for sid in earlier if (s := data.sprint(sid)) is not None]
    chain_start = len(result)
    sprint: Sprint | None = data.sprint(start.sprint.id) or copy.deepcopy(start.sprint)
    while sprint is not None and len(result) - chain_start < count:
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
    people: list[Person],
    sprints: list[Sprint],
    rows: list[dict[str, Any]],
    confirmed: Collection[str] | None = None,
) -> list[Sprint]:
    """Überträgt die bearbeitete Matrix auf Kopien aller Sprints (gleiche Reihenfolge).

    Eingetragene Fehltage bestätigen den Sprint. Ohne Einträge bestätigt nichts stillschweigend:
    ``confirmed`` nennt die Sprints, für die ausdrücklich „niemand fehlt“ bestätigt ist. Ist
    ``confirmed`` angegeben, verliert ein Sprint ohne Einträge, der dort fehlt, seine
    Bestätigung (zurück auf unbekannt); ohne Angabe bleibt der Stand unverändert."""
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
        if sprint.absences or (confirmed is not None and sprint.id in confirmed):
            sprint.absence_state = AbsenceState.CONFIRMED
        elif confirmed is not None and absence_status(original) is AbsenceState.CONFIRMED:
            sprint.absence_state = AbsenceState.UNKNOWN  # Bestätigung aufgehoben
        result.append(sprint)
    return result


def _only_absences(sprint: Sprint) -> bool:
    """Sprint trägt außer (leeren) Fehltagen nichts – eine reine Bestätigung der Fehltage."""
    return (
        sprint.capacity is None
        and sprint.forecast_ist is None
        and sprint.velocity is None
        and sprint.scope_creep is None
        and sprint.planning is None
        and sprint.forecast_plan is None
        and not sprint.products
        and not sprint.note
    )


def resettable_sprints(data: TeamData, today: date) -> list[Sprint]:
    """Künftige Sprintdateien, die nur Fehltage enthalten und am Ende der erfassten Sprints
    stehen: Löschen stellt „keine Informationen“ her (Fehltage wieder nach der Historie
    geschätzt)."""
    result: list[Sprint] = []
    for sprint in reversed(sorted(data.sprints, key=lambda s: s.start)):
        if sprint.start > today and _only_absences(sprint):
            result.append(sprint)
        else:
            break
    return sorted(result, key=lambda s: s.start)


def sprints_to_save(data: TeamData, originals: list[Sprint], edited: list[Sprint]) -> list[Sprint]:
    """Sprints, deren Fehltage oder deren Stand (unbekannt / angekündigt / bestätigt) sich
    geändert haben. Sprints ohne Datei werden nur angelegt, wenn dazu etwas eingetragen oder
    bestätigt wurde."""
    return [
        new
        for old, new in zip(originals, edited, strict=True)
        if new.absences != old.absences or absence_status(new) is not absence_status(old)
    ]


# --- Sprintkalender -------------------------------------------------------------------

CALENDAR_COLUMNS = ["Sprint", "Start", "Letzter Tag", "Arbeitstage", "Status"]


def calendar_table(data: TeamData, sprints: list[Sprint], today: date) -> list[dict[str, Any]]:
    """Eine Zeile je Sprint; „Letzter Tag“ = Ende − 1 (das Ende ist der Start des nächsten)."""
    rows = []
    for s in sprints:
        if s.end <= today:
            state = "abgeschlossen"
        elif s.start <= today:
            state = "laufend"
        else:
            state = "geplant" if data.sprint(s.id) else "noch ohne Datei"
        rows.append(
            {
                "Sprint": s.id,
                "Start": s.start,
                "Letzter Tag": s.end - timedelta(days=1),
                "Arbeitstage": len(team_workdays(data.team, s.start, s.end)),
                "Status": state,
            }
        )
    return rows


def apply_calendar(
    data: TeamData, sprints: list[Sprint], rows: list[dict[str, Any]]
) -> tuple[list[Sprint], list[str]]:
    """Übernimmt geänderte letzte Tage; jeder folgende Sprint beginnt am Tag danach und
    behält seine Länge, sofern sein letzter Tag nicht selbst geändert wurde. IDs noch nicht
    angelegter Sprints werden neu vergeben. Liefert (Sprints, Fehler)."""
    errors: list[str] = []
    result: list[Sprint] = []
    persisted = {s.id for s in data.sprints}
    for i, (original, row) in enumerate(zip(sprints, rows, strict=True)):
        sprint = copy.deepcopy(original)
        if result:
            previous = result[-1]
            sprint.start = previous.end
            if data.sprint(original.id) is None:
                sprint.id = next_id(previous.id, sprint.start, data.team.sprint.numbering)
        try:
            last = as_date(row.get("Letzter Tag"))
        except ValueError:
            last = None
        if last is None:
            errors.append(t("Zeile {row}: letzter Tag fehlt", row=i + 1))
            last = original.end - timedelta(days=1)
        if last == original.end - timedelta(days=1):
            # unverändert → Länge behalten, d. h. mit dem Vorgänger mitverschieben
            end = sprint.start + (original.end - original.start)
        else:
            end = last + timedelta(days=1)
        if end <= sprint.start:
            errors.append(
                t(
                    "Sprint {id}: letzter Tag liegt vor dem Start {start}",
                    id=sprint.id,
                    start=sprint.start,
                )
            )
        sprint.end = end if end > sprint.start else original.end
        if sprint.id != original.id and (
            sprint.id in persisted or any(s.id == sprint.id for s in result)
        ):
            errors.append(
                t(
                    "Sprint-ID {id} wäre doppelt – bitte zuerst die folgenden Sprints anpassen.",
                    id=sprint.id,
                )
            )
        result.append(sprint)
    # Gespeicherte Sprints nach dem angezeigten Zeitraum um dieselbe Differenz verschieben.
    if sprints and result:
        delta = result[-1].end - sprints[-1].end
        if delta:
            for later in data.sprints:
                if later.start >= sprints[-1].end:
                    moved = copy.deepcopy(later)
                    moved.start += delta
                    moved.end += delta
                    result.append(moved)
    return result, errors


def calendar_to_save(
    data: TeamData, originals: list[Sprint], after: list[Sprint], create_missing: bool
) -> list[Sprint]:
    """Zu speichernde Sprints: geänderte Daten, auf Wunsch fehlende Dateien und verschobene
    gespeicherte Sprints nach dem angezeigten Zeitraum."""
    window, shifted = after[: len(originals)], after[len(originals) :]
    changed = [
        new
        for old, new in zip(originals, window, strict=True)
        if (old.start, old.end) != (new.start, new.end)
        or (create_missing and data.sprint(new.id) is None)
    ]
    return changed + shifted


# --- Personen -------------------------------------------------------------------------

# Auswahlwert für „Bundesland wie im Team eingestellt“.
TEAM_REGION = "(Team)"
PEOPLE_COLUMNS = [
    "_id",
    "Name",
    "Land",
    "Bundesland",
    "Arbeitswoche",
    "ab",
    "bis",
    "FTE",
    "Produktionszugriff",
]
# Spalten, die allein eine Zeile nicht „befüllt“ machen (Häkchen-Spalte hat immer einen Wert).
PEOPLE_FLAG_COLUMNS = ("_id", "Produktionszugriff")


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
            "Land": p.country or TEAM_REGION,
            "Bundesland": p.region or TEAM_REGION,
            "Arbeitswoche": p.workweek or "",
            "ab": m.start,
            "bis": m.end,
            "FTE": m.fte,
            "Produktionszugriff": p.production_access,
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
        if all(is_blank(row.get(c)) for c in PEOPLE_COLUMNS if c not in PEOPLE_FLAG_COLUMNS):
            continue
        name = "" if is_blank(row.get("Name")) else str(row["Name"]).strip()
        if not name:
            errors.append(t("Zeile {row}: Name fehlt", row=i))
            continue
        pid = None if is_blank(row.get("_id")) else str(row["_id"])
        if pid is None:
            pid = name_to_id.get(name.lower())
        if pid is None:
            pid = new_person_id(name, used)
            used.add(pid)
            name_to_id[name.lower()] = pid
        access = not is_blank(row.get("Produktionszugriff")) and bool(row["Produktionszugriff"])
        raw_country = row.get("Land")
        country = None if is_blank(raw_country) or raw_country == TEAM_REGION else str(raw_country)
        raw_workweek = row.get("Arbeitswoche")
        workweek = None if is_blank(raw_workweek) else str(raw_workweek).strip().lower()
        if workweek is not None:
            try:
                weekend_from_workweek(workweek)
            except ValueError:
                errors.append(
                    t(
                        "Zeile {row} ({name}): Arbeitswoche '{value}' ist unbekannt",
                        row=i,
                        name=name,
                        value=workweek,
                    )
                )
                continue
        raw_region = row.get("Bundesland")
        region = None if is_blank(raw_region) or raw_region == TEAM_REGION else str(raw_region)
        person = visible_people.get(pid)
        if person is None:
            person = visible_people[pid] = Person(
                id=pid, name=name, region=region, country=country, workweek=workweek
            )
        elif (
            person.name != name
            or person.region != region
            or person.country != country
            or person.workweek != workweek
        ):
            errors.append(
                t(
                    "Zeile {row}: Für {name} stehen in mehreren Zeilen unterschiedliche Namen "
                    "oder Bundesländer – bitte einheitlich eintragen.",
                    row=i,
                    name=person.name,
                )
            )
            continue
        person.production_access = person.production_access or access
        try:
            start, end = as_date(row.get("ab")), as_date(row.get("bis"))
        except ValueError:
            errors.append(t("Zeile {row} ({name}): ungültiges Datum", row=i, name=name))
            continue
        if start is None:
            errors.append(t("Zeile {row} ({name}): 'ab' fehlt", row=i, name=name))
            continue
        try:
            fte = 1.0 if is_blank(row.get("FTE")) else float(row["FTE"])
        except TypeError, ValueError:
            fte = -1.0
        if not 0 <= fte <= 1:
            errors.append(
                t(
                    "Zeile {row} ({name}): FTE muss zwischen 0 und 1 liegen "
                    "(0 = keine Kapazität, z. B. bei längerer Abwesenheit)",
                    row=i,
                    name=name,
                )
            )
            continue
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


# --- Produkte ------------------------------------------------------------------------

PRODUCT_COLUMNS = ["_id", "Name", "PO", "Anteil", "ab", "bis"]


def product_table(
    products: list[Product], today: date, show_former: bool
) -> tuple[list[dict[str, Any]], list[Product]]:
    """Eine Zeile je Produkt. Liefert (Zeilen, ausgeblendete ehemalige Produkte)."""
    visible = [p for p in products if show_former or p.end is None or p.end >= today]
    hidden = [p for p in products if p not in visible]
    rows = [
        {
            "_id": p.id,
            "Name": p.name,
            "PO": p.po or "",
            "Anteil": None if p.share is None else round(p.share * 100, 6),
            "ab": p.start,
            "bis": p.end,
        }
        for p in visible
    ]
    return rows, hidden


@dataclass
class ProductsResult:
    products: list[Product]
    errors: list[str]
    deleted: list[str]


def products_from_table(
    rows: list[dict[str, Any]], original: list[Product], hidden: list[Product]
) -> ProductsResult:
    """Baut die Produktliste aus der Tabelle; neue Zeilen bekommen eine ID aus dem Namen."""
    errors: list[str] = []
    used = {p.id for p in original}
    seen: set[str] = set()
    result: list[Product] = []
    for i, row in enumerate(rows, start=1):
        if all(is_blank(row.get(c)) for c in PRODUCT_COLUMNS if c != "_id"):
            continue
        name = "" if is_blank(row.get("Name")) else str(row["Name"]).strip()
        if not name:
            errors.append(t("Zeile {row}: Name fehlt", row=i))
            continue
        if name.lower() in seen:
            errors.append(t("Zeile {row}: {name} ist doppelt", row=i, name=name))
            continue
        seen.add(name.lower())
        pid = None if is_blank(row.get("_id")) else str(row["_id"])
        if pid is None:
            pid = new_person_id(name, used, fallback="produkt")
            used.add(pid)
        try:
            start, end = as_date(row.get("ab")), as_date(row.get("bis"))
        except ValueError:
            errors.append(t("Zeile {row} ({name}): ungültiges Datum", row=i, name=name))
            continue
        if start and end and end < start:
            errors.append(t("Zeile {row} ({name}): 'bis' liegt vor 'ab'", row=i, name=name))
            continue
        po = None if is_blank(row.get("PO")) else str(row["PO"]).strip()
        share = None if is_blank(row.get("Anteil")) else float(row["Anteil"]) / 100
        if share is not None and not 0 < share <= 1:
            errors.append(
                t("Zeile {row} ({name}): Anteil muss zwischen 0 und 100 % liegen", row=i, name=name)
            )
            continue
        result.append(Product(id=pid, name=name, po=po, start=start, end=end, share=share))
    kept = {p.id for p in result} | {p.id for p in hidden}
    deleted = [p.name for p in original if p.id not in kept]
    order = {p.id: n for n, p in enumerate(original)}
    products = [*result, *copy.deepcopy(hidden)]
    products.sort(key=lambda p: order.get(p.id, len(order)))
    return ProductsResult(products=products, errors=errors, deleted=deleted)


def product_values_table(d: Distribution) -> list[dict[str, Any]]:
    """Eine Zeile je Produkt mit Standard und den erfassten Werten (Spaltennamen wie MEASURES)."""
    return [
        {
            "_id": r.product.id,
            "Produkt": r.product.name + ("" if r.active else " (nicht betreut)"),
            "PO": r.product.po or "",
            **{label: r.value(m) for m, label in (MEASURES | PRODUCTION_MEASURES).items()},
        }
        for r in d.rows
    ]


def apply_product_values(sprint: Sprint, rows: list[dict[str, Any]], measures: list[str]) -> Sprint:
    """Kopie von ``sprint`` mit den bearbeiteten Spalten ``measures`` (z. B. ["planned"])."""
    result = copy.deepcopy(sprint)
    for row in rows:
        pid = str(row["_id"])
        values = result.products.get(pid, ProductValues())
        for m in measures:
            label = (MEASURES | PRODUCTION_MEASURES)[m]
            if label not in row:
                continue  # Spalte war nicht zu sehen: gespeicherten Wert nicht überschreiben
            raw = row[label]
            setattr(values, m, None if is_blank(raw) else float(raw))
        if values.is_empty():
            result.products.pop(pid, None)
        else:
            result.products[pid] = values
    return result


def parse_numbers(raw: str) -> list[float]:
    """„4,25 4.5“ → [4.25, 4.5]; wirft ValueError bei ungültigen oder nicht endlichen Einträgen."""
    numbers = [float(x.replace(",", ".")) for x in raw.replace(";", " ").split()]
    if not all(math.isfinite(n) for n in numbers):
        raise ValueError(t("Bitte eine endliche Zahl eingeben."))
    return numbers


@dataclass(frozen=True)
class CapacityUsage:
    """Verplante Menge gegenüber dem Forecast PLAN: Rest (negativ = zu viel) und Auslastung."""

    planned: float
    plan: float

    @property
    def rest(self) -> float:
        return self.plan - self.planned

    @property
    def ratio(self) -> float:
        """Anteil des Forecast PLAN, der verplant ist (über 1 = überplant; 0 ohne PLAN)."""
        return self.planned / self.plan if self.plan > 0 else 0.0

    @property
    def over(self) -> bool:
        return self.rest < 0


def capacity_usage(plan: float | None, planned: float | None) -> CapacityUsage | None:
    """None, solange PLAN oder verplante Menge fehlt (dann gibt es nichts zu vergleichen)."""
    if plan is None or planned is None:
        return None
    return CapacityUsage(planned=planned, plan=plan)


def preplanned_complete(sprint: Sprint, products: list[Product]) -> bool:
    """Die PO-Vorplanung gilt als erledigt, wenn jedes im Sprint aktive Produkt einen Wert hat.
    Ohne bekannte aktive Produkte (``products`` leer oder keins aktiv) genügt irgendein Wert."""
    active = [p.id for p in products if p.active_between(sprint.start, sprint.end)]
    if not active:
        return any(v.preplanned is not None for v in sprint.products.values())
    return all(
        (values := sprint.products.get(pid)) is not None and values.preplanned is not None
        for pid in active
    )


def board_steps_done(
    recorded: Sprint | None, products: list[Product] | None = None
) -> dict[str, bool]:
    """Erledigt-Haken der Schrittleiste (Fehltage, PO-Vorplanung, Planning, Review) für einen
    Sprint – aus den gespeicherten Daten, ``recorded`` ist der Sprint ohne Sprintdatei ``None``.

    Fehltage zählen nur als erledigt, wenn sie bestätigt sind (Stand ``absence_status``:
    eingetragen oder ausdrücklich „niemand fehlt“); unbekannte und nur angekündigte Fehltage
    (aus der PO-Vorplanung) bekommen keinen Haken. Die PO-Vorplanung zählt, wenn alle im Sprint
    aktiven ``products`` einen Wert haben."""
    if recorded is None:
        return {"fehltage": False, "vorplanung": False, "planning": False, "review": False}
    return {
        "fehltage": absence_status(recorded) is AbsenceState.CONFIRMED,
        "vorplanung": preplanned_complete(recorded, products or []),
        "planning": recorded.forecast_ist is not None,
        "review": recorded.velocity is not None,
    }


@dataclass
class StartTask:
    """Eine der drei Aufgaben der Startseite: wohin der Klick führt und warum."""

    key: str  # prepare | planning | review
    page: str  # Seitenschlüssel (siehe web.ui.PAGES)
    sprint_id: str | None
    hint: str
    done: bool = False


def start_tasks(fc: Forecast, products: bool = True) -> list[StartTask]:
    """Die nächste sinnvolle Seite je Aufgabe, abgeleitet vom Stand des Sprints.

    Ohne offenen Sprint (kein Planning-Kandidat) führen „Sprint vorbereiten“ und „Planning“ zum
    Sprintkalender, damit dort Sprints angelegt werden."""
    nxt = fc.default_entry("planning")
    review = fc.default_entry("review")
    tasks: list[StartTask] = []
    if nxt is None:
        hint = t("Kein offener Sprint – zuerst im Sprintkalender Sprints anlegen.")
        tasks.append(StartTask("prepare", "sprints", None, hint))
        tasks.append(StartTask("planning", "sprints", None, hint))
    else:
        sprint = fc.data.sprint(nxt.sprint.id) or nxt.sprint
        sid = sprint.id
        # Wie der Haken „Fehltage“ der Schrittleiste (``board_steps_done``): Als bekannt gelten
        # nur bestätigte Fehltage; angekündigte (aus der PO-Vorplanung) bestätigen nichts.
        absences = absence_status(sprint)
        if absences is not AbsenceState.CONFIRMED:
            hint = (
                t("Sprint {id}: Fehltage unbekannt.", id=sid)
                if absences is AbsenceState.UNKNOWN
                else t("Sprint {id}: Fehltage angekündigt, noch nicht bestätigt.", id=sid)
            )
            tasks.append(StartTask("prepare", "fehltage", sid, hint))
        elif products and not preplanned_complete(sprint, fc.data.products):
            tasks.append(
                StartTask(
                    "prepare",
                    "vorplanung",
                    sid,
                    t("Sprint {id}: Fehltage bekannt, PO-Vorplanung fehlt noch.", id=sid),
                )
            )
        else:
            tasks.append(
                StartTask("prepare", "fehltage", sid, t("Sprint {id}: vorbereitet.", id=sid), True)
            )
        committed = sprint.forecast_ist is not None
        tasks.append(
            StartTask(
                "planning",
                "planning",
                sid,
                t("Sprint {id}: Commitment eingetragen.", id=sid)
                if committed
                else t("Sprint {id}: Commitment fehlt noch.", id=sid),
                committed,
            )
        )
    if review is None:
        tasks.append(StartTask("review", "review", None, t("Kein Sprint zum Abschließen.")))
    else:
        sprint = fc.data.sprint(review.sprint.id) or review.sprint
        closed = sprint.velocity is not None
        tasks.append(
            StartTask(
                "review",
                "review",
                sprint.id,
                t("Sprint {id}: abgeschlossen.", id=sprint.id)
                if closed
                else t("Sprint {id} läuft noch – Review am Sprintende.", id=sprint.id)
                if sprint.end > fc.today
                else t("Sprint {id}: Velocity fehlt noch.", id=sprint.id),
                closed,
            )
        )
    return tasks


# --- „Ohne Git verwenden“: dauerhaft je Ordner in den Benutzereinstellungen ------------------

WITHOUT_GIT_KEY = "without_git_dirs"


def resolved_path(path: Path) -> Path:
    """Aufgelöster Pfad; ein nicht auflösbarer (toter Netzlaufwerkpfad) bleibt, wie er ist."""
    try:
        return path.resolve()
    except OSError, RuntimeError:
        return path


def without_git_dirs() -> list[str]:
    """Ordner, die ausdrücklich ohne Git verwendet werden (aufgelöste Pfade)."""
    raw = config.load().get(WITHOUT_GIT_KEY)
    return [p for p in raw if isinstance(p, str) and p.strip()] if isinstance(raw, list) else []


def is_without_git(path: Path) -> bool:
    return str(resolved_path(path)) in without_git_dirs()


def remember_without_git(path: Path) -> None:
    """Merkt die Entscheidung dauerhaft (ohne Doppelte). Wirft ``config.SettingsError``, wenn
    die Einstellungen nicht gespeichert werden können."""
    here = str(resolved_path(path))
    known = without_git_dirs()
    if here not in known:
        config.update(**{WITHOUT_GIT_KEY: [*known, here]})


def forget_without_git(path: Path) -> None:
    """Nimmt die Entscheidung zurück (z. B. wenn der Wechsel in den Ordner scheiterte)."""
    here = str(resolved_path(path))
    known = without_git_dirs()
    if here in known:
        config.update(**{WITHOUT_GIT_KEY: [p for p in known if p != here]})
