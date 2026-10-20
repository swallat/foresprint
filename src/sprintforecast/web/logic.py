# SPDX-License-Identifier: EUPL-1.2
"""Conversion between web tables and the data model, without Streamlit so it is testable."""

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
    """None, empty text or NaN/NaT from pandas."""
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
    """Copy of ``data`` in which the given sprints are replaced or added."""
    result = copy.deepcopy(data)
    by_id = {s.id: s for s in result.sprints}
    for s in sprints:
        by_id[s.id] = copy.deepcopy(s)
    result.sprints = sorted(by_id.values(), key=lambda s: s.start)
    return result


def open_velocity_sprints(fc: Forecast, count: int = 2) -> list[Sprint]:
    """Running or finished sprints without a recorded velocity (the last ``count``);
    an expected velocity can be assumed for them."""
    open_ = [
        e.sprint for e in fc.entries if e.sprint.start <= fc.today and e.sprint.velocity is None
    ]
    return open_[-count:]


@dataclass(frozen=True)
class Assumption:
    """The team's forecast for an open sprint."""

    commitment: float
    not_done: float | None = None
    additional_done: float | None = None

    @property
    def expected(self) -> float:
        """Expected completed amount (velocity)."""
        return max(self.commitment - (self.not_done or 0.0) + (self.additional_done or 0.0), 0.0)


def record_prognoses(
    data: TeamData,
    target: Sprint,
    assumed: dict[str, Assumption],
    plan: float | None,
    comment: str,
    now: datetime | None = None,
) -> list[Sprint]:
    """Attach the assumptions as a forecast to the affected sprints (copies) and return all
    sprints to save, including ``target`` (the target sprint of the pre-planning)."""
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
                commitment=a.commitment,
                not_done=a.not_done,
                additional_done=a.additional_done,
                expected_done=a.expected,
                target=target.id,
                plan=plan,
                preplanned=preplanned,
            )
        )
    return list(result.values())


def default_sprint_commitment(fc: Forecast, sprint: Sprint) -> float | None:
    """Default for the commitment in the what-if: the sprint's recorded value, otherwise that
    of the nearest earlier sprint that has one recorded."""
    if sprint.commitment is not None:
        return sprint.commitment
    earlier = [e.sprint for e in fc.entries if e.sprint.start < sprint.start]
    return next((s.commitment for s in reversed(earlier) if s.commitment is not None), None)


def whatif_forecast(fc: Forecast, velocities: dict[str, float] | dict[str, Assumption]) -> Forecast:
    """Forecast assuming the given sprints reach the velocity.
    Nothing is saved; ``fc`` stays unchanged."""
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


# --- Absences matrix ------------------------------------------------------------------


def absence_sprints(data: TeamData, fc: Forecast, count: int, past: int = 0) -> list[Sprint]:
    """Running sprint and the following ones (recorded or generated from the calendar), preceded
    optionally by the last ``past`` finished sprints (for adding absences retroactively)."""
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
    """One row per person, one column per sprint (absences); inactive cells are None."""
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
    """Apply the edited matrix to copies of all sprints (same order).

    Entered absences confirm the sprint. Without entries nothing is confirmed silently:
    ``confirmed`` names the sprints for which "Nobody is absent" is explicitly confirmed. If
    ``confirmed`` is given, a sprint without entries that is missing there loses its
    confirmation (back to unknown); without it the state stays unchanged."""
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
            sprint.absence_state = AbsenceState.UNKNOWN  # confirmation revoked
        result.append(sprint)
    return result


def _only_absences(sprint: Sprint) -> bool:
    """Sprint holds nothing besides (empty) absences, a pure confirmation of the absences."""
    return (
        sprint.capacity is None
        and sprint.commitment is None
        and sprint.velocity is None
        and sprint.scope_creep is None
        and sprint.planning is None
        and sprint.forecast_plan is None
        and not sprint.products
        and not sprint.note
    )


def resettable_sprints(data: TeamData, today: date) -> list[Sprint]:
    """Future sprint files that contain only absences and sit at the end of the recorded
    sprints: deleting restores "no information" (absences estimated from the history again)."""
    result: list[Sprint] = []
    for sprint in reversed(sorted(data.sprints, key=lambda s: s.start)):
        if sprint.start > today and _only_absences(sprint):
            result.append(sprint)
        else:
            break
    return sorted(result, key=lambda s: s.start)


