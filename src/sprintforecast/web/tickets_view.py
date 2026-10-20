# SPDX-License-Identifier: EUPL-1.2
"""Page "Tickets" of the ticket pre-planning (docs/design/ticket-planning.md, section 8).

Filter over products and projects, project traffic light, timeline, sprint columns with
earmarks, refinement list, open points, import with preview and maintenance of projects and
manual estimates. The computation is ``preplan.distribute``; this module only selects and
displays. Loaded by ``ui.page_tickets`` only (``features.tickets``); the filter and the table
builders are pure functions so that tests need no browser."""

from __future__ import annotations

import copy
import tempfile
import textwrap
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st

from sprintforecast.calendar import following_sprint
from sprintforecast.forecast import Forecast, find_sprint
from sprintforecast.i18n import t
from sprintforecast.label_writeback import LabelPlan, apply_label_writes, plan_label_writes
from sprintforecast.model import (
    BudgetBasis,
    Earmark,
    EstimateSource,
    ManualEstimate,
    ProductValues,
    Project,
    Rule,
    Sprint,
)
from sprintforecast.preplan import (
    LIGHTS,
    REASONS,
    SOURCES,
    Distribution,
    HandoverRow,
    Variant,
    Variants,
    distribute_variants,
    handover_rows,
    project_range,
)
from sprintforecast.sources import RawTicket, SourceError, open_source
from sprintforecast.sources.csv import CsvSource
from sprintforecast.storage import DataError, Repository, TeamData, save_sprints_together
from sprintforecast.ticket_import import (
    DROPPED_ENDED,
    KINDS,
    UNCLEAR_NO_ESTIMATE,
    UNCLEAR_RULE,
    TicketChange,
    TicketImportPlan,
    apply_import,
    plan_import,
)
from sprintforecast.web.logic import with_sprints
from sprintforecast.web.ui import (
    _next_step,
    _saved_text,
    alt,
    page_intro,
    page_link,
    pd,
    save,
    today,
)

# Colour per traffic light; the text of the light is always shown as well (not colour alone).
LIGHT_COLOURS = {
    "on_track": "#2e9e5b",
    "tight": "#e0a800",
    "missed": "#d64545",
    "empty": "#9aa0a6",
}
LIGHT_SYMBOLS = {"on_track": "🟢", "tight": "🟡", "missed": "🔴", "empty": "⚪"}
# One letter per origin of an estimate on a ticket card (legend below the columns).
SOURCE_LETTERS = {
    EstimateSource.REFINED: "R",
    EstimateSource.ROUGH: "U",
    EstimateSource.MANUAL: "M",
    EstimateSource.NONE: "–",
}
# Sources of an assignment rule the maintenance table edits (other rules stay as they are).
EDITABLE_SOURCES = ("epic", "component", "label")
AUTOMATIC = ""
CARD_LIMIT = 30
IMPORT_LIMIT = 15


def exact(value: float | None) -> str:
    """A value as it is written (no rounding to one decimal)."""
    return "–" if value is None else f"{value:g}"


def fmt(value: float | None) -> str:
    if value is None:
        return "–"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


# --- Filter -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    """What the filter shows: the chosen projects and, separately, tickets without a project.
    It only hides; the distribution itself always runs on all tickets (the budget is shared)."""

    projects: frozenset[str]
    no_project: bool = True
    # All project ids; a ticket of an id outside it counts as "without project" (as in the
    # distribution). None = the chosen projects are all there are.
    known: frozenset[str] | None = None

    def shows(self, project: str | None) -> bool:
        if project is None or project not in (self.known or self.projects):
            return self.no_project
        return project in self.projects


def project_options(data: TeamData, products: set[str] | None) -> list[Project]:
    """The projects of the chosen products (None = no product filter)."""
    return [p for p in data.projects if products is None or p.product in products]


# --- Tables (pure) ----------------------------------------------------------------------------


def project_rows(
    data: TeamData, dist: Distribution, sel: Selection, variants: Variants | None = None
) -> list[dict[str, Any]]:
    """One row per shown project: target, sprints, traffic light and open points. With the
    range of ``variants`` the last sprint is shown per variant and the light as a range."""
    ranged = variants is not None and variants.available
    rows = []
    for status in dist.projects:
        project = data.project(status.project)
        if project is None or not sel.shows(project.id):
            continue
        light = f"{LIGHT_SYMBOLS[status.light]} {t(LIGHTS[status.light])}"
        last: dict[str, Any] = {t("Last sprint"): status.last_sprint or "–"}
        if ranged:
            assert variants is not None
            span = project_range(variants, status.project)
            if not span.uniform:
                best, worst = (t(LIGHTS[x]) for x in span.light_range)
                light += f" ({best} – {worst})"
            last = {
                t("Last sprint optimistic"): span.last_sprint[Variant.OPTIMISTIC] or "–",
                t("Last sprint median"): span.last_sprint[Variant.MEDIAN] or "–",
                t("Last sprint conservative"): span.last_sprint[Variant.CONSERVATIVE] or "–",
            }
        rows.append(
            {
                t("Project"): project.name,
                t("Product"): project.product or "–",
                t("Target"): project.target,
                t("Target sprint"): status.target_sprint or "–",
                **last,
                t("Traffic light"): light,
                t("Outstanding"): status.open_tickets,
                t("Not distributable"): status.not_distributable,
            }
        )
    return rows


def _bar_span(dist: Distribution, project_id: str, axis: list[str]) -> tuple[int, int] | None:
    """First and last column of a project's bar on ``axis`` (tickets after the horizon extend
    the bar to the end); None when no ticket of the project is placed."""
    own = [p for p in dist.placements if p.project == project_id and p.sprint is not None]
    positions = [axis.index(p.sprint) for p in own if p.sprint in axis]
    beyond = any(p.sprint in dist.later for p in own)
    if not positions and not beyond:
        return None
    first = min(positions) if positions else len(axis) - 1
    last = len(axis) - 1 if beyond else max(positions)
    return first, last


def timeline_range_rows(
    data: TeamData, variants: Variants, sel: Selection, axis: list[str]
) -> list[dict[str, Any]]:
    """The lighter area of the timeline: per project the sprints that lie within the bars of
    the optimistic or conservative variant but outside the median bar."""
    if not variants.available:
        return []
    rows: list[dict[str, Any]] = []
    for status in variants.median.projects:
        project = data.project(status.project)
        if project is None or not sel.shows(project.id):
            continue
        spans = [_bar_span(d, project.id, axis) for _, d in variants.items()]
        median = _bar_span(variants.median, project.id, axis)
        found = [x for x in spans if x is not None]
        if median is None or not found:
            continue
        first, last = min(x[0] for x in found), max(x[1] for x in found)
        for i in range(first, last + 1):
            if not median[0] <= i <= median[1]:
                rows.append(
                    {
                        t("Project"): project.name,
                        t("Sprint"): axis[i],
                        t("Traffic light"): t(LIGHTS[status.light]),
                    }
                )
    return rows


def timeline_rows(
    data: TeamData, dist: Distribution, sel: Selection, axis: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bars and target marks of the timeline over the sprints in ``axis``: per project one bar
    from the first to the last sprint of its tickets (tickets after the horizon extend the bar
    to the end), the target sprint as a mark."""
    bars: list[dict[str, Any]] = []
    marks: list[dict[str, Any]] = []
    for status in dist.projects:
        project = data.project(status.project)
        if project is None or not sel.shows(project.id):
            continue
        span = _bar_span(dist, project.id, axis)
        if span is None:
            continue
        first, last = span
        light = t(LIGHTS[status.light])
        for i in range(first, last + 1):
            bars.append(
                {
                    t("Project"): project.name,
                    t("Sprint"): axis[i],
                    t("Traffic light"): light,
                    "light": status.light,
                }
            )
        if status.target_sprint in axis:
            marks.append(
                {
                    t("Project"): project.name,
                    t("Sprint"): status.target_sprint,
                    t("Target"): f"{project.target:%d.%m.%Y}" if project.target else "–",
                }
            )
    return bars, marks


