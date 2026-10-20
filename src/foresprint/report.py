# SPDX-License-Identifier: EUPL-1.2
"""Markdown report (rendered by GitHub/GitLab, including the Mermaid chart)."""

from __future__ import annotations

from foresprint.analysis import MIN_SAMPLES, average_focus_factor, band, buffer_hint
from foresprint.capacity import AbsenceHistory
from foresprint.engine import UNSURE_SOURCES, CapacitySource, round_half_up
from foresprint.forecast import Forecast, TimelineEntry
from foresprint.git import blank_controls, md_code
from foresprint.i18n import is_english, t
from foresprint.model import AbsenceState, Sprint, absence_status


def fmt(value: float | None, digits: int = 1, suffix: str = "") -> str:
    """Number with the thousands and decimal separators of the language (1.234,5 or 1,234.5)."""
    if value is None:
        return "–"
    text = f"{value:,.{digits}f}"
    if not is_english():
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return text + suffix


def fmt_capacity(value: float | None, digits: int = 1) -> str:
    """Capacity for display, rounded half up (from .5 up) like ``rounded`` and the frozen
    value. Python's formatting rounds an exact half to the even digit (25.25 → "25.2") and must
    not be used directly for capacities. The forecast keeps calculating with the unrounded
    value.

    ``digits`` is the team's ``capacity.rounding`` setting (default 1), the same as in
    ``CapacityBreakdown.rounded``: display and frozen value then also agree with a different
    number of decimal places. Callers with a team or sprint pass it
    (``TimelineEntry.capacity_digits``, ``CapacityBreakdown.rounding``)."""
    return "–" if value is None else fmt(round_half_up(value, digits), digits)


def pct(value: float | None) -> str:
    return "–" if value is None else fmt(value * 100, 0, " %")


def period(e: TimelineEntry) -> str:
    return f"{e.sprint.start:%d.%m.} – {e.sprint.end:%d.%m.%Y}"


def source_label(source: CapacitySource | None) -> str:
    return t(source.value) if source else ""


def capacity_source_note(e: TimelineEntry, warning: str = "⚠️ ") -> str:
    """Source of the capacity alone (without the number), for metrics whose value should not be
    shortened by an appended text; with the ``warning`` prefix for an uncertain source (the web
    UI passes none: no emojis there), empty without a source."""
    source = e.result.plan_capacity_source
    if source in UNSURE_SOURCES:
        return f"{warning}{source_label(source)}"
    return source_label(source)


def capacity_label(e: TimelineEntry) -> str:
    """Capacity with the source appended, as one text (tables, reports, command line)."""
    source = e.result.plan_capacity_source
    value = fmt_capacity(e.result.plan_capacity, e.capacity_digits)
    if source in UNSURE_SOURCES:
        return f"{value} {capacity_source_note(e)}"
    return f"{value} ({capacity_source_note(e)})" if source else value


def band_range(fc: Forecast, e: TimelineEntry) -> str:
    """The range of a future sprint as "low–high" for tables ("–" if it cannot be calculated or
    the sprint is already completed)."""
    from foresprint.analysis import band

    b = band(fc, e) if e.sprint.end > fc.today else None
    return f"{fmt(b.low)}–{fmt(b.high)}" if b else "–"


def band_note(fc: Forecast, e: TimelineEntry, without_assumption: bool = False) -> str:
    """Range with the sample size as a sentence right at a forecast tile; with a hint if there
    is little data. Empty if the range cannot be calculated or the sprint is already completed
    (the range belongs to today's history, the forecast of an old sprint does not).
    ``without_assumption``: the forecast next to it calculates with an assumption, the range
    does not."""
    from foresprint.analysis import band, few_samples

    b = band(fc, e) if e.sprint.end > fc.today else None
    if b is None:
        return ""
    note = t(
        "Range {low}–{high} from the last {samples} sprints",
        low=fmt(b.low),
        high=fmt(b.high),
        samples=b.samples,
    )
    if without_assumption:
        note = f"{note} ({t('without the assumption')})"
    return f"{note} · {t('little data, rough hint')}" if few_samples(fc) else note


def absence_status_label(sprint: Sprint) -> str:
    """State of a sprint's absences in words."""
    return {
        AbsenceState.CONFIRMED: t("confirmed"),
        AbsenceState.EXPECTED: t("announced"),
        AbsenceState.UNKNOWN: t("unknown"),
    }[absence_status(sprint)]


