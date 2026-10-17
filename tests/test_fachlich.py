# SPDX-License-Identifier: EUPL-1.2
"""Fachliche Tests: Eigenschaften der Berechnung, Randfälle, handgerechnete Beispiele und ein
Backtest (rückblickende Prüfung).

Die Konsistenztests prüfen, ob Seiten zum Rechenkern passen. Diese Tests prüfen, ob der
Rechenkern fachlich Sinn ergibt – unabhängig davon, wie er implementiert ist."""

import random
import statistics
from datetime import date, timedelta
from pathlib import Path

import pytest

from sprintforecast import analysis
from sprintforecast.calendar import team_workdays
from sprintforecast.capacity import sprint_capacity
from sprintforecast.engine import CapacitySource, SprintInput, compute
from sprintforecast.forecast import build_forecast
from sprintforecast.model import (
    ForecastSettings,
    Membership,
    Person,
    Sprint,
    Team,
    TrendMode,
)
from sprintforecast.storage import Repository, TeamData

TODAY = date(2026, 10, 15)
MODES = list(TrendMode)
REF = 40.0


# --- Hilfen --------------------------------------------------------------------------------


def inputs_for(velocities: list[float | None], capacity: float = 40.0, future: int = 3):
    """Sprints mit fester Kapazität; ``None`` = offen (Zukunft)."""
    rows = [
        SprintInput(
            id=str(i),
            capacity=capacity,
            capacity_source=CapacitySource.RECORDED,
            forecast_ist=v,
            velocity=v,
            scope_creep=None,
        )
        for i, v in enumerate(velocities)
    ]
    rows += [
        SprintInput(
            id=f"f{i}",
            capacity=capacity,
            capacity_source=CapacitySource.RECORDED,
            forecast_ist=None,
            velocity=None,
            scope_creep=None,
        )
        for i in range(future)
    ]
    return rows


def settings(mode: TrendMode, window: int = 5) -> ForecastSettings:
    return ForecastSettings(reference_capacity=REF, window=window, trend_mode=mode)


def team_data(velocities: list[float], capacity: float = 40.0, window: int = 5) -> TeamData:
    team = Team(key="t", name="T")
    team.forecast.reference_capacity = REF
    team.forecast.window = window
    start = date(2026, 1, 7)
    sprints = []
    for i, v in enumerate(velocities):
        s = start + timedelta(days=14 * i)
        sprints.append(
            Sprint(
                f"2026.{i + 1}",
                s,
                s + timedelta(days=14),
                capacity=capacity,
                velocity=v,
                forecast_ist=v,
            )
        )
    team.sprint.first_id, team.sprint.first_start = "2026.1", start
    return TeamData(team=team, sprints=sprints)


def person(pid="a", fte=1.0, workweek=None, since=date(2020, 1, 1)) -> Person:
    return Person(pid, pid.upper(), workweek=workweek, memberships=[Membership(since, fte=fte)])


def sprint_at(start: date, days: int = 14, absences=None) -> Sprint:
    return Sprint("x", start, start + timedelta(days=days), absences=absences or {})


def capacity_of(people, sprint, **team_kw) -> float:
    team = Team(key="t", name="T")
    team.capacity.region = "NW"
    for key, value in team_kw.items():
        setattr(team.capacity, key, value)
    return sprint_capacity(team, people, sprint).capacity


# --- Eigenschaften des Rechenkerns -----------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("window", [1, 3, 5])
def test_constant_velocity_gives_constant_forecast(mode, window):
    """Konstante Velocity → konstanter Forecast, in jedem Trend-Modus."""
    results = compute(inputs_for([10.0] * 12), settings(mode, window))
    future = results[12:]
    assert [r.plan for r in future] == [10.0, 10.0, 10.0]
    assert not any(r.trend_fallback for r in future)


