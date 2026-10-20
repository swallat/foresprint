# SPDX-License-Identifier: EUPL-1.2
"""A5, remainder: sprints that count as confirmed only through fields other than "absences
confirmed" (older files without a stored state) and have no absences are included in the expected
absence rate as "0 % lost". The rate is flagged as uncertain, without any number changing."""

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
from sprintforecast.report import (
    absence_derived_hint,
    absence_derived_note,
    reliability_notes,
    render,
)
from sprintforecast.storage import Repository
from sprintforecast.web.logic import absence_matrix, edit_absences, sprints_to_save

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
    """The previous calculation (before the flagging), rebuilt independently."""
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
    assert "2 Sprints" in note and "gelten nur als bestätigt" in note and "0 % Ausfall" in note
    detailed = absence_derived_note(history, detailed=True, window=4)
    assert detailed and detailed.startswith(note)
    assert "„Sprint vorbereiten: Fehltage“" in detailed and "„Fehltage speichern“" in detailed
    assert "Fenster der letzten 4 Sprints (Einstellung `absence_history`)" in detailed
    assert (
        "In der Tabelle „Stand der Fehltage“ gelten diese Sprints als bestätigt, weil sie "
        "bereits geplant oder ausgewertet wurden; es sind aber keine Fehltage gespeichert."
    ) in detailed
    hint = absence_derived_hint(history)
    assert hint and NOTE in hint and "2 Sprints" in hint and "2026.19" not in hint
    assert "„Sprint vorbereiten: Fehltage“" in hint


def test_singular_and_plural(data_dir: Path):
    edit(data_dir, "2026.19", absences={})
    _, _, history = history_of(data_dir)
    note = absence_derived_note(history)
    assert note and "1 Sprint in der" in note and "gilt nur als bestätigt" in note
    assert "bereits geplant oder ausgewertet wurde" in note and "Sprints" not in note.split("(")[0]
    hint = absence_derived_hint(history)
    assert hint and "1 Sprint der Quote" in hint
    edit(data_dir, "2026.20", absences={})
    _, _, history = history_of(data_dir)
    hint = absence_derived_hint(history)
    assert hint and "2 Sprints der Quote" in hint


def test_note_in_the_command_line_has_no_backticks(data_dir: Path):
    edit(data_dir, "2026.19", absences={})
    _, fc, history = history_of(data_dir)
    assert "`2026.19`" in (absence_derived_note(history) or "")
    note = absence_derived_note(history, code=False)
    assert note and "2026.19" in note and "`" not in note
    assert any("2026.19" in n and "`" not in n for n in reliability_notes(fc, code=False))


def test_explicitly_confirmed_sprint_without_absences_is_not_flagged(data_dir: Path):
    edit(data_dir, "2026.19", absences={}, absence_state="confirmed", absences_confirmed=True)
    _, _, history = history_of(data_dir)
    assert "2026.19" in history.sprints  # counts with rate 0
    assert history.derived == []
    assert absence_derived_note(history) is None


def test_sprint_with_recorded_absences_is_not_flagged(data_dir: Path):
    edit(data_dir, "2026.19", absences={"anna": 2})  # no stored state, but entries
    _, _, history = history_of(data_dir)
    assert history.derived == []


def test_unknown_sprint_is_neither_counted_nor_flagged(data_dir: Path):
    edit(data_dir, "2026.19", absences={}, absence_state="unknown")
    _, _, history = history_of(data_dir)
    assert "2026.19" not in history.sprints and history.derived == []


def test_only_sprints_inside_the_window_are_named(data_dir: Path):
    edit(data_dir, "2026.16", absences={})  # outside the last four
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
    """Rate, rates per sprint and all capacities stay bit-identical to the previous calculation,
    and the same whether a sprint is only derived or explicitly confirmed."""
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

    # Control: record all derived states explicitly, same numbers
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
    """Without estimated sprints the rate is not used anywhere: then no notice either."""
    edit(data_dir, "2026.19", absences={})
    data = Repository(data_dir).load("demo")
    data.team.capacity.absence_history = 0
    assert NOTE not in render(build_forecast(data, TODAY))

    fc = estimated_forecast(data_dir)
    assert fc.absences is not None and fc.absences.derived == ["2026.19"]
    for e in fc.entries:  # all capacities come from confirmed absences
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
    assert "`" not in capacity.formula  # table: plain text
    explanation = plain_explanation(fc, entry)
    assert (
        NOTE in explanation and "`2026.19`" in explanation and "„Fehltage speichern“" in explanation
    )
    assert "Fenster der letzten 4 Sprints" in explanation  # team setting
    assert NOTE not in plain_explanation(fc, entry, note=False)  # command line: separate
    assert NOTE not in next(s for s in steps(fc, entry, note=False) if s.key == "capacity").formula
    # Tooltip (Markdown): sprint IDs as code, the notice short and without IDs
    tip = next(s for s in steps(fc, entry, code=True) if s.key == "capacity").formula
    assert "`2026.19`" in tip and NOTE in tip and "Details auf der Seite" in tip
    assert tip.count("2026.19") == 1  # only in the rate list, not in the notice

    # Not estimated (e.g. recorded capacity): no notice although derived is filled
    assert fc.absences is not None and fc.absences.derived == ["2026.19"]
    recorded = dataclasses.replace(
        entry,
        result=dataclasses.replace(entry.result, plan_capacity_source=CapacitySource.RECORDED),
    )
    assert NOTE not in plain_explanation(fc, recorded)
    assert NOTE not in next(s for s in steps(fc, recorded) if s.key == "capacity").formula

    data = Repository(data_dir).load("demo")
    data.sprint("2026.19").absence_state = AbsenceState.CONFIRMED
    fc2 = build_forecast(data, TODAY)
    entry2 = next(
        e for e in fc2.upcoming() if e.result.plan_capacity_source is CapacitySource.ESTIMATED
    )
    assert NOTE not in next(s for s in steps(fc2, entry2) if s.key == "capacity").formula
    assert NOTE not in plain_explanation(fc2, entry2)