def sprints_to_save(data: TeamData, originals: list[Sprint], edited: list[Sprint]) -> list[Sprint]:
    """Sprints whose absences or state (unknown / expected / confirmed) have changed.
    Sprints without a file are only created if something was entered or confirmed for them."""
    return [
        new
        for old, new in zip(originals, edited, strict=True)
        if new.absences != old.absences or absence_status(new) is not absence_status(old)
    ]


# --- Sprint calendar -------------------------------------------------------------------

CALENDAR_COLUMNS = ["Sprint", "Start", "Last day", "Working days", "Status"]


def calendar_table(data: TeamData, sprints: list[Sprint], today: date) -> list[dict[str, Any]]:
    """One row per sprint; "Last day" = end − 1 (the end is the start of the next one)."""
    rows = []
    for s in sprints:
        if s.end <= today:
            state = "finished"
        elif s.start <= today:
            state = "running"
        else:
            state = "planned" if data.sprint(s.id) else "no file yet"
        rows.append(
            {
                "Sprint": s.id,
                "Start": s.start,
                "Last day": s.end - timedelta(days=1),
                "Working days": len(team_workdays(data.team, s.start, s.end)),
                "Status": state,
            }
        )
    return rows


def apply_calendar(
    data: TeamData, sprints: list[Sprint], rows: list[dict[str, Any]]
) -> tuple[list[Sprint], list[str]]:
    """Apply changed last days; each following sprint starts the day after and keeps its
    length unless its own last day was changed. IDs of sprints not yet created are reassigned.
    Returns (sprints, errors)."""
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
            last = as_date(row.get("Last day"))
        except ValueError:
            last = None
        if last is None:
            errors.append(t("Row {row}: last day missing", row=i + 1))
            last = original.end - timedelta(days=1)
        if last == original.end - timedelta(days=1):
            # unchanged → keep the length, i.e. shift along with the predecessor
            end = sprint.start + (original.end - original.start)
        else:
            end = last + timedelta(days=1)
        if end <= sprint.start:
            errors.append(
                t(
                    "Sprint {id}: last day is before the start {start}",
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
                    (
                        "Sprint ID {id} would be duplicated – please adjust the following "
                        "sprints first."
                    ),
                    id=sprint.id,
                )
            )
        result.append(sprint)
    # Shift saved sprints after the displayed period by the same difference.
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
    """Sprints to save: changed dates, missing files on request, and shifted saved sprints
    after the displayed period."""
    window, shifted = after[: len(originals)], after[len(originals) :]
    changed = [
        new
        for old, new in zip(originals, window, strict=True)
        if (old.start, old.end) != (new.start, new.end)
        or (create_missing and data.sprint(new.id) is None)
    ]
    return changed + shifted


# --- People -------------------------------------------------------------------------

# Selection value for "state as set in the team".
TEAM_REGION = "(Team)"
PEOPLE_COLUMNS = [
    "_id",
    "Name",
    "Country",
    "State",
    "Work week",
    "from",
    "until",
    "FTE",
    "Production access",
]
# Columns that alone do not make a row "filled" (a checkbox column always has a value).
PEOPLE_FLAG_COLUMNS = ("_id", "Production access")


def people_table(
    people: list[Person], today: date, show_former: bool
) -> tuple[list[dict[str, Any]], list[Person]]:
    """One row per membership. Returns (rows, hidden people)."""
    visible = [p for p in people if show_former or p.is_current(today)]
    hidden = [p for p in people if p not in visible]
    rows = [
        {
            "_id": p.id,
            "Name": p.name,
            "Country": p.country or TEAM_REGION,
            "State": p.region or TEAM_REGION,
            "Work week": p.workweek or "",
            "from": m.start,
            "until": m.end,
            "FTE": m.fte,
            "Production access": p.production_access,
        }
        for p in sorted(visible, key=lambda p: p.name.lower())
        for m in p.memberships
    ]
    return rows, hidden