def sprint_fill(dist: Distribution, sprint: str) -> list[tuple[str | None, float, float]]:
    """``(product, budget, used)`` per product of a sprint."""
    return [(b.product, b.base, b.fixed + b.placed) for b in dist.budgets if b.sprint == sprint]


def refinement_rows(data: TeamData, dist: Distribution, sel: Selection) -> list[dict[str, Any]]:
    rows = []
    for item in dist.refinement:
        ticket = data.ticket(item.ticket)
        if ticket is None or not sel.shows(ticket.project):
            continue
        project = data.project(ticket.project) if ticket.project else None
        rows.append(
            {
                t("Sprint"): item.sprint,
                t("Latest by"): item.deadline,
                t("Ticket"): ticket.key,
                t("Title"): ticket.title,
                t("Project"): project.name if project else "–",
                t("Estimate"): t(SOURCES[item.source.value]),
                t("Refined status unclear"): item.unclear,
            }
        )
    return rows


def open_rows(data: TeamData, dist: Distribution, sel: Selection) -> list[dict[str, Any]]:
    rows = []
    for p in dist.not_distributable():
        ticket = data.ticket(p.ticket)
        if ticket is None or not sel.shows(ticket.project):
            continue
        project = data.project(ticket.project) if ticket.project else None
        rows.append(
            {
                t("Ticket"): ticket.key,
                t("Title"): ticket.title,
                t("Project"): project.name if project else "–",
                t("Reason"): t(REASONS[p.reason]),
            }
        )
    return rows


def change_note(change: TicketChange) -> str:
    """Readable text for the ``note`` of a change of the import preview."""
    note = change.note
    if not note:
        return ""
    if change.kind == "sprint_unresolved":
        return t('Sprint name "{name}"', name=note)
    if change.kind == "changed":
        return {"estimate": t("Estimate"), "remaining": t("Remaining")}.get(note, note)
    if change.kind == "refined_unclear":
        if note == UNCLEAR_RULE:
            return t("only via refined_also_if, label missing")
        if note == UNCLEAR_NO_ESTIMATE:
            return t("label without estimate")
    if change.kind == "earmark_dropped" and note == DROPPED_ENDED:
        return t("sprint ended")
    if change.kind == "missing":
        return t("earmark for sprint {sprint} stays", sprint=note)
    return note


def change_titles() -> dict[str, str]:
    return {
        "new": t("New tickets"),
        "changed": t("Changed numbers"),
        "done": t("Done"),
        "missing": t("No longer in the import"),
        "unassigned": t("Not assigned to a project yet"),
        "unknown_epic": t("Unknown epics (candidates for a new project)"),
        "refined_unclear": t("Refined status unclear"),
        "earmark_dropped": t("Earmark dropped"),
        "sprint_unresolved": t(
            "Sprint not recognised (map it under tracker.sprint_names in team.yaml)"
        ),
        "earmark_from_label": t("Earmark taken from the label planned_for_…"),
    }


