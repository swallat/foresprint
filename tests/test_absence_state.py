# SPDX-License-Identifier: EUPL-1.2
"""Stand der Fehltage je Sprint (unbekannt / angekündigt / bestätigt) und die Historie der
Fehltage (A5, B2)."""

from datetime import date
from pathlib import Path

import pytest
import yaml

from sprintforecast.capacity import absence_history
from sprintforecast.model import AbsenceState, ProductValues, Sprint, absence_status
from sprintforecast.storage import DataError, Repository

START, END = date(2026, 11, 11), date(2026, 11, 25)


def write(data_dir: Path, name: str, extra: str) -> Path:
    path = data_dir / "demo" / "sprints" / f"{name}.yaml"
    path.write_text(f"id: '{name}'\nstart: 2026-11-11\nend: 2026-11-25\n{extra}", encoding="utf-8")
    return path


def state_of(data_dir: Path, name: str) -> AbsenceState:
    return absence_status(Repository(data_dir).load("demo").sprint(name))


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ("", AbsenceState.UNKNOWN),  # leere Datei bestätigt nichts
        ("products:\n  webshop: {preplanned: 3}\n", AbsenceState.UNKNOWN),  # nur Vorplanung
        ("expected_absences: {anna: 2}\n", AbsenceState.EXPECTED),
        ("absences: {anna: 2}\n", AbsenceState.CONFIRMED),
        ("absences_confirmed: true\n", AbsenceState.CONFIRMED),  # ältere Datei
        ("forecast_ist: 9\n", AbsenceState.CONFIRMED),  # ältere Datei: geplant = bekannt
        ("velocity: 9\n", AbsenceState.CONFIRMED),
        ("absence_state: unknown\nforecast_ist: 9\n", AbsenceState.UNKNOWN),  # ausdrücklich
        ("absence_state: unknown\nexpected_absences: {anna: 1}\n", AbsenceState.EXPECTED),
        ("absence_state: confirmed\n", AbsenceState.CONFIRMED),  # „niemand fehlt“
        ("absence_state: unknown\nabsences: {anna: 1}\n", AbsenceState.CONFIRMED),  # Einträge
    ],
)
def test_state_is_read_from_existing_files(data_dir: Path, extra: str, expected: AbsenceState):
    write(data_dir, "2026.30", extra)
    assert state_of(data_dir, "2026.30") is expected


def test_invalid_state_is_reported(data_dir: Path):
    write(data_dir, "2026.30", "absence_state: vielleicht\n")
    with pytest.raises(DataError, match="absence_state 'vielleicht' unbekannt"):
        Repository(data_dir).load("demo")


def test_resaving_a_legacy_file_keeps_it_unchanged(data_dir: Path):
    path = write(data_dir, "2026.30", "forecast_ist: 9\n")
    repo = Repository(data_dir)
    repo.save_sprint("demo", repo.load("demo").sprint("2026.30"))
    saved = yaml.safe_load(path.read_text())
    assert "absence_state" not in saved  # keine Migration nötig
    assert state_of(data_dir, "2026.30") is AbsenceState.CONFIRMED


def test_saving_planning_values_pins_the_unknown_state(data_dir: Path):
    """Das Planning allein (Commitment) bestätigt keine Fehltage: Der Stand wird mit der
    Datei festgehalten."""
    repo = Repository(data_dir)
    sprint = Sprint("2026.30", START, END, forecast_ist=9.0, absence_state=AbsenceState.UNKNOWN)
    path = repo.save_sprint("demo", sprint)
    assert yaml.safe_load(path.read_text())["absence_state"] == "unknown"
    assert state_of(data_dir, "2026.30") is AbsenceState.UNKNOWN


