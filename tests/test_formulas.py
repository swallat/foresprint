# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

from sprintforecast.forecast import build_forecast
from sprintforecast.formulas import step, steps
from sprintforecast.storage import Repository


def fc(data_dir: Path):
    return build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))


def test_formulas_are_symbolic_and_calculation_has_numbers(data_dir: Path):
    f = fc(data_dir)
    e = f.entry("2026.22")
    plan = step(f, e, "plan")
    assert plan.formula.startswith("Forecast PLAN = ")
    assert "n. Velocity-Trend / Referenzkapazität × Kapazität" in plan.formula
    assert plan.calculation == "15,28 / 45 × 30,0 = 10,185 → 10,1 PT"
    trend = step(f, e, "trend")
    assert trend.formula.startswith("n. Velocity-Trend = Ø[−2] / Ø[−3]")
    assert trend.calculation == "16,84 / 17,66 × 16,02 = 15,28"
    capacity = step(f, e, "capacity").calculation
    assert "Ben (10 − 0 − 0) × 0,5" in capacity and capacity.endswith("30,0 PT (abgerundet)")


def test_past_sprint_steps(data_dir: Path):
    f = fc(data_dir)
    names = [s.name for s in steps(f, f.entry("2026.20"))]
    assert names[:3] == ["Kapazität", "n. Velocity", "Ø n. Velocity"]
    assert "Fulfillment" in names and "Planning-Delta" in names
    assert step(f, f.entry("2026.20"), "average").calculation.endswith("/ 5 = 16,84")
