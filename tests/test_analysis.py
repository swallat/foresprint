# SPDX-License-Identifier: EUPL-1.2
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from sprintforecast import analysis
from sprintforecast.forecast import build_forecast
from sprintforecast.model import Sprint, Team
from sprintforecast.storage import Repository, TeamData

TODAY = date(2026, 10, 15)


def team_with(velocities: list[float], capacity: float = 40, scope=None) -> TeamData:
    """Abgeschlossene Sprints mit fester Kapazität; Referenz 40 → n. Velocity = Velocity."""
    team = Team(key="t", name="T")
    team.forecast.reference_capacity = 40
    team.forecast.window = 5
    start = date(2026, 6, 3)
    sprints = []
    for i, v in enumerate(velocities):
        s = start + timedelta(days=14 * i)
        sprints.append(
            Sprint(
                f"2026.{i + 1}", s, s + timedelta(days=14), capacity=capacity, velocity=v,
                forecast_ist=v, scope_creep=None if scope is None else scope[i],
            )
        )  # fmt: skip
    return TeamData(team=team, sprints=sprints)


def test_band_uses_min_median_max_of_recent_sprints():
    data = team_with([30, 8, 10, 12, 20, 14])  # letzte 5: 8, 10, 12, 20, 14
    fc = build_forecast(data, TODAY)
    entry = fc.upcoming()[0]
    cap = entry.result.plan_capacity
    b = analysis.band(fc, entry)
    assert (b.low, b.mid, b.high, b.samples) == (
        pytest.approx(int(8 / 40 * cap * 10) / 10),
        pytest.approx(int(12 / 40 * cap * 10) / 10),
        pytest.approx(int(20 / 40 * cap * 10) / 10),
        5,
    )


def test_band_needs_history():
    fc = build_forecast(team_with([10]), TODAY)
    assert analysis.band(fc, fc.upcoming()[0]) is None


def test_focus_factor():
    fc = build_forecast(team_with([10, 20, 30], capacity=40), TODAY)
    assert analysis.focus_factor(fc.history()[0]) == pytest.approx(0.25)
    assert analysis.average_focus_factor(fc) == pytest.approx(0.5)


def test_buffer_hint():
    fc = build_forecast(team_with([10] * 5, scope=[0.3, 0.3, 0.3, None, None]), TODAY)
    hint = analysis.buffer_hint(fc)
    assert hint.samples == 3 and hint.average_scope_creep == pytest.approx(0.3)
    assert hint.configured_small_stuff == pytest.approx(0.2)
    assert hint.buffer_too_small
    fc = build_forecast(team_with([10] * 5, scope=[0.1, 0.1, None, None, None]), TODAY)
    assert not analysis.buffer_hint(fc).sufficient_data


def test_completion_is_deterministic_with_constant_velocity():
    # konstante Velocity 10 bei Kapazität 40 = Referenz → 10 je Sprint, Roadmap 80 % → 8
    data = team_with([10] * 5)
    result = analysis.completion(data, TODAY, remaining=20, share=0.8, runs=500)
    future = result.sprints
    assert result.p50 == result.p85 == future[2]  # 8 + 8 + 8 ≥ 20 im 3. Sprint
    assert result.cumulative[2] == pytest.approx(1.0)
    assert analysis.completion(data, TODAY, remaining=20, share=1.0, runs=10).p85 == future[1]
    # Projektanteil 50 % vom Roadmap-Anteil → 4 je Sprint → im 5. Sprint fertig
    half = analysis.completion(data, TODAY, remaining=20, share=0.8 * 0.5, runs=10)
    assert half.p85 == future[4]
    assert half.per_sprint == pytest.approx(4.0)
    assert analysis.completion(data, TODAY, remaining=20, share=0) is None