def change_rows(plan: TicketImportPlan, kind: str) -> list[dict[str, str]]:
    def show(value: Any) -> str:
        return "–" if value in (None, [], "") else str(value)

    return [
        {
            t("Ticket"): c.key,
            t("Title"): c.title,
            t("before"): show(c.old),
            t("new"): show(c.new),
            t("Notice"): change_note(c),
        }
        for c in plan.of_kind(kind)
    ]


# --- Project rules in the maintenance table ---------------------------------------------------


def handover_sprints(data: TeamData, rows: list[HandoverRow], overwrite: bool) -> list[Sprint]:
    """The sprints to write for a handover to the PO pre-planning (``preplanned``): only the
    rows that write, a sprint that exists only in the calendar gets its file, and the sprint
    sequence stays gapless (the calendar-only sprints in between are created too), as the
    command ``tickets --handover`` does."""
    changed: dict[str, Sprint] = {}
    for row in rows:
        if not row.writes(overwrite):
            continue
        sprint = changed.get(row.sprint)
        if sprint is None:
            found = find_sprint(data, row.sprint)
            if found is None:
                continue
            sprint = copy.deepcopy(found)
        values = sprint.products.get(row.product, ProductValues())
        values.preplanned = row.proposed
        sprint.products[row.product] = values
        changed[row.sprint] = sprint
    pending = {sid for sid in changed if data.sprint(sid) is None}
    last = data.sprints[-1] if data.sprints else None
    while pending:
        last = following_sprint(data.team, last)
        pending.discard(last.id)
        if data.sprint(last.id) is None:
            changed.setdefault(last.id, last)
    return sorted(changed.values(), key=lambda x: x.start)


def editable_columns(rule: Rule | None) -> dict[str, list[str]] | None:
    """The values per source of a rule the table can show: no rule, one leaf or the short form
    of epic, component and label. None = the rule is more complex (stays untouched)."""
    if rule is None:
        return {}
    leaves = [rule] if rule.op == "leaf" else rule.children if rule.short else None
    if leaves is None or any(
        leaf.op != "leaf" or leaf.source not in EDITABLE_SOURCES for leaf in leaves
    ):
        return None
    return {leaf.source or "": list(leaf.values) for leaf in leaves}


def rule_from_columns(columns: dict[str, list[str]]) -> Rule | None:
    """The rule of the table values (short form for several sources)."""
    leaves = [Rule(source=s, values=columns[s]) for s in EDITABLE_SOURCES if columns.get(s)]
    if not leaves:
        return None
    return leaves[0] if len(leaves) == 1 else Rule(op="any", children=leaves, short=True)


def split_values(text: str | None) -> list[str]:
    return [v for part in (text or "").split(",") if (v := part.strip())]


def apply_project_rows(projects: list[Project], rows: list[tuple[Any, ...]]) -> list[Project]:
    """The projects with the values of the maintenance table: one row per project in the same
    order, columns ``id, name, product, target, priority, budget basis, epics, components,
    labels``. The id is never changed; a nested rule stays as it is."""
    result = []
    for project, row in zip(projects, rows, strict=True):
        _, name, product, target, priority, basis, *values = row
        match = project.match
        if editable_columns(project.match) is not None:
            match = rule_from_columns(
                {s: split_values(v) for s, v in zip(EDITABLE_SOURCES, values, strict=True)}
            )
        result.append(
            replace(
                project,
                name=project.name if _missing(name) else str(name).strip(),
                product=None if _missing(product) else str(product).strip() or None,
                target=_date(target),
                priority=0 if _missing(priority) else int(priority),
                budget_basis=None if _missing(basis) or not basis else BudgetBasis(basis),
                match=match,
            )
        )
    return result


def estimates_from_rows(rows: list[tuple[Any, ...]]) -> list[ManualEstimate]:
    """Manual estimates of the table rows ``ticket, estimate, note``; rows without a ticket
    are dropped. Raises ``ValueError`` when a ticket occurs twice."""
    result: dict[str, ManualEstimate] = {}
    for ticket, estimate, note in rows:
        if not isinstance(ticket, str) or not ticket:
            continue
        if ticket in result:
            raise ValueError(ticket)
        result[ticket] = ManualEstimate(
            ticket,
            None if _missing(estimate) else float(estimate),
            note.strip() or None if isinstance(note, str) else None,
        )
    return list(result.values())


def _missing(value: Any) -> bool:
    return value is None or bool(pd.isna(value))


def _date(value: Any) -> date | None:
    if _missing(value):
        return None
    return value.date() if hasattr(value, "date") else value


# --- Page -------------------------------------------------------------------------------------


