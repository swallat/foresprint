# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

from sprintforecast.forecast import build_forecast
from sprintforecast.formulas import step, steps
from sprintforecast.storage import Repository


def fc(data_dir: Path):
    return build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))


def test_plan_calculation_shows_numbers(data_dir: Path):
    f = fc(data_dir)
    e = f.entry("2026.22")
    assert step(f, e, "Forecast PLAN").calculation == "15,28 / 45 × 30,0 = 10,185 → 10,1 PT"
    trend = step(f, e, "n. Velocity-Trend")
    assert "multiplikativ" in trend.formula
    assert trend.calculation == "16,84 / 17,66 × 16,02 = 15,28"
    capacity = step(f, e, "Kapazität").calculation
    assert "Ben (10 − 0 − 0) × 0,5" in capacity and capacity.endswith("30,0 PT (abgerundet)")


def test_past_sprint_steps(data_dir: Path):
    f = fc(data_dir)
    names = [s.name for s in steps(f, f.entry("2026.20"))]
    assert names[:3] == ["Kapazität", "n. Velocity", "Ø n. Velocity"]
    assert "Fulfillment" in names and "Planning-Delta" in names
    assert step(f, f.entry("2026.20"), "Ø n. Velocity").calculation.endswith("/ 5 = 16,84")