def run_cli(data_dir: Path, *args: str):
    return runner.invoke(cli_app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args])


def test_command_line_and_report_file(data_dir: Path):
    plain = run_cli(data_dir, "forecast", "demo")
    assert plain.exit_code == 0, plain.output
    assert NOTE not in plain.output
    edit(data_dir, "2026.19", absences={})
    result = run_cli(data_dir, "forecast", "demo")
    assert result.exit_code == 0, result.output
    assert NOTE in result.output and "2026.19" in result.output
    assert "`2026.19`" not in result.output  # command line: no Markdown backticks
    explained = run_cli(data_dir, "forecast", "demo", "--explain", "2026.23")
    assert explained.exit_code == 0, explained.output
    out = " ".join(explained.output.split())  # ignore console line breaks
    assert out.count(NOTE) == 1  # only the ⚠ line, not also explanatory text and table cell
    for web_only in ("`2026.19`", "`absence_history`", "`sprintforecast absences`"):
        assert web_only not in out  # no Markdown backticks in the console
    for web_text in ("Fehltage speichern", "Stand der Fehltage", "Sprint vorbereiten: Fehltage"):
        assert web_text not in out  # no instructions for the web UI
    assert "sprintforecast absences demo <SPRINT>" in out  # the command instead
    assert "Fenster der letzten 4 Sprints" in out
    report = run_cli(data_dir, "report", "demo")
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
    return (
        [w.value for w in at.warning] + [c.value for c in at.caption] + [i.value for i in at.info]
    )


def hints(at) -> list[str]:
    return [v for v in shown(at) if NOTE in v]


@pytest.mark.parametrize("page", ["fehltage", "forecast", "vorplanung", "planning"])
def test_web_pages_show_the_note_only_when_needed(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str
):
    edit(data_dir, "2026.22", absences={}, expected_absences={})
    assert not hints(web_page(data_dir, monkeypatch, page))
    edit(data_dir, "2026.19", absences={})
    at = web_page(data_dir, monkeypatch, page)
    found = hints(at)
    assert found, page
    if page == "fehltage":  # detailed, with the sprints, as information (no warning)
        assert any("`2026.19`" in v for v in found)
        assert not any(NOTE in w.value for w in at.warning)
        assert any(NOTE in i.value for i in at.info)
    else:  # short, without list, with a pointer to the page
        assert all("2026.19" not in v and "Sprint vorbereiten: Fehltage" in v for v in found)
    edit(data_dir, "2026.19", absences={}, absence_state="confirmed")
    assert not hints(web_page(data_dir, monkeypatch, page))