def test_completion_on_demo(data_dir: Path):
    data = Repository(data_dir).load("demo")
    result = analysis.completion(data, TODAY, remaining=40, share=0.8)
    order = result.sprints
    assert order.index(result.p50) <= order.index(result.p85)
    assert result.cumulative == sorted(result.cumulative)
    # Mit Personenliste kommt die Kapazität immer aus Kalender und Personen, nie aus dem Trend.
    assert result.trend_capacity_sprints == []
    no_people = Repository(data_dir).load("demo")
    no_people.people = []
    trend_only = analysis.completion(no_people, TODAY, remaining=40, share=0.8)
    assert "2026.23" in trend_only.trend_capacity_sprints  # Teams ohne Personenliste
    assert analysis.completion(data, TODAY, remaining=0, share=1) is None


def test_existing_values_are_unchanged(data_dir: Path):
    """Die Analysen ergänzen nur – Forecast PLAN, Roadmap, Kleinkram bleiben wie bisher."""
    fc = build_forecast(Repository(data_dir).load("demo"), TODAY)
    upcoming = {e.sprint.id: (e.result.plan, e.result.roadmap) for e in fc.upcoming()}
    # Demo mit Trend-Modus flat (Standard): konstanter Durchschnitt statt klassischer Trend
    assert upcoming["2026.21"] == (9.5, pytest.approx(7.6))
    assert upcoming["2026.22"] == (11.2, pytest.approx(8.96))


def test_buffer_hint_compares_on_the_same_base():
    """A9: Scope Creep ist auf das Commitment bezogen, der Kleinkram-Anteil auf den Forecast PLAN –
    verglichen wird auf dem Forecast PLAN."""
    data = team_with([10.0] * 6, scope=[0.3] * 6)
    fc = build_forecast(data, date(2026, 12, 31))
    hint = analysis.buffer_hint(fc)
    # Plan = Commitment (10): 30 % Scope Creep sind 30 % des Plans, mehr als die 20 % Kleinkram
    assert hint.average_scope_creep == pytest.approx(0.3)
    assert hint.average_late_share == pytest.approx(0.3) and hint.buffer_too_small
    for sprint in data.sprints:
        sprint.forecast_plan = 20.0  # beim Planning wurde doppelt so viel prognostiziert
    hint = analysis.buffer_hint(build_forecast(data, date(2026, 12, 31)))
    assert hint.average_scope_creep == pytest.approx(0.3)  # Eingabe unverändert
    assert hint.average_late_share == pytest.approx(0.15)  # 0,3 × 10 / 20
    assert not hint.buffer_too_small


def test_completion_note_only_below_the_minimum_of_samples():
    from sprintforecast.report import completion_note

    assert completion_note(analysis.MIN_SAMPLES) is None
    note = completion_note(analysis.MIN_SAMPLES - 1)
    assert note and note.startswith("Wenig Daten: Die Simulation zieht aus nur 4 Sprints")
    # Das Fenster deckelt die Schwelle: mehr als ``window`` Werte gibt es nie.
    assert completion_note(3, window=3) is None
    assert completion_note(2, window=3).startswith("Wenig Daten: Die Simulation zieht aus nur 2")


# --- Plan in der Bandbreite: laufender Sprint mit erfasstem Review-Wert (Velocity) -----------


def running_sprint(
    velocities: list[float | None],
    *,
    window: int = 5,
    capacities: list[float] | None = None,
):
    """Teamdaten, deren letzter Sprint läuft (``today`` mitten darin); ``None`` = Review-Wert
    noch nicht erfasst. Liefert ``(data, today)``."""
    data = team_with([v or 0.0 for v in velocities])
    data.team.forecast.window = window
    for i, (sprint, v) in enumerate(zip(data.sprints, velocities, strict=True)):
        if v is None:
            sprint.velocity = sprint.forecast_ist = None
        if capacities is not None:
            sprint.capacity = capacities[i]
    return data, data.sprints[-1].start + timedelta(days=5)