@pytest.mark.parametrize("mode", MODES)
def test_forecast_scales_with_capacity_not_with_noise_in_capacity(mode):
    """Gleiche normierte Velocity: halbe Kapazität → halber Forecast."""
    rows = inputs_for([10.0] * 8, future=0)
    rows += [
        SprintInput("half", 20.0, CapacitySource.RECORDED, None, None, None),
        SprintInput("full", 40.0, CapacitySource.RECORDED, None, None, None),
    ]
    r = compute(rows, settings(mode))
    assert r[-2].plan == pytest.approx(r[-1].plan / 2)


@pytest.mark.parametrize("seed", range(10))
def test_plan_lies_within_band_for_default_mode(seed):
    """Der Plan (flat) liegt in der Bandbreite der letzten Sprints."""
    rng = random.Random(seed)
    data = team_data([max(1.0, rng.gauss(12, 3)) for _ in range(14)])
    fc = build_forecast(data, date(2026, 1, 7) + timedelta(days=14 * 14))
    assert data.team.forecast.trend_mode is TrendMode.FLAT
    for e in fc.upcoming():
        b = analysis.band(fc, e)
        assert b is not None and b.low <= e.result.plan <= b.high


def test_classic_and_linear_can_leave_the_band():
    """Begründung für den flat-Standard (A1): Linear schreibt Rauschen fort und liegt nach
    wenigen Zukunftssprints außerhalb der eigenen Bandbreite."""
    values = [10, 11, 13, 14, 16, 17, 19, 21, 22, 24]  # steigend
    data = team_data([float(v) for v in values])
    data.team.forecast.trend_mode = TrendMode.LINEAR
    data.team.forecast.horizon = 5
    fc = build_forecast(data, date(2026, 1, 7) + timedelta(days=14 * len(values)))
    outside = [
        e.sprint.id
        for e in fc.upcoming()
        if (b := analysis.band(fc, e)) and not b.low <= e.result.plan <= b.high
    ]
    assert outside, "linear sollte bei steigender Reihe aus der Bandbreite laufen"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("seed", range(5))
def test_forecast_is_never_negative(mode, seed):
    rng = random.Random(seed)
    falling = [max(0.0, 40 - 5 * i + rng.gauss(0, 2)) for i in range(10)]
    for r in compute(inputs_for(falling, future=6), settings(mode, window=3)):
        assert r.plan is None or r.plan >= 0
        assert r.normalized_velocity.trend is None or r.normalized_velocity.trend >= 0


def test_holiday_sprint_has_less_capacity_than_normal_sprint():
    people = [person("a"), person("b", fte=0.5)]
    normal = sprint_at(date(2026, 11, 2))  # 10 Arbeitstage
    christmas = sprint_at(date(2026, 12, 21))  # 25.12. (Fr) und 01.01. (Fr) fallen hinein
    assert len(team_workdays(Team(key="t", name="T"), normal.start, normal.end)) == 10
    assert capacity_of(people, christmas) < capacity_of(people, normal)
    assert capacity_of(people, normal) == pytest.approx(15.0)  # (1 + 0,5) × 10
    assert capacity_of(people, christmas) == pytest.approx(12.0)  # (1 + 0,5) × 8


@pytest.mark.parametrize("seed", range(8))
def test_more_people_never_means_less_capacity(seed):
    rng = random.Random(seed)
    sprint = sprint_at(date(2026, 10, 14), absences={"p0": rng.choice([0, 1, 2])})
    people: list[Person] = []
    previous = 0.0
    for n in range(6):
        people.append(person(f"p{n}", fte=rng.choice([0.2, 0.5, 0.8, 1.0])))
        for kw in ({}, {"overhead_share": 0.1}, {"overhead_days": 1.0}):
            now = capacity_of(people, sprint, **kw)
            if not kw:
                assert now >= previous
                previous = now
            assert now >= 0