def page(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Tickets"))
    if not data.team.features.tickets:
        st.info(
            t(
                "Ticket pre-planning is switched off. Switch it on under Team → Settings "
                '("Ticket pre-planning").'
            )
        )
        page_link("einstellungen")
        return
    page_intro(
        t(
            "Distribute tickets over future sprints and check whether the projects meet "
            "their target date. First import the tickets, then create projects with a "
            "target date."
        ),
        t(
            "The distribution is recalculated every time from tickets, projects and "
            "forecast; only projects, earmarks and own estimates are stored. The filter "
            "hides projects without changing the distribution: the budget of a sprint "
            "stays shared."
        ),
    )
    key = data.team.key
    variants = distribute_variants(data, today())
    dist = variants.median
    sel = _filter(data, key)
    tabs = st.tabs(
        [
            t("Overview"),
            t("Sprints"),
            t("Refinement"),
            t("Open points"),
            t("Import"),
            t("Maintenance"),
        ]
    )
    with tabs[0]:
        _overview(data, fc, dist, sel, variants)
    with tabs[1]:
        _sprint_columns(repo, data, dist, sel)
        _handover(repo, data, dist)
    with tabs[2]:
        _refinement(data, dist, sel)
    with tabs[3]:
        _open_points(data, dist, sel)
    with tabs[4]:
        _import(repo, data, fc)
        _label_section(data, fc)
    with tabs[5]:
        _projects_editor(repo, data)
        _estimates_editor(repo, data)


def _filter(data: TeamData, key: str) -> Selection:
    """Products and projects individually deselectable; applies to all parts of the page."""
    products: set[str] | None = None
    left, right = st.columns(2)
    if data.team.features.products and data.products:
        ids = [p.id for p in data.products]
        names = {p.id: p.name for p in data.products}
        chosen = left.multiselect(
            t("Products"),
            ids,
            default=ids,
            format_func=lambda i: names[i],
            key=f"tickets-{key}-products",
        )
        products = set(chosen)
    options = project_options(data, products)
    names = {p.id: p.name for p in options}
    shown = right.multiselect(
        t("Projects"),
        list(names),
        default=list(names),
        format_func=lambda i: names[i],
        key=f"tickets-{key}-projects-{'-'.join(sorted(names))}",
    )
    without = st.checkbox(
        t("Show tickets without a project"), value=True, key=f"tickets-{key}-none"
    )
    return Selection(frozenset(shown), without, frozenset(p.id for p in data.projects))


def _overview(
    data: TeamData, fc: Forecast, dist: Distribution, sel: Selection, variants: Variants
) -> None:
    if not data.tickets:
        st.info(t("No tickets yet. Read a CSV file from the ticket system on the **Import** tab."))
        return
    if dist.no_forecast:
        st.warning(
            t(
                "No budget yet: without past sprints with velocity there is no forecast, "
                "so the tickets cannot be distributed."
            )
        )
    for cycle in dist.cycles:
        st.error(f"{t('circular dependencies')}: {' → '.join([*cycle, cycle[0]])}")
    rows = project_rows(data, dist, sel, variants)
    if not rows:
        st.info(t("No project selected or created."))
        return
    if not variants.available:
        st.caption(
            t("No range: fewer than two sprints with velocity. Only the median variant is shown.")
        )
    st.subheader(t("Projects"))
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={t("Target"): st.column_config.DateColumn(format="DD.MM.YYYY")},
    )
    st.subheader(t("Timeline"))
    chart = _timeline_chart(data, fc, dist, sel, variants)
    if chart is None:
        st.caption(t("No distributed tickets in the selected projects yet."))
    else:
        st.altair_chart(chart, width="stretch")
        st.caption(
            t(
                "◆ Target sprint of the project. Colour and text show the traffic light; "
                "the lighter area is the range of the optimistic to conservative variant."
            )
        )


def _timeline_chart(
    data: TeamData, fc: Forecast, dist: Distribution, sel: Selection, variants: Variants
) -> alt.Chart | None:
    axis = ([fc.current.sprint.id] if fc.current is not None else []) + dist.sprints
    bars, marks = timeline_rows(data, dist, sel, axis)
    if not bars:
        return None
    project, sprint, light = t("Project"), t("Sprint"), t("Traffic light")
    order = list(dict.fromkeys(b[project] for b in bars))
    texts = [t(LIGHTS[k]) for k in LIGHTS]
    scale = alt.Scale(domain=texts, range=[LIGHT_COLOURS[k] for k in LIGHTS])
    chart = (
        alt.Chart(pd.DataFrame(bars))
        .mark_rect(height=18)
        .encode(
            x=alt.X(f"{sprint}:N", sort=axis),
            y=alt.Y(f"{project}:N", sort=order, title=None),
            color=alt.Color(f"{light}:N", scale=scale),
            tooltip=[f"{project}:N", f"{sprint}:N", f"{light}:N"],
        )
    )
    spread = timeline_range_rows(data, variants, sel, axis)
    if spread:
        # Drawn first, so the median bars stay on top.
        chart = (
            alt.Chart(pd.DataFrame(spread))
            .mark_rect(height=18, opacity=0.3)
            .encode(
                x=alt.X(f"{sprint}:N", sort=axis),
                y=alt.Y(f"{project}:N", sort=order, title=None),
                color=alt.Color(f"{light}:N", scale=scale, legend=None),
                tooltip=[f"{project}:N", f"{sprint}:N"],
            )
        ) + chart
    if marks:
        target = t("Target")
        chart += (
            alt.Chart(pd.DataFrame(marks))
            .mark_point(
                shape="diamond",
                size=140,
                filled=True,
                color="#ffffff",
                stroke="#333333",
                strokeWidth=1.5,
            )
            .encode(
                x=alt.X(f"{sprint}:N", sort=axis),
                y=alt.Y(f"{project}:N", sort=order),
                tooltip=[f"{project}:N", f"{target}:N"],
            )
        )
    return chart


def _sprint_columns(repo: Repository, data: TeamData, dist: Distribution, sel: Selection) -> None:
    key = data.team.key
    if not dist.sprints:
        st.info(t("No future sprints in the period."))
        return
    count = int(
        st.number_input(
            t("Number of sprints"),
            min_value=1,
            max_value=len(dist.sprints),
            value=min(4, len(dist.sprints)),
            key=f"tickets-{key}-sprints",
        )
    )
    for start in range(0, count, 4):
        chunk = dist.sprints[start : min(start + 4, count)]
        for column, sprint in zip(st.columns(len(chunk)), chunk, strict=True):
            with column:
                _sprint_column(data, dist, sel, sprint)
    st.caption(
        t(
            "R = refined · U = rough estimate (unrefined) · M = own estimate · **bold** = "
            "sprint according to the ticket system (fixed) · ✎ = earmark"
        )
    )
    _earmark_form(repo, data, dist, sel)