def future_entries(fc):
    return [e for e in fc.upcoming() if e.sprint.start > fc.today]


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("window", [2, 3, 5, 8])
def test_plan_lies_in_band_once_the_running_sprint_has_a_review_value(seed, window):
    """Eigenschaft: Mit erfasster Velocity des laufenden Sprints liegen Plan der Folgesprints
    (der damit rechnet) und Spanne auf derselben Wertemenge – der Plan liegt in der Spanne, auch
    wenn der Review-Wert ein Ausreißer ist und die Kapazität schwankt."""
    rng = random.Random(seed)
    count = rng.randint(3, 14)  # ab drei Werten gibt es einen Plan (dünne Historie)
    velocities = [round(rng.uniform(1, 40), 1) for _ in range(count)]
    velocities[-1] = rng.choice([0.5, 80.0, velocities[-1]])  # Ausreißer als Review-Wert
    capacities = [rng.choice([20.0, 32.0, 40.0, 48.0]) for _ in range(count)]
    data, today = running_sprint(velocities, window=window, capacities=capacities)
    fc = build_forecast(data, today)
    assert fc.current is not None and fc.current.sprint.velocity == velocities[-1]
    for entry in future_entries(fc):
        b = analysis.band(fc, entry)
        assert b is not None
        assert b.low <= entry.result.plan <= b.high, (entry.sprint.id, b, entry.result.plan)
        assert b.samples == min(window, count)


def test_running_sprints_review_value_enters_band_and_sample_count():
    data, today = running_sprint([10, 12, 8, 14, 11, 30])
    fc = build_forecast(data, today)
    entry = future_entries(fc)[0]
    cap = entry.result.plan_capacity
    assert analysis.normalized_history(fc) == [12.0, 8.0, 14.0, 11.0, 30.0]
    assert analysis.sample_count(fc) == 5
    b = analysis.band(fc, entry)
    assert (b.low, b.high, b.samples) == (
        pytest.approx(int(8 / 40 * cap * 10) / 10),
        pytest.approx(int(30 / 40 * cap * 10) / 10),
        5,
    )
    # Der Plan rechnet mit dem Mittel derselben fünf Werte (15), nicht mit dem Mittel ohne den
    # Review-Wert (11).
    assert entry.result.plan == pytest.approx(int(15 / 40 * cap * 10) / 10)


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("window", [3, 5])
def test_band_and_samples_are_unchanged_while_no_review_value_is_recorded(seed, window):
    """Ohne erfassten Review-Wert des laufenden Sprints zählen nur abgeschlossene Sprints –
    wie bisher (``fc.history()``)."""
    rng = random.Random(seed)
    velocities: list[float | None] = [
        round(rng.uniform(1, 40), 1) for _ in range(rng.randint(3, 12))
    ]
    velocities.append(None)  # laufender Sprint, Review steht noch aus
    data, today = running_sprint(velocities, window=window)
    fc = build_forecast(data, today)
    old = [e.result.normalized_velocity.value for e in fc.history()]
    old = [v for v in old if v is not None][-window:]
    assert analysis.normalized_history(fc) == old
    assert analysis.sample_count(fc) == len(old)
    for entry in future_entries(fc):
        b = analysis.band(fc, entry)
        assert b.samples == len(old)
        assert (b.low, b.high) == (
            pytest.approx(analysis.round_down(min(old) / 40 * entry.result.plan_capacity, 1)),
            pytest.approx(analysis.round_down(max(old) / 40 * entry.result.plan_capacity, 1)),
        )
        assert b.low <= entry.result.plan <= b.high