@pytest.mark.parametrize("days", [7, 14, 21, 28])
def test_different_sprint_lengths_scale_capacity(days):
    """Kapazität zählt die Arbeitstage: 7 Kalendertage ≈ 5 Arbeitstage usw. (ohne Feiertage)."""
    start = date(2026, 3, 2)  # Montag, keine Feiertage bis Ende März
    people = [person("a")]
    assert capacity_of(people, sprint_at(start, days)) == pytest.approx(days / 7 * 5)


# --- Randfälle -------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [TrendMode.CLASSIC, TrendMode.LINEAR])
def test_exactly_window_sprints_gives_flat_with_note(mode):
    """A4: Genau ``window`` Sprints Historie → Forecast statt keinem, mit Hinweis."""
    results = compute(inputs_for([8.0, 10.0, 12.0], future=2), settings(mode, window=3))
    assert [r.plan for r in results[3:]] == [10.0, 10.0]
    assert all(r.trend_fallback for r in results[3:])


def test_empty_history_gives_no_forecast_and_no_error():
    results = compute(inputs_for([], future=3), settings(TrendMode.FLAT))
    assert [r.plan for r in results] == [None, None, None]


def test_one_value_below_window_gives_no_trend():
    results = compute(inputs_for([10.0], future=2), settings(TrendMode.FLAT, window=3))
    assert [r.plan for r in results[1:]] == [None, None]


def test_fte_zero_gives_zero_capacity_and_no_division_error():
    sprint = sprint_at(date(2026, 10, 14))
    assert capacity_of([person("a", fte=0.0)], sprint) == 0.0
    # Sprint mit Kapazität 0: normierte Velocity nicht definiert, Forecast ohne Absturz
    rows = [
        *inputs_for([10.0] * 6, future=0),
        SprintInput("zero", 0.0, CapacitySource.RECORDED, None, 5.0, None),
        *inputs_for([], future=1),
    ]
    results = compute(rows, settings(TrendMode.FLAT))
    assert results[6].normalized_velocity.value is None
    assert results[7].plan is not None


def test_gaps_do_not_count_as_values():
    """A4: Lücken (Sprints ohne Velocity) zählen nicht mit; das Fenster reicht weiter zurück."""
    values: list[float | None] = [10.0, 10.0, None, 10.0, None, 10.0, 10.0]
    results = compute(inputs_for(values, future=1), settings(TrendMode.FLAT, window=5))
    assert results[-1].plan == 10.0
    assert results[-1].samples == 5


# --- Handgerechnete Beispiele: FTE, Arbeitswoche, Overhead, Fehltage --------------------------

START = date(2026, 3, 2)  # Montag; 10 Arbeitstage bis 16.03., keine Feiertage


def test_fte_is_share_of_the_persons_working_days():
    """A6: Mo–Fr + FTE 0,8 = Vier-Tage-Woche + FTE 1 = 8 PT; beides zusammen zöge doppelt ab."""
    s = sprint_at(START)
    assert capacity_of([person(fte=0.8)], s) == pytest.approx(8.0)
    assert capacity_of([person(fte=1.0, workweek="mon,tue,wed,thu")], s) == pytest.approx(8.0)
    doubled = capacity_of([person(fte=0.8, workweek="mon,tue,wed,thu")], s)
    assert doubled == pytest.approx(6.4)  # 8 × 0,8 – der Fall, den die Hilfe warnend erklärt
    assert capacity_of([person(fte=0.5)], s) == pytest.approx(5.0)


def test_absences_are_taken_in_person_days_times_fte():
    s = sprint_at(START, absences={"a": 2})
    assert capacity_of([person(fte=1.0)], s) == pytest.approx(8.0)
    assert capacity_of([person(fte=0.5)], s) == pytest.approx(4.0)  # (5 − 2 × 0,5)