def confirm_all_upcoming(data_dir: Path) -> None:
    """All future sprints get confirmed absences: nothing is estimated anymore."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    for e in build_forecast(data, TODAY).upcoming():
        sprint = data.sprint(e.sprint.id) or e.sprint
        sprint.absence_state = AbsenceState.CONFIRMED
        repo.save_sprint("demo", sprint)


@pytest.mark.parametrize("page", ["forecast", "vorplanung", "planning"])
def test_web_pages_without_estimated_sprints_show_no_hint(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str
):
    edit(data_dir, "2026.19", absences={})
    confirm_all_upcoming(data_dir)
    fc = build_forecast(Repository(data_dir).load("demo"), TODAY)
    assert fc.absences is not None and fc.absences.derived == ["2026.19"]
    assert not any(e.result.plan_capacity_source is CapacitySource.ESTIMATED for e in fc.upcoming())
    assert not hints(web_page(data_dir, monkeypatch, page))


@pytest.mark.parametrize("page", ["planning", "vorplanung"])
def test_tooltips_show_foreign_sprint_ids_only_as_code(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str
):
    """Sprint IDs come from files; the tooltips are Markdown (bold, links)."""
    evil = "2026.19 **fett** www.e.de"
    sprints = data_dir / "demo" / "sprints"
    raw = yaml.safe_load((sprints / "2026.19.yaml").read_text(encoding="utf-8"))
    raw.update(id=evil, absences={})
    (sprints / "2026.19.yaml").unlink()
    (sprints / f"{evil}.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    edit(data_dir, "2026.22", absences={}, expected_absences={})  # the selected sprint: estimated
    fc = estimated_forecast(data_dir)
    assert fc.absences is not None and fc.absences.derived == [evil]

    at = web_page(data_dir, monkeypatch, page)
    tips = [m.help for m in at.metric if m.label == "Kapazität (PT)"]
    assert tips and all("Fehltage unbekannt" in tip for tip in tips), page
    for tip in tips:
        assert f"`{evil}`" in tip  # as code span
        assert evil not in tip.replace(f"`{evil}`", "")  # nowhere else raw
        assert "Quote unsicher" in tip and tip.count("Quote unsicher") == 1


def test_absence_page_explains_what_to_do(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    edit(data_dir, "2026.19", absences={})
    at = web_page(data_dir, monkeypatch, "fehltage")
    expander = next(e for e in at.expander if e.label == "Was tun bei unsicherer Quote?")
    text = " ".join(m.value for m in expander.markdown)
    assert "„Sprint vorbereiten: Fehltage“" in text and "„Fehltage speichern“" in text
    assert "Fenster der letzten 4 Sprints (Einstellung `absence_history`)" in text
    assert "bereits geplant oder ausgewertet" in text


def test_planning_page_shows_the_note(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    edit(data_dir, "2026.19", absences={})
    edit(data_dir, "2026.22", absences={}, expected_absences={})
    at = web_page(data_dir, monkeypatch, "planning")
    assert any("Gerechnet wird mit" in w.value for w in at.warning)  # capacity is estimated
    assert hints(at)


def test_explicit_confirmation_of_a_legacy_sprint_is_not_stored(data_dir: Path):
    """Recorded limitation (see notice text): for sprints with velocity/planning the derivation
    gives the same as "confirmed", so saving writes no state to the file; the sprint stays
    "derived" as long as it has no absences."""
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


def test_confirming_a_legacy_sprint_on_the_absence_page_saves_nothing(data_dir: Path):
    """UI path: "Nobody is absent" is already ticked for the derived sprint; there is nothing to
    save, the notice stays (separate, open decision of the owner)."""
    edit(data_dir, "2026.19", absences={})
    data = Repository(data_dir).load("demo")
    originals = [data.sprint("2026.19")]
    rows = absence_matrix(data.people, originals)
    edited = edit_absences(data.people, originals, rows, confirmed={"2026.19"})
    assert sprints_to_save(data, originals, edited) == []


def sprint_like(data, sprint_id: str, **fields):
    return dataclasses.replace(data.sprint("2026.19"), id=sprint_id, **fields)


def test_expected_only_sprint_is_neither_counted_nor_flagged(data_dir: Path):
    data = Repository(data_dir).load("demo")
    past = [e.sprint for e in build_forecast(data, TODAY).history() if e.recorded]
    before = absence_history(data.team, data.people, past, 4)
    expected = sprint_like(
        data,
        "x.expected",
        absences={},
        absence_state=None,
        expected_absences={data.people[0].id: 2.0},
        velocity=None,
        forecast_ist=None,
        forecast_plan=None,
        planning=None,
    )
    assert absence_status(expected) is AbsenceState.EXPECTED
    after = absence_history(data.team, data.people, [*past, expected], 4)
    assert after == before  # rate, rates, sprints and derived unchanged
    assert "x.expected" not in after.sprints and "x.expected" not in after.derived


def test_sprint_without_capacity_is_neither_counted_nor_flagged(data_dir: Path):
    data = Repository(data_dir).load("demo")
    past = [e.sprint for e in build_forecast(data, TODAY).history() if e.recorded]
    before = absence_history(data.team, data.people, past, 4)
    # Before all people have joined: gross capacity 0, but "derived confirmed"
    empty = sprint_like(
        data,
        "x.empty",
        start=date(2000, 1, 3),
        end=date(2000, 1, 17),
        absences={},
        absence_state=None,
        velocity=1.0,
    )
    assert absence_status(empty) is AbsenceState.CONFIRMED
    after = absence_history(data.team, data.people, [*past, empty], 4)
    assert after == before
    assert "x.empty" not in after.sprints and "x.empty" not in after.derived


def test_note_is_translated(data_dir: Path, english):
    edit(data_dir, "2026.19", absences={})
    _, _, history = history_of(data_dir)
    note = absence_derived_note(history, detailed=True, window=4)
    assert note and "Rate uncertain" in note and NOTE not in note
    assert "1 sprint in the" in note and "only counts as confirmed" in note
    assert '"Prepare the sprint: absences" page' in note and "Save absences" in note
    assert "last 4 sprints" in note
    hint = absence_derived_hint(history)
    assert hint and "1 sprint in the rate" in hint and "Prepare the sprint: absences" in hint
    edit(data_dir, "2026.20", absences={})
    _, _, history = history_of(data_dir)
    assert "2 sprints in the" in (absence_derived_note(history) or "")
    assert t("What to do about an uncertain rate?") == "What to do about an uncertain rate?"