def test_saving_without_a_state_derives_it_from_the_previous_file(data_dir: Path):
    path = write(data_dir, "2026.30", "products:\n  webshop: {preplanned: 3}\n")
    repo = Repository(data_dir)
    sprint = repo.load("demo").sprint("2026.30")
    sprint.forecast_ist = 9.0  # z. B. Planning auf einer bisher unbestätigten Datei
    repo.save_sprint("demo", sprint)
    assert yaml.safe_load(path.read_text())["absence_state"] == "unknown"


def test_new_file_for_an_evaluated_sprint_counts_as_confirmed(data_dir: Path):
    """Import aus einem anderen Werkzeug: Sprint mit Velocity ist ausgewertet."""
    repo = Repository(data_dir)
    path = repo.save_sprint("demo", Sprint("2026.30", START, END, velocity=9.0))
    assert "absence_state" not in yaml.safe_load(path.read_text())  # wie die Ableitung
    assert state_of(data_dir, "2026.30") is AbsenceState.CONFIRMED


def test_confirmed_nobody_absent_roundtrip_writes_both_keys(data_dir: Path):
    repo = Repository(data_dir)
    sprint = Sprint("2026.30", START, END, absence_state=AbsenceState.CONFIRMED)
    saved = yaml.safe_load(repo.save_sprint("demo", sprint).read_text())
    assert saved["absence_state"] == "confirmed" and saved["absences_confirmed"] is True
    assert state_of(data_dir, "2026.30") is AbsenceState.CONFIRMED


def test_expected_absences_do_not_confirm_and_unconfirm_keeps_expected():
    sprint = Sprint("x", START, END, expected_absences={"anna": 2.0})
    assert absence_status(sprint) is AbsenceState.EXPECTED
    sprint.absences_confirmed = True
    assert absence_status(sprint) is AbsenceState.CONFIRMED
    sprint.absences_confirmed = False
    assert absence_status(sprint) is AbsenceState.EXPECTED


def test_preplanning_only_file_does_not_confirm():
    sprint = Sprint("x", START, END, products={"a": ProductValues(preplanned=2.0)})
    assert absence_status(sprint) is AbsenceState.UNKNOWN


# --- A5: Fehltage-Historie -----------------------------------------------------------------


def test_history_counts_confirmed_zero_sprints_and_skips_unknown(data_dir: Path):
    data = Repository(data_dir).load("demo")
    past = [s for s in data.sprints if s.end <= date(2026, 10, 15)][-4:]
    for sprint in past:  # alle vier bestätigt, nur der letzte mit Fehltagen
        sprint.absences = {}
        sprint.absence_state = AbsenceState.CONFIRMED
    past[-1].absences = {data.people[0].id: 5.0}
    history = absence_history(data.team, data.people, past, 4)
    assert history.sprints == [s.id for s in past]
    assert history.rates[:3] == [0.0, 0.0, 0.0]  # bestätigte Null-Sprints zählen mit
    assert history.rate == pytest.approx(history.rates[-1] / 4)

    past[0].absence_state = AbsenceState.UNKNOWN  # unbekannt zählt nicht
    past[0].velocity = past[0].forecast_ist = past[0].forecast_plan = None
    past[0].planning = None
    skipped = absence_history(data.team, data.people, past, 4)
    assert past[0].id not in skipped.sprints and len(skipped.sprints) == 3
    assert skipped.rate == pytest.approx(history.rates[-1] / 3)


def test_history_uses_only_the_last_count_sprints_and_shows_them(data_dir: Path):
    data = Repository(data_dir).load("demo")
    past = [s for s in data.sprints if s.end <= date(2026, 10, 15)]
    history = absence_history(data.team, data.people, past, 2)
    assert history.sprints == [s.id for s in past[-2:]]
    assert absence_history(data.team, data.people, past, 0).rate is None


def test_history_without_confirmed_sprints_has_no_rate(data_dir: Path):
    data = Repository(data_dir).load("demo")
    blank = Sprint("x", START, END, absence_state=AbsenceState.UNKNOWN)
    assert absence_history(data.team, data.people, [blank], 4).rate is None
