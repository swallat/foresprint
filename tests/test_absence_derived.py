# SPDX-License-Identifier: EUPL-1.2
"""A5, Rest: Sprints, die nur aus anderen Feldern als „Fehltage bestätigt“ gelten (ältere Dateien
ohne gespeicherten Stand) und keine Fehltage haben, zählen in der erwarteten Fehltage-Quote mit
„0 % Ausfall“. Die Quote wird als unsicher gekennzeichnet – ohne dass sich eine Zahl ändert."""

import copy
import dataclasses
from datetime import date
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sprintforecast.capacity import absence_history
from sprintforecast.cli import app as cli_app
from sprintforecast.engine import CapacitySource
from sprintforecast.forecast import build_forecast
from sprintforecast.formulas import plain_explanation, steps
from sprintforecast.i18n import t
from sprintforecast.model import AbsenceState, absence_status
from sprintforecast.report import absence_derived_note, reliability_notes, render
from sprintforecast.storage import Repository

TODAY = date(2026, 10, 15)
NOTE = "Quote unsicher"
runner = CliRunner(env={"COLUMNS": "250"})


def edit(data_dir: Path, sprint_id: str, **fields) -> None:
    path = data_dir / "demo" / "sprints" / f"{sprint_id}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.update(fields)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")


def history_of(data_dir: Path, count: int = 4):
    data = Repository(data_dir).load("demo")
    fc = build_forecast(data, TODAY)
    past = [e.sprint for e in fc.history() if e.recorded]
    return data, fc, absence_history(data.team, data.people, past, count)


def old_rate(data, past, count):
    """Die bisherige Rechnung (vor der Kennzeichnung), unabhängig nachgebaut."""
    from sprintforecast.capacity import sprint_capacity

    rates = []
    for s in past:
        if absence_status(s) is not AbsenceState.CONFIRMED:
            continue
        without = copy.deepcopy(s)
        without.absences = {}
        full = sprint_capacity(data.team, data.people, without).gross
        if full > 0:
            rates.append(1 - sprint_capacity(data.team, data.people, s).gross / full)
    rates = rates[-count:]
    return (sum(rates) / len(rates) if rates else None), rates


def test_demo_data_has_no_derived_sprints(data_dir: Path):
    _, _, history = history_of(data_dir)
    assert history.sprints and history.derived == []
    assert absence_derived_note(history) is None


def test_legacy_sprint_without_absences_is_named(data_dir: Path):
    edit(data_dir, "2026.19", absences={})
    edit(data_dir, "2026.20", absences={})
    _, _, history = history_of(data_dir)
    assert history.derived == ["2026.19", "2026.20"]
    assert set(history.derived) <= set(history.sprints)
    note = absence_derived_note(history)
    assert note and NOTE in note and "`2026.19`, `2026.20`" in note
    assert "2 der Sprints" in note and "0 % Ausfall" in note
    detailed = absence_derived_note(history, detailed=True)
    assert detailed and detailed.startswith(note)
    assert "„Fehltage“" in detailed and "„Fehltage speichern“" in detailed


def test_explicitly_confirmed_sprint_without_absences_is_not_flagged(data_dir: Path):
    edit(data_dir, "2026.19", absences={}, absence_state="confirmed", absences_confirmed=True)
    _, _, history = history_of(data_dir)
    assert "2026.19" in history.sprints  # zählt mit Quote 0 mit
    assert history.derived == []
    assert absence_derived_note(history) is None


def test_sprint_with_recorded_absences_is_not_flagged(data_dir: Path):
    edit(data_dir, "2026.19", absences={"anna": 2})  # kein gespeicherter Stand, aber Einträge
    _, _, history = history_of(data_dir)
    assert history.derived == []


def test_unknown_sprint_is_neither_counted_nor_flagged(data_dir: Path):
    edit(data_dir, "2026.19", absences={}, absence_state="unknown")
    _, _, history = history_of(data_dir)
    assert "2026.19" not in history.sprints and history.derived == []


def test_only_sprints_inside_the_window_are_named(data_dir: Path):
    edit(data_dir, "2026.16", absences={})  # außerhalb der letzten vier
    _, _, history = history_of(data_dir, 4)
    assert "2026.16" not in history.sprints and history.derived == []
    _, _, wide = history_of(data_dir, 6)
    assert "2026.16" in wide.derived