def _handover(repo: Repository, data: TeamData, dist: Distribution) -> None:
    """Hands the sums of the placed tickets per sprint and product (median variant) over to the
    PO pre-planning: preview first, written after the confirmation; a value already entered
    stays unless the box to replace it is ticked."""
    if not data.team.features.products or not data.products:
        return
    key = data.team.key
    st.divider()
    st.subheader(t("Handover to the PO pre-planning"))
    st.caption(
        t(
            "The sums of the distributed tickets per sprint and product (median variant) "
            "as the PO's pre-planning. Only values that are not entered yet are written; "
            "values already entered stay unless replacing is chosen."
        )
    )
    count = int(
        st.number_input(
            t("Number of sprints"),
            min_value=1,
            max_value=max(len(dist.sprints), 1),
            value=min(6, max(len(dist.sprints), 1)),
            key=f"tickets-{key}-handover-count",
        )
    )
    overwrite = st.checkbox(
        t("Replace pre-planning the PO already entered"), key=f"tickets-{key}-handover-overwrite"
    )
    if dist.no_forecast:
        st.warning(
            t(
                "No budget yet: without past sprints with velocity there is no forecast, "
                "so the tickets cannot be distributed."
            )
        )
    rows = handover_rows(data, dist, count)
    if not rows:
        st.info(t("Nothing to hand over: no ticket is distributed in the sprints shown."))
        return
    names = {p.id: p.name for p in data.products}
    notes = {
        "write": t("new"),
        "same": t("unchanged"),
        "keep": t("PO value stays"),
        "overwrite": t("will be replaced"),
    }
    st.dataframe(
        pd.DataFrame(
            [
                {
                    t("Sprint"): r.sprint,
                    t("Product"): names.get(r.product, r.product),
                    t("So far"): exact(r.current),
                    t("Proposal"): exact(r.proposed),
                    t("Notice"): notes[r.action(overwrite)],
                }
                for r in rows
            ]
        ),
        hide_index=True,
    )
    to_save = handover_sprints(data, rows, overwrite)
    if not any(r.writes(overwrite) for r in rows):
        st.caption(t("Nothing to write: the PO pre-planning is already in place."))
        return
    if st.button(
        t("Adopt into the PO pre-planning"), type="primary", key=f"tickets-{key}-handover"
    ):
        after = with_sprints(data, to_save)
        ids = [x.id for x in after.sprints]
        saved = {x.id for x in to_save}
        checked = saved | {ids[i + 1] for i, sid in enumerate(ids[:-1]) if sid in saved}
        if save(
            after,
            [f"{sid}.yaml" for sid in checked],
            lambda: save_sprints_together(repo, key, to_save),
            flash=True,
        ):
            st.rerun()


def _sprint_column(data: TeamData, dist: Distribution, sel: Selection, sprint: str) -> None:
    st.markdown(f"**{sprint}**")
    for product, budget, used in sprint_fill(dist, sprint):
        name = next((p.name for p in data.products if p.id == product), None)
        prefix = f"{name}: " if name and len(data.products) > 1 else ""
        st.caption(
            t(
                "{prefix}Budget {budget} · used {used} · free {free}",
                prefix=prefix,
                budget=fmt(budget),
                used=fmt(used),
                free=fmt(budget - used),
            )
        )
        st.progress(min(1.0, used / budget) if budget > 0 else 0.0)
    shown = [p for p in dist.in_sprint(sprint) if sel.shows(p.project)]
    for p in shown[:CARD_LIMIT]:
        ticket = data.ticket(p.ticket)
        project = data.project(p.project) if p.project else None
        title = textwrap.shorten(ticket.title if ticket else "", 38, placeholder="…")
        name = f"**{p.ticket}**" if p.reason == "fixed_sprint" else p.ticket
        mark = " ✎" if p.reason == "earmark" else ""
        with st.container(border=True):
            st.markdown(f"{name} {title}")
            st.caption(
                f"{fmt(p.size)} {SOURCE_LETTERS[p.source]}{mark} · "
                f"{project.name if project else t(REASONS['no_project'])}"
            )
    if len(shown) > CARD_LIMIT:
        st.caption(t("… and {count} more", count=len(shown) - CARD_LIMIT))