@dataclass
class PeopleResult:
    people: list[Person]
    errors: list[str]
    # Names of the people or periods that are missing compared to the original state.
    deleted: list[str]


def people_from_table(
    rows: list[dict[str, Any]], original: list[Person], hidden: list[Person]
) -> PeopleResult:
    """Build the people list from the table. New rows without an ID belong to the person with
    the same name (e.g. FTE change) or get a new ID."""
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
            errors.append(t("Row {row}: name missing", row=i))
            continue
        pid = None if is_blank(row.get("_id")) else str(row["_id"])
        if pid is None:
            pid = name_to_id.get(name.lower())
        if pid is None:
            pid = new_person_id(name, used)
            used.add(pid)
            name_to_id[name.lower()] = pid
        access = not is_blank(row.get("Production access")) and bool(row["Production access"])
        raw_country = row.get("Country")
        country = None if is_blank(raw_country) or raw_country == TEAM_REGION else str(raw_country)
        raw_workweek = row.get("Work week")
        workweek = None if is_blank(raw_workweek) else str(raw_workweek).strip().lower()
        if workweek is not None:
            try:
                weekend_from_workweek(workweek)
            except ValueError:
                errors.append(
                    t(
                        "Row {row} ({name}): work week '{value}' is unknown",
                        row=i,
                        name=name,
                        value=workweek,
                    )
                )
                continue
        raw_region = row.get("State")
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
                    (
                        "Row {row}: {name} has different names or states in several rows – "
                        "please enter them consistently."
                    ),
                    row=i,
                    name=person.name,
                )
            )
            continue
        person.production_access = person.production_access or access
        try:
            start, end = as_date(row.get("from")), as_date(row.get("until"))
        except ValueError:
            errors.append(t("Row {row} ({name}): invalid date", row=i, name=name))
            continue
        if start is None:
            errors.append(t("Row {row} ({name}): 'from' missing", row=i, name=name))
            continue
        try:
            fte = 1.0 if is_blank(row.get("FTE")) else float(row["FTE"])
        except TypeError, ValueError:
            fte = -1.0
        if not 0 <= fte <= 1:
            errors.append(
                t(
                    (
                        "Row {row} ({name}): FTE must be between 0 and 1 (0 = no capacity, "
                        "e.g. during a long absence)"
                    ),
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


# --- Products ------------------------------------------------------------------------

PRODUCT_COLUMNS = ["_id", "Name", "PO", "Anteil", "from", "until"]


def product_table(
    products: list[Product], today: date, show_former: bool
) -> tuple[list[dict[str, Any]], list[Product]]:
    """One row per product. Returns (rows, hidden former products)."""
    visible = [p for p in products if show_former or p.end is None or p.end >= today]
    hidden = [p for p in products if p not in visible]
    rows = [
        {
            "_id": p.id,
            "Name": p.name,
            "PO": p.po or "",
            "Anteil": None if p.share is None else round(p.share * 100, 6),
            "from": p.start,
            "until": p.end,
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
    """Build the product list from the table; new rows get an ID derived from the name."""
    errors: list[str] = []
    used = {p.id for p in original}
    seen: set[str] = set()
    result: list[Product] = []
    for i, row in enumerate(rows, start=1):
        if all(is_blank(row.get(c)) for c in PRODUCT_COLUMNS if c != "_id"):
            continue
        name = "" if is_blank(row.get("Name")) else str(row["Name"]).strip()
        if not name:
            errors.append(t("Row {row}: name missing", row=i))
            continue
        if name.lower() in seen:
            errors.append(t("Row {row}: {name} is a duplicate", row=i, name=name))
            continue
        seen.add(name.lower())
        pid = None if is_blank(row.get("_id")) else str(row["_id"])
        if pid is None:
            pid = new_person_id(name, used, fallback="produkt")
            used.add(pid)
        try:
            start, end = as_date(row.get("from")), as_date(row.get("until"))
        except ValueError:
            errors.append(t("Row {row} ({name}): invalid date", row=i, name=name))
            continue
        if start and end and end < start:
            errors.append(t("Row {row} ({name}): 'until' is before 'from'", row=i, name=name))
            continue
        po = None if is_blank(row.get("PO")) else str(row["PO"]).strip()
        share = None if is_blank(row.get("Anteil")) else float(row["Anteil"]) / 100
        if share is not None and not 0 < share <= 1:
            errors.append(
                t("Row {row} ({name}): share must be between 0 and 100 %", row=i, name=name)
            )
            continue
        old = next((p for p in original if p.id == pid), None)
        result.append(
            Product(
                id=pid,
                name=name,
                po=po,
                start=start,
                end=end,
                share=share,
                match=old.match if old else None,  # not a column of the table
            )
        )
    kept = {p.id for p in result} | {p.id for p in hidden}
    deleted = [p.name for p in original if p.id not in kept]
    order = {p.id: n for n, p in enumerate(original)}
    products = [*result, *copy.deepcopy(hidden)]
    products.sort(key=lambda p: order.get(p.id, len(order)))
    return ProductsResult(products=products, errors=errors, deleted=deleted)


def product_values_table(d: Distribution) -> list[dict[str, Any]]:
    """One row per product with the default and recorded values (column names as in MEASURES)."""
    return [
        {
            "_id": r.product.id,
            "Product": r.product.name + ("" if r.active else t(" (not looked after)")),
            "PO": r.product.po or "",
            **{label: r.value(m) for m, label in (MEASURES | PRODUCTION_MEASURES).items()},
        }
        for r in d.rows
    ]


def apply_product_values(sprint: Sprint, rows: list[dict[str, Any]], measures: list[str]) -> Sprint:
    """Copy of ``sprint`` with the edited columns ``measures`` (e.g. ["planned"])."""
    result = copy.deepcopy(sprint)
    for row in rows:
        pid = str(row["_id"])
        values = result.products.get(pid, ProductValues())
        for m in measures:
            label = (MEASURES | PRODUCTION_MEASURES)[m]
            if label not in row:
                continue  # column was not visible: do not overwrite the saved value
            raw = row[label]
            setattr(values, m, None if is_blank(raw) else float(raw))
        if values.is_empty():
            result.products.pop(pid, None)
        else:
            result.products[pid] = values
    return result


def parse_numbers(raw: str) -> list[float]:
    """Parse "4,25 4.5" → [4.25, 4.5]; raises ValueError for invalid or non-finite entries."""
    numbers = [float(x.replace(",", ".")) for x in raw.replace(";", " ").split()]
    if not all(math.isfinite(n) for n in numbers):
        raise ValueError(t("Please enter a finite number."))
    return numbers


@dataclass(frozen=True)
class CapacityUsage:
    """Planned amount versus the Forecast PLAN: remainder (negative = too much) and utilization."""

    planned: float
    plan: float

    @property
    def rest(self) -> float:
        return self.plan - self.planned

    @property
    def ratio(self) -> float:
        """Share of the Forecast PLAN that is planned (above 1 = overplanned; 0 without PLAN)."""
        return self.planned / self.plan if self.plan > 0 else 0.0

    @property
    def over(self) -> bool:
        return self.rest < 0


def capacity_usage(plan: float | None, planned: float | None) -> CapacityUsage | None:
    """None while PLAN or the planned amount is missing (nothing to compare then)."""
    if plan is None or planned is None:
        return None
    return CapacityUsage(planned=planned, plan=plan)


def preplanned_complete(sprint: Sprint, products: list[Product]) -> bool:
    """PO pre-planning counts as done when every product active in the sprint has a value.
    Without known active products (``products`` empty or none active) any value suffices."""
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
    """Done checkmarks of the step bar (absences, PO pre-planning, Planning, Review) for a
    sprint, from the saved data; ``recorded`` is ``None`` for a sprint without a sprint file.

    Absences only count as done if they are confirmed (``absence_status`` state: entered or
    explicitly "Nobody is absent"); unknown and merely expected absences (from the PO
    pre-planning) get no checkmark. PO pre-planning counts when all ``products`` active in the
    sprint have a value."""
    if recorded is None:
        return {"absences": False, "preplanning": False, "planning": False, "review": False}
    return {
        "absences": absence_status(recorded) is AbsenceState.CONFIRMED,
        "preplanning": preplanned_complete(recorded, products or []),
        "planning": recorded.commitment is not None,
        "review": recorded.velocity is not None,
    }


@dataclass
class StartTask:
    """One of the three tasks on the start page: where the click leads and why."""

    key: str  # prepare | planning | review
    page: str  # page key (see web.ui.PAGES)
    sprint_id: str | None
    hint: str
    done: bool = False


def start_tasks(fc: Forecast, products: bool = True) -> list[StartTask]:
    """The next sensible page per task, derived from the sprint's state.

    Without an open sprint (no Planning candidate), "Prepare the sprint" and "Planning" lead to
    the sprint calendar so that sprints get created there."""
    nxt = fc.default_entry("planning")
    review = fc.default_entry("review")
    tasks: list[StartTask] = []
    if nxt is None:
        hint = t("No open sprint – first create sprints in the sprint calendar.")
        tasks.append(StartTask("prepare", "sprints", None, hint))
        tasks.append(StartTask("planning", "sprints", None, hint))
    else:
        sprint = fc.data.sprint(nxt.sprint.id) or nxt.sprint
        sid = sprint.id
        # Like the "Absences" checkmark of the step bar (``board_steps_done``): only confirmed
        # absences count as known; expected ones (from the PO pre-planning) confirm nothing.
        absences = absence_status(sprint)
        if absences is not AbsenceState.CONFIRMED:
            hint = (
                t("Sprint {id}: absences unknown.", id=sid)
                if absences is AbsenceState.UNKNOWN
                else t("Sprint {id}: absences announced, not yet confirmed.", id=sid)
            )
            tasks.append(StartTask("prepare", "absences", sid, hint))
        elif products and not preplanned_complete(sprint, fc.data.products):
            tasks.append(
                StartTask(
                    "prepare",
                    "preplanning",
                    sid,
                    t("Sprint {id}: absences known, PO pre-planning still missing.", id=sid),
                )
            )
        else:
            tasks.append(
                StartTask("prepare", "absences", sid, t("Sprint {id}: prepared.", id=sid), True)
            )
        committed = sprint.commitment is not None
        tasks.append(
            StartTask(
                "planning",
                "planning",
                sid,
                t("Sprint {id}: commitment entered.", id=sid)
                if committed
                else t("Sprint {id}: commitment still missing.", id=sid),
                committed,
            )
        )
    if review is None:
        tasks.append(StartTask("review", "review", None, t("No sprint to close.")))
    else:
        sprint = fc.data.sprint(review.sprint.id) or review.sprint
        closed = sprint.velocity is not None
        tasks.append(
            StartTask(
                "review",
                "review",
                sprint.id,
                t("Sprint {id}: closed.", id=sprint.id)
                if closed
                else t(
                    "Sprint {id} is still running – review at the end of the sprint.", id=sprint.id
                )
                if sprint.end > fc.today
                else t("Sprint {id}: velocity still missing.", id=sprint.id),
                closed,
            )
        )
    return tasks


# --- "Use without Git": permanently per folder in the user settings ------------------

WITHOUT_GIT_KEY = "without_git_dirs"


def resolved_path(path: Path) -> Path:
    """Resolved path; one that cannot be resolved (dead network drive path) stays as it is."""
    try:
        return path.resolve()
    except OSError, RuntimeError:
        return path


def without_git_dirs() -> list[str]:
    """Folders that are explicitly used without Git (resolved paths)."""
    raw = config.load().get(WITHOUT_GIT_KEY)
    return [p for p in raw if isinstance(p, str) and p.strip()] if isinstance(raw, list) else []


def is_without_git(path: Path) -> bool:
    return str(resolved_path(path)) in without_git_dirs()


def remember_without_git(path: Path) -> None:
    """Remember the decision permanently (without duplicates). Raises ``config.SettingsError`` if
    the settings cannot be saved."""
    here = str(resolved_path(path))
    known = without_git_dirs()
    if here not in known:
        config.update(**{WITHOUT_GIT_KEY: [*known, here]})


def forget_without_git(path: Path) -> None:
    """Revoke the decision (e.g. if switching to the folder failed)."""
    here = str(resolved_path(path))
    known = without_git_dirs()
    if here in known:
        config.update(**{WITHOUT_GIT_KEY: [p for p in known if p != here]})
