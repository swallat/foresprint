# SPDX-License-Identifier: EUPL-1.2
import pytest

from sprintforecast.engine import (
    CapacitySource,
    PlanSource,
    SprintInput,
    compute,
    gaps_in_window,
    rolling_average,
    round_down,
    trend,
)
from sprintforecast.model import ForecastSettings, Planning, TrendMode

N = None


def test_round_down():
    assert round_down(15.72, 1) == 15.7
    assert round_down(14.0, 1) == 14.0
    # Gleitkommafehler dürfen nicht eine Stelle zu tief abrunden.
    assert round_down(0.1 + 0.2, 1) == 0.3
    assert round_down(-1.25, 1) == -1.2


def test_rolling_average_needs_full_window_and_own_value():
    assert rolling_average([1, 2, 3, 4, 5, 6, N], 5) == [N, N, N, N, 3, 4, N]


def test_rolling_average_skips_gaps_and_always_uses_window_values():
    # Sprints ohne Wert zählen nicht mit; das Fenster reicht entsprechend weiter zurück.
    assert rolling_average([2, N, 4, 6, 8], 5) == [N, N, N, N, N]  # nur vier Werte
    assert rolling_average([2, N, 4, 6, 8, 10], 5) == [N, N, N, N, N, 6.0]
    assert rolling_average([1, 2, N, 3, N, 4, 5], 3) == [N, N, N, 2.0, N, 3.0, 4.0]


def test_gaps_in_window_counts_skipped_sprints():
    assert gaps_in_window([1, 2, N, 3, N, 4, 5], 3) == 1
    assert gaps_in_window([1, 2, 3, 4, 5], 3) == 0
    assert gaps_in_window([N, N], 3) == 0


AVG = [N, N, N, 8.0, 10.0, 12.0, N, N, N]


def test_trend_classic_mixes_linear_and_multiplicative():
    t = trend(AVG, TrendMode.CLASSIC)
    assert t[:6] == [N] * 6
    assert t[6] == pytest.approx(14.0)  # 12 + (12 − 10)
    assert t[7] == pytest.approx(16.8)  # 12 / 10 × 14
    assert t[8] == pytest.approx(19.6)  # 16.8 + (16.8 − 14)


def test_trend_linear():
    assert trend(AVG, TrendMode.LINEAR)[6:] == pytest.approx([14.0, 16.0, 18.0])


def test_trend_flat():
    assert trend(AVG, TrendMode.FLAT)[6:] == [12.0, 12.0, 12.0]


def _input(i, capacity=40.0, velocity=None, forecast_ist=None, planning=None):
    return SprintInput(
        id=str(i),
        capacity=capacity,
        capacity_source=CapacitySource.RECORDED if capacity is not None else None,
        forecast_ist=forecast_ist,
        velocity=velocity,
        scope_creep=None,
        planning=planning,
    )


def test_compute_forecast_plan():
    settings = ForecastSettings(reference_capacity=40, window=2, trend_mode=TrendMode.CLASSIC)
    inputs = [
        _input(0, velocity=10, forecast_ist=12.34),
        _input(1, velocity=12, forecast_ist=11),
        _input(2, velocity=14, forecast_ist=13),
        # laufender Sprint: Kapazität bekannt, Velocity offen
        _input(3, capacity=20, planning=Planning(carryover=1, backlog=8, corrections=[0.5])),
        # künftiger Sprint ohne Kapazität → Kapazitäts-Trend
        _input(4, capacity=None),
    ]
    r = compute(inputs, settings)

    assert r[0].plan == 12.3 and r[0].plan_source is PlanSource.ACTUAL
    assert r[2].normalized_velocity.value == pytest.approx(14.0)
    assert r[2].fulfillment.value == pytest.approx(14 / 13)

    # n. Velocity Ø: [-, 11, 13] → Trend Sprint 3 = 13 + 2 = 15
    assert r[3].normalized_velocity.trend == pytest.approx(15.0)
    assert r[3].plan == 7.5 and r[3].plan_source is PlanSource.FORECAST  # 15/40×20
    assert r[3].roadmap == pytest.approx(6.0)
    assert r[3].small_stuff == pytest.approx(1.5)
    assert r[3].planning_total == pytest.approx(8.5)
    assert r[3].planning_delta == pytest.approx(-1.0)

    # Kapazität Ø: [-, 40, 40, 30] → Trend Sprint 4 = 30 + (30 − 40) = 20
    assert r[4].plan_capacity == pytest.approx(20.0)
    assert r[4].plan_capacity_source is CapacitySource.TREND
    # n. Velocity Trend Sprint 4 (multiplikativ): 13/11 × 15
    assert r[4].plan == round_down(13 / 11 * 15 / 40 * 20, 1)


def test_trend_accepts_text_mode():
    """Ein Text darf nicht stillschweigend im Zweig ``linear`` landen (A15)."""
    assert trend(AVG, "flat")[6:] == [12.0, 12.0, 12.0]
    assert trend(AVG, "classic")[7] == pytest.approx(16.8)
    assert trend(AVG, "klassisch")[7] == pytest.approx(16.8)  # alter deutscher Name
    with pytest.raises(ValueError):
        trend(AVG, "quadratisch")


def test_default_trend_mode_is_flat():
    assert ForecastSettings().trend_mode is TrendMode.FLAT


@pytest.mark.parametrize("mode", list(TrendMode))
def test_trend_never_negative(mode):
    falling = [N, N, 20.0, 10.0, 2.0, N, N, N]
    assert all(v is None or v >= 0 for v in trend(falling, mode))


@pytest.mark.parametrize("mode", [TrendMode.CLASSIC, TrendMode.LINEAR])
def test_thin_history_falls_back_to_flat(mode):
    """Genau ``window`` Sprints: ein einziger Durchschnitt, kein Anstieg bestimmbar."""
    thin = [N, N, N, 8.0, N, N]
    assert trend(thin, mode)[4:] == [8.0, 8.0]
    settings = ForecastSettings(reference_capacity=40, window=2, trend_mode=mode)
    inputs = [_input(0, velocity=10), _input(1, velocity=12), _input(2), _input(3)]
    r = compute(inputs, settings)
    assert r[2].plan is not None and r[2].trend_fallback
    assert r[2].plan == 11.0  # Ø 11 bleibt stehen
    assert r[2].samples == 2


def test_enough_history_has_no_fallback():
    settings = ForecastSettings(reference_capacity=40, window=2, trend_mode=TrendMode.LINEAR)
    inputs = [_input(i, velocity=10 + i) for i in range(4)] + [_input(4)]
    assert not compute(inputs, settings)[4].trend_fallback


def test_plan_never_negative():
    settings = ForecastSettings(reference_capacity=40, window=1, trend_mode=TrendMode.LINEAR)
    inputs = [_input(0, velocity=30), _input(1, velocity=10), _input(2, velocity=1), _input(3)]
    assert compute(inputs, settings)[3].plan == 0.0
