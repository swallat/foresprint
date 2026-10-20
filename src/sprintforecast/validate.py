# SPDX-License-Identifier: EUPL-1.2
"""Checks the data for errors and plausibility."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import SafeConstructor

from sprintforecast.calendar import (
    countries,
    expected_id_form,
    following_sprint,
    id_fits_numbering,
    subdivisions,
    team_workdays,
    weekend_from_workweek,
)
from sprintforecast.git import blank_controls
from sprintforecast.i18n import t
from sprintforecast.model import (
    RULE_SOURCES,
    TRACKER_KINDS,
    Rule,
    Sprint,
    Ticket,
    TrackerSettings,
    base_url_problem,
)
from sprintforecast.storage import (
    TEAM_FILES,
    TICKET_FILES,
    DataError,
    Repository,
    TeamData,
    compose_yaml,
    tracker_from_raw,
)


class Level(StrEnum):
    ERROR = "Error"
    WARNING = "Notice"

    @property
    def label(self) -> str:
        """Display name in the selected language."""
        return t(self.value)


@dataclass
class Issue:
    level: Level
    where: str
    message: str


def _g(value: float) -> str:
    return f"{value:g}"


def _check_product_shares(data: TeamData, today: date, error, warning) -> None:
    """Fixed shares of the products looked after at the same time must not add up to more than
    100 % (per sprint and today); at exactly 100 % nothing is left for products without a share."""
    periods = [(t("Sprint {id}", id=s.id), s.start, s.end) for s in data.sprints]
    periods.append((t("today"), today, today + timedelta(days=1)))
    reported: set[tuple[float, bool]] = set()
    for label, start, end in periods:
        active = [p for p in data.products if p.active_between(start, end)]
        total = sum(p.share for p in active if p.share is not None)
        rest = any(p.share is None for p in active)
        key = (round(total, 6), rest)
        if key in reported:
            continue
        if total > 1 + 1e-9:
            reported.add(key)
            error(
                "products.yaml",
                t(
                    "Fixed shares add up to {total} % ({period}) – more than 100 %",
                    total=f"{total * 100:g}",
                    period=label,
                ),
            )
        elif total > 1 - 1e-9 and rest:
            reported.add(key)
            warning(
                "products.yaml",
                t(
                    (
                        "Fixed shares add up to 100 % ({period}) – nothing is left for "
                        "products without a fixed share"
                    ),
                    period=label,
                ),
            )


# --- Ticket pre-planning ---------------------------------------------------------------


def rule_problems(rule: Rule) -> list[str]:
    """Why an assignment rule is invalid (spec section 6.4): unknown sources, leaves without
    values, operators without conditions, short and long form mixed. Empty = valid."""
    problems: list[str] = []

    def walk(node: Rule) -> None:
        if node.op == "leaf":
            if node.source not in RULE_SOURCES:
                problems.append(
                    t(
                        "unknown source '{source}' (allowed: {allowed})",
                        source=node.source,
                        allowed=", ".join(RULE_SOURCES),
                    )
                )
            if not node.values:
                problems.append(t("'{source}' without values (empty list)", source=node.source))
            return
        if node.short and any(child.op != "leaf" for child in node.children):
            problems.append(
                t(
                    "Short and long form mixed: any, all and none each stand alone, not "
                    "next to sources or next to each other"
                )
            )
        if not node.children:
            problems.append(
                t("no condition") if node.short else t("'{op}' without conditions", op=node.op)
            )
        for child in node.children:
            walk(child)

    walk(rule)
    return problems


def find_cycles(tickets: list[Ticket]) -> list[list[str]]:
    """Cycles in ``depends_on`` (keys in dependency order), each reported once. Dependencies on
    keys outside the list are ignored."""
    graph = {tk.key: [] for tk in tickets}
    for tk in tickets:
        graph[tk.key] = [d for d in tk.depends_on if d in graph]
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for start in graph:
        if state.get(start):
            continue
        state[start] = 1
        path = [start]
        stack = [iter(graph[start])]
        while stack:
            for nxt in stack[-1]:
                if state.get(nxt, 0) == 1:  # back edge: the path from nxt onwards is a cycle
                    cycle = path[path.index(nxt) :]
                    first = cycle.index(min(cycle))
                    canon = cycle[first:] + cycle[:first]
                    if tuple(canon) not in seen:
                        seen.add(tuple(canon))
                        cycles.append(canon)
                elif not state.get(nxt):
                    state[nxt] = 1
                    path.append(nxt)
                    stack.append(iter(graph[nxt]))
                    break
            else:
                state[path.pop()] = 2
                stack.pop()
    return cycles


def _known_sprints(data: TeamData, ahead: int = 52) -> dict[str, Sprint]:
    """The sprint files plus the following sprints from the calendar (earmarks name
    sprints that have no file yet), by id."""
    ids = {s.id: s for s in data.sprints}
    last = data.sprints[-1] if data.sprints else None
    try:
        for _ in range(ahead):
            last = following_sprint(data.team, last)
            ids[last.id] = last
    except DataError:
        pass  # no first sprint: reported above
    return ids


def _check_tracker_source(tr: TrackerSettings, error, warn) -> None:
    """Kind-specific rules of the ``tracker`` section (``kind: jira`` needs address and JQL)."""
    if tr.kind not in TRACKER_KINDS:
        error(
            "team.yaml",
            t("tracker.kind: only {allowed}", allowed=", ".join(TRACKER_KINDS)),
        )
        return
    if tr.kind != "jira":
        return
    if not tr.base_url:
        error(
            "team.yaml",
            t("tracker.base_url is missing (address of the Jira server, http or https)"),
        )
    else:
        problem = base_url_problem(tr.base_url)
        if problem == "invalid":
            error("team.yaml", t("tracker.base_url must be an http or https address"))
        elif problem == "credentials":
            error("team.yaml", t("tracker.base_url must not contain credentials"))
        elif problem == "extra":
            error(
                "team.yaml",
                t("tracker.base_url must not contain parameters (?…) or a fragment (#…)"),
            )
        elif tr.base_url.strip().lower().startswith("http://"):
            warn(
                "team.yaml",
                t("tracker.base_url is unencrypted (http): the token could be read by others"),
            )
    if not tr.query:
        error("team.yaml", t("tracker.query is missing (JQL query of the tickets)"))
    if not tr.fields.estimate:
        warn(
            "team.yaml",
            t("tracker.fields.estimate is missing: without an estimate nothing can be distributed"),
        )


def _check_tickets(data: TeamData, today: date, error, warn) -> None:
    """Projects, tickets and pre-planning (only with ``features.tickets``)."""
    team = data.team
    tr = team.tracker
    if team.tracker_raw is not None:
        # An unreadable section kept while the feature was off: switching it on must not
        # produce a team that does not load.
        try:
            tracker_from_raw(team.tracker_raw, "team.yaml")
        except (DataError, ValueError, TypeError) as e:
            error("team.yaml", str(e).removeprefix("team.yaml: "))
    if tr.dependency_gap not in (0, 1):
        error("team.yaml", t("tracker.dependency_gap must be 0 or 1"))
    order = tr.project_match_order
    if any(s not in RULE_SOURCES for s in order) or len(set(order)) != len(order):
        error(
            "team.yaml",
            t(
                "tracker.project_match_order: only sources from {allowed}, each at most once",
                allowed=", ".join(RULE_SOURCES),
            ),
        )
    if tr.rough_factor <= 0:
        error("team.yaml", t("tracker.rough_factor must be > 0"))
    if tr.refined_also_if is not None:
        for problem in rule_problems(tr.refined_also_if):
            error("team.yaml", t("tracker.refined_also_if: {problem}", problem=problem))
    if not tr.link_type.strip():
        error("team.yaml", t("tracker.link_type must not be empty"))
    _check_tracker_source(tr, error, warn)

    products = {p.id: p for p in data.products}
    project_ids: set[str] = set()
    for pr in data.projects:
        where = f"projects.yaml: {pr.id}"
        if pr.id in project_ids:
            error(where, t("duplicate id"))
        project_ids.add(pr.id)
        if team.features.products:
            if not pr.product:
                error(where, t("product is missing (the product distribution is on)"))
            elif pr.product not in products:
                error(where, t("unknown product '{id}'", id=pr.product))
            elif (end := products[pr.product].end) is not None and end < today:
                warn(where, t("Product '{id}' ended on {end}", id=pr.product, end=end))
        elif pr.product:
            error(where, t("product must be empty (the product distribution is off)"))
        if pr.target is None:
            error(where, t("target is missing"))
        elif pr.target < today:
            warn(where, t("target {date} lies in the past", date=pr.target))
        if pr.match is not None:
            for problem in rule_problems(pr.match):
                error(where, t("match: {problem}", problem=problem))
        elif not any(tk.project == pr.id for tk in data.tickets):
            warn(where, t("neither a match rule nor assigned tickets"))

    known_sprints = _known_sprints(data)
    keys: set[str] = set()
    for tk in data.tickets:
        where = f"tickets.yaml: {tk.key}"
        if tk.key in keys:
            error(where, t("key is duplicated"))
        keys.add(tk.key)
        for name in ("estimate", "remaining"):
            value = getattr(tk, name)
            if value is not None and value < 0:
                error(where, t("{name} must not be negative", name=name))
        if tk.project is not None and tk.project not in project_ids:
            error(where, t("unknown project '{id}'", id=tk.project))
        if tk.in_sprint is not None and tk.in_sprint not in known_sprints:
            warn(where, t("in_sprint '{id}' is not a known sprint", id=tk.in_sprint))
    for cycle in find_cycles(data.tickets):
        error(
            "tickets.yaml",
            t("Circular dependencies: {cycle}", cycle=" → ".join([*cycle, cycle[0]])),
        )

    earmarked: set[str] = set()
    for e in data.preplan.earmarks:
        where = f"preplan.yaml: {e.ticket}"
        if e.ticket in earmarked:
            error(where, t("several earmarks for the same ticket"))
        earmarked.add(e.ticket)
        if e.ticket not in keys:
            warn(where, t("Earmark for an unknown ticket (not in the last import)"))
        if e.sprint not in known_sprints:
            warn(where, t("Sprint '{id}' is not known", id=e.sprint))
        elif known_sprints[e.sprint].end <= today:
            warn(
                where,
                t(
                    "Earmark for the past sprint '{id}' (ignored; the next import drops it)",
                    id=e.sprint,
                ),
            )
    estimated: set[str] = set()
    for m in data.preplan.estimates:
        where = f"preplan.yaml: {m.ticket}"
        if m.ticket in estimated:
            error(where, t("several estimates for the same ticket"))
        estimated.add(m.ticket)
        if m.ticket not in keys:
            warn(where, t("Estimate for an unknown ticket (not in the last import)"))
        if m.estimate is None:
            error(where, t("estimate is missing"))
        elif m.estimate < 0:
            error(where, t("{name} must not be negative", name="estimate"))


def check_team(data: TeamData, today: date) -> list[Issue]:
    issues: list[Issue] = []
    team = data.team

    def error(where: str, msg: str) -> None:
        issues.append(Issue(Level.ERROR, where, msg))

    def warn(where: str, msg: str) -> None:
        issues.append(Issue(Level.WARNING, where, msg))

    f = team.forecast
    if f.reference_capacity <= 0:
        error("team.yaml", t("forecast.reference_capacity must be > 0"))
    if f.window < 1:
        error("team.yaml", t("forecast.window must be ≥ 1"))
    if not 0 <= f.roadmap_share <= 1:
        error("team.yaml", t("forecast.roadmap_share must be between 0 and 1"))
    if not 0 <= team.capacity.overhead_share < 1:
        error("team.yaml", t("capacity.overhead_share must be between 0 and 1"))
    country = team.capacity.country
    if country not in countries():
        error("team.yaml", t("Country '{country}' is not supported", country=country))
    elif team.capacity.region and team.capacity.region not in subdivisions(country):
        error(
            "team.yaml",
            t(
                "Region '{region}' does not belong to country {country}",
                region=team.capacity.region,
                country=country,
            ),
        )
    try:
        weekend_from_workweek(team.capacity.workweek)
    except ValueError:
        error("team.yaml", t("Unknown work week '{value}'", value=team.capacity.workweek))
    if team.capacity.absence_history < 0:
        error("team.yaml", t("capacity.absence_history must not be negative"))
    if team.capacity.overhead_days < 0:
        error("team.yaml", t("capacity.overhead_days must not be negative"))
    if team.sprint.length_days < 1:
        error("team.yaml", t("sprint.length_days must be ≥ 1"))
    if not data.sprints and (team.sprint.first_id is None or team.sprint.first_start is None):
        error(
            "team.yaml",
            t("Without sprint files, sprint.first.id and sprint.first.start are required"),
        )
    # Calendar, absences and forecast form the follow-up IDs from the running sprint to beyond
    # the last one (without sprint files: from the first sprint). Completed sprints before that
    # do not matter; the last one always counts.
    chain = [(f"sprints/{s.id}.yaml", s.id, s.end) for s in data.sprints if s.end > today]
    if data.sprints and data.sprints[-1].end <= today:
        last = data.sprints[-1]
        chain.append((f"sprints/{last.id}.yaml", last.id, last.end))
    if not data.sprints and team.sprint.first_id and team.sprint.first_start:
        first_end = team.sprint.first_start + timedelta(days=max(team.sprint.length_days, 1))
        chain.append(("team.yaml", team.sprint.first_id, first_end))
    for where, sprint_id, next_start in chain:
        if not id_fits_numbering(sprint_id, next_start, team.sprint.numbering):
            error(
                where,
                t(
                    (
                        "ID does not match the numbering (expected {expected}) – the ID of the "
                        "following sprint cannot be formed"
                    ),
                    expected=expected_id_form(team.sprint.numbering),
                ),
            )

    ids: set[str] = set()
    for p in data.people:
        where = f"people.yaml: {p.id}"
        if p.id in ids:
            error(where, t("duplicate id"))
        ids.add(p.id)
        if not p.memberships:
            warn(where, t("no memberships recorded"))
        ordered = sorted(p.memberships, key=lambda m: m.start)
        for m in ordered:
            if not 0 <= m.fte <= 1:
                error(where, t("fte {fte} must be between 0 and 1", fte=m.fte))
            if m.end is not None and m.end < m.start:
                error(
                    where,
                    t(
                        "membership ends ({end}) before it starts ({start})",
                        end=m.end,
                        start=m.start,
                    ),
                )
        for a, b in itertools.pairwise(ordered):
            if a.end is None or a.end >= b.start:
                error(
                    where,
                    t("memberships overlap ({a} / {b})", a=a.start, b=b.start),
                )

    for p in data.people:
        where = f"people.yaml: {p.id}"
        try:
            weekend_from_workweek(p.workweek)
        except ValueError:
            error(where, t("Unknown work week '{value}'", value=p.workweek))
        if p.country and p.country not in countries():
            error(where, t("Country '{country}' is not supported", country=p.country))
        elif p.region and p.region not in subdivisions(p.country or country):
            error(
                where,
                t(
                    "Region '{region}' does not belong to country {country}",
                    region=p.region,
                    country=p.country or country,
                ),
            )

    product_ids: set[str] = set()
    for prod in data.products:
        where = f"products.yaml: {prod.id}"
        if prod.id in product_ids:
            error(where, t("duplicate id"))
        product_ids.add(prod.id)
        if prod.share is not None and not 0 < prod.share <= 1:
            error(where, t("share must be between 0 and 1"))
        if prod.start and prod.end and prod.end < prod.start:
            error(
                where,
                t(
                    "period ends ({end}) before it starts ({start})",
                    end=prod.end,
                    start=prod.start,
                ),
            )
    products = {p.id: p for p in data.products}
    _check_product_shares(data, today, error, warn)

    people = {p.id: p for p in data.people}
    previous = None
    for s in data.sprints:
        where = f"sprints/{s.id}.yaml"
        if s.end <= s.start:
            error(where, t("end must be after start"))
        if previous is not None and s.start < previous.end:
            error(where, t("overlaps sprint {id}", id=previous.id))
        if previous is not None and s.start > previous.end:
            warn(
                where,
                t(
                    "gap after sprint {id} ({end} → {start})",
                    id=previous.id,
                    end=previous.end,
                    start=s.start,
                ),
            )
        previous = s

        for pid, absent in s.expected_absences.items():
            if pid not in people:
                error(where, t("Announced absences for unknown person '{id}'", id=pid))
            elif absent < 0:
                error(where, t("expected_absences.{id} must not be negative", id=pid))

        days = len(team_workdays(team, s.start, s.end))
        for pid, absent in s.absences.items():
            person = people.get(pid)
            if person is None:
                error(where, t("absences for unknown person '{id}'", id=pid))
            elif not person.active_between(s.start, s.end):
                warn(where, t("'{id}' is not in the team during this sprint", id=pid))
            if absent < 0:
                error(where, t("absences for '{id}' are negative", id=pid))
            elif absent > days:
                error(
                    where,
                    t(
                        "'{id}': {absent} days absent, the sprint only has {days} working days",
                        id=pid,
                        absent=_g(absent),
                        days=days,
                    ),
                )

        for pid, values in s.products.items():
            product = products.get(pid)
            if product is None:
                error(where, t("values for unknown product '{id}'", id=pid))
            elif not product.active_between(s.start, s.end) and not values.is_empty():
                warn(
                    where,
                    t(
                        (
                            "according to the product list, product '{id}' is not handled in "
                            "this sprint"
                        ),
                        id=pid,
                    ),
                )
            for name in (
                "preplanned",
                "planned",
                "done",
                "production_planned",
                "production_done",
            ):
                value = getattr(values, name)
                if value is not None and value < 0:
                    error(where, t("products.{id}.{name} must not be negative", id=pid, name=name))
        for pid, values in s.products.items():
            for whole, part in (
                (values.planned, values.production_planned),
                (values.done, values.production_done),
            ):
                if part is not None and part > (whole or 0.0) + 0.05:
                    warn(
                        where,
                        t(
                            (
                                "Product '{id}': production access ({part}) is larger than the "
                                "total ({whole})"
                            ),
                            id=pid,
                            part=_g(part),
                            whole=_g(whole or 0.0),
                        ),
                    )
        planned = [v.planned for v in s.products.values() if v.planned is not None]
        if planned and s.commitment is not None and sum(planned) > s.commitment + 0.05:
            warn(
                where,
                t(
                    "planned per product ({planned}) exceeds the commitment ({commitment})",
                    planned=_g(sum(planned)),
                    commitment=_g(s.commitment),
                ),
            )
        done = [v.done for v in s.products.values() if v.done is not None]
        if done and s.velocity is not None and sum(done) > s.velocity + 0.05:
            warn(
                where,
                t(
                    "done per product ({done}) exceeds the velocity ({velocity})",
                    done=_g(sum(done)),
                    velocity=_g(s.velocity),
                ),
            )

        for name in ("not_done", "additional_done", "production_planned", "production_done"):
            value = getattr(s, name)
            if value is not None and value < 0:
                error(where, t("{name} must not be negative", name=name))
        if (
            s.production_planned is not None
            and s.commitment is not None
            and s.production_planned > s.commitment + 0.05
        ):
            warn(
                where,
                t(
                    "Planned with production access ({part}) exceeds the commitment ({whole})",
                    part=_g(s.production_planned),
                    whole=_g(s.commitment),
                ),
            )
        if (
            s.velocity is not None
            and s.commitment is not None
            and (s.not_done is not None or s.additional_done is not None)
        ):
            expected = s.commitment - (s.not_done or 0.0) + (s.additional_done or 0.0)
            if abs(expected - s.velocity) > 0.05:
                warn(
                    where,
                    t(
                        (
                            "Commitment ({commitment}) − not finished ({open}) + additionally done "
                            "({extra}) gives {expected}, but the velocity is {velocity}"
                        ),
                        commitment=_g(s.commitment),
                        open=_g(s.not_done or 0.0),
                        extra=_g(s.additional_done or 0.0),
                        expected=_g(expected),
                        velocity=_g(s.velocity),
                    ),
                )
        non_negative = {
            "capacity": s.capacity,
            "forecast_ist": s.commitment,  # the file key keeps its name
            "velocity": s.velocity,
            "forecast_plan": s.forecast_plan,
        }
        for name, value in non_negative.items():
            if value is not None and value < 0:
                error(where, t("{name} must not be negative", name=name))
        if s.scope_creep is not None and not 0 <= s.scope_creep <= 1:
            warn(
                where,
                t(
                    "scope_creep {value} is outside 0–1 (a share, not a percentage?)",
                    value=_g(s.scope_creep),
                ),
            )
        if s.capacity == 0:
            warn(where, t("capacity 0 – normalized velocity cannot be calculated"))
        if s.velocity is not None and s.commitment and s.velocity > 2 * s.commitment:
            warn(where, t("velocity is more than twice the commitment – typo?"))

        if s.planning is not None and s.end > today:
            committed = s.planning.committed
            if s.commitment is not None and committed and abs(s.commitment - committed) > 0.05:
                warn(
                    where,
                    t(
                        (
                            "commitment {commitment} differs from carry-over + backlog "
                            "({planned}) – typo or missing ticket?"
                        ),
                        commitment=_g(s.commitment),
                        planned=_g(committed),
                    ),
                )
            if sum(s.planning.corrections) > committed:
                warn(where, t("corrections exceed carry-over + backlog"))

        if s.end <= today:
            if s.velocity is None:
                warn(where, t("sprint has ended, velocity missing (record the review)"))
            if s.capacity is None:
                warn(
                    where,
                    t(
                        "sprint has ended, capacity not frozen (otherwise calculated from "
                        "the current people list)"
                    ),
                )
    if team.features.tickets:
        _check_tickets(data, today, error, warn)
    return issues


def issues_for(data: TeamData, today: date, filenames: list[str]) -> list[Issue]:
    """Check results that concern one of the named files (e.g. "2026.21.yaml")."""
    return [i for i in check_team(data, today) if any(name in i.where for name in filenames)]


# --- Silent assumptions when loading ---------------------------------------------------
#
# Loading does not change because of this: a duplicate key still counts as "the last one
# wins", an empty value as 0. The check only makes this visible. Empty values are reported
# only where a number is expected and the program silently reads the empty value as 0.
# Intentionally empty fields (``to:``, ``capacity:``, ``forecast_ist:``, ``region:`` ...) are
# valid and produce no message.

_EMPTY_AS_ZERO: tuple[tuple[str, ...], ...] = (
    ("people", "*", "memberships", "*", "fte"),
    ("planning", "carryover"),
    ("planning", "backlog"),
    ("planning", "corrections", "*"),
    ("absences", "*"),
    ("expected_absences", "*"),
    ("prognoses", "*", "preplanned", "*"),
    ("projects", "*", "priority"),
)
_NULL_TAG = "tag:yaml.org,2002:null"
_STR_TAG = "tag:yaml.org,2002:str"
_MERGE_TAG = "tag:yaml.org,2002:merge"


def _format_path(path: tuple[str | int, ...]) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else part)
    return out


def _is_empty_value(node: yaml.Node) -> bool:
    if not isinstance(node, yaml.ScalarNode):
        return False
    return node.tag == _NULL_TAG or (node.tag == _STR_TAG and node.value == "")


def _matches(path: tuple[str | int, ...], pattern: tuple[str, ...]) -> bool:
    return len(path) == len(pattern) and all(
        want == "*" or want == str(got) for want, got in zip(pattern, path, strict=True)
    )


# Mappings whose keys the program reads with str() (person and product abbreviations): there
# ``1`` and ``"1"`` are the same key. Everywhere else the loader keeps both entries.
_STR_KEYED: tuple[tuple[str, ...], ...] = (
    ("products",),
    ("absences",),
    ("expected_absences",),
    ("prognoses", "*", "preplanned"),
    ("tracker", "sprint_names"),
)
# Upper limit of visited nodes per file: protects against anchor bombs (references that
# multiply many times over). Real files are far below it.
_MAX_VISITS = 50_000
# Further limits per file: computing time, number of messages and entries per line list. The
# "Check" page renders each message individually.
_MAX_SECONDS = 2.0
_MAX_ISSUES = 50
_MAX_PLACES = 10

# Path as a linked list (parent path, part): depth costs nothing when creating it.
type _Path = tuple[_Path | None, str | int] | None


def _materialize(cell: _Path) -> tuple[str | int, ...]:
    parts: list[str | int] = []
    while cell is not None:
        cell, part = cell
        parts.append(part)
    return tuple(reversed(parts))


def _key_of(node: yaml.Node, as_text: bool, canon: dict[Any, str]) -> tuple[str, Any]:
    """Display text and comparison key. With ``as_text`` (places where the program builds
    ``str()``) the text counts, otherwise the type too (``1`` is not ``"1"``).
    ``canon`` belongs to the surrounding mapping: the loader first builds the dict with Python
    equality (``1 == 1.0 == True``, the first key object stays) and only then applies ``str()``;
    ``canon`` remembers the text of the first entry for each key object."""
    if not isinstance(node, yaml.ScalarNode):
        return str(id(node)), ("node", id(node))
    if node.tag == _STR_TAG:
        value: Any = node.value
    else:
        try:
            value = SafeConstructor().construct_object(node, deep=True)
        except Exception:  # unusual key: the text is enough
            value = node.value
    # Control characters from files (line break, ESC) never belong in a message
    shown = blank_controls(str(value))
    try:
        hash(value)
    except TypeError:  # unhashable: the loader would reject the key anyway
        return shown, (str(value) if as_text else ("node", id(node)))
    if as_text:
        return shown, canon.setdefault(value, str(value))
    # Like the loader: Python equality (1 == 1.0 == True), but not 1 == "1"
    return shown, value


def _inherited(
    node: yaml.MappingNode,
    as_text: bool,
    canon: dict[Any, str],
    taken: set[Any],
    visiting: frozenset[int],
) -> list[tuple[yaml.Node, yaml.Node]]:
    """Entries that ``node`` inherits via ``<<`` and that the loader keeps (PyYAML rules:
    explicit keys always win; with several ``<<`` in the same mapping the later one, with a
    list ``<<: [a, b]`` the earlier source; within a source its own keys before those it
    inherited). ``taken`` are the keys already assigned."""
    result: list[tuple[yaml.Node, yaml.Node]] = []
    merges = [vn for kn, vn in node.value if kn.tag == _MERGE_TAG]
    for value_node in reversed(merges):  # the last ``<<`` overrides the earlier ones
        sources = value_node.value if isinstance(value_node, yaml.SequenceNode) else [value_node]
        for source in sources:
            if not isinstance(source, yaml.MappingNode) or id(source) in visiting:
                continue
            own = [
                (kn, vn, _key_of(kn, as_text, canon)[1])
                for kn, vn in source.value
                if kn.tag != _MERGE_TAG
            ]
            fresh = [(kn, vn, c) for kn, vn, c in own if c not in taken]
            taken.update(c for _, _, c in fresh)
            result += [(kn, vn) for kn, vn, _ in fresh]
            result += _inherited(source, as_text, canon, taken, visiting | {id(source)})
    return result


def _position(found: list[tuple[int, int]]) -> tuple[str, str]:
    """Occurrences (line, column) as text; if all are on one line (flow notation
    ``{a: 1, a: 2}``), with columns."""
    if len({line for line, _ in found}) == 1:
        line = found[0][0]
        cols = _listed([c for _, c in found])
        return (
            t("all in line {line}, columns {cols}", line=line, cols=cols),
            t("line {line}, column {col}", line=line, col=found[-1][1]),
        )
    return (
        t("lines {lines}", lines=_listed([n for n, _ in found])),
        t("line {line}", line=found[-1][0]),
    )


def _listed(numbers: list[int]) -> str:
    """Numbers as a list, shortened if there are very many (the message would be huge otherwise)."""
    shown = ", ".join(str(n) for n in numbers[:_MAX_PLACES])
    if len(numbers) > _MAX_PLACES:
        shown += t(" … and {n} more", n=len(numbers) - _MAX_PLACES)
    return shown


def check_yaml_text(text: str, name: str) -> list[Issue]:
    """Duplicate keys and empty values silently read as 0 in a YAML file (as a notice)."""
    try:
        root = compose_yaml(text)
    except yaml.YAMLError:
        return []  # loading reports invalid YAML as an error
    except RecursionError:
        return [Issue(Level.WARNING, name, t("The file is nested too deeply and was not checked."))]
    issues: list[Issue] = []
    omitted = 0

    def report(message: str) -> None:
        nonlocal omitted
        if len(issues) < _MAX_ISSUES:
            issues.append(Issue(Level.WARNING, name, message))
        else:
            omitted += 1

    # Steps: (node, path) on entering, (node, None) on leaving. Iterative so that extreme
    # nesting does not fail at the recursion limit. A node is visited once per path
    # (anchors/references make it count under every path); ``active`` holds the nodes on the
    # way to the root and stops circular references.
    stack: list[tuple[yaml.Node, _Path | None, bool]] = []
    if root is not None:
        stack.append((root, None, True))
    active: set[int] = set()
    visited: set[int] = set()  # nodes entered before (references hit them)
    duplicates_done: set[int] = set()  # mappings whose duplicate keys are already reported
    visits = repeats = 0
    stopped = ""
    deadline = time.monotonic() + _MAX_SECONDS
    while stack:
        node, cell, entering = stack.pop()
        if not entering:
            active.discard(id(node))
            continue
        visits += 1
        if id(node) in visited:
            repeats += 1
        visited.add(id(node))
        if visits > _MAX_VISITS or (visits % 1024 == 0 and time.monotonic() > deadline):
            # "Anchor" is the right hint only if references are the main cause.
            stopped = (
                t(
                    "The file refers to the same parts (anchors) so often that it was not "
                    "checked completely."
                )
                if repeats * 2 > visits
                else t("The file is too large or too deeply nested to be checked completely.")
            )
            break
        if isinstance(node, yaml.ScalarNode):
            path = _materialize(cell)
            if _is_empty_value(node) and any(_matches(path, p) for p in _EMPTY_AS_ZERO):
                report(
                    t(
                        (
                            "The value of '{where}' (line {line}) is empty. The program "
                            "silently counts it as 0. Please enter a number (0 if it really is "
                            "zero)."
                        ),
                        where=_format_path(path),
                        line=node.start_mark.line + 1,
                    )
                )
            continue
        if id(node) in active:  # reference to a parent node: do not repeat endlessly
            continue
        active.add(id(node))
        stack.append((node, None, False))
        children: list[tuple[yaml.Node, _Path | None, bool]] = []
        if isinstance(node, yaml.SequenceNode):
            children = [(item, (cell, i), True) for i, item in enumerate(node.value)]
        else:
            path = _materialize(cell)
            as_text = any(_matches(path, p) for p in _STR_KEYED)
            canon: dict[Any, str] = {}  # per key object, the text of the first entry
            found: dict[Any, list[tuple[int, int]]] = {}
            shown: dict[Any, str] = {}
            kept: dict[Any, tuple[yaml.Node, str]] = {}  # per key, the last entry
            for key_node, value_node in node.value:
                if key_node.tag == _MERGE_TAG:  # inherited entries: see _inherited
                    continue
                text_of_key, compare = _key_of(key_node, as_text, canon)
                mark = key_node.start_mark
                found.setdefault(compare, []).append((mark.line + 1, mark.column + 1))
                shown[compare] = text_of_key
                kept[compare] = (value_node, text_of_key)
            # The loader keeps only the last entry: overridden values are not read.
            children = [(value_node, (cell, text), True) for value_node, text in kept.values()]
            # Inherited entries (``<<``) count only where no explicit entry replaces them.
            for key_node, value_node in _inherited(
                node, as_text, canon, set(found), frozenset({id(node)})
            ):
                text_of_key = _key_of(key_node, as_text, canon)[0]
                children.append((value_node, (cell, text_of_key), True))
            first_time = id(node) not in duplicates_done  # references: report only once
            duplicates_done.add(id(node))
            for compare, places in found.items():
                if len(places) > 1 and first_time:
                    where = _format_path((*path, shown[compare]))
                    lines, last = _position(places)
                    report(
                        t(
                            (
                                "The key '{where}' appears more than once in the file "
                                "({lines}). The program reads only the last entry ({last}); "
                                "the others are silently ignored. Please delete the extra "
                                "lines and keep the correct value."
                            ),
                            where=where,
                            lines=lines,
                            last=last,
                        )
                    )
        stack.extend(reversed(children))
    if omitted:
        issues.append(
            Issue(
                Level.WARNING,
                name,
                t("… and {n} more notes in this file", n=omitted),
            )
        )
    if stopped:
        issues.append(Issue(Level.WARNING, name, stopped))
    return issues


def _tickets_enabled(base: Path) -> bool:
    """``features.tickets`` according to team.yaml in ``base`` (unreadable = off)."""
    try:
        raw = yaml.safe_load((base / "team.yaml").read_text(encoding="utf-8"))
        return bool(raw["features"]["tickets"])
    except OSError, UnicodeDecodeError, KeyError, TypeError, yaml.YAMLError:
        return False  # the loader reports problems with the file


def check_team_files(base: Path, tickets: bool | None = None) -> list[Issue]:
    """Silent assumptions in a team's files (folder ``base``): duplicate keys and empty number
    fields, each as a notice with file name, line and key path. The ticket pre-planning files
    only with ``features.tickets`` (``tickets``; if not given, according to team.yaml)."""
    if tickets is None:
        tickets = _tickets_enabled(base)
    files = [base / name for name in TEAM_FILES if tickets or name not in TICKET_FILES]
    files += sorted((base / "sprints").glob("*.yaml"))
    issues: list[Issue] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue  # loading reports missing or unreadable files
        name = path.relative_to(base).as_posix()
        issues += check_yaml_text(text, name)
    return issues


def check_all(repo: Repository, today: date) -> dict[str, list[Issue]]:
    result = {}
    for key in repo.teams():
        try:
            data = repo.load(key)
            result[key] = check_team(data, today) + check_team_files(
                repo.team_dir(key), data.team.features.tickets
            )
        except DataError as e:
            result[key] = [Issue(Level.ERROR, key, str(e))]
    return result
