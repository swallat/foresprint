# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

from foresprint.forecast import build_forecast
from foresprint.formulas import GENERAL, _exact, general, plain_explanation, step, steps
from foresprint.locale_de import DE
from foresprint.model import TrendMode
from foresprint.storage import Repository


def test_general_capacity_formula_names_trend_only_without_people_list(english):
    """With a people list, capacity comes from the calendar and people; the trend only applies
    without one."""
    de = DE[GENERAL["capacity"]]
    assert de.count("Trend") == 1 and de.endswith("Trend nur ohne Personenliste")
    assert "unbekannte Fehltage nach der Historie geschätzt (ohne Historie ohne Abzug)" in de
    assert "ohne Fehltage: Trend" not in de
    assert general("capacity").endswith("trend only without a people list")


def test_exact_shows_up_to_four_digits_without_superfluous_zeros():
    assert _exact(30.4375) == "30,4375"
    assert _exact(25.25) == "25,25"
    assert _exact(30.0) == "30"
    assert _exact(100.0) == "100"
    assert _exact(0.0) == "0"
    assert _exact(30.123456) == "30,1235"  # more than 4 digits are rounded
    assert _exact(None) == "–"
    assert _exact(-0.00001) == "0"  # no “-0”
    assert _exact(1234.5) == "1.234,5"  # thousands separator like fmt


def test_exact_keeps_integer_zeros_without_decimals():
    """Zeros are only removed after the decimal separator: 100 stays 100, not 1."""
    assert _exact(100.0, 0) == "100"
    assert _exact(10.0, 0) == "10"
    assert _exact(30.4, 0) == "30"
    assert _exact(1000.0, 0) == "1.000"
    assert _exact(100.0, 1) == "100"


def fc(data_dir: Path):
    return build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))


def test_formulas_flat_default_calculation(data_dir: Path):
    f = fc(data_dir)  # demo: trend mode flat
    e = f.entry("2026.22")
    assert step(f, e, "plan").calculation == "16,8433 / 45 × 30 = 11,229 → 11,2 PT"
    assert step(f, e, "trend").formula == "n. Velocity-Trend = Wert_vorher (flat)"


def test_formulas_thin_history_note(data_dir: Path):
    data = Repository(data_dir).load("demo")
    data.team.forecast.trend_mode = TrendMode.LINEAR
    data.team.forecast.window = 20  # exactly as many Sprints with velocity as the window
    f = build_forecast(data, date(2026, 10, 15))
    e = f.entry("2026.22")
    assert e.result.trend_fallback
    assert "Historie dünn" in step(f, e, "trend").formula


def test_formulas_are_symbolic_and_calculation_has_numbers(data_dir: Path):
    data = Repository(data_dir).load("demo")
    data.team.forecast.trend_mode = TrendMode.CLASSIC  # check the classic formula
    f = build_forecast(data, date(2026, 10, 15))
    e = f.entry("2026.22")
    plan = step(f, e, "plan")
    assert plan.formula.startswith("Forecast PLAN = ")
    assert "n. Velocity-Trend / Referenzkapazität × Kapazität" in plan.formula
    assert plan.calculation == "15,2771 / 45 × 30 = 10,185 → 10,1 PT"
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
    assert "16,8433 / 45 × 30 = 11,229 PT" in text and "**11,2 PT**" in text
    assert "2026.16, 2026.17, 2026.18, 2026.19, 2026.20" in text  # basis of the average
    assert "schreibt Schwankungen" not in text  # flat: no warning


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