def absence_derived_note(
    history: AbsenceHistory | None,
    detailed: bool = False,
    code: bool = True,
    window: int = 0,
) -> str | None:
    """Hint that the expected absence rate is uncertain: sprints that count as confirmed only
    from other fields (older files without a stored state) and have no absences count as
    "0 % lost" and pull the rate down. The numbers stay unchanged. None if no such sprint goes
    into the rate.

    The sprint IDs come from files and are shown in code notation (``md_code``) so that they
    change nothing in Markdown (``code=False`` for tables, plain text and the command line,
    there with ``sprint_text``). ``detailed`` adds what to do."""
    if history is None or not history.derived:
        return None
    count = len(history.derived)
    sprints = ", ".join(md_code(i) if code else sprint_text(i) for i in history.derived)
    if count == 1:
        note = t(
            (
                "Rate uncertain: {count} sprint in the expected absence rate ({sprints}) only "
                "counts as confirmed because it has already been planned or reviewed; no "
                'absences are saved, so the rate assumes "0 % lost". The estimated capacity '
                "of future sprints may be too high."
            ),
            count=count,
            sprints=sprints,
        )
    else:
        note = t(
            (
                "Rate uncertain: {count} sprints in the expected absence rate ({sprints}) only "
                "count as confirmed because they have already been planned or reviewed; no "
                'absences are saved, so the rate assumes "0 % lost". The estimated capacity '
                "of future sprints may be too high."
            ),
            count=count,
            sprints=sprints,
        )
    return note + " " + absence_derived_remedy(window) if detailed else note


def sprint_text(sprint_id: str) -> str:
    """Sprint ID for plain text without Markdown (table, command line): control characters and
    text direction characters become spaces, as with ``md_code``."""
    return blank_controls(sprint_id)


def absence_derived_hint(history: AbsenceHistory | None) -> str | None:
    """Short pointer for pages that show only the estimated capacity (without the list of
    sprints; that is on the absences page, in the calculation path, in the report)."""
    if history is None or not history.derived:
        return None
    page = t("Prepare the sprint: absences")
    if len(history.derived) == 1:
        return t(
            (
                "Rate uncertain: no absences are saved for {count} sprint in the rate. Details "
                'on the "{page}" page.'
            ),
            count=1,
            page=page,
        )
    return t(
        (
            "Rate uncertain: no absences are saved for {count} sprints in the rate. Details on "
            'the "{page}" page.'
        ),
        count=len(history.derived),
        page=page,
    )


def absence_derived_remedy(window: int) -> str:
    """What to do about an uncertain absence rate (without sprint IDs). ``window`` is the
    ``absence_history`` setting: how long the hint stays."""
    return t(
        (
            "If someone was absent in one of these sprints, enter the absences on the "
            '"{page}" page and save them with "Save absences" (or with `foresprint '
            'absences`). If nobody was absent, the rate is correct. In the "Absence status" '
            "table these sprints count as confirmed because they have already been planned or "
            "reviewed; but no absences are saved. The note stays until the sprints drop out of "
            "the window of the last {window} sprints (setting `absence_history`) or absences "
            "are entered."
        ),
        page=t("Prepare the sprint: absences"),
        window=window,
    )


def absence_derived_cli_remedy(window: int, team: str) -> str:
    """Like :func:`absence_derived_remedy`, for the command line: the command instead of the
    web UI steps, without Markdown."""
    return t(
        (
            "If someone was absent in one of these sprints, add the absences with: "
            "foresprint absences {team} <SPRINT>. If nobody was absent, the rate is "
            "correct. The note stays until the sprints drop out of the window of the last "
            "{window} sprints (setting absence_history) or absences are entered."
        ),
        team=team,
        window=window,
    )


def reliability_notes(fc: Forecast, code: bool = True) -> list[str]:
    """Hints on the reliability of the forecast (command line and report). ``code=False`` for
    the command line: sprint IDs without Markdown backticks, plus the command to add them
    later."""
    from foresprint.model import TrendMode

    notes = []
    estimated = any(
        e.result.plan_capacity_source is CapacitySource.ESTIMATED for e in fc.upcoming()
    )
    if estimated and (note := absence_derived_note(fc.absences, code=code)):
        if not code:
            team = fc.data.team
            note += " " + absence_derived_cli_remedy(team.capacity.absence_history, team.key)
        notes.append(note)
    if note := few_samples_note(fc):
        notes.append(note)
    mode = fc.data.team.forecast.trend_mode
    if any(e.result.trend_fallback for e in fc.upcoming()):
        notes.append(
            t(
                (
                    "Thin history: the history is not enough for trend mode {mode}, “constant” "
                    "(last average) applies."
                ),
                mode=mode.value,
            )
        )
    if mode is not TrendMode.FLAT:
        notes.append(
            t(
                (
                    "Trend mode {mode}: extrapolates fluctuations and can rise or fall "
                    "(caution with long horizons). “Constant” (flat) is robust – set with "
                    "`foresprint settings`."
                ),
                mode=mode.value,
            )
        )
    return notes


