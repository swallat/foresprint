# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the calculation engine (``foresprint.engine``) for the Go port: the
rounding helpers, rolling average, gaps, trend modes and ``compute`` on hand-made series that
reach the corners the demo and synthetic teams do not (thin history, gaps, negative
projections, every trend mode, rounding digits, a missing capacity)."""

from __future__ import annotations

from foresprint import engine
from foresprint.model import ForecastSettings, Planning, TrendMode

N = None

SERIES: dict[str, list[float | None]] = {
    "full": [10, 12, 11, 13, 14, 12, 15, 16, 14, N, N, N, N],
    "gaps": [10, N, 12, 11, N, N, 13, 14, 12, N, 15, N, N, N],
    "thin": [8, 9, 10, N, N, N],
    "thin-gap": [N, 8, N, 9, 10, N, N, N],
    "two": [8, 9, N, N],
    "falling": [30, 26, 22, 18, 14, 10, 6, N, N, N, N, N],
    "steep": [5, 4, 3, 2, 1, 0.5, N, N, N, N],
    "rising": [1, 2, 4, 8, 16, 32, N, N, N],
    "empty": [N, N, N],
    "none-last": [10, 11, 12, 13, 14, N],
    "float-noise": [0.1, 0.2, 0.3, 0.1 + 0.2, 0.7, 0.1, N, N],
}

ROUNDING_VALUES = [
    0,
    0.5,
    1.5,
    2.5,
    2.675,
    29.999999999,
    30.0000000001,
    0.1 + 0.2,
    1e-10,
    12.345,
    12.355,
    -0.5,
    -2.5,
    -29.999999999,
    100.0,
    67.0 / 3,
    25.25,
    25.75,
    0.049999999,
    0.05,
    0.95,
    1234.5678,
]


def _settings(
    window: int, mode: TrendMode, rounding: int = 1, share: float = 0.8
) -> ForecastSettings:
    return ForecastSettings(
        reference_capacity=40.0,
        window=window,
        roadmap_share=share,
        rounding=rounding,
        trend_mode=mode,
        horizon=3,
    )


def generate(ctx) -> None:
    out: dict = {"rounding": [], "series": [], "compute": []}
    for value in ROUNDING_VALUES:
        for digits in (0, 1, 2, 3):
            out["rounding"].append(
                {
                    "value": value,
                    "digits": digits,
                    "round_down": engine.round_down(value, digits),
                    "round_half_up": engine.round_half_up(value, digits),
                }
            )
    for name, values in SERIES.items():
        for window in (1, 2, 3, 5):
            average = engine.rolling_average(values, window)
            entry = {
                "name": name,
                "values": values,
                "window": window,
                "average": average,
                "thin": engine.thin_history(values, window),
                "gaps": engine.gaps_in_window(values, window),
                "trends": {},
            }
            for mode in TrendMode:
                trend, fallback = engine._trend(average, mode)
                entry["trends"][mode.value] = {"trend": trend, "fallback": fallback}
            out["series"].append(entry)
    out["klassisch"] = engine.parse_trend_mode("klassisch").value

    # compute(): capacity from recorded values, with gaps; planning in two sprints.
    capacities: list[float | None] = [30, 35, 28, 32, N, 30, 31, N, N, N, N, 33, N, N]
    velocity: list[float | None] = [20, 25, 18, 22, 24, N, 21, 23, N, N, N, N, N, N]
    commitment: list[float | None] = [22, 24, 20, 23, 24, 25, 22, 24, 26, N, N, N, N, N]
    scope: list[float | None] = [0.1, N, 0.2, 0.05, 0.0, N, N, N, N, N, N, N, N, N]
    plannings = {3: Planning(5, 10, [1.5, 2.0]), 7: Planning(0, 12, [])}
    for window in (3, 5):
        for mode in TrendMode:
            for rounding, share in ((1, 0.8), (0, 0.75), (2, 0.9)):
                inputs = [
                    engine.SprintInput(
                        id=f"S{i + 1}",
                        capacity=c,
                        capacity_source=engine.CapacitySource.RECORDED if c is not None else None,
                        commitment=commitment[i],
                        velocity=velocity[i],
                        scope_creep=scope[i],
                        planning=plannings.get(i),
                    )
                    for i, c in enumerate(capacities)
                ]
                settings = _settings(window, mode, rounding, share)
                out["compute"].append(
                    {
                        "window": window,
                        "mode": mode.value,
                        "rounding": rounding,
                        "share": share,
                        "results": ctx.jsonable(engine.compute(inputs, settings)),
                    }
                )
    ctx.write("engine/cases.json", ctx.dump_json(ctx.jsonable(out)))