@pytest.mark.parametrize(
    ("cleared", "explicit", "count"),
    [
        ([], [], 4),
        (["2026.19"], [], 4),
        (["2026.17", "2026.18", "2026.19", "2026.20"], [], 4),
        (["2026.17", "2026.18", "2026.19", "2026.20"], ["2026.18", "2026.20"], 4),
        (["2026.19"], ["2026.19"], 4),
        (["2026.19", "2026.20"], [], 2),
        (["2026.19"], [], 1),
    ],
)
def test_numbers_do_not_change(data_dir: Path, cleared: list[str], explicit: list[str], count: int):
    """Quote, Quoten je Sprint und alle Kapazitäten bleiben bitgleich zur bisherigen Rechnung –
    und gleich, ob ein Sprint nur abgeleitet oder ausdrücklich bestätigt ist."""
    for sprint_id in cleared:
        extra = {"absence_state": "confirmed"} if sprint_id in explicit else {}
        edit(data_dir, sprint_id, absences={}, **extra)
    data = Repository(data_dir).load("demo")
    data.team.capacity.absence_history = count
    fc = build_forecast(data, TODAY)
    past = [e.sprint for e in fc.history() if e.recorded]
    rate, rates = old_rate(data, past, count)
    assert fc.absences is not None
    assert fc.absences.rate == rate and fc.absences.rates == rates

    # Gegenprobe: alle abgeleiteten Stände ausdrücklich festhalten – dieselben Zahlen
    pinned = copy.deepcopy(data)
    for s in pinned.sprints:
        s.absence_state = absence_status(s)
    fc2 = build_forecast(pinned, TODAY)
    assert fc2.absences is not None and fc2.absences.derived == []
    assert (fc2.absences.rate, fc2.absences.rates, fc2.absences.sprints) == (
        fc.absences.rate,
        fc.absences.rates,
        fc.absences.sprints,
    )
    assert [e.result.plan_capacity for e in fc2.entries] == [
        e.result.plan_capacity for e in fc.entries
    ]
    assert [e.result.plan for e in fc2.entries] == [e.result.plan for e in fc.entries]
    expected = [s for s in cleared if s not in explicit and s in fc.absences.sprints]
    assert fc.absences.derived == expected


def estimated_forecast(data_dir: Path):
    data = Repository(data_dir).load("demo")
    fc = build_forecast(data, TODAY)
    assert any(e.result.plan_capacity_source is CapacitySource.ESTIMATED for e in fc.upcoming())
    return fc


def test_reliability_notes_and_report_name_the_sprints(data_dir: Path):
    edit(data_dir, "2026.19", absences={})
    fc = estimated_forecast(data_dir)
    notes = [n for n in reliability_notes(fc) if NOTE in n]
    assert len(notes) == 1 and "`2026.19`" in notes[0]
    assert f"⚠️ {notes[0]}" in render(fc)


def test_no_note_without_need(data_dir: Path):
    fc = estimated_forecast(data_dir)
    assert not any(NOTE in n for n in reliability_notes(fc))
    assert NOTE not in render(fc)
    edit(data_dir, "2026.19", absences={}, absence_state="confirmed")
    assert NOTE not in render(estimated_forecast(data_dir))


def test_no_note_when_the_rate_is_not_used(data_dir: Path):
    """Ohne geschätzte Sprints geht die Quote nirgends ein: Dann auch kein Hinweis."""
    edit(data_dir, "2026.19", absences={})
    data = Repository(data_dir).load("demo")
    data.team.capacity.absence_history = 0
    assert NOTE not in render(build_forecast(data, TODAY))

    fc = estimated_forecast(data_dir)
    assert fc.absences is not None and fc.absences.derived == ["2026.19"]
    for e in fc.entries:  # alle Kapazitäten kommen aus bestätigten Fehltagen
        if e.result.plan_capacity_source is CapacitySource.ESTIMATED:
            e.result = dataclasses.replace(e.result, plan_capacity_source=CapacitySource.PEOPLE)
    assert NOTE not in render(fc)


