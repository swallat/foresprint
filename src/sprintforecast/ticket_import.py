# SPDX-License-Identifier: EUPL-1.2
"""Ticket import of the pre-planning (docs/design/ticket-planning.md, section 6).

Turns the raw tickets of a source (``sources/``) into :class:`~sprintforecast.model.Ticket`
objects: sprint names become sprint ids, the refined state and the project are derived from
``tracker`` and ``projects.yaml``. Like the Excel import it has two stages: :func:`plan_import`
compares with the last import and the earmarks (reconciliation, section 6.5) and writes nothing;
:func:`apply_import` writes tickets.yaml and, when it changed, preplan.yaml. Manual estimates of
the PO are not applied here; the distribution (preplan.py) does that."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sprintforecast.forecast import Forecast, find_sprint, lookup_sprint
from sprintforecast.i18n import t
from sprintforecast.model import EstimateSource, Preplan, Project, Ticket, TrackerSettings
from sprintforecast.sources import RawTicket
from sprintforecast.storage import Repository, TeamData
from sprintforecast.validate import find_cycles

# Kinds of a TicketChange, in the order the preview shows them.
KINDS: tuple[str, ...] = (
    "new",  # key not in the last import
    "changed",  # estimate or remaining differs (``note`` = field, old/new = numbers)
    "done",  # resolved now (was open or unknown before)
    "missing",  # key no longer delivered: removed from tickets.yaml
    "unassigned",  # no project, or several via the same source (``new`` = candidates)
    "unknown_epic",  # epic no project rule refers to (``key`` = epic, ``new`` = ticket keys)
    "refined_unclear",  # refined only via refined_also_if (note "rule") or label without estimate
    # earmark discarded: real sprint wins (old/new = sprints), ticket done, or its sprint is
    # over (note ``DROPPED_ENDED``)
    "earmark_dropped",
    "sprint_unresolved",  # sprint name of the tracker unknown to the tool (``note`` = name)
)
# ``note`` of a refined_unclear change.
UNCLEAR_RULE = "rule"
UNCLEAR_NO_ESTIMATE = "no_estimate"
# ``note`` of an earmark_dropped change whose sprint is over (an open ticket cannot be put into
# the past).
DROPPED_ENDED = "ended"


@dataclass
class TicketChange:
    kind: str
    key: str
    title: str = ""
    old: Any = None
    new: Any = None
    note: str | None = None


@dataclass
class TicketImportPlan:
    """Result of the preview: the tickets to write, the reconciled preplan and what changed."""

    tickets: list[Ticket]
    preplan: Preplan
    # True when the reconciliation dropped an earmark: preplan.yaml is written as well.
    preplan_changed: bool = False
    changes: list[TicketChange] = field(default_factory=list)
    # Hints that do not belong to one ticket of the import (translated texts).
    warnings: list[str] = field(default_factory=list)
    # Name of the source (file name or query) stored in tickets.yaml.
    source: str | None = None

    def of_kind(self, kind: str) -> list[TicketChange]:
        return [c for c in self.changes if c.kind == kind]

    def unchanged(self, data: TeamData) -> bool:
        """Would applying the plan leave the stored files as they are (apart from the time
        stamp)? Then nothing is written (a new source name counts as a change). ``changes`` is
        not the measure: it also lists hints that stay as long as the data does (unassigned
        tickets, unknown epics ...)."""
        return (
            not self.preplan_changed
            and self.tickets == data.tickets
            and self.source == data.tickets_source
        )


# --- Single ticket ---------------------------------------------------------------------------


def is_refined(
    facts: dict[str, list[str]], estimate: float | None, tracker: TrackerSettings
) -> tuple[bool, bool]:
    """``(refined, unclear)`` of a ticket with these facts (spec section 6.3).

    The label with an estimate is a clear refinement. Without the label, ``refined_also_if``
    counts as refined but unclear (the label is sometimes forgotten). The label without an
    estimate is unclear and not refined: there is nothing to calculate with."""
    has_label = bool(tracker.refined_label) and tracker.refined_label in facts.get("label", [])
    if has_label:
        return (True, False) if estimate is not None else (False, True)
    if tracker.refined_also_if is not None and tracker.refined_also_if.matches(facts):
        return True, True
    return False, False


def assign_project(
    facts: dict[str, list[str]], projects: list[Project], order: list[str] | tuple[str, ...]
) -> tuple[str | None, list[str]]:
    """``(project id, candidates)`` of a ticket with these facts (spec section 6.4).

    Of all projects whose rule matches, the one matching via the source earliest in ``order``
    wins; sources outside the order rank last. Several projects matching via the same best
    source contradict each other: no project, all of them as candidates (in file order)."""

    def rank(sources: set[str]) -> int:
        positions = [order.index(s) for s in sources if s in order]
        return min(positions) if positions else len(order)

    matching = [
        (p.id, rank(p.match.matched_sources(facts)))
        for p in projects
        if p.match is not None and p.match.matches(facts)
    ]
    if not matching:
        return None, []
    best = min(r for _, r in matching)
    winners = [pid for pid, r in matching if r == best]
    if len(winners) == 1:
        return winners[0], []
    return None, winners


def resolve_sprint(name: str | None, data: TeamData, fc: Forecast) -> str | None:
    """The tool's sprint id for a sprint name of the tracker: the name itself when it is a known
    id (recorded, in the forecast or in the calendar ahead), else ``tracker.sprint_names``,
    else None (the raw name stays on the ticket)."""
    if not name:
        return None
    if data.sprint(name) is not None or fc.entry(name) is not None:
        return name
    if find_sprint(data, name, max_ahead=52) is not None:
        return name
    return data.team.tracker.sprint_names.get(name)


def convert(raw: RawTicket, data: TeamData, fc: Forecast, projects: list[Project]) -> Ticket:
    """A raw ticket as the tool stores it: sprint resolved, refined state and project derived.

    Jira keeps closed sprints in the Sprint field of an open ticket (carried over): such a
    sprint is resolved but does not count as the ticket's sprint (``in_sprint`` stays None,
    ``sprint_name`` keeps the name for display)."""
    tracker = data.team.tracker
    in_sprint = resolve_sprint(raw.sprint_name, data, fc)
    if in_sprint is not None and sprint_ended(in_sprint, fc):
        in_sprint = None
    ticket = Ticket(
        key=raw.key,
        title=raw.title,
        status=raw.status,
        issue_type=raw.issue_type,
        estimate=raw.estimate,
        remaining=raw.remaining,
        in_sprint=in_sprint,
        sprint_name=raw.sprint_name,
        rank=raw.rank,
        epic=raw.epic,
        labels=list(raw.labels),
        components=list(raw.components),
        depends_on=list(raw.blocked_by),
        done=raw.resolved,
    )
    facts = ticket.facts()
    # The size the distribution calculates with (remaining if filled, else the estimate).
    size = ticket.size(tracker.planning_uses)
    refined, unclear = is_refined(facts, size, tracker)
    ticket.refined_unclear = unclear
    if size is None:
        ticket.estimate_source = EstimateSource.NONE
    elif refined and not unclear:
        ticket.estimate_source = EstimateSource.REFINED
    else:
        ticket.estimate_source = EstimateSource.ROUGH
    ticket.project, ticket.project_candidates = assign_project(
        facts, projects, tracker.project_match_order
    )
    return ticket


# --- Preview and apply -----------------------------------------------------------------------


def known_epics(projects: list[Project]) -> set[str]:
    """Epics some project rule refers to."""
    found: set[str] = set()
    for p in projects:
        if p.match is not None:
            for leaf in p.match.leaves():
                if leaf.source == "epic":
                    found.update(leaf.values)
    return found


def sprint_ended(sprint_id: str, fc: Forecast) -> bool:
    """Is the sprint known and already over (its end is not after today)?"""
    sprint = lookup_sprint(fc, sprint_id)
    return sprint is not None and sprint.end <= fc.today


def _sprint_open(sprint_id: str, data: TeamData, fc: Forecast, today: date) -> bool:
    """Is the sprint known and current or in the future (its end after today)?"""
    sprint = lookup_sprint(fc, sprint_id)
    return sprint is not None and sprint.end > today


def plan_import(
    data: TeamData,
    fc: Forecast,
    raws: list[RawTicket],
    today: date,
    source: str | None = None,
) -> TicketImportPlan:
    """Converts the raw tickets and reconciles them with the last import and the earmarks
    (spec section 6.5); nothing is written."""
    old = {tk.key: tk for tk in data.tickets}
    preplan = copy.deepcopy(data.preplan)
    plan = TicketImportPlan(tickets=[], preplan=preplan, source=source)
    epics_known = known_epics(data.projects)
    unknown: dict[str, list[str]] = {}

    seen: dict[str, Ticket] = {}
    for raw in raws:
        if raw.key in seen:
            plan.warnings.append(
                t("Ticket {key} kommt mehrfach vor; der letzte Eintrag gilt", key=raw.key)
            )
        seen[raw.key] = convert(raw, data, fc, data.projects)
    plan.tickets = list(seen.values())

    for tk in plan.tickets:
        prev = old.get(tk.key)
        if prev is None and not tk.done:
            plan.changes.append(TicketChange("new", tk.key, tk.title))
        if prev is not None:
            for name in ("estimate", "remaining"):
                before, after = getattr(prev, name), getattr(tk, name)
                if before != after:
                    plan.changes.append(
                        TicketChange("changed", tk.key, tk.title, before, after, note=name)
                    )
        earmark = preplan.earmark_for(tk.key)
        if tk.done:
            if prev is None or not prev.done:
                plan.changes.append(TicketChange("done", tk.key, tk.title))
            if earmark is not None:
                preplan.earmarks.remove(earmark)
                plan.changes.append(
                    TicketChange("earmark_dropped", tk.key, tk.title, old=earmark.sprint)
                )
            continue
        if earmark is not None and sprint_ended(earmark.sprint, fc):
            preplan.earmarks.remove(earmark)
            plan.changes.append(
                TicketChange(
                    "earmark_dropped", tk.key, tk.title, old=earmark.sprint, note=DROPPED_ENDED
                )
            )
            earmark = None
        if tk.in_sprint is None:
            # A closed sprint is resolved but not the ticket's sprint; only names the tool
            # cannot resolve are reported.
            if tk.sprint_name and resolve_sprint(tk.sprint_name, data, fc) is None:
                plan.changes.append(
                    TicketChange("sprint_unresolved", tk.key, tk.title, note=tk.sprint_name)
                )
        elif (
            earmark is not None
            and earmark.sprint != tk.in_sprint
            and _sprint_open(tk.in_sprint, data, fc, today)
        ):
            # The real sprint of the tracker wins over the earmark of the tool.
            preplan.earmarks.remove(earmark)
            plan.changes.append(
                TicketChange("earmark_dropped", tk.key, tk.title, earmark.sprint, tk.in_sprint)
            )
        if tk.project is None:
            plan.changes.append(
                TicketChange("unassigned", tk.key, tk.title, new=list(tk.project_candidates))
            )
        if tk.epic and tk.epic not in epics_known:
            unknown.setdefault(tk.epic, []).append(tk.key)
        if tk.refined_unclear:
            # With the label the only way to be unclear is a missing size; without it the
            # ticket counts as refined only via ``refined_also_if``.
            label = data.team.tracker.refined_label
            note = UNCLEAR_NO_ESTIMATE if label and label in tk.labels else UNCLEAR_RULE
            plan.changes.append(TicketChange("refined_unclear", tk.key, tk.title, note=note))

    for epic, keys in unknown.items():
        plan.changes.append(TicketChange("unknown_epic", epic, new=keys))

    for key, prev in old.items():
        if key in seen:
            continue
        earmark = preplan.earmark_for(key)
        if earmark is not None and sprint_ended(earmark.sprint, fc):
            preplan.earmarks.remove(earmark)
            plan.changes.append(
                TicketChange(
                    "earmark_dropped", key, prev.title, old=earmark.sprint, note=DROPPED_ENDED
                )
            )
            earmark = None
        plan.changes.append(
            TicketChange("missing", key, prev.title, note=earmark.sprint if earmark else None)
        )
        if earmark is not None:
            plan.warnings.append(
                t(
                    "Ticket {key} ist nicht mehr im Import; die Vormerkung für Sprint {sprint} "
                    "bleibt bestehen",
                    key=key,
                    sprint=earmark.sprint,
                )
            )
        elif preplan.estimate_for(key) is not None:
            plan.warnings.append(
                t(
                    "Ticket {key} ist nicht mehr im Import; die eigene Schätzung bleibt bestehen",
                    key=key,
                )
            )

    # Earmarks of tickets that left an earlier import: nothing else drops them, so they go
    # once their sprint is over.
    for earmark in list(preplan.earmarks):
        if earmark.ticket in seen or earmark.ticket in old:
            continue
        if sprint_ended(earmark.sprint, fc):
            preplan.earmarks.remove(earmark)
            plan.changes.append(
                TicketChange(
                    "earmark_dropped", earmark.ticket, old=earmark.sprint, note=DROPPED_ENDED
                )
            )

    for cycle in find_cycles(plan.tickets):
        plan.warnings.append(
            t("Abhängigkeiten im Kreis: {cycle}", cycle=" → ".join([*cycle, cycle[0]]))
        )
    plan.changes.sort(key=lambda c: KINDS.index(c.kind))
    plan.preplan_changed = preplan != data.preplan
    return plan


def apply_import(
    repo: Repository, key: str, plan: TicketImportPlan, now: datetime | None = None
) -> list[Path]:
    """Writes tickets.yaml (time stamp ``now``, source of the plan) and, only when the
    reconciliation changed it, preplan.yaml."""
    paths = [repo.save_tickets(key, plan.tickets, now or datetime.now(), plan.source)]
    if plan.preplan_changed:
        paths.append(repo.save_preplan(key, plan.preplan))
    return paths