def test_completed_sprints_forecast_numbers_do_not_change():
    """Nur Spanne, Stichprobe und Simulation ändern sich – nicht die Prognose abgeschlossener
    Sprints oder der Folgesprints ohne neuen Wert."""
    data, today = running_sprint([10, 12, 8, 14, 11, None])
    before = [(e.sprint.id, e.result.plan) for e in build_forecast(data, today).entries]
    data.sprints[-1].velocity = 11.0  # Review-Wert erfassen: ändert nur die Folgesprints
    after = build_forecast(data, today).entries
    closed = [e for e in after if e.sprint.end <= today]
    assert [(e.sprint.id, e.result.plan) for e in closed] == before[: len(closed)]


@pytest.mark.parametrize("window", [1, 2, 3, 5, 8])
def test_sample_count_is_capped_at_the_window(window):
    data, today = running_sprint([float(10 + i) for i in range(12)], window=window)
    fc = build_forecast(data, today)
    assert analysis.sample_count(fc) == window
    assert len(analysis.normalized_history(fc)) == window
    if window >= 2:  # weniger als zwei Werte: keine Simulation (Mindestwert bleibt)
        assert analysis.completion(data, today, 20, 1.0, runs=20).samples == window
    else:
        assert analysis.completion(data, today, 20, 1.0, runs=20) is None
    # Die Schwelle für „wenig Daten“ passt zur Rechnung: ein volles Fenster ist nie „wenig“.
    assert not analysis.few_samples(fc)


def test_few_samples_follows_what_is_drawn_from():
    data, today = running_sprint([10.0, 11.0, 12.0], window=5)  # 2 abgeschlossene + laufender
    fc = build_forecast(data, today)
    assert analysis.sample_count(fc) == 3 and analysis.few_samples(fc)
    data, today = running_sprint([10.0, 11.0, 12.0, 9.0, 10.0, 12.0], window=5)
    assert not analysis.few_samples(build_forecast(data, today))
    data, today = running_sprint([10.0, 11.0, None], window=5)
    assert analysis.sample_count(build_forecast(data, today)) == 2


def test_reliability_note_counts_the_values_drawn_from():
    from sprintforecast.report import reliability_notes

    data, today = running_sprint([10.0, 11.0, 12.0], window=5)
    note = reliability_notes(build_forecast(data, today))[0]
    assert note.startswith("Wenig Daten: bisher nur 3 Sprints mit Velocity (ab 5 ")
    data, today = running_sprint([10.0, 11.0, 12.0], window=3)
    assert not any(
        n.startswith("Wenig Daten") for n in reliability_notes(build_forecast(data, today))
    )


def test_simulation_draws_from_the_running_sprints_review_value():
    data, today = running_sprint([10.0, 10.0, 40.0])
    result = analysis.completion(data, today, remaining=100, share=1.0, runs=200)
    assert result.samples == 3
    # ohne Review-Wert nur die zwei abgeschlossenen (je 10)
    data.sprints[-1].velocity = None
    without = analysis.completion(data, today, remaining=100, share=1.0, runs=200)
    assert without.samples == 2
    assert without.per_sprint == pytest.approx(10.0)
    assert result.cumulative != without.cumulative


def test_simulation_still_needs_two_values():
    """Mindestwert der Simulation (und der Spanne): zwei Werte, der laufende Sprint zählt mit."""
    data, today = running_sprint([10.0])  # nur der laufende Sprint
    assert analysis.completion(data, today, remaining=20, share=1.0, runs=10) is None
    data, today = running_sprint([10.0, None])
    assert analysis.completion(data, today, remaining=20, share=1.0, runs=10) is None
    assert (
        analysis.band(build_forecast(data, today), build_forecast(data, today).upcoming()[0])
        is None
    )
    data, today = running_sprint([10.0, 10.0])  # ein abgeschlossener + laufender mit Review-Wert
    assert analysis.completion(data, today, remaining=20, share=1.0, runs=10).samples == 2
    # genau zwei Werte reichen auch für die Spanne (hier zwei abgeschlossene)
    data, today = running_sprint([10.0, 10.0, None])
    fc = build_forecast(data, today)
    assert analysis.band(fc, future_entries(fc)[0]).samples == 2