def _earmark_form(repo: Repository, data: TeamData, dist: Distribution, sel: Selection) -> None:
    """Reserve a ticket for a sprint or release it again (back to the automatic distribution)."""
    key = data.team.key
    st.subheader(t("Earmark and release"))
    candidates = [tk for tk in data.tickets if not tk.done and sel.shows(tk.project)]
    if not candidates:
        st.caption(t("No tickets to earmark."))
        return
    titles = {
        tk.key: f"{tk.key} {textwrap.shorten(tk.title, 50, placeholder='…')}" for tk in candidates
    }
    chosen = st.selectbox(
        t("Ticket"),
        list(titles),
        format_func=lambda k: titles[k],
        key=f"tickets-{key}-earmark-ticket",
    )
    if chosen is None:
        return
    placement = dist.placement(chosen)
    if placement is not None and placement.reason == "fixed_sprint":
        st.info(
            t(
                (
                    "{key} is in sprint {sprint} according to the ticket system and cannot be "
                    "moved here."
                ),
                key=chosen,
                sprint=placement.sprint,
            )
        )
        return
    earmark = data.preplan.earmark_for(chosen)
    options = [AUTOMATIC, *dist.sprints]
    if earmark is not None and earmark.sprint not in options:
        options.append(earmark.sprint)
    where = (
        t("Earmarked for sprint {sprint}.", sprint=earmark.sprint)
        if earmark
        else t("Not earmarked: {state}.", state=t(REASONS[placement.reason]) if placement else "–")
    )
    st.caption(where)
    sprint = st.selectbox(
        t("Sprint"),
        options,
        index=options.index(earmark.sprint) if earmark else 0,
        format_func=lambda s: t("distribute automatically (release)") if s == AUTOMATIC else s,
        key=f"tickets-{key}-earmark-sprint-{chosen}",
    )
    note = st.text_input(
        t("Note"),
        value=earmark.note or "" if earmark else "",
        key=f"tickets-{key}-earmark-note-{chosen}",
    )
    current = (earmark.sprint, earmark.note or "") if earmark else (AUTOMATIC, "")
    changed = (sprint, note.strip() if sprint != AUTOMATIC else "") != current
    label = t("Release") if sprint == AUTOMATIC else t("Earmark")
    if not st.button(label, type="primary", disabled=not changed, key=f"tickets-{key}-earmark-go"):
        return
    after = copy.deepcopy(data)
    after.preplan.earmarks = [e for e in after.preplan.earmarks if e.ticket != chosen]
    if sprint != AUTOMATIC:
        after.preplan.earmarks.append(Earmark(chosen, sprint, note.strip() or None))
    if save(after, ["preplan.yaml"], lambda: [repo.save_preplan(key, after.preplan)], flash=True):
        st.rerun()


def _refinement(data: TeamData, dist: Distribution, sel: Selection) -> None:
    st.caption(
        t(
            "Tickets with a rough or own estimate, per sprint they are in. They have to be "
            "refined by the planning of the sprint."
        )
    )
    unclear = [data.ticket(k) for k in dist.unclear]
    unclear = [tk for tk in unclear if tk is not None and sel.shows(tk.project)]
    if unclear:
        st.warning(
            t(
                "Refined status unclear (counts as rough): {keys}",
                keys=", ".join(tk.key for tk in unclear),
            )
        )
    rows = refinement_rows(data, dist, sel)
    if not rows:
        st.info(t("Nothing to refine."))
        return
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={t("Latest by"): st.column_config.DateColumn(format="DD.MM.YYYY")},
    )


def _open_points(data: TeamData, dist: Distribution, sel: Selection) -> None:
    rows = open_rows(data, dist, sel)
    if not rows:
        st.info(t("All tickets are distributed."))
        return
    st.caption(
        t(
            "These tickets cannot be distributed. Enter an own estimate under "
            "**Maintenance**; split tickets that are too large in the ticket system."
        )
    )
    st.dataframe(pd.DataFrame(rows), hide_index=True)


# --- Import -----------------------------------------------------------------------------------


def _import(repo: Repository, data: TeamData, fc: Forecast) -> None:
    key = data.team.key
    counter = f"tickets-{key}-import-n"
    st.markdown(
        t(
            "Reads the tickets from Jira or from the CSV export of the advanced Jira "
            "search. It first shows what would change; nothing is written until you "
            "confirm."
        )
    )
    fetched = f"tickets-{key}-fetched"
    if data.team.tracker.kind == "jira":
        if st.button(
            t("Read tickets from Jira"),
            icon=":material/cloud_download:",
            key=f"tickets-{key}-fetch",
        ):
            st.session_state.pop(fetched, None)
            if result := _fetch_jira(data):
                st.session_state[fetched] = result
        st.caption(t("Or read a CSV file (without network access):"))
    upload = st.file_uploader(
        t("CSV file"), type=["csv"], key=f"tickets-{key}-file-{st.session_state.get(counter, 0)}"
    )
    if upload is None:
        if fetched in st.session_state:
            raws, name = st.session_state[fetched]
            _import_preview(repo, data, fc, raws, name, counter, fetched)
        return
    name = Path(upload.name).name
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(upload.getvalue())
        try:
            raws = CsvSource(path, data.team.tracker.fields).fetch()
        except SourceError as e:
            st.error(str(e).replace(str(path), name))  # not the temporary path
            return
    _import_preview(repo, data, fc, raws, name, counter, fetched)


def _label_signature(plan: LabelPlan) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    return [(w.key, tuple(w.add), tuple(w.remove)) for w in plan.writes]


def _plan_labels(data: TeamData, fc: Forecast, source: Any) -> LabelPlan:
    """Reads the tickets fresh (the labels must be current) and plans the label changes against
    the earmarks, as the command ``tickets --write-labels`` does."""
    raws = source.fetch()
    if not raws:
        raise SourceError(
            t(
                "The query returned no tickets – nothing written. Check the JQL "
                "(tracker.query) and the permissions of the token."
            )
        )
    import_plan = plan_import(data, fc, raws, today(), adopt_labels=False)
    return plan_label_writes(import_plan.tickets, import_plan.preplan)


