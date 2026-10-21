# SPDX-License-Identifier: EUPL-1.2
"""Consistency: the same metric must have the same value everywhere.

The calculation core (``build_forecast``) is the source of truth. Compared are the report
(FORECAST.md), command line, formula calculation paths, product distribution and the web UI
pages for every future Sprint, including Sprints without a file (trend) and those with a
file (people list).
"""

import re
from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from foresprint.analysis import band
from foresprint.capacity import sprint_capacity
from foresprint.cli import app as cli_app
from foresprint.engine import CapacitySource, round_down
from foresprint.forecast import build_forecast
from foresprint.formulas import capacity_step, plain_explanation, step, steps
from foresprint.i18n import t
from foresprint.model import AbsenceState
from foresprint.products import distribution
from foresprint.report import (
    absence_status_label,
    capacity_label,
    fmt,
    fmt_capacity,
    render,
)
from foresprint.storage import AS_OF_ENV, DATA_ENV, Repository

TODAY = date(2026, 10, 15)
APP = Path(__file__).parent.parent / "src" / "foresprint" / "web" / "app.py"


def num(text: str) -> float:
    """'10,1 PT', '9,0', '25,5 (Personenliste)' → number."""
    match = re.search(r"-?\d+(?:[.,]\d+)?", text)
    assert match, text
    return float(match.group().replace(",", "."))


@pytest.fixture
def fc(data_dir: Path):
    return build_forecast(Repository(data_dir).load("demo"), TODAY)


def open_app(data_dir: Path, monkeypatch: pytest.MonkeyPatch, today: str = "2026-10-15") -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, today)
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


