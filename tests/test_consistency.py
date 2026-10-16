# SPDX-License-Identifier: EUPL-1.2
"""Konsistenz: Dieselbe Kennzahl muss an allen Stellen denselben Wert haben.

Die Wahrheit liefert der Rechenkern (``build_forecast``). Verglichen werden Bericht
(FORECAST.md), Kommandozeile, Formel-Rechenwege, Produktverteilung und die Seiten der
Weboberfläche für jeden künftigen Sprint – auch für Sprints ohne Datei (Trend) und solche
mit Datei (Personenliste).
"""

import re
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from sprintforecast.analysis import band
from sprintforecast.cli import app as cli_app
from sprintforecast.forecast import build_forecast
from sprintforecast.formulas import steps
from sprintforecast.products import distribution
from sprintforecast.report import fmt, render
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository

TODAY = date(2026, 10, 15)
APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"


def num(text: str) -> float:
    """„10,1 PT“, „9,0“, „25,5 (Personenliste)“ → Zahl."""
    match = re.search(r"-?\d+(?:[.,]\d+)?", text)
    assert match, text
    return float(match.group().replace(",", "."))


@pytest.fixture
def fc(data_dir: Path):
    return build_forecast(Repository(data_dir).load("demo"), TODAY)


@pytest.fixture
def web(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def page(at: AppTest, key: str) -> AppTest:
    at.switch_page(f"seiten/{key}.py").run()
    assert not at.exception, at.exception
    return at


def upcoming_ids(fc) -> list[str]:
    return [e.sprint.id for e in fc.upcoming()]


# --- Rechenkern ↔ Bericht ↔ Kommandozeile ↔ Rechenweg ----------------------------------


def test_internal_identities_hold(fc):
    """Roadmap + Kleinkram = Forecast PLAN; Plan = abgerundet(Trend / Referenz × Kapazität)."""
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
        if line.startswith("| 20") and len(cells) == 8 and "%" not in cells[6]:  # Prognosetabelle
            rows[cells[0]] = cells
    assert set(rows) == set(upcoming_ids(fc))
    for e in fc.upcoming():
        cells = rows[e.sprint.id]
        assert num(cells[3]) == pytest.approx(num(fmt(e.result.plan_capacity)))
        assert cells[4] == fmt(e.result.normalized_velocity.trend, 2)
        assert cells[5].strip("*") == fmt(e.result.plan)
        assert cells[6] == fmt(e.result.roadmap, 2)
        assert cells[7] == fmt(e.result.small_stuff, 2)


def test_report_history_matches_engine(fc):
    rows = {}
    for line in render(fc).splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| 20") and len(cells) == 8 and "%" in cells[6]:
            rows[cells[0]] = cells
    assert rows
    for e in fc.history(10):
        cells = rows[e.sprint.id]
        r = e.result
        assert cells[1] == fmt(r.capacity.value, 1)
        assert cells[3] == fmt(r.velocity.value, 2)
        assert cells[4] == fmt(r.normalized_velocity.value, 2)


def test_cli_forecast_shows_engine_values(data_dir: Path, fc):
    result = CliRunner(env={"COLUMNS": "260"}).invoke(
        cli_app, ["--daten", str(data_dir), "--stichtag", "2026-10-15", "forecast", "demo"]
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
        assert fmt(r.plan_capacity, 1) in by_key["capacity"].calculation


# --- Produktverteilung -------------------------------------------------------------------


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


# --- Weboberfläche -----------------------------------------------------------------------


def test_forecast_page_matches_engine(web: AppTest, fc):
    page(web, "forecast")
    tiles = {m.label.split(" ")[0]: m.value for m in web.metric if m.label[:4] == "2026"}
    table = next(d.value for d in web.dataframe if "Roadmap" in d.value.columns)
    for e in fc.upcoming():
        r = e.result
        sid = e.sprint.id
        assert num(tiles[sid]) == pytest.approx(num(fmt(r.plan)))
        row = table[table["Sprint"] == sid].iloc[0]
        assert row.iloc[5] == fmt(r.plan)
        assert row["Roadmap"] == fmt(r.roadmap, 2)
        assert row["Kleinkram"] == fmt(r.small_stuff, 2)
        assert row.iloc[4] == fmt(r.normalized_velocity.trend, 2)


@pytest.mark.parametrize("sprint", ["2026.21", "2026.22", "2026.23", "2026.24"])
def test_planning_vorplanung_products_and_analysis_agree(web: AppTest, fc, sprint: str):
    expected = fc.entry(sprint).result.plan

    page(web, "vorplanung")
    web.selectbox(key="vorplanung-sprint").set_value(sprint).run()
    assert not web.exception, web.exception
    headline = next(m for m in web.metric if m.label == f"Forecast PLAN {sprint}")
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

    page(web, "produkte")
    web.selectbox(key="products-sprint").set_value(sprint).run()
    assert not web.exception, web.exception
    assert any(fmt(expected, 2) in c.value for c in web.caption), [c.value for c in web.caption]


def test_planning_page_shows_engine_plan(web: AppTest, fc):
    """Planning-Seite Schritt 2: Forecast PLAN wie im Rechenkern (Sprint ohne Fehltagebestätigung
    unverändert, mit gespeicherter Datei ebenso)."""
    sprint = "2026.22"
    page(web, "planning")
    web.selectbox(key="planning-sprint").set_value(sprint).run()
    web.radio(key="planning-step").set_value(1).run()
    assert not web.exception, web.exception
    tile = next(m for m in web.metric if m.label.startswith("Forecast PLAN"))
    assert num(tile.value) == pytest.approx(fc.entry(sprint).result.plan)


def test_analysis_band_uses_the_same_plan(web: AppTest, fc):
    page(web, "analyse")
    table = next(d.value for d in web.dataframe if "konservativ" in d.value.columns)
    for e in fc.upcoming():
        row = table[table["Sprint"] == e.sprint.id].iloc[0]
        assert row.iloc[1] == fmt(e.result.plan)
        b = band(fc, e)
        if b is not None:
            assert row["mittel"] == fmt(b.mid)


def test_absences_page_preview_matches_engine_for_known_sprints(web: AppTest, fc):
    """Sprints mit Datei: Kapazität und Forecast PLAN der Vorschau = Rechenkern."""
    page(web, "fehltage")
    table = next(d.value for d in web.dataframe if "Kapazität (PT)" in d.value.columns)
    for _, row in table.iterrows():
        entry = fc.entry(row["Sprint"])
        if entry.recorded and entry.result.plan_capacity_source.value == "Personenliste":
            assert num(row["Kapazität (PT)"]) == pytest.approx(entry.result.plan_capacity)
            assert num(row.iloc[2]) == pytest.approx(entry.result.plan)


def test_history_table_matches_engine(web: AppTest, fc):
    page(web, "forecast")
    table = next(d.value for d in web.dataframe if "Ø n. Velocity" in d.value.columns)
    for e in fc.history(10):
        row = table[table["Sprint"] == e.sprint.id].iloc[0]
        assert row["n. Velocity"] == fmt(e.result.normalized_velocity.value, 2)
        assert row["Ø n. Velocity"] == fmt(e.result.normalized_velocity.average, 2)


def test_review_defaults_to_computed_capacity(web: AppTest, data_dir: Path):
    """Die vorbelegten verfügbaren Personentage im Review = Kapazität aus Personenliste."""
    from sprintforecast.capacity import sprint_capacity

    data = Repository(data_dir).load("demo")
    sprint = data.sprint("2026.21")
    expected = sprint.capacity if sprint.capacity is not None else None
    if expected is None:
        expected = sprint_capacity(data.team, data.people, sprint).capacity
    page(web, "review")
    web.selectbox(key="review-sprint").set_value("2026.21").run()
    assert web.number_input(key="capacity-2026.21").value == pytest.approx(expected)