def _label_section(data: TeamData, fc: Forecast) -> None:
    """Write-back of the earmarks as the Jira label ``planned_for_<sprint_id>``: preview first,
    written only after a second click, and only the changes of the preview."""
    tracker = data.team.tracker
    if tracker.kind != "jira" or not tracker.write_labels:
        return
    key = data.team.key
    stored = f"tickets-{key}-labelplan"
    st.divider()
    st.subheader(t("Write earmarks to Jira as labels"))
    st.caption(
        t(
            "Each earmark corresponds to the label planned_for_<sprint> on the ticket; an "
            "outdated label is removed. Tickets in a real sprint get none. The preview "
            "comes first; nothing is written until you confirm."
        )
    )
    if st.button(t("Check label changes"), key=f"tickets-{key}-labels-plan"):
        st.session_state.pop(stored, None)
        source = None
        try:
            source = open_source(tracker)
            with st.spinner(t("Reading Jira …")):
                st.session_state[stored] = _plan_labels(data, fc, source)
        except SourceError as e:
            st.error(str(e))
        finally:
            _close(source)
    plan = st.session_state.get(stored)
    if plan is None:
        return
    for warning in plan.warnings:
        st.warning(warning)
    if not plan.writes:
        st.info(t("No label changes needed."))
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    t("Ticket"): w.key,
                    t("Title"): w.title,
                    t("Add label"): ", ".join(w.add) or "–",
                    t("Remove label"): ", ".join(w.remove) or "–",
                }
                for w in plan.writes
            ]
        ),
        hide_index=True,
    )
    if not st.button(t("Write to Jira"), type="primary", key=f"tickets-{key}-labels-write"):
        return
    source = None
    try:
        source = open_source(tracker)
        with st.spinner(t("Reading Jira …")):
            fresh = _plan_labels(data, fc, source)
        if _label_signature(fresh) != _label_signature(plan):
            # Jira changed since the preview: show the new one instead of writing the old one.
            st.session_state[stored] = fresh
            st.session_state["flash"] = [
                (
                    "warning",
                    t("The state in Jira changed since the preview - please check again."),
                )
            ]
            st.rerun()
        written = apply_label_writes(source, fresh)
    except SourceError as e:
        # What was written before the failure is in Jira now: the preview is out of date.
        st.session_state.pop(stored, None)
        st.error(str(e))
        return
    finally:
        _close(source)
    st.session_state.pop(stored, None)
    st.session_state["flash"] = [
        (
            "success",
            t(
                (
                    '{count} tickets changed in Jira. Then "Read tickets from Jira" to adopt '
                    "the state."
                ),
                count=written,
            ),
        )
    ]
    st.rerun()


def _close(source: Any) -> None:
    if source is not None and hasattr(source, "close"):
        source.close()


def _fetch_jira(data: TeamData) -> tuple[list[RawTicket], str] | None:
    """Reads the tickets of the Jira query (token from the environment or the keychain); shows
    the error and returns None when that fails. An empty result never replaces the last import."""
    source = None
    try:
        source = open_source(data.team.tracker)
        with st.spinner(t("Reading Jira …")):
            raws = source.fetch()
    except SourceError as e:
        st.error(str(e))
        return None
    finally:
        _close(source)
    if not raws and data.tickets:
        st.error(
            t(
                "The query returned no tickets – nothing written. Check the JQL "
                "(tracker.query) and the permissions of the token."
            )
        )
        return None
    return raws, str(source.name)


def _import_preview(
    repo: Repository,
    data: TeamData,
    fc: Forecast,
    raws: list[RawTicket],
    source: str,
    counter: str,
    fetched: str | None = None,
) -> None:
    """Preview and apply for tickets of any source (a CSV upload or the tracker)."""
    key = data.team.key
    plan = plan_import(data, fc, raws, today(), source=source)
    titles = change_titles()
    for kind in KINDS:
        rows = change_rows(plan, kind)
        if not rows:
            continue
        with st.expander(f"{titles[kind]} ({len(rows)})", expanded=kind in ("new", "unassigned")):
            st.dataframe(pd.DataFrame(rows[:IMPORT_LIMIT]), hide_index=True)
            if len(rows) > IMPORT_LIMIT:
                st.caption(t("… and {count} more", count=len(rows) - IMPORT_LIMIT))
    for warning in plan.warnings:
        st.warning(warning)
    if plan.unchanged(data):
        st.info(t("No changes compared to the existing files."))
        return
    if not st.button(t("Apply changes"), type="primary", key=f"tickets-{key}-apply"):
        return
    step = _next_step()
    try:
        paths = apply_import(repo, key, plan)
    except (DataError, OSError) as e:
        st.error(str(e))
        return
    st.session_state["flash"] = [("success", _saved_text(", ".join(p.name for p in paths), step))]
    st.session_state[counter] = st.session_state.get(counter, 0) + 1  # empties the upload
    if fetched:
        st.session_state.pop(fetched, None)
    st.rerun()


# --- Maintenance ------------------------------------------------------------------------------


def _projects_editor(repo: Repository, data: TeamData) -> None:
    key = data.team.key
    st.subheader(t("Projects"))
    st.caption(
        t(
            "A project is an undertaking of the PO with a target date, not a Jira project. "
            "Tickets are assigned by epics, components or labels (comma-separated); the "
            "order of precedence is in team.yaml (tracker.project_match_order)."
        )
    )
    products = [p.id for p in data.products] if data.team.features.products else []
    id_, name, product, target = (t("Id"), t("Name"), t("Product"), t("Target"))
    priority, basis = t("Priority"), t("Budget basis")
    columns = {"epic": t("Epics"), "component": t("Components"), "label": t("Labels")}
    complex_ids = []
    rows = []
    for p in data.projects:
        values = editable_columns(p.match)
        if values is None:
            complex_ids.append(p.id)
            values = {}
        rows.append(
            {
                id_: p.id,
                name: p.name,
                product: p.product or "",
                target: p.target,
                priority: p.priority,
                basis: p.budget_basis.value if p.budget_basis else "",
                **{columns[s]: ", ".join(values.get(s, [])) for s in EDITABLE_SOURCES},
            }
        )
    if rows:
        config: dict[str, Any] = {
            id_: st.column_config.TextColumn(disabled=True),
            target: st.column_config.DateColumn(format="DD.MM.YYYY"),
            priority: st.column_config.NumberColumn(min_value=0, step=1),
            basis: st.column_config.SelectboxColumn(
                options=["", *(b.value for b in BudgetBasis)],
                help=t("Empty = the team's setting (tracker.budget_basis)."),
            ),
        }
        if products:
            config[product] = st.column_config.SelectboxColumn(options=["", *products])
        edited = st.data_editor(
            pd.DataFrame(rows), hide_index=True, column_config=config, key=f"tickets-{key}-projects"
        )
        for pid in complex_ids:
            st.caption(
                t(
                    (
                        "The assignment rule of {id} is nested and can only be changed in "
                        "projects.yaml."
                    ),
                    id=pid,
                )
            )
        if st.button(t("Save projects"), type="primary", key=f"tickets-{key}-projects-save"):
            after = copy.deepcopy(data)
            after.projects = apply_project_rows(
                after.projects, [tuple(row) for row in edited.itertuples(index=False)]
            )
            _save_projects(repo, data, after)
    _add_project_form(repo, data, products)
    if data.projects:
        _remove_project_form(repo, data)