def test_overhead_days_replace_percentage_for_confirmed_and_expected_absences():
    """A8: Eine gemeinsame Rechnung. Feste PT ersetzen den Prozentabzug (nicht addiert)."""
    s = sprint_at(START)
    people = [person("a"), person("b", fte=0.5)]
    assert capacity_of(people, s, overhead_share=0.1) == pytest.approx(13.5)  # 15 − 10 %
    assert capacity_of(people, s, overhead_days=1.0) == pytest.approx(13.5)  # 15 − (1 + 0,5)
    both = capacity_of(people, s, overhead_share=0.1, overhead_days=1.0)
    assert both == pytest.approx(13.5)  # nicht 12,0


def test_expected_and_estimated_absences_use_the_same_overhead_rule():
    """Bestätigte Fehltage (2 Tage), erwartete Quote (20 %) und angekündigte Fehltage rechnen
    gleich: erst Fehltage, dann Overhead, dann Rundung."""
    people = [person("a")]
    team = Team(key="t", name="T")
    team.capacity.region = "NW"
    team.capacity.overhead_days = 1.0
    confirmed = sprint_at(START, absences={"a": 2})
    assert sprint_capacity(team, people, confirmed).capacity == pytest.approx(7.0)  # 8 − 1
    estimated = sprint_capacity(team, people, sprint_at(START), absence_rate=0.2).capacity
    assert estimated == pytest.approx(7.0)  # 10 × 0,8 − 1
    assert sprint_capacity(team, people, sprint_at(START), absence_rate=0.2).overhead == 1.0


def test_unknown_absences_still_use_calendar_and_people():
    """A2: Kapazität künftiger Sprints ohne Fehltage kommt aus Kalender und Personen, nicht aus
    dem Trend – hier mit einem Feiertagssprint, den ein Trend nicht kennen kann."""
    data = team_data([10.0] * 6)
    data.people = [person("a")]
    data.team.capacity.region = "NW"
    for s in data.sprints:
        s.capacity = None
        s.velocity = None
    data.sprints = data.sprints[:0]
    data.team.sprint.first_start = date(2026, 12, 21)  # erster Sprint enthält 2 Feiertage
    data.team.sprint.first_id = "2026.1"
    fc = build_forecast(data, date(2026, 12, 1))
    first, second = fc.entries[0], fc.entries[1]
    assert first.result.plan_capacity_source is CapacitySource.CALENDAR
    assert first.result.plan_capacity == pytest.approx(8.0)  # 10 − 2 Feiertage
    assert second.result.plan_capacity == pytest.approx(10.0)
    assert first.result.plan_capacity < second.result.plan_capacity


# --- Backtest ----------------------------------------------------------------------------------


def predict(
    values: list[float], mode: TrendMode, window: int, capacity: float = 40.0, ahead: int = 1
) -> float:
    """Normierte Velocity, die für den Sprint ``ahead`` Sprints nach ``values`` prognostiziert
    würde (1 = der nächste)."""
    results = compute(inputs_for(values, capacity, future=ahead), settings(mode, window))
    trend = results[-1].normalized_velocity.trend
    assert trend is not None
    return trend


def backtest(series: list[float], window: int = 5, ahead: int = 1) -> dict[str, float]:
    """Für jeden Sprint ab ``window`` + 2: mit den damals verfügbaren Daten (``ahead`` Sprints
    vorher) prognostizieren und mit dem tatsächlichen Wert vergleichen (mittlerer absoluter
    Fehler je Verfahren)."""
    errors: dict[str, list[float]] = {m.value: [] for m in MODES} | {"mean": [], "median": []}
    for i in range(window + 2 + ahead - 1, len(series)):
        past, actual = series[: i - ahead + 1], series[i]
        for mode in MODES:
            errors[mode.value].append(abs(predict(past, mode, window, ahead=ahead) - actual))
        recent = past[-window:]
        errors["mean"].append(abs(statistics.fmean(recent) - actual))
        errors["median"].append(abs(statistics.median(recent) - actual))
    return {name: statistics.fmean(values) for name, values in errors.items()}


def stationary(seed: int, n: int = 40) -> list[float]:
    rng = random.Random(seed)
    return [max(1.0, rng.gauss(12, 2.5)) for _ in range(n)]