@pytest.fixture
def web(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    return open_app(data_dir, monkeypatch)


def page(at: AppTest, key: str) -> AppTest:
    at.switch_page(f"page_scripts/{key}.py").run()
    assert not at.exception, at.exception
    return at


def upcoming_ids(fc) -> list[str]:
    return [e.sprint.id for e in fc.upcoming()]


# --- Calculation core ↔ report ↔ command line ↔ calculation path ----------------------------------


def test_internal_identities_hold(fc):
    """Roadmap + small items = Forecast PLAN; plan = floor(trend / reference × capacity)."""
    ref = fc.data.team.forecast.reference_capacity
    for e in fc.upcoming():
        r = e.result
        assert r.roadmap + r.small_stuff == pytest.approx(r.plan)
        if r.normalized_velocity.trend is not None and r.plan_capacity is not None:
            exact = r.normalized_velocity.trend / ref * r.plan_capacity
            assert r.plan <= exact + 1e-9 < r.plan + 10**-fc.data.team.forecast.rounding


def test_report_table_matches_engine(fc):
    rows = {}
    for line in render(fc).splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| 20") and len(cells) == 9:  # forecast table
            rows[cells[0]] = cells
    assert set(rows) == set(upcoming_ids(fc))
    for e in fc.upcoming():
        cells = rows[e.sprint.id]
        assert num(cells[3]) == pytest.approx(num(half_up(e.result.plan_capacity)))
        assert cells[4] == fmt(e.result.normalized_velocity.trend, 2)
        assert cells[5].strip("*") == fmt(e.result.plan)
        b = band(fc, e)
        assert cells[6] == (f"{fmt(b.low)}–{fmt(b.high)}" if b else "–")
        assert cells[7] == fmt(e.result.roadmap, 2)
        assert cells[8] == fmt(e.result.small_stuff, 2)


def test_report_history_matches_engine(fc):
    rows = {}
    for line in render(fc).splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| 20") and len(cells) == 8:
            rows[cells[0]] = cells
    assert rows
    for e in fc.history(10):
        cells = rows[e.sprint.id]
        r = e.result
        assert cells[1] == half_up(r.capacity.value)
        assert cells[3] == fmt(r.velocity.value, 2)
        assert cells[4] == fmt(r.normalized_velocity.value, 2)


def test_cli_forecast_shows_engine_values(data_dir: Path, fc):
    result = CliRunner(env={"COLUMNS": "260"}).invoke(
        cli_app, ["--data", str(data_dir), "--as-of", "2026-10-15", "forecast", "demo"]
    )
    assert result.exit_code == 0, result.output
    lines = {
        sid: next(line for line in result.output.splitlines() if sid in line)
        for sid in upcoming_ids(fc)
    }
    for e in fc.upcoming():
        line = lines[e.sprint.id]
        assert fmt(e.result.plan) in line, line
        assert fmt(e.result.normalized_velocity.trend, 2) in line, line


def test_formula_steps_reproduce_the_numbers(fc):
    for e in fc.upcoming():
        by_key = {s.key: s for s in steps(fc, e)}
        r = e.result
        assert fmt(r.plan) in by_key["plan"].calculation
        assert fmt(r.roadmap, 2) in by_key["roadmap"].calculation
        assert fmt(r.small_stuff, 2) in by_key["small_stuff"].calculation
        assert half_up(r.plan_capacity) in by_key["capacity"].calculation


# --- Product distribution -------------------------------------------------------------------


def test_distribution_adds_up_to_available(fc):
    for e in fc.upcoming():
        d = distribution(fc, e)
        if d.available is None or not d.active_count:
            continue
        assert d.total("standard") == pytest.approx(d.available)
        basis = d.plan if d.basis.value == "plan" else d.plan * fc.data.team.forecast.roadmap_share
        assert d.available == pytest.approx(basis)
        if e.sprint.forecast_plan is None:
            assert d.plan == e.result.plan


def test_fixed_share_distribution_adds_up(data_dir: Path):
    data = Repository(data_dir).load("demo")
    data.products[1].share = 0.1
    fc = build_forecast(data, TODAY)
    for e in fc.upcoming():
        d = distribution(fc, e)
        if d.available is not None and d.active_count:
            assert d.total("standard") == pytest.approx(d.available)


# --- Web UI -----------------------------------------------------------------------


def test_forecast_page_matches_engine(web: AppTest, fc):
    page(web, "forecast")
    tiles = {m.label.split(" ")[0]: m.value for m in web.metric if m.label[:4] == "2026"}
    table = next(d.value for d in web.dataframe if "Verplanbar" in d.value.columns)
    for e in fc.upcoming():
        r = e.result
        sid = e.sprint.id
        assert num(tiles[sid]) == pytest.approx(num(fmt(r.plan)))
        row = table[table["Sprint"] == sid].iloc[0]
        assert row["Prognose aktuell (PT)"] == fmt(r.plan)
        assert row["Verplanbar"] == fmt(r.roadmap, 2)
        assert row["Kleinkram"] == fmt(r.small_stuff, 2)
        assert row["n. Velocity-Trend"] == fmt(r.normalized_velocity.trend, 2)
        assert row["Fehltage"] == absence_status_label(e.sprint)
        assert row["Kapazität (PT)"] == capacity_label(e)


@pytest.mark.parametrize("sprint", ["2026.21", "2026.22", "2026.23", "2026.24"])
def test_planning_preplanning_products_and_analysis_agree(web: AppTest, fc, sprint: str):
    expected = fc.entry(sprint).result.plan

    page(web, "preplanning")
    web.selectbox(key="preplanning-sprint").set_value(sprint).run()
    assert not web.exception, web.exception
    headline = next(m for m in web.metric if m.label == f"Prognose aktuell {sprint}")
    available = next(m for m in web.metric if m.label == "Verteilbar")
    assert num(headline.value) == pytest.approx(expected)
    assert num(available.value) == pytest.approx(expected, abs=0.051)
    standard = [
        num(row["Standard"])
        for d in web.dataframe
        if "Differenz" in d.value.columns
        for _, row in d.value.iterrows()
    ]
    assert sum(standard) == pytest.approx(expected, abs=0.1)

    page(web, "products")
    web.selectbox(key="products-sprint").set_value(sprint).run()
    assert not web.exception, web.exception
    assert any(fmt(expected, 2) in c.value for c in web.caption), [c.value for c in web.caption]


def test_planning_page_shows_engine_plan(web: AppTest, fc):
    """Planning page step 2: Forecast PLAN as in the calculation core (Sprint without absences
    confirmation unchanged, likewise with a saved file)."""
    sprint = "2026.22"
    page(web, "planning")
    web.selectbox(key="planning-sprint").set_value(sprint).run()
    web.button(key=f"planning-step-{1}").click().run()
    assert not web.exception, web.exception
    tile = next(m for m in web.metric if m.label.startswith("Prognose aktuell"))
    assert num(tile.value) == pytest.approx(fc.entry(sprint).result.plan)


def test_analysis_band_uses_the_same_plan(web: AppTest, fc):
    page(web, "analysis")
    table = next(d.value for d in web.dataframe if "konservativ" in d.value.columns)
    for e in fc.upcoming():
        row = table[table["Sprint"] == e.sprint.id].iloc[0]
        assert row.iloc[1] == fmt(e.result.plan)
        b = band(fc, e)
        if b is not None:
            assert row["mittel"] == fmt(b.mid)


def test_absences_page_preview_matches_engine(web: AppTest, fc):
    """Capacity (with source), absences status and Forecast PLAN of the preview = calculation
    core, for all Sprints, including Sprints with unknown absences."""
    from foresprint.report import absence_status_label, capacity_label

    page(web, "absences")
    table = next(d.value for d in web.dataframe if "Kapazität (PT)" in d.value.columns)
    assert len(table) >= 4
    for _, row in table.iterrows():
        entry = fc.entry(row["Sprint"])
        assert row["Kapazität (PT)"] == capacity_label(entry)
        assert row["Fehltage"] == absence_status_label(entry.sprint)
        assert num(row["Forecast PLAN (PT)"]) == pytest.approx(entry.result.plan)


def test_history_table_matches_engine(web: AppTest, fc):
    page(web, "forecast")
    table = next(d.value for d in web.dataframe if "Ø n. Velocity" in d.value.columns)
    for e in fc.history(10):
        row = table[table["Sprint"] == e.sprint.id].iloc[0]
        assert row["n. Velocity"] == fmt(e.result.normalized_velocity.value, 2)
        assert row["Ø n. Velocity"] == fmt(e.result.normalized_velocity.average, 2)


def test_review_defaults_to_computed_capacity(web: AppTest, data_dir: Path):
    """The prefilled available person days in the Review = capacity from the people list,
    rounded the way it is frozen (A14: unrounded internally, ``rounded`` for storage)."""
    data = Repository(data_dir).load("demo")
    sprint = data.sprint("2026.21")
    expected = sprint.capacity if sprint.capacity is not None else None
    if expected is None:
        expected = sprint_capacity(data.team, data.people, sprint).rounded
    page(web, "review")
    web.selectbox(key="review-sprint").set_value("2026.21").run()
    assert web.number_input(key="capacity-2026.21").value == pytest.approx(expected)


# --- Capacity at the rounding boundary (A14) ----------------------------------------------------
#
# Ben is absent 3.5 instead of 3 days: the capacity of 2026.21 is 25.25, exactly half.
# Python's formatting would give "25,2" (even digit); rounded half up, "25,3" applies
# everywhere. The forecast, however, calculates with 25.25. The expectations are written out
# as text or come from ``half_up`` (independent of ``fmt_capacity``), not from the formatter
# under test.

BORDER = "2026.21"
BORDER_LABEL = "25,3 (Personenliste)"
LATER = "2026-11-20"  # reference date on which 2026.21 is over (past tables)


def half_up(value: float, digits: int = 1) -> str:
    """Oracle: rounded half up, with decimal comma (via Decimal, without thousands separator)."""
    rounded = Decimal(repr(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f"{rounded:.{digits}f}".replace(".", ",")


def with_absences(data_dir: Path, sprint: str, **absences: float) -> Path:
    repo = Repository(data_dir)
    data = repo.load("demo")
    target = data.sprint(sprint)
    target.absences.update(absences)
    repo.save_sprint("demo", target)
    return data_dir


def with_recorded_capacity(data_dir: Path, sprint: str, capacity: float) -> Path:
    repo = Repository(data_dir)
    target = repo.load("demo").sprint(sprint)
    target.capacity = capacity
    repo.save_sprint("demo", target)
    return data_dir


def with_capacity_settings(data_dir: Path, **settings: float) -> Path:
    repo = Repository(data_dir)
    team = repo.load("demo").team
    for name, value in settings.items():
        setattr(team.capacity, name, value)
    repo.save_team(team)
    return data_dir


def cli(data_dir: Path, *args: str, today: str = "2026-10-15", input: str | None = None) -> str:
    runner = CliRunner(env={"COLUMNS": "260"})
    base = ["--data", str(data_dir), "--as-of", today]
    result = runner.invoke(cli_app, [*base, *args], input=input)
    assert result.exit_code == 0, result.output
    return result.output


def table_cells(text: str, first: str) -> list[str]:
    """Cells of the first table row (Rich or Markdown) whose first cell starts with
    ``first``."""
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"[|│┃]", line.strip())][1:-1]
        if cells and cells[0].startswith(first):
            return cells
    raise AssertionError(f"Zeile {first!r} fehlt in:\n{text}")


def sprint_file(data_dir: Path, sprint: str) -> dict:
    return yaml.safe_load((data_dir / "demo" / "sprints" / f"{sprint}.yaml").read_text("utf-8"))


def history_capacity(at: AppTest, sprint: str) -> str:
    """Capacity in the history table of the forecast page."""
    table = next(d.value for d in at.dataframe if "Ø n. Velocity" in d.value.columns)
    return table[table["Sprint"] == sprint].iloc[0]["Kapazität (PT)"]


@pytest.fixture
def border_dir(data_dir: Path) -> Path:
    return with_absences(data_dir, BORDER, ben=3.5)


@pytest.fixture
def border_fc(border_dir: Path):
    return build_forecast(Repository(border_dir).load("demo"), TODAY)


@pytest.fixture
def border_web(border_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    return open_app(border_dir, monkeypatch)


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [
        (25.25, 1, "25,3"),
        (25.2499, 1, "25,2"),
        (25.35, 1, "25,4"),
        (30.0, 1, "30,0"),
        (5.05, 1, "5,1"),
        (25.25, 0, "25"),
        (25.5, 0, "26"),
        (25.25, 2, "25,25"),
    ],
)
def test_fmt_capacity_rounds_half_up(value: float, digits: int, expected: str):
    assert fmt_capacity(value, digits) == expected
    assert half_up(value, digits) == expected  # the oracle itself
    assert fmt_capacity(None) == "–"
    assert fmt_capacity(1234.25) == "1.234,3"


def test_border_capacity_is_exactly_half(border_dir: Path, border_fc):
    r = border_fc.entry(BORDER).result
    assert r.plan_capacity == pytest.approx(25.25)  # unrounded internally
    # Python's formatting rounds to the even digit: that was the inconsistent display.
    assert fmt(r.plan_capacity) == "25,2"
    data = Repository(border_dir).load("demo")
    breakdown = sprint_capacity(data.team, data.people, data.sprint(BORDER))
    assert breakdown.rounded == 25.3  # prefill in the Review and frozen value


def test_border_capacity_is_displayed_alike_in_report_cli_and_steps(border_dir: Path, border_fc):
    e = border_fc.entry(BORDER)
    assert capacity_label(e) == BORDER_LABEL

    assert table_cells(render(border_fc), BORDER)[3] == BORDER_LABEL

    calculation = next(s for s in steps(border_fc, e) if s.key == "capacity").calculation
    assert calculation.endswith("= 25,25 → 25,3 PT (gerundet)")
    assert "stehen 25,3 PT zur Verfügung" in plain_explanation(border_fc, e)

    assert table_cells(cli(border_dir, "forecast", "demo"), BORDER)[3] == BORDER_LABEL
    panel = cli(border_dir, "forecast", "demo", "--explain", BORDER)
    assert "→ 25,3 PT" in panel and "→ 25,2 PT" not in panel
    assert "stehen 25,3 PT zur Verfügung" in panel


def test_capacity_table_rounds_every_row_like_the_sum(border_dir: Path):
    """Person rows and total are in one table: Ben (10 − 3.5) × 0.5 = 3.25 → 3.3."""
    out = cli(border_dir, "capacity", "demo", BORDER)
    shown = {name: table_cells(out, name)[-1] for name in ("Anna", "Ben", "Cem", "Dana", "Summe")}
    assert shown == {"Anna": "10,0", "Ben": "3,3", "Cem": "5,0", "Dana": "7,0", "Summe": "25,3"}


def test_capacity_table_rounds_the_share_deduction_like_the_sum(data_dir: Path):
    """Gross 22.5, deduction 50% = 11.25 → 11.3; Dana 4.25 → 4.3 (Python showed 11.2 and 4.2)."""
    with_absences(data_dir, BORDER, ben=3.5, cem=5, dana=5.75)
    with_capacity_settings(data_dir, overhead_share=0.5)
    out = cli(data_dir, "capacity", "demo", BORDER)
    assert table_cells(out, "Dana")[-1] == "4,3"
    assert table_cells(out, "Abzug")[-1] == "−11,3"
    assert table_cells(out, "Summe")[-1] == "11,3"


def test_capacity_table_rounds_the_fixed_deduction_like_the_sum(border_dir: Path):
    """The fixed deduction is capped at the person's capacity: Σ = 25.25 → 25.3, remainder 0."""
    with_capacity_settings(border_dir, overhead_days=100.0)
    out = cli(border_dir, "capacity", "demo", BORDER)
    assert table_cells(out, "Abzug")[-1] == "−25,3"
    assert table_cells(out, "Summe")[-1] == "0,0"


def test_border_capacity_review_in_cli_freezes_half_up(border_dir: Path):
    out = cli(border_dir, "review", "demo", BORDER, input="y\n9,5\n0.1\nn\n")
    assert "25,3 PT" in out and "25,2" not in out
    assert sprint_file(border_dir, BORDER)["capacity"] == 25.3


def test_border_capacity_in_web_pages_and_frozen_value(
    border_web: AppTest, border_dir: Path, border_fc
):
    page(border_web, "forecast")
    table = next(d.value for d in border_web.dataframe if "Verplanbar" in d.value.columns)
    assert table[table["Sprint"] == BORDER].iloc[0]["Kapazität (PT)"] == BORDER_LABEL
    assert any(f"Kapazität {BORDER_LABEL} PT" in c.value for c in border_web.caption)

    page(border_web, "absences")
    absences = next(d.value for d in border_web.dataframe if "Kapazität (PT)" in d.value.columns)
    assert absences[absences["Sprint"] == BORDER].iloc[0]["Kapazität (PT)"] == BORDER_LABEL

    page(border_web, "planning")
    border_web.selectbox(key="planning-sprint").set_value(BORDER).run()
    for step_index in (0, 1):  # absences, Forecast PLAN
        border_web.button(key=f"planning-step-{step_index}").click().run()
        assert not border_web.exception, border_web.exception
        tile = next(m for m in border_web.metric if m.label == "Kapazität (PT)")
        assert tile.value == "25,3", step_index

    page(border_web, "review")
    border_web.selectbox(key="review-sprint").set_value(BORDER).run()
    field = border_web.number_input(key=f"capacity-{BORDER}")
    assert field.value == pytest.approx(25.3)
    assert "25,3 PT" in field.help and "25,2" not in field.help
    border_web.number_input(key=f"velocity-{BORDER}").set_value(9.25)
    next(b for b in border_web.button if b.label == "Review speichern").click().run()
    assert not border_web.exception, border_web.exception
    assert sprint_file(border_dir, BORDER)["capacity"] == 25.3


def test_border_capacity_in_the_announcement_for_the_next_sprint(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Absences page: "fit into the next sprint … (capacity …)". 2026.22 with Ben 3.5: 28.25."""
    with_absences(data_dir, "2026.22", ben=3.5)
    at = page(open_app(data_dir, monkeypatch), "absences")
    assert any("(Kapazität 28,3 PT)" in m.value for m in at.markdown), [
        m.value for m in at.markdown
    ]


# --- Past Sprints, recorded capacity ---------------------------------------------------


def test_border_capacity_in_past_sprint_tables(border_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """2026.21 is over and not frozen: the capacity comes from the people list."""
    fc = build_forecast(Repository(border_dir).load("demo"), date.fromisoformat(LATER))
    assert fc.entry(BORDER) in fc.history()
    assert fc.entry(BORDER).result.capacity.value == pytest.approx(25.25)
    assert table_cells(render(fc), BORDER)[1] == "25,3"  # report, history
    assert table_cells(cli(border_dir, "forecast", "demo", today=LATER), BORDER)[3] == "25,3"
    at = page(open_app(border_dir, monkeypatch, today=LATER), "forecast")
    assert history_capacity(at, BORDER) == "25,3"


@pytest.fixture
def recorded_dir(data_dir: Path) -> Path:
    """Capacity 25.25 in the sprint file; the people list would give 25.5."""
    return with_recorded_capacity(data_dir, BORDER, 25.25)


def test_recorded_capacity_is_displayed_half_up(recorded_dir: Path):
    fc = build_forecast(Repository(recorded_dir).load("demo"), TODAY)
    e = fc.entry(BORDER)
    assert e.result.plan_capacity_source is CapacitySource.RECORDED
    assert e.result.plan_capacity == pytest.approx(25.25)
    assert capacity_label(e) == "25,3 (erfasst)"
    assert next(s for s in steps(fc, e) if s.key == "capacity").calculation == "= 25,3 PT"
    assert "stehen 25,3 PT zur Verfügung" in plain_explanation(fc, e)
    assert table_cells(render(fc), BORDER)[3] == "25,3 (erfasst)"
    assert table_cells(cli(recorded_dir, "forecast", "demo"), BORDER)[3] == "25,3 (erfasst)"
    out = cli(recorded_dir, "capacity", "demo", BORDER)
    assert "In der Sprintdatei eingetragen/eingefroren: 25,3 PT" in out


def test_recorded_capacity_in_past_sprint_tables(
    recorded_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    fc = build_forecast(Repository(recorded_dir).load("demo"), date.fromisoformat(LATER))
    assert table_cells(render(fc), BORDER)[1] == "25,3"
    assert table_cells(cli(recorded_dir, "forecast", "demo", today=LATER), BORDER)[3] == "25,3"
    at = page(open_app(recorded_dir, monkeypatch, today=LATER), "forecast")
    assert history_capacity(at, BORDER) == "25,3"


def test_recorded_capacity_in_the_planning_hint(recorded_dir: Path, monkeypatch):
    at = page(open_app(recorded_dir, monkeypatch), "planning")
    at.selectbox(key="planning-sprint").set_value(BORDER).run()
    at.button(key=f"planning-step-{0}").click().run()
    assert not at.exception, at.exception
    assert any("feste Kapazität (25,3 PT)" in i.value for i in at.info), [i.value for i in at.info]


def test_recorded_capacity_in_the_cli_absences_prompt(recorded_dir: Path):
    out = cli(recorded_dir, "absences", "demo", BORDER, input="0\n0\n0\n0\nn\n")
    assert "feste Kapazität (25,3)" in out and "25.25" not in out


# --- Every source of capacity, every number of decimal places -------------------------------------

# The people list computes the step from the people (see above); all other sources show the
# capacity of the result.
SHOWN_SOURCES = [
    CapacitySource.RECORDED,
    CapacitySource.TREND,
    CapacitySource.CALENDAR,
    CapacitySource.EXPECTED,
    CapacitySource.ESTIMATED,
]


@pytest.mark.parametrize("source", SHOWN_SOURCES)
@pytest.mark.parametrize(("digits", "shown"), [(1, "25,3"), (0, "25"), (2, "25,25")])
def test_capacity_step_of_every_source_rounds_half_up(fc, source: CapacitySource, digits, shown):
    """The capacity step shows 25.25 for every source, rounded to the team's decimal places."""
    e = fc.entry("2026.22")
    result = replace(e.result, plan_capacity=25.25, plan_capacity_source=source)
    patched = replace(e, result=result, capacity_digits=digits)
    assert capacity_step(fc, patched).calculation == f"= {shown} PT"
    assert capacity_label(patched).startswith(shown + " ")


@pytest.mark.parametrize(("rounding", "shown", "frozen"), [(0, "25", 25.0), (2, "25,25", 25.25)])
def test_capacity_rounding_setting_is_followed_by_display_and_frozen_value(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, rounding: int, shown: str, frozen: float
):
    """``capacity.rounding`` applies equally to display, prefill and frozen value."""
    with_absences(data_dir, BORDER, ben=3.5)
    with_capacity_settings(data_dir, rounding=rounding)
    data = Repository(data_dir).load("demo")
    assert sprint_capacity(data.team, data.people, data.sprint(BORDER)).rounded == frozen
    fc = build_forecast(data, TODAY)
    e = fc.entry(BORDER)
    assert e.capacity_digits == rounding
    assert capacity_label(e) == f"{shown} (Personenliste)"
    assert next(s for s in steps(fc, e) if s.key == "capacity").calculation.endswith(
        f"= 25,25 → {shown} PT (gerundet)"
    )
    assert table_cells(render(fc), BORDER)[3] == f"{shown} (Personenliste)"
    assert table_cells(cli(data_dir, "forecast", "demo"), BORDER)[3] == f"{shown} (Personenliste)"
    assert table_cells(cli(data_dir, "capacity", "demo", BORDER), "Summe")[-1] == shown

    at = page(open_app(data_dir, monkeypatch), "review")
    at.selectbox(key="review-sprint").set_value(BORDER).run()
    field = at.number_input(key=f"capacity-{BORDER}")
    assert field.value == pytest.approx(frozen)
    assert f"{shown} PT" in field.help

    out = cli(data_dir, "review", "demo", BORDER, input="y\n9,5\n0.1\nn\n")
    assert f"{shown} PT" in out
    assert sprint_file(data_dir, BORDER)["capacity"] == frozen


# --- Equations in the calculation path ------------------------------------------------------------


def test_equations_contain_the_numbers_used_for_the_calculation(border_fc):
    """The equation shows the trend and capacity actually used in the calculation (up to 4
    digits, without superfluous zeros), not the values rounded for display: recalculating
    gives the displayed result. The plan stays rounded down."""
    ref = border_fc.data.team.forecast.reference_capacity
    shown = {"2026.21": "25,25", "2026.22": "30", "2026.23": "30,4375", "2026.24": "30,4375"}
    assert {e.sprint.id for e in border_fc.upcoming()} == set(shown)
    for e in border_fc.upcoming():
        r = e.result
        calculation = next(s for s in steps(border_fc, e) if s.key == "plan").calculation
        match = re.fullmatch(
            r"([\d,]+) / ([\d,]+) × ([\d,]+) = ([\d,]+) → ([\d,]+) PT", calculation
        )
        assert match, calculation
        trend_text, ref_text, capacity_text, raw_text, plan_text = match.groups()
        assert capacity_text == shown[e.sprint.id], calculation
        assert num(ref_text) == ref
        assert num(trend_text) == pytest.approx(r.normalized_velocity.trend, abs=5e-5)
        assert num(capacity_text) == pytest.approx(r.plan_capacity, abs=5e-5)
        recomputed = num(trend_text) / ref * num(capacity_text)
        assert fmt(recomputed, 3) == raw_text, calculation  # the equation holds
        assert num(plan_text) == r.plan == round_down(recomputed, 1)

        text = plain_explanation(border_fc, e)
        assert f"{trend_text} / {ref:g} × {capacity_text} = {raw_text} PT" in text, text


def test_velocity_step_uses_the_exact_capacity(border_dir: Path):
    data = Repository(border_dir).load("demo")
    data.sprint(BORDER).velocity = 10.0
    fc = build_forecast(data, date.fromisoformat(LATER))  # 2026.21 over, not frozen
    e = fc.entry(BORDER)
    assert e.result.plan_capacity_source is CapacitySource.PEOPLE
    calculation = step(fc, e, "normalized_velocity").calculation
    assert calculation.startswith("10,00 / 25,25 × 45 = ")
    assert num(calculation.rsplit("= ", 1)[1]) == pytest.approx(10 / 25.25 * 45, abs=5e-3)


# --- The plan calculates with the unrounded capacity (per source) -------------------------------

# Ben 0.5, Cem 4.5 and Dana 3 absences: capacity 27.25. With the rounded 27.3 a different
# plan (10.2) would result than with the unrounded capacity (10.1); 27.25 is used.


def assert_plan_from_unrounded_capacity(fc, sprint: str, source: CapacitySource) -> None:
    e = fc.entry(sprint)
    r = e.result
    ref = fc.data.team.forecast.reference_capacity
    trend = r.normalized_velocity.trend
    assert r.plan_capacity_source is source
    assert r.plan_capacity == pytest.approx(27.25)
    assert round_down(trend / ref * 27.3, 1) != round_down(trend / ref * 27.25, 1)  # precondition
    assert r.plan == round_down(trend / ref * 27.25, 1) == 10.1
    assert capacity_label(e).startswith("27,3 ")
    calculation = next(s for s in steps(fc, e) if s.key == "plan").calculation
    assert "× 27,25 =" in calculation and calculation.endswith("→ 10,1 PT")


def test_plan_is_computed_from_the_unrounded_capacity(data_dir: Path):
    """Source people list (confirmed absences)."""
    with_absences(data_dir, BORDER, ben=0.5, cem=4.5)
    fc = build_forecast(Repository(data_dir).load("demo"), TODAY)
    assert_plan_from_unrounded_capacity(fc, BORDER, CapacitySource.PEOPLE)


def test_plan_with_announced_absences_uses_the_unrounded_capacity(data_dir: Path):
    """Source announced absences (PO pre-planning, nothing confirmed): the capacity with the
    announced absences must not be rounded prematurely."""
    data = Repository(data_dir).load("demo")
    sprint = data.sprint("2026.22")
    sprint.absences = {}
    sprint.absence_state = AbsenceState.UNKNOWN
    sprint.expected_absences = {"ben": 0.5, "cem": 4.5, "dana": 3.0}
    fc = build_forecast(data, TODAY)
    assert_plan_from_unrounded_capacity(fc, "2026.22", CapacitySource.EXPECTED)


def test_capacity_label_is_the_value_followed_by_the_source_note():
    """The source alone (for metrics whose value must not be truncated) and the composed
    text of the tables say the same."""
    from types import SimpleNamespace

    from foresprint.engine import UNSURE_SOURCES, CapacitySource
    from foresprint.report import capacity_source_note

    def entry(source):
        return SimpleNamespace(
            result=SimpleNamespace(plan_capacity=50.55, plan_capacity_source=source),
            capacity_digits=1,
        )

    value = fmt_capacity(50.55, 1)
    assert capacity_source_note(entry(None)) == ""
    assert capacity_label(entry(None)) == value
    for source in CapacitySource:
        note = capacity_source_note(entry(source))
        assert note.endswith(t(source.value))
        if source in UNSURE_SOURCES:
            assert note.startswith("⚠️ ")
            assert capacity_label(entry(source)) == f"{value} {note}"
        else:
            assert "⚠" not in note
            assert capacity_label(entry(source)) == f"{value} ({note})"