def test_rechenweg_names_the_uncertainty(data_dir: Path):
    edit(data_dir, "2026.19", absences={})
    fc = estimated_forecast(data_dir)
    entry = next(
        e for e in fc.upcoming() if e.result.plan_capacity_source is CapacitySource.ESTIMATED
    )
    capacity = next(s for s in steps(fc, entry) if s.key == "capacity")
    assert NOTE in capacity.formula and "2026.19" in capacity.formula
    assert "`" not in capacity.formula  # Tabelle: Klartext
    explanation = plain_explanation(fc, entry)
    assert (
        NOTE in explanation and "`2026.19`" in explanation and "„Fehltage speichern“" in explanation
    )

    data = Repository(data_dir).load("demo")
    data.sprint("2026.19").absence_state = AbsenceState.CONFIRMED
    fc2 = build_forecast(data, TODAY)
    entry2 = next(
        e for e in fc2.upcoming() if e.result.plan_capacity_source is CapacitySource.ESTIMATED
    )
    assert NOTE not in next(s for s in steps(fc2, entry2) if s.key == "capacity").formula
    assert NOTE not in plain_explanation(fc2, entry2)


def run_cli(data_dir: Path, *args: str):
    return runner.invoke(cli_app, ["--daten", str(data_dir), "--stichtag", "2026-10-15", *args])


def test_command_line_and_report_file(data_dir: Path):
    plain = run_cli(data_dir, "forecast", "demo")
    assert plain.exit_code == 0, plain.output
    assert NOTE not in plain.output
    edit(data_dir, "2026.19", absences={})
    result = run_cli(data_dir, "forecast", "demo")
    assert result.exit_code == 0, result.output
    assert NOTE in result.output and "2026.19" in result.output
    report = run_cli(data_dir, "bericht", "demo")
    assert report.exit_code == 0, report.output
    text = (data_dir / "demo" / "FORECAST.md").read_text(encoding="utf-8")
    assert f"⚠️ {NOTE}" in text and "`2026.19`" in text


APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"


def web_page(data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from sprintforecast.storage import DATA_ENV, STICHTAG_ENV

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.switch_page(f"seiten/{page}.py").run()
    assert not at.exception, at.exception
    return at


def shown(at) -> list[str]:
    return [w.value for w in at.warning] + [c.value for c in at.caption]


@pytest.mark.parametrize("page", ["fehltage", "forecast"])
def test_web_pages_show_the_note_only_when_needed(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str
):
    assert not any(NOTE in v for v in shown(web_page(data_dir, monkeypatch, page)))
    edit(data_dir, "2026.19", absences={})
    at = web_page(data_dir, monkeypatch, page)
    assert any(NOTE in v and "`2026.19`" in v for v in shown(at))
    edit(data_dir, "2026.19", absences={}, absence_state="confirmed")
    assert not any(NOTE in v for v in shown(web_page(data_dir, monkeypatch, page)))


def test_absence_page_explains_what_to_do(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    edit(data_dir, "2026.19", absences={})
    at = web_page(data_dir, monkeypatch, "fehltage")
    expander = next(e for e in at.expander if e.label == "Was tun bei unsicherer Quote?")
    text = " ".join(m.value for m in expander.markdown)
    assert "„Fehltage speichern“" in text and "Niemand fehlt" in text


def test_planning_page_shows_the_note(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    edit(data_dir, "2026.19", absences={})
    edit(data_dir, "2026.22", absences={}, expected_absences={})
    at = web_page(data_dir, monkeypatch, "planning")
    assert any("Gerechnet wird mit" in w.value for w in at.warning)  # Kapazität ist geschätzt
    assert any(NOTE in v and "`2026.19`" in v for v in shown(at))


def test_explicit_confirmation_of_a_legacy_sprint_is_not_stored(data_dir: Path):
    """Festgehaltene Einschränkung (siehe Hinweistext): Bei Sprints mit Velocity/Planning ergibt
    die Ableitung dasselbe wie „bestätigt“, daher schreibt das Speichern keinen Stand in die
    Datei – der Sprint bleibt „abgeleitet“, solange er keine Fehltage hat."""
    edit(data_dir, "2026.19", absences={})
    repo = Repository(data_dir)
    sprint = repo.load("demo").sprint("2026.19")
    sprint.absence_state = AbsenceState.CONFIRMED
    repo.save_sprint("demo", sprint)
    assert "absence_state" not in yaml.safe_load(
        (data_dir / "demo" / "sprints" / "2026.19.yaml").read_text(encoding="utf-8")
    )
    _, _, history = history_of(data_dir)
    assert history.derived == ["2026.19"]


def test_note_is_translated(data_dir: Path, english):
    edit(data_dir, "2026.19", absences={})
    _, _, history = history_of(data_dir)
    note = absence_derived_note(history, detailed=True)
    assert note and "Rate uncertain" in note and NOTE not in note
    assert "Save absences" in note
    assert t("Was tun bei unsicherer Quote?") == "What to do about an uncertain rate?"