def few_samples_note(fc: Forecast) -> str | None:
    """Warning "Little data" of the forecast (command line, report and web UI): the sample of
    range and simulation (``sample_count``, capped at the window) is below ``MIN_SAMPLES``. If
    the window caps it, the sentence names both numbers (sample and all recorded values) and
    explains the window. ``None`` without values or from the threshold on."""
    from foresprint.analysis import available_count, sample_count

    samples = sample_count(fc)
    if not samples or samples >= MIN_SAMPLES:
        return None
    available = available_count(fc)
    if available > samples:
        note = t(
            (
                "Little data: the range draws from only {samples} of the {available} recorded "
                "sprints with velocity (from {min} on, the range is more reliable). Plan and "
                "range are rough hints."
            ),
            samples=samples,
            available=available,
            min=MIN_SAMPLES,
        )
    else:
        note = t(
            (
                "Little data: so far only {samples} sprints with velocity (from {min} on, the "
                "range is more reliable). Plan and range are rough hints."
            ),
            samples=samples,
            min=MIN_SAMPLES,
        )
    hint = window_hint(fc.data.team.forecast.window, samples, available)
    return f"{note} {hint}" if hint else note


def window_hint(window: int, samples: int, available: int, simulation: bool = False) -> str:
    """Addition to "Little data" when the forecast window below ``MIN_SAMPLES`` actually caps
    the sample (``available`` recorded values, ``samples`` of them in the calculation): the
    sample can then never reach the threshold. Otherwise empty, even if there are simply no
    more values. ``simulation``: the hint is attached to the completion simulation's warning."""
    if window >= MIN_SAMPLES or available <= samples:
        return ""
    if simulation:
        return t(
            (
                "The forecast window is set to {window} sprints; with a larger window "
                "(settings) more values go into the range and the simulation."
            ),
            window=window,
        )
    return t(
        (
            "The forecast window is set to {window} sprints; with a larger window (settings) "
            "more values go into the range."
        ),
        window=window,
    )


def completion_note(samples: int) -> str | None:
    """Warning of the completion simulation for little data (command line and web UI)."""
    if samples >= MIN_SAMPLES:
        return None
    return t(
        (
            "Little data: the simulation draws from only {samples} sprints (from {min} on, "
            "statements are more reliable). The frequencies are rough hints."
        ),
        samples=samples,
        min=MIN_SAMPLES,
    )


def status(fc: Forecast, e: TimelineEntry) -> str:
    if e.sprint.end <= fc.today:
        return t("finished")
    if e.sprint.start <= fc.today:
        return f"**{t('running')}**"
    return t("planned")