def test_backtest_flat_equals_the_constant_mean_forecast():
    """flat ist der konstante Forecast aus dem Mittel der letzten Sprints – nicht schlechter."""
    for seed in range(5):
        result = backtest(stationary(seed))
        assert result["flat"] == pytest.approx(result["mean"])


def test_backtest_default_mode_is_best_on_stationary_series():
    """Auf stationären Reihen mit Rauschen ist der Standard besser als classic/linear und nicht
    schlechter als der konstante Forecast (Mittel, Median)."""
    totals: dict[str, list[float]] = {}
    for seed in range(20):
        for name, error in backtest(stationary(seed)).items():
            totals.setdefault(name, []).append(error)
    mae = {name: statistics.fmean(v) for name, v in totals.items()}
    assert mae["flat"] < mae["classic"] and mae["flat"] < mae["linear"]
    assert mae["flat"] <= mae["mean"] + 1e-9
    assert mae["flat"] <= mae["median"] * 1.05  # Median ist bei Normalrauschen nicht besser


def test_backtest_three_sprints_ahead_penalizes_extrapolating_noise():
    """Je weiter voraus, desto mehr schadet das Fortschreiben von Rauschen (A1)."""
    totals: dict[str, list[float]] = {}
    for seed in range(20):
        for name, error in backtest(stationary(seed), ahead=3).items():
            totals.setdefault(name, []).append(error)
    mae = {name: statistics.fmean(v) for name, v in totals.items()}
    assert mae["flat"] < mae["classic"] * 0.9
    assert mae["flat"] < mae["linear"] * 0.9
    assert mae["flat"] <= mae["mean"] + 1e-9


def test_backtest_trend_series_shows_when_linear_is_better():
    """Bei einem echten, stabilen Trend schlägt ``linear`` den Standard – deshalb bleibt es
    ausdrücklich wählbar, aber nicht der Standard."""
    series = [10 + 0.6 * i + random.Random(i).gauss(0, 0.3) for i in range(40)]
    result = backtest(series)
    assert result["linear"] < result["flat"]


def test_backtest_jump_series_flat_recovers_after_one_window():
    """Nach einem Sprung (Teamwechsel) holt der Standard die neue Höhe nach einem Fenster ein."""
    rng = random.Random(3)
    series = [max(1.0, rng.gauss(10, 1)) for _ in range(20)]
    series += [max(1.0, rng.gauss(16, 1)) for _ in range(20)]
    window = 5
    late = [
        abs(predict(series[:i], TrendMode.FLAT, window) - series[i])
        for i in range(20 + window + 1, 40)  # ab einem Fenster nach dem Sprung
    ]
    early = [
        abs(predict(series[:i], TrendMode.FLAT, window) - series[i]) for i in range(20, 20 + window)
    ]
    assert statistics.fmean(late) < statistics.fmean(early) / 2


def demo_series() -> list[float]:
    data = Repository(Path(__file__).parent.parent / "examples" / "teams").load("demo")
    fc = build_forecast(data, TODAY)
    return [
        v
        for e in fc.history()
        if (v := e.result.normalized_velocity.value) is not None  # Referenz des Demo-Teams
    ]


def test_backtest_on_demo_history_default_mode_is_not_worse_than_constant_forecast():
    series = demo_series()
    assert len(series) >= 15
    result = backtest(series)
    assert result["flat"] <= result["mean"] + 1e-9
    assert result["flat"] <= result["classic"]  # classic läuft dem Rauschen hinterher
    assert result["flat"] <= result["linear"]


def test_plan_of_demo_lies_in_band():
    data = Repository(Path(__file__).parent.parent / "examples" / "teams").load("demo")
    fc = build_forecast(data, TODAY)
    for e in fc.upcoming():
        b = analysis.band(fc, e)
        assert b is not None and b.low <= e.result.plan <= b.high