def _save_projects(repo: Repository, data: TeamData, after: Any) -> None:
    if save(
        after,
        ["projects.yaml"],
        lambda: [repo.save_projects(data.team.key, after.projects)],
        flash=True,
    ):
        st.rerun()


def _add_project_form(repo: Repository, data: TeamData, products: list[str]) -> None:
    key = data.team.key
    with (
        st.expander(t("Create project"), icon=":material/add:"),
        st.form(f"tickets-{key}-add-project", clear_on_submit=True),
    ):
        left, right = st.columns(2)
        new_id = left.text_input(t("Id"), help=t("Short key, e.g. payment-v2."))
        new_name = right.text_input(t("Name"))
        product = left.selectbox(t("Product"), ["", *products]) if products else ""
        target = right.date_input(t("Target"), value=None, format="DD.MM.YYYY")
        epics = left.text_input(t("Epics"))
        labels = right.text_input(t("Labels"))
        components = left.text_input(t("Components"))
        if not st.form_submit_button(t("Create project"), type="primary"):
            return
    new_id = new_id.strip()
    if not new_id or not new_name.strip():
        st.error(t("Id and name are required."))
        return
    if data.project(new_id) is not None:
        st.error(t("A project with the id {id} already exists.", id=new_id))
        return
    after = copy.deepcopy(data)
    after.projects.append(
        Project(
            id=new_id,
            name=new_name.strip(),
            product=product or None,
            target=target,
            match=rule_from_columns(
                {
                    "epic": split_values(epics),
                    "label": split_values(labels),
                    "component": split_values(components),
                }
            ),
        )
    )
    _save_projects(repo, data, after)


def _remove_project_form(repo: Repository, data: TeamData) -> None:
    key = data.team.key
    with st.expander(t("Remove project"), icon=":material/delete:"):
        names = {p.id: p.name for p in data.projects}
        chosen = st.selectbox(
            t("Project"), list(names), format_func=lambda i: names[i], key=f"tickets-{key}-rm"
        )
        count = sum(1 for tk in data.tickets if tk.project == chosen)
        st.caption(
            t(
                (
                    '{count} tickets currently belong to it; afterwards they are "without '
                    'project" until the next import assigns them again.'
                ),
                count=count,
            )
        )
        if st.button(t("Remove project"), key=f"tickets-{key}-rm-go"):
            after = copy.deepcopy(data)
            after.projects = [p for p in after.projects if p.id != chosen]
            for tk in after.tickets:  # tickets.yaml must not name a project that is gone
                if tk.project == chosen:
                    tk.project = None
                tk.project_candidates = [c for c in tk.project_candidates if c != chosen]
            key_ = data.team.key
            if save(
                after,
                ["projects.yaml", "tickets.yaml"],
                lambda: [
                    repo.save_projects(key_, after.projects),
                    repo.save_tickets(
                        key_, after.tickets, data.tickets_imported, data.tickets_source
                    ),
                ],
                flash=True,
            ):
                st.rerun()


def _estimates_editor(repo: Repository, data: TeamData) -> None:
    key = data.team.key
    st.subheader(t("Own estimates"))
    st.caption(
        t(
            "For tickets without an estimate in the ticket system. The number applies only "
            "here and is not overwritten by the next import."
        )
    )
    ticket, estimate, note = t("Ticket"), t("Estimate"), t("Note")
    keys = [tk.key for tk in data.tickets if not tk.done]
    known = {e.ticket for e in data.preplan.estimates}
    options = keys + sorted(known - set(keys))
    frame = pd.DataFrame(
        [
            {ticket: e.ticket, estimate: e.estimate, note: e.note or ""}
            for e in data.preplan.estimates
        ],
        columns=[ticket, estimate, note],
    )
    edited = st.data_editor(
        frame,
        hide_index=True,
        num_rows="dynamic",
        key=f"tickets-{key}-estimates",
        column_config={
            ticket: st.column_config.SelectboxColumn(options=options, required=True),
            estimate: st.column_config.NumberColumn(min_value=0.0, step=0.5),
        },
    )
    if not st.button(t("Save estimates"), type="primary", key=f"tickets-{key}-est-save"):
        return
    after = copy.deepcopy(data)
    try:
        after.preplan.estimates = estimates_from_rows(
            [tuple(row) for row in edited.itertuples(index=False)]
        )
    except ValueError:
        st.error(t("Each ticket only once."))
        return
    if save(after, ["preplan.yaml"], lambda: [repo.save_preplan(key, after.preplan)], flash=True):
        st.rerun()