def render(fc: Forecast, history: int = 10) -> str:
    team = fc.data.team
    unit = team.unit.value
    f = team.forecast
    lines = [
        f"# Sprint-Forecast {team.name}",
        "",
        t(
            (
                "As of: {today} · unit: {unit} · reference capacity: {ref} PT · Ø over "
                "{window} sprints · trend: `{mode}`"
            ),
            today=f"{fc.today:%d.%m.%Y}",
            unit=unit,
            ref=fmt(f.reference_capacity, 0),
            window=f.window,
            mode=f.trend_mode.value,
        ),
        "",
        t("> Generated automatically with `foresprint report`. Do not edit by hand."),
        "",
        f"## {t('Projection')}",
        "",
        "| Sprint | "
        + t(
            (
                "Period | Status | Capacity (PT) | norm. velocity trend | **Forecast PLAN** "
                "({unit}) | Range | Plannable ({share}) | Small items |"
            ),
            unit=unit,
            share=pct(f.roadmap_share),
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    upcoming = fc.upcoming()
    for e in upcoming:
        r = e.result
        lines.append(
            f"| {e.sprint.id} | {period(e)} | {status(fc, e)} | {capacity_label(e)} "
            f"| {fmt(r.normalized_velocity.trend, 2)} | **{fmt(r.plan)}** "
            f"| {band_range(fc, e)} | {fmt(r.roadmap, 2)} | {fmt(r.small_stuff, 2)} |"
        )
    if any(e.result.plan_capacity_source in UNSURE_SOURCES for e in upcoming):
        lines += [
            "",
            t(
                (
                    "⚠️ *Trend/calendar*: no absences are recorded for this sprint yet, the "
                    "capacity is estimated. `foresprint absences {team} <SPRINT>` makes "
                    "the forecast reliable."
                ),
                team=team.key,
            ),
        ]

    for note in reliability_notes(fc):
        lines += ["", f"⚠️ {note}"]

    current = fc.current
    if current and current.result.planning_total is not None:
        r = current.result
        lines += [
            "",
            t(
                (
                    "**Planning {id}:** total {total} {unit}, delta to the Forecast PLAN "
                    "{delta} {unit}"
                ),
                id=current.sprint.id,
                total=fmt(r.planning_total, 2),
                delta=fmt(r.planning_delta, 2),
                unit=unit,
            ),
        ]

    past = fc.history(history)
    lines += [
        "",
        t("## History (last {count} sprints)", count=len(past)),
        "",
        "| Sprint | "
        + t(
            "Capacity (PT) | Commitment | Velocity | norm. velocity | Ø norm. velocity | "
            "Fulfillment | Scope creep |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in past:
        r = e.result
        lines.append(
            f"| {e.sprint.id} | {fmt_capacity(r.capacity.value, e.capacity_digits)} "
            f"| {fmt(r.commitment.value, 2)} "
            f"| {fmt(r.velocity.value, 2)} | {fmt(r.normalized_velocity.value, 2)} "
            f"| {fmt(r.normalized_velocity.average, 2)} | {pct(r.fulfillment.value)} "
            f"| {pct(r.scope_creep.value)} |"
        )

    chart = past + [e for e in upcoming if e not in past]
    if len(chart) >= 2:

        def series(values: list[float | None]) -> str:
            return "[" + ", ".join("0" if v is None else f"{v:.2f}" for v in values) + "]"

        lines += [
            "",
            f"## {t('Chart')}",
            "",
            t(
                "Lines: commitment (past) or Forecast PLAN (future), velocity and "
                "normalized velocity (past: actual value, future: trend)."
            ),
            "",
            "```mermaid",
            "xychart-beta",
            f"    x-axis [{', '.join(f'"{e.sprint.id}"' for e in chart)}]",
            f'    y-axis "{unit}"',
            "    line " + series([e.result.commitment.value or e.result.plan for e in chart]),
            "    line "
            + series([e.result.velocity.value or e.result.velocity.trend for e in chart]),
            "    line "
            + series(
                [
                    e.result.normalized_velocity.value or e.result.normalized_velocity.trend
                    for e in chart
                ]
            ),
            "```",
        ]
    lines += _products_section(fc)
    lines += _tickets_section(fc)
    lines += _analysis_section(fc)
    return "\n".join(lines) + "\n"


def _tickets_section(fc: Forecast, sprints: int = 6) -> list[str]:
    """Ticket pre-planning: project traffic light and the next sprints (only with
    ``features.tickets`` and imported tickets)."""
    data = fc.data
    if not data.team.features.tickets or not data.tickets:
        return []
    from foresprint.preplan import LIGHTS, distribute

    dist = distribute(data, fc.today)
    lines = ["", f"## {t('Tickets')}"]
    if dist.projects:
        lines += [
            "",
            f"| {t('Project')} | {t('Target')} | {t('Target sprint')} | {t('Last sprint')} "
            f"| {t('Traffic light')} | {t('Outstanding')} | {t('Not distributable')} |",
            "|---|---|---|---|---|---|---|",
        ]
        for status in dist.projects:
            project = data.project(status.project)
            name = project.name if project else status.project
            target = f"{project.target:%d.%m.%Y}" if project and project.target else "–"
            lines.append(
                f"| {name} | {target} | {status.target_sprint or '–'} "
                f"| {status.last_sprint or '–'} | {t(LIGHTS[status.light])} "
                f"| {status.open_tickets} | {status.not_distributable} |"
            )
    if dist.sprints[:sprints]:
        unit = data.team.unit.value
        lines += [
            "",
            f"| Sprint | {t('Budget')} ({unit}) | {t('Used')} | {t('Free')} | {t('Tickets')} |",
            "|---|---|---|---|---|",
        ]
        for sprint_id in dist.sprints[:sprints]:
            cells = [b for b in dist.budgets if b.sprint == sprint_id]
            base = sum(b.base for b in cells)
            used = sum(b.fixed + b.placed for b in cells)
            count = len(dist.in_sprint(sprint_id))
            lines.append(
                f"| {sprint_id} | {fmt(base)} | {fmt(used)} | {fmt(base - used)} | {count} |"
            )
    refine = len(dist.refinement)
    open_points = len(dist.not_distributable())
    if refine or open_points:
        lines += [
            "",
            t(
                "{refine} tickets still have to be refined, {open} cannot be distributed.",
                refine=refine,
                open=open_points,
            ),
        ]
    return lines


def _analysis_section(fc: Forecast) -> list[str]:
    """Supplementary analyses (range, focus factor, buffer) at the end of the report."""
    unit = fc.data.team.unit.value
    rows = [(e, b) for e in fc.upcoming() if (b := band(fc, e)) is not None]
    lines: list[str] = []
    if rows:
        lines += [
            "",
            t("## Additionally: range"),
            "",
            t(
                (
                    "Forecast with the lowest, median and highest normalized velocity of the "
                    "last {count} sprints (instead of the trend)."
                ),
                count=rows[0][1].samples,
            ),
            "",
            t(
                "| Sprint | Forecast PLAN ({unit}) | conservative | median | optimistic |",
                unit=unit,
            ),
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {e.sprint.id} | {fmt(e.result.plan)} | {fmt(b.low)} | {fmt(b.mid)} "
            f"| {fmt(b.high)} |"
            for e, b in rows
        ]
    focus = average_focus_factor(fc)
    hint = buffer_hint(fc)
    facts = []
    if focus is not None:
        facts.append(t("Ø focus factor (velocity / capacity): {value}", value=fmt(focus, 2)))
    if hint.average_scope_creep is not None:
        facts.append(
            t(
                (
                    "Ø scope creep ({count} sprints): {scope} of the commitment = {late} of "
                    "the Forecast PLAN · small-items share: {small}"
                ),
                count=hint.samples,
                scope=pct(hint.average_scope_creep),
                late=pct(hint.average_late_share),
                small=pct(hint.configured_small_stuff),
            )
            + (t(" ⚠️ buffer smaller than the unplanned share") if hint.buffer_too_small else "")
        )
    if facts:
        lines += ["", *[f"- {f}" for f in facts]]
    return lines


def _products_section(fc: Forecast, history: int = 6) -> list[str]:
    """Distribution per product: current and next sprint, balance of the last sprints."""
    from foresprint.products import (
        MEASURES,
        balance,
        distribution,
        measure_label,
        missing_footnote,
    )

    if not fc.data.products:
        return []
    unit = fc.data.team.unit.value
    lines = ["", f"## {t('Products')}"]
    shown = []
    for e in (fc.current, fc.default_entry("planning")):
        if e is not None and e not in shown:
            shown.append(e)
    for e in shown:
        d = distribution(fc, e)
        if not d.rows:
            continue
        lines += [
            "",
            f"**Sprint {e.sprint.id}** ({status(fc, e).replace('*', '')})",
            "",
            f"| {t('Product')} | PO | "
            + " | ".join(f"{measure_label(m)} ({unit})" for m in MEASURES)
            + " |",
            "|---|---|" + "---|" * len(MEASURES),
        ]
        lines += [
            f"| {r.product.name} | {r.product.po or ''} | "
            + " | ".join(fmt(r.value(m), 2) for m in MEASURES)
            + " |"
            for r in d.rows
        ]
    # only products with at least one value (as in the web UI)
    rows = [b for b in balance(fc, fc.history(history)) if b.sprints]
    if rows:
        with_missing = any(b.missing for b in rows)
        header = t("| Product | Sprints | Σ standard | Σ done | Balance ({unit}) |", unit=unit)
        lines += [
            "",
            t("**Balance** (Σ done − Σ standard, last {count} sprints)", count=history),
            "",
            header + (f" {t('no value')} |" if with_missing else ""),
            "|---|---|---|---|---|" + ("---|" if with_missing else ""),
        ]
        lines += [
            f"| {b.product.name} | {b.sprints} | {fmt(b.standard, 2)} | {fmt(b.done, 2)} "
            f"| {fmt(b.difference, 2)} |" + (f" {b.missing} |" if with_missing else "")
            for b in rows
        ]
        if with_missing:
            lines += ["", f"*{missing_footnote()}*"]
    return lines
