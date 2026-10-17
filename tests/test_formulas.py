# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

from sprintforecast.forecast import build_forecast
from sprintforecast.formulas import plain_explanation, step, steps
from sprintforecast.model import TrendMode
from sprintforecast.storage import Repository


def fc(data_dir: Path):
    return build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))


def test_formulas_flat_default_calculation(data_dir: Path):
    f = fc(data_dir)  # Demo: Trend-Modus flat
    e = f.entry("2026.22")
    assert step(f, e, "plan").calculation == "16,84 / 45 × 30,0 = 11,229 → 11,2 PT"
    assert step(f, e, "trend").formula == "n. Velocity-Trend = Wert_vorher (flat)"


def test_formulas_thin_history_note(data_dir: Path):
    data = Repository(data_dir).load("demo")
    data.team.forecast.trend_mode = TrendMode.LINEAR
    data.team.forecast.window = 20  # genau so viele Sprints mit Velocity wie das Fenster
    f = build_forecast(data, date(2026, 10, 15))
    e = f.entry("2026.22")
    assert e.result.trend_fallback
    assert "Historie dünn" in step(f, e, "trend").formula


def test_formulas_are_symbolic_and_calculation_has_numbers(data_dir: Path):
    data = Repository(data_dir).load("demo")
    data.team.forecast.trend_mode = TrendMode.CLASSIC  # klassische Formel prüfen
    f = build_forecast(data, date(2026, 10, 15))
    e = f.entry("2026.22")
    plan = step(f, e, "plan")
    assert plan.formula.startswith("Forecast PLAN = ")
    assert "n. Velocity-Trend / Referenzkapazität × Kapazität" in plan.formula
    assert plan.calculation == "15,28 / 45 × 30,0 = 10,185 → 10,1 PT"
    trend = step(f, e, "trend")
    assert trend.formula.startswith("n. Velocity-Trend = Ø[−2] / Ø[−3]")
    assert trend.calculation == "16,84 / 17,66 × 16,02 = 15,28"
    capacity = step(f, e, "capacity").calculation
    assert "Ben (10 − 0 − 0) × 0,5" in capacity and capacity.endswith("30,0 PT (gerundet)")


def test_past_sprint_steps(data_dir: Path):
    f = fc(data_dir)
    names = [s.name for s in steps(f, f.entry("2026.20"))]
    assert names[:3] == ["Kapazität", "n. Velocity", "Ø n. Velocity"]
    assert "Fulfillment" in names and "Planning-Delta" in names
    assert step(f, f.entry("2026.20"), "average").calculation.endswith("/ 5 = 16,84")


def test_plain_explanation_names_numbers_sources_and_sprints(data_dir: Path):
    f = fc(data_dir)
    text = plain_explanation(f, f.entry("2026.22"))
    assert "16,84" in text and "30,0 PT" in text and "Personenliste" in text
    assert "11,229" in text and "**11,2 PT**" in text
    assert "2026.16, 2026.17, 2026.18, 2026.19, 2026.20" in text  # Basis des Durchschnitts
    assert "schreibt Schwankungen" not in text  # flat: keine Warnung


def test_plain_explanation_warns_for_extrapolating_modes_and_thin_history(data_dir: Path):
    data = Repository(data_dir).load("demo")
    data.team.forecast.trend_mode = TrendMode.LINEAR
    f = build_forecast(data, date(2026, 10, 15))
    assert "schreibt Schwankungen" in plain_explanation(f, f.entry("2026.22"))
    data.team.forecast.window = 20
    thin = build_forecast(data, date(2026, 10, 15))
    assert "Historie ist dünn" in plain_explanation(thin, thin.entry("2026.22"))


def test_plain_explanation_for_past_sprint(data_dir: Path):
    f = fc(data_dir)
    assert "Vergangener Sprint" in plain_explanation(f, f.entry("2026.20"))
