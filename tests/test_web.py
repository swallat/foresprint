# SPDX-License-Identifier: EUPL-1.2
"""Web UI: render pages, save forms, commit (without a browser, via AppTest)."""

import shutil
import subprocess
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from webfixtures import STEP_DONE_MARK, nav_done, nav_help, nav_links, nav_steps, nav_titles

from sprintforecast.forecast import build_forecast
from sprintforecast.i18n import t
from sprintforecast.model import Sprint
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository
from sprintforecast.web import ui
from sprintforecast.web.ui import PAGE_FEATURES, PAGE_INFO, PAGES, START_TASKS

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"


def start(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


@pytest.fixture
def app(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    return start(data_dir, monkeypatch)


def goto(at: AppTest, page: str) -> AppTest:
    at.switch_page(f"seiten/{page}.py").run()
    assert not at.exception, at.exception
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception
    return at


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_invalid_as_of_variable_shows_error(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "morgen")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert len(at.error) == 1
    for part in (STICHTAG_ENV, "morgen", "JJJJ-MM-TT"):
        assert part in at.error[0].value
    assert not at.header  # the page is not drawn


def test_start_is_default_page(app: AppTest):
    assert app.header[0].value == "Was möchtest du tun?"
    # 2026.22 is prepared (absences, pre-planning) but not scheduled yet
    assert [s.value for s in app.subheader] == [
        "✅ Sprint vorbereiten",
        "⬜ Planning",
        "⬜ Sprint abschließen",
    ]


def test_start_tasks_lead_to_the_next_sensible_step(app: AppTest):
    """Today is 2026-10-15: 2026.21 is running (review open), 2026.22 is the next candidate."""
    app.button(key="start-planning").click().run()
    assert not app.exception, app.exception
    assert app.header[0].value == "Sprint Planning"
    assert app.selectbox(key="planning-sprint").value == "2026.22"

    goto(app, "start")
    app.button(key="start-review").click().run()
    assert not app.exception, app.exception
    assert app.header[0].value == "Sprint Review"
    assert app.selectbox(key="review-sprint").value == "2026.21"


def _change_2026_22(data_dir: Path, **fields) -> None:
    path = data_dir / "demo" / "sprints" / "2026.22.yaml"
    raw = yaml.safe_load(path.read_text())
    raw.update(fields)
    path.write_text(yaml.safe_dump(raw))


def test_start_prepare_asks_for_absences_when_unknown(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _change_2026_22(data_dir, absences={})
    at = start(data_dir, monkeypatch)
    assert any("Fehltage unbekannt" in w.value for w in at.main.markdown)
    at.button(key="start-prepare").click().run()
    assert at.header[0].value == "Planbare Fehltage"


def test_start_prepare_asks_for_preplanning_once_absences_are_known(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _change_2026_22(data_dir, products={})
    at = start(data_dir, monkeypatch)
    assert any("PO-Vorplanung fehlt noch" in w.value for w in at.main.markdown)
    at.button(key="start-prepare").click().run()
    assert at.header[0].value == "PO-Vorplanung"
    assert at.selectbox(key="vorplanung-sprint").value == "2026.22"


def test_start_prepare_still_asks_while_one_product_has_no_value(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _change_2026_22(data_dir, products={"webshop": {"preplanned": 3.0}})
    at = start(data_dir, monkeypatch)
    assert any("PO-Vorplanung fehlt noch" in w.value for w in at.main.markdown)


def test_start_prepare_is_not_stuck_without_products(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Products feature on, but no products created: no permanent pre-planning."""
    import shutil

    shutil.rmtree(data_dir / "demo" / "products", ignore_errors=True)
    (data_dir / "demo" / "products.yaml").unlink(missing_ok=True)
    _change_2026_22(data_dir, products={})
    at = start(data_dir, monkeypatch)
    assert not any("PO-Vorplanung fehlt noch" in w.value for w in at.main.markdown)


def test_forecast_page_shows_the_forecast(app: AppTest):
    goto(app, "forecast")
    values = [m.value for m in app.metric]
    assert values[:2] == ["9,5 PT", "11,2 PT"]  # like `sprintforecast forecast demo`
    # With a people list the capacity comes from calendar and people: no trend warning
    assert not any("Trend" in w.value for w in app.warning)


def test_forecast_range_stays_short_and_names_its_samples_below(app: AppTest):
    """The line under the metric is cut off with four columns: only the range itself,
    the number of sprints behind it is in the label."""
    goto(app, "forecast")
    deltas = [m.delta for m in app.metric[:3]]
    assert all(d.startswith("Spanne ") and "(" not in d for d in deltas), deltas
    assert all(len(d) <= 20 for d in deltas), deltas
    captions = [c.value for c in app.caption]
    assert sum("Spanne aus den letzten 5 Sprints" in c for c in captions) >= 1


def test_forecast_warns_when_absences_unknown_and_no_history(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    team = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team.read_text())
    raw["capacity"]["absence_history"] = 0  # no estimate
    team.write_text(yaml.safe_dump(raw))
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any(
        "2026.23" in w.value and "Kalender, Fehltage unbekannt" in w.value for w in at.warning
    )


@pytest.mark.parametrize("page", sorted(PAGE_INFO))
def test_pages_render(data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str):
    if feature := PAGE_FEATURES.get(page):  # the page only exists with its feature switched on
        team = data_dir / "demo" / "team.yaml"
        raw = yaml.safe_load(team.read_text())
        raw["features"][feature] = True
        team.write_text(yaml.safe_dump(raw))
    app = start(data_dir, monkeypatch)
    goto(app, page)
    assert not app.error
    assert app.header[0].value


def test_help_shows_workflow_and_terms(app: AppTest):
    goto(app, "hilfe")
    assert [t.label for t in app.tabs] == [
        "Ablauf", "Begriffe", "Eingabefelder", "Team-Einstellungen", "Zusammenarbeit (Git)",
        "Kommandozeile",
    ]  # fmt: skip
    assert any("Commitment" in c.value for c in app.caption)  # source: Commitment


def test_absences_save_does_not_confirm_silently(app: AppTest, data_dir: Path):
    """Saving without an entry and without explicit confirmation creates nothing (B2)."""
    goto(app, "fehltage")
    assert not any("angelegt" in c.value for c in app.caption)
    assert next(b for b in app.button if b.label == "Fehltage speichern").disabled
    assert not (data_dir / "demo" / "sprints" / "2026.24.yaml").exists()


def test_absences_confirm_nobody_absent_creates_sprint_files(app: AppTest, data_dir: Path):
    goto(app, "fehltage")
    frame = next(d.value for d in app.dataframe if "Niemand fehlt" in d.value.columns)
    states = f"absence-states-{frame['Sprint'].iloc[0]}-{len(frame)}"
    rows = {
        i: {"Niemand fehlt": True}
        for i, sprint in enumerate(frame["Sprint"])
        if sprint in ("2026.23", "2026.24")
    }
    app.session_state[states] = {"edited_rows": rows, "added_rows": [], "deleted_rows": []}
    app.run()
    assert any("2026.23, 2026.24 angelegt" in c.value for c in app.caption)
    click(app, "Fehltage speichern")
    saved = load(data_dir / "demo" / "sprints" / "2026.24.yaml")
    assert saved["absences"] == {} and saved["absence_state"] == "confirmed"
    assert saved["absences_confirmed"] is True  # older program versions keep reading it
    goto(app, "forecast")
    assert not any("Trend" in w.value for w in app.warning)


def test_reset_absences_text_names_calendar_and_people_not_trend(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """After the reset the capacity from calendar and people remains; only the absences
    are estimated from the history (a trend exists only without a people list)."""
    repo = Repository(data_dir)
    nxt = build_forecast(repo.load("demo"), date(2026, 10, 15)).entries[-1].sprint
    repo.save_sprint("demo", Sprint(id=nxt.id, start=nxt.start, end=nxt.end))
    at = goto(start(data_dir, monkeypatch), "fehltage")
    assert "Fehltage zurücksetzen" in [s.value for s in at.subheader]
    caption = next(c.value for c in at.caption if "Zurücksetzen löscht" in c.value)
    assert "Trend" not in caption
    assert "nach der Historie geschätzt (ohne Historie ohne Abzug)" in caption
    assert "Kalender und Personen" in caption


def planning_step(at: AppTest, sprint: str, step: int) -> AppTest:
    """Planning page: pick a sprint and jump to step (0-2) of the flow."""
    goto(at, "planning")
    at.selectbox(key="planning-sprint").set_value(sprint).run()
    at.radio(key="planning-step").set_value(step).run()
    assert not at.exception, at.exception
    return at


def test_planning_defaults_to_next_planning(app: AppTest):
    goto(app, "planning")
    # 2026.21 is running and already planned (Commitment) -> next is 2026.22
    assert app.selectbox(key="planning-sprint").value == "2026.22"
    assert app.radio(key="planning-step").value == 0


def test_planning_flow_absences_then_plan(app: AppTest, data_dir: Path):
    goto(app, "planning")
    assert any("Arbeitstage (Mo–Fr)" in c.value for c in app.caption)
    click(app, "Weiter")  # absences unchanged, sprint file exists
    assert app.radio(key="planning-step").value == 1
    assert any(m.label.startswith("Prognose aktuell") for m in app.metric)
    assert any("Standard = Forecast PLAN" in c.value for c in app.caption)


def test_planning_saves(app: AppTest, data_dir: Path):
    planning_step(app, "2026.21", 2)
    app.number_input(key="fist-2026.21").set_value(9.5)
    app.number_input(key="backlog-2026.21").set_value(8.0)
    app.text_input[0].set_value("0,5 1")
    click(app, "Planning speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert sprint["forecast_ist"] == 9.5
    assert sprint["planning"]["backlog"] == 8
    assert sprint["planning"]["corrections"] == [0.5, 1]
    assert any("Delta" in i.value for i in app.info)


def test_planning_commitment_writes_a_protocol_with_all_sections(app: AppTest, data_dir: Path):
    planning_step(app, "2026.21", 2)
    app.number_input(key="fist-2026.21").set_value(9.5)
    click(app, "Planning speichern")
    [path] = (data_dir / "demo" / "protokolle").glob("2026.21-planning-*.md")
    text = path.read_text(encoding="utf-8")
    assert text.index("## Fehltage") < text.index("## Einplanung") < text.index("## Commitment")
    assert "- Commitment (PT): 9,5" in text
    assert text.count("_Stand: ") >= 1


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e999"])
def test_planning_rejects_non_finite_corrections(app: AppTest, data_dir: Path, raw: str):
    path = data_dir / "demo" / "sprints" / "2026.21.yaml"
    before = path.read_bytes()
    planning_step(app, "2026.21", 2)
    app.number_input(key="backlog-2026.21").set_value(8.0)
    app.text_input[0].set_value(raw)
    click(app, "Planning speichern")
    assert any("endliche Zahlen" in e.value for e in app.error)
    assert path.read_bytes() == before


def test_review_saves_and_freezes_capacity(app: AppTest, data_dir: Path):
    goto(app, "review")
    app.selectbox(key="review-sprint").set_value("2026.21").run()
    app.number_input(key="velocity-2026.21").set_value(9.25)
    next(n for n in app.number_input if n.label == "Scope Creep (%)").set_value(10.0)
    click(app, "Review speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert sprint["capacity"] == 25.5
    assert sprint["velocity"] == 9.25
    assert sprint["scope_creep"] == pytest.approx(0.1)
    assert app.session_state["pending_tags"] == ["demo/2026.21"]


def test_settings_save(app: AppTest, data_dir: Path):
    goto(app, "einstellungen")
    app.selectbox(key="settings-demo-forecast.trend_mode").set_value("classic")
    app.number_input(key="settings-demo-forecast.roadmap_share").set_value(70.0)
    click(app, "Speichern")
    team = load(data_dir / "demo" / "team.yaml")
    assert team["forecast"]["trend_mode"] == "classic"
    assert team["forecast"]["roadmap_share"] == pytest.approx(0.7)
    assert any("rückwirkend" in w.value for w in app.warning)


def test_overhead_fields_stay_in_sync(app: AppTest, data_dir: Path):
    goto(app, "einstellungen")
    app.number_input(key="settings-demo-capacity.overhead_days").set_value(1.0).run()
    # 14 calendar days = 10 working days -> 1 PD = 10 %
    assert app.number_input(key="settings-demo-capacity.overhead_share").value == 10.0
    app.number_input(key="settings-demo-capacity.overhead_share").set_value(20.0).run()
    assert app.number_input(key="settings-demo-capacity.overhead_days").value == 2.0
    click(app, "Speichern")
    capacity = load(data_dir / "demo" / "team.yaml")["capacity"]
    assert capacity["overhead_share"] == pytest.approx(0.2)
    assert capacity["overhead_days"] == 2


def test_new_team(app: AppTest, data_dir: Path):
    goto(app, "neues_team")
    app.text_input[0].set_value("team-b").run()
    app.text_input(key="new-team-b-sprint.first_id").set_value("2026.15")
    app.text_input(key="new-team-b-capacity.region").set_value("BY")
    click(app, "Team anlegen")
    team = load(data_dir / "team-b" / "team.yaml")
    assert team["capacity"]["region"] == "BY"
    assert team["sprint"]["first"] == {"id": "2026.15", "start": date(2026, 10, 15)}
    assert app.session_state["selected_team"] == "team-b"


def test_new_team_asks_for_the_first_sprint_first(app: AppTest):
    """The first sprint is its own section before all other settings, the ID without a default
    (a prefilled 2026.1 was overlooked and then hard to change)."""
    goto(app, "neues_team")
    app.text_input[0].set_value("team-b").run()
    assert [h.value for h in app.subheader] == ["Erster Sprint", "Weitere Einstellungen"]
    # Per field type in page order: the first sprint comes before name, unit, etc.
    assert app.text_input[1].key == "new-team-b-sprint.first_id"  # right after the abbreviation
    assert app.text_input[2].key == "new-team-b-name"
    assert app.selectbox[0].key == "new-team-b-sprint.numbering"
    assert app.date_input[0].key == "new-team-b-sprint.first_start"
    assert app.text_input(key="new-team-b-sprint.first_id").value == ""


def test_new_team_requires_the_first_sprint_id(app: AppTest, data_dir: Path):
    goto(app, "neues_team")
    app.text_input[0].set_value("team-b").run()
    click(app, "Team anlegen")
    assert any("ID des ersten Sprints: Bitte einen Wert eingeben." in e.value for e in app.error)
    assert not (data_dir / "team-b").exists()
    assert app.session_state.get("selected_team") != "team-b"


@pytest.mark.parametrize("key", ["../x", "a/b", "..", "con", "-x", "a" * 65])
def test_new_team_rejects_invalid_key(app: AppTest, data_dir: Path, key: str):
    goto(app, "neues_team")
    app.text_input[0].set_value(key).run()
    assert not app.exception, app.exception
    assert any("Kleinbuchstaben a–z" in e.value or "Windows" in e.value for e in app.error)
    assert not [b for b in app.button if b.label == "Team anlegen"]  # no form
    assert sorted(p.name for p in data_dir.parent.iterdir()) == ["teams"]
    assert sorted(p.name for p in data_dir.iterdir()) == ["demo"]


def test_new_team_refuses_a_key_that_only_differs_in_case(app: AppTest, data_dir: Path):
    shutil.copytree(data_dir / "demo", data_dir / "Alpha")
    goto(app, "neues_team")
    app.text_input[0].set_value("alpha").run()
    assert any("existiert bereits (als 'Alpha'" in e.value for e in app.error)
    assert not [b for b in app.button if b.label == "Team anlegen"]
    assert sorted(p.name for p in data_dir.iterdir()) == ["Alpha", "demo"]


def test_new_team_key_is_normalized_before_the_check(app: AppTest, data_dir: Path):
    goto(app, "neues_team")
    app.text_input[0].set_value("  Team_C ").run()
    assert not app.error
    app.text_input(key="new-team_c-sprint.first_id").set_value("2026.15")
    click(app, "Team anlegen")
    assert (data_dir / "team_c" / "team.yaml").is_file()
    assert app.session_state["selected_team"] == "team_c"


def test_without_any_team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    at = start(tmp_path, monkeypatch)
    assert any("Noch kein Team" in i.value for i in at.info)
    for page in ("neues_team", "hilfe", "personen"):
        goto(at, page)


def test_team_without_history(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression: an empty chart crashed the Forecast page."""
    team = data_dir / "aaa-neu"
    team.mkdir()
    (team / "team.yaml").write_text(
        "name: Neu\nsprint:\n  first: {id: '2026.20', start: 2026-10-14}\n"
    )
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert at.sidebar.selectbox[1].value == "aaa-neu"
    assert any("Noch keine Werte" in i.value for i in at.info)
    for page in ("fehltage", "planning", "review", "personen", "einstellungen"):
        goto(at, page)


def test_git_panel_without_repository(app: AppTest):
    assert any("in keinem Git-Repository" in c.value for c in app.sidebar.caption)


def test_commit_button(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "T")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "t@t")
    git(data_dir, "init", "-q", "-b", "main")
    git(data_dir, "add", "-A")
    git(data_dir, "commit", "-qm", "init")
    at = start(data_dir, monkeypatch)
    assert any("alles committet" in e.label for e in at.sidebar.expander)

    goto(at, "review")
    at.selectbox(key="review-sprint").set_value("2026.21").run()
    at.number_input(key="velocity-2026.21").set_value(9.0)
    click(at, "Review speichern")
    assert at.session_state["pending_tags"] == ["demo/2026.21"]

    # New run through the main script (AppTest does not render the sidebar again after page
    # switches); pending tags live in the session state.
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.session_state["pending_tags"] = ["demo/2026.21"]
    at.run()
    # Sprint file and review minutes (protokolle/2026.21-review-....md).
    assert any("2 offene Änderung" in e.label for e in at.sidebar.expander)
    at.text_input(key="commit_message").set_value("Review 2026.21")
    next(b for b in at.button if b.label == "Änderungen committen").click().run()
    assert git(data_dir, "log", "-1", "--format=%s") == "Review 2026.21"
    assert git(data_dir, "tag") == "demo/2026.21"
    assert git(data_dir, "status", "--porcelain") == ""
    assert at.session_state["pending_tags"] == []


def save_review(at: AppTest, button: str = "Review speichern") -> str:
    """Saves a review and returns the success message."""
    goto(at, "review")
    at.selectbox(key="review-sprint").set_value("2026.21").run()
    at.number_input(key="velocity-2026.21").set_value(9.0)
    click(at, button)
    return next(s.value for s in at.success if s.value.startswith(("Gespeichert", "Saved")))


def sidebar_buttons(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Sidebar buttons in a new run (after saving)."""
    return [b.label for b in start(data_dir, monkeypatch).sidebar.button]


def test_saved_message_without_git_names_no_button(app: AppTest):
    message = save_review(app)
    assert message == "Gespeichert: 2026.21.yaml."


def test_saved_message_with_git_but_no_server_points_to_commit(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    message = save_review(start(data_dir, monkeypatch))
    assert "**Änderungen committen**" in message
    assert "Speichern und teilen" not in message
    buttons = sidebar_buttons(data_dir, monkeypatch)
    assert "Änderungen committen" in buttons and "Speichern und teilen" not in buttons


def test_saved_message_without_branch_names_no_button(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without a branch the sidebar only offers "Back to the branch"."""
    git(repo, "checkout", "-q", "--detach")
    message = save_review(start(data_dir, monkeypatch))
    assert message == "Gespeichert: 2026.21.yaml."
    assert "Änderungen committen" not in sidebar_buttons(data_dir, monkeypatch)


def test_saved_message_with_server_points_to_save_and_share(
    shared, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    message = save_review(start(data_dir, monkeypatch))
    assert message.startswith("Gespeichert: 2026.21.yaml. Mit **Speichern und teilen**")
    assert message.endswith(
        "in Git sichern und mit dem Team teilen (nur lokal: **Änderungen committen**)."
    )
    buttons = sidebar_buttons(data_dir, monkeypatch)
    assert "Speichern und teilen" in buttons and "Änderungen committen" in buttons


def test_saved_message_with_server_is_also_flashed(
    shared, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    at = goto(start(data_dir, monkeypatch), "planning")
    at.selectbox(key="planning-sprint").set_value("2026.23").run()
    click(at, "Niemand fehlt – bestätigen und weiter")
    assert any("Mit **Speichern und teilen**" in s.value for s in at.success)


def test_saved_message_in_english(english, shared, data_dir: Path, monkeypatch):
    message = save_review(start(data_dir, monkeypatch), "Save review")
    assert message == (
        "Saved: 2026.21.yaml. Use **Save and share** in the sidebar to save to Git and share "
        "with the team (local only: **Commit changes**)."
    )


def test_saved_message_names_no_button_when_the_content_was_already_saved(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Saving the same state again changes nothing: the sidebar then offers no "Commit changes"
    button, and the message does not mention it either."""
    from sprintforecast.git import invalidate_status

    save_review(start(data_dir, monkeypatch))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Review")
    invalidate_status()
    message = save_review(start(data_dir, monkeypatch))
    assert message == "Gespeichert: 2026.21.yaml."
    assert "Änderungen committen" not in sidebar_buttons(data_dir, monkeypatch)


def test_saved_message_with_server_names_no_button_when_nothing_changed(
    shared, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    from sprintforecast.git import invalidate_status

    save_review(start(data_dir, monkeypatch))
    git(data_dir.parent, "add", "-A")
    git(data_dir.parent, "commit", "-qm", "Review")
    invalidate_status()
    message = save_review(start(data_dir, monkeypatch))
    assert message == "Gespeichert: 2026.21.yaml."


def test_saving_still_works_when_git_cannot_report_its_state(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """The notice must never prevent saving."""
    from sprintforecast.git import GitError
    from sprintforecast.web import ui

    def broken(root: Path):
        raise GitError("kaputt")

    monkeypatch.setattr(ui, "cached_sync_state", broken)
    message = save_review(start(data_dir, monkeypatch))
    assert message == "Gespeichert: 2026.21.yaml."
    saved = yaml.safe_load((data_dir / "demo" / "sprints" / "2026.21.yaml").read_text())
    assert saved["velocity"] == 9


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "commit"),
        ({"remote": "origin"}, "share"),
        ({"unfinished": "merge"}, ""),
        ({"conflicts": ("2026.21.yaml",)}, ""),
        ({"branch": None}, ""),
    ],
)
def test_next_step_follows_what_the_sidebar_offers(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, changes: dict, expected: str
):
    import dataclasses

    from sprintforecast.gitsync import SyncState
    from sprintforecast.web import ui

    state = SyncState(root=data_dir, branch="main", upstream=None, remote=None)
    monkeypatch.setattr(ui, "data_dir", lambda: data_dir)
    monkeypatch.setattr(ui, "git_available", lambda: True)
    monkeypatch.setattr(ui, "git_root", lambda root: root)
    monkeypatch.setattr(ui, "cached_sync_state", lambda root: dataclasses.replace(state, **changes))
    assert ui._next_step() == expected


def test_next_step_is_empty_without_git_or_repository(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    from sprintforecast.web import ui

    monkeypatch.setattr(ui, "data_dir", lambda: data_dir)
    monkeypatch.setattr(ui, "git_available", lambda: False)
    assert ui._next_step() == ""
    monkeypatch.setattr(ui, "git_available", lambda: True)
    monkeypatch.setattr(ui, "git_root", lambda root: None)
    assert ui._next_step() == ""


def test_help_intro_names_both_ways_to_secure_the_changes(app: AppTest):
    goto(app, "hilfe")
    intro = app.main.markdown[0].value
    assert "**Änderungen committen**" in intro and "**Speichern und teilen**" in intro
    assert "Reiter „Zusammenarbeit (Git)“" in intro
    assert "Zusammenarbeit (Git)" in [tab.label for tab in app.tabs]


def test_commit_button_refuses_files_with_conflict_markers(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Markers without an open merge: nothing is committed, the message names the file and the
    way to the "Resolve conflicts" page."""
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "T")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "t@t")
    git(data_dir, "init", "-q", "-b", "main")
    git(data_dir, "add", "-A")
    git(data_dir, "commit", "-qm", "init")
    sprint = data_dir / "demo" / "sprints" / "2026.21.yaml"
    sprint.write_text(
        "<<<<<<< HEAD\nvelocity: 5\n=======\nvelocity: 7\n>>>>>>> origin/main\n", encoding="utf-8"
    )
    at = start(data_dir, monkeypatch)
    at.text_input(key="commit_message").set_value("Mit Markierungen")
    next(b for b in at.button if b.label == "Änderungen committen").click().run()
    assert not at.exception, at.exception
    assert git(data_dir, "log", "-1", "--format=%s") == "init"
    shown = " ".join(e.value for e in [*at.sidebar.error, *at.error])
    shown = shown.replace("\\", "")  # Markdown escaping (md_plain)
    assert "Konflikte lösen" in shown and "2026.21.yaml" in shown


def test_planning_prefills_commitment(app: AppTest, data_dir: Path):
    planning_step(app, "2026.22", 2)
    assert app.number_input(key="fist-2026.22").value is None  # not the value of 2026.21
    app.number_input(key="carry-2026.22").set_value(1.5)
    app.number_input(key="backlog-2026.22").set_value(11.0)
    click(app, "Planning speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.22.yaml")
    assert sprint["forecast_ist"] == 12.5
    assert any("Überkipper + Backlog übernommen" in i.value for i in app.info)


def test_planning_warns_on_mismatch(app: AppTest, data_dir: Path):
    planning_step(app, "2026.22", 2)
    app.number_input(key="fist-2026.22").set_value(20.0)
    app.number_input(key="backlog-2026.22").set_value(11.0)
    click(app, "Planning speichern")
    assert load(data_dir / "demo" / "sprints" / "2026.22.yaml")["forecast_ist"] == 20
    assert any("weicht von Überkipper + Backlog" in w.value for w in app.warning)


def test_planning_control_calculation_is_optional(app: AppTest, data_dir: Path):
    planning_step(app, "2026.22", 2)
    app.number_input(key="fist-2026.22").set_value(11.0)
    click(app, "Planning speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.22.yaml")
    assert sprint["forecast_ist"] == 11
    assert "planning" not in sprint


def test_sidebar_on_every_page(app: AppTest):
    """Regression: a `pages/` folder activated Streamlit's old page detection, so direct page
    calls ran without navigation and team selection."""
    for page in ("planning", "hilfe", "pruefung"):
        goto(app, page)
        assert app.sidebar.selectbox[1].value == "demo"


def test_people_page_toggle_former(app: AppTest):
    goto(app, "personen")
    assert any("1 ehemalige Person" in c.value for c in app.caption)
    app.toggle(key="show_former").set_value(True).run()
    assert not any("ehemalige Person" in c.value for c in app.caption)
    click(app, "Personen speichern")  # saving unchanged works without a prompt
    assert any("Gespeichert" in s.value for s in app.success)


def test_analysis_page(app: AppTest):
    goto(app, "analyse")
    assert app.header[0].value == "Analyse"
    app.number_input(key="rest").set_value(40.0)
    app.number_input(key="project_share").set_value(50.0)
    click(app, "Berechnen")
    assert any("40 % des Forecasts" in m.label for m in app.metric)
    labels = [m.label for m in app.metric]
    assert "in 85 % der Simulationen" in labels
    assert "mit 85 % Sicherheit" not in labels  # no commitment: model-dependent frequency
    # The simulation draws only from the window (5 sprints): sample visible, no warning once the
    # threshold (5) is reached
    assert not any("Wenig Daten" in w.value for w in app.warning)
    assert any("Stichprobe: 5 Sprints" in c.value for c in app.caption)
    assert any(m.value.startswith("2026.") or m.value.startswith("2027.") for m in app.metric)


def test_planning_freezes_forecast_plan(app: AppTest, data_dir: Path):
    planning_step(app, "2026.22", 2)
    app.number_input(key="fist-2026.22").set_value(10.0)
    click(app, "Planning speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.22.yaml")
    assert sprint["forecast_plan"] == 11.2
    assert any("kann starten" in s.value for s in app.success)


def test_products_page(app: AppTest):
    goto(app, "produkte")
    assert app.selectbox(key="products-sprint").value == "2026.22"
    assert any("3 betreute Produkte" in c.value for c in app.caption)
    app.selectbox(key="products-sprint").set_value("2026.20").run()
    assert any("Saldo" in c.value for c in app.caption)
    app.radio(key="products-measure").set_value("planned").run()
    assert not app.exception


def test_product_list_page(app: AppTest, data_dir: Path):
    goto(app, "produktliste")
    assert any("1 ehemalige(s) Produkt" in c.value for c in app.caption)
    click(app, "Produkte speichern")
    assert any("Gespeichert" in s.value for s in app.success)
    assert len(load(data_dir / "demo" / "products.yaml")["products"]) == 4


def test_calendar_page_creates_sprints(app: AppTest, data_dir: Path):
    goto(app, "sprints")
    assert any("2026.23 (neu)" in c.value for c in app.caption)
    click(app, "Sprints anlegen bzw. speichern")
    assert (data_dir / "demo" / "sprints" / "2026.26.yaml").exists()


def test_calendar_texts_follow_the_configured_workweek(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    team_file = data_dir / "demo" / "team.yaml"
    team = load(team_file)
    team.setdefault("capacity", {})["workweek"] = "mon,tue,wed,thu"
    team_file.write_text(yaml.safe_dump(team, allow_unicode=True))
    at = goto(start(data_dir, monkeypatch), "sprints")
    assert any("Teams (Mo–Do)" in m.value for m in at.markdown)
    assert not any("Mo–Fr" in m.value for m in at.markdown)


def test_whatif_panel_has_one_title_on_both_pages(app: AppTest):
    titles = set()
    for page in ("forecast", "vorplanung"):
        goto(app, page)
        titles |= {e.label for e in app.expander if "Was-wäre-wenn" in e.label}
    assert titles == {"Was-wäre-wenn: Prognose des Teams für offene Sprints"}


def test_prognosis_history_is_compact_until_details_are_requested(app: AppTest):
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    next(
        n
        for n in app.number_input
        if n.key and n.key.startswith("vorplanung-whatif-") and n.key.endswith("-open")
    ).set_value(3.0).run()
    click(app, "PO-Vorplanung speichern")
    app.run()  # the page reads the saved forecast only in the next run

    def history():
        return next(d.value for d in app.dataframe if "Zeitpunkt" in d.value.columns)

    assert "erwartet erledigt" in history().columns
    assert "nicht erledigt" not in history().columns
    app.toggle(key="prognosis-details").set_value(True).run()
    assert "nicht erledigt" in history().columns


def test_setup_when_no_data_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    empty = tmp_path / "leer"
    empty.mkdir()
    at = start(empty, monkeypatch)
    assert any("Kein Datenordner gefunden" in w.value for w in at.warning)
    target = tmp_path / "neu" / "sprint-daten"
    at.text_input(key="data-new").set_value(str(target)).run()
    click(at, "Anlegen")
    assert (target / ".git").is_dir() and (target / "teams").is_dir()
    assert "*.xlsx" in (target / ".gitignore").read_text()
    from sprintforecast.storage import saved_data_dir

    assert saved_data_dir() == (target / "teams").resolve()
    assert not any("Kein Datenordner gefunden" in w.value for w in at.warning)


def test_choose_folder_without_git_offers_init_or_use_without_git(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    at = start(data_dir, monkeypatch)
    goto(at, "datenordner")
    plain = tmp_path / "ohne-git"
    plain.mkdir()
    at.text_input(key="data-path").set_value(str(plain)).run()
    click(at, "Übernehmen")
    assert any("in keinem Git-Repository" in w.value for w in at.warning)
    click(at, f"Git-Repository in {plain} anlegen")
    assert (plain / ".git").is_dir()


def test_choose_folder_can_be_used_without_git(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """B7: Git is not a prerequisite for getting started."""
    at = start(data_dir, monkeypatch)
    goto(at, "datenordner")
    plain = tmp_path / "ohne-git"
    plain.mkdir()
    at.text_input(key="data-path").set_value(str(plain)).run()
    click(at, "Übernehmen")
    click(at, "Ohne Git verwenden")
    assert not (plain / ".git").exists()
    from sprintforecast.storage import saved_data_dir

    assert saved_data_dir() == plain.resolve()
    assert any("liegt in keinem Git-Repository" in c.value for c in at.sidebar.caption)


def test_new_team_with_three_sprints_gets_a_first_forecast(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """B7: Forecast from 3 sprints on (thin history), before that a notice, not an empty page."""
    sprints = sorted((data_dir / "demo" / "sprints").glob("*.yaml"))
    for f in sprints[3:]:
        f.unlink()
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any(m.value.endswith("PT") and m.value != "– PT" for m in at.metric)
    assert any("Wenig Daten" in w.value for w in at.warning)
    assert not any("Noch kein Forecast" in i.value for i in at.info)
    sprints[2].unlink()  # only two sprints with velocity
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any("Noch kein Forecast: bisher 2 Sprint(s)" in i.value for i in at.info)


def test_whatif_panel_on_forecast_page(app: AppTest):
    goto(app, "forecast")
    box = next(n for n in app.number_input if n.key and n.key.endswith("-open"))
    before = len(app.dataframe)
    box.set_value(6.0).run()
    assert not app.exception
    assert len(app.dataframe) == before + 1
    shown = [d.value for d in app.dataframe if "Differenz" in d.value.columns]
    assert shown and len(shown[0]) >= 1


def test_preplanning_page_saves_values(app: AppTest, data_dir: Path):
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
    assert any("Standard" in c.value for c in app.caption)
    assert not app.exception
    # Editing the table: set pre-planning for a product and save
    app.session_state["vorplanung-2026.22"] = {
        "edited_rows": {0: {"PO pre-planning": 3.5}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    click(app, "PO-Vorplanung speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.22.yaml")
    assert sprint["products"]["webshop"]["preplanned"] == 3.5


def test_product_tables_show_empty_cells_as_dash_not_none(app: AppTest):
    """Pre-planning, Planning, Review (editors) and product distribution (table): empty cells
    show a dash instead of "None"; display only, the data stays None."""

    def product_frames() -> list:
        return [d for d in app.dataframe if "Product" in d.value.columns]

    goto(app, "vorplanung")
    editors = [d for d in product_frames() if "_id" in d.value.columns]
    assert [d.proto.placeholder for d in editors] == ["–"]
    assert "Planning" not in editors[0].value.columns  # only in Planning

    planning_step(app, "2026.22", 1)
    editors = [d for d in product_frames() if "_id" in d.value.columns]
    assert [d.proto.placeholder for d in editors] == ["–"]

    goto(app, "review")
    app.selectbox(key="review-sprint").set_value("2026.21").run()
    editors = [d for d in product_frames() if "_id" in d.value.columns]
    assert [d.proto.placeholder for d in editors] == ["–"]

    goto(app, "produkte")
    tables = [d for d in product_frames() if "Standard" in d.value.columns]
    assert tables and tables[0].proto.placeholder == "–"


def test_product_editor_shows_only_columns_of_the_phase(app: AppTest):
    """Each meeting shows only columns that are entered or decided there."""

    def editor_columns() -> list[str]:
        [editor] = [d for d in app.dataframe if {"_id", "Product"} <= set(d.value.columns)]
        return [c for c in editor.value.columns if c not in ("_id", "Product", "PO")]

    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
    assert editor_columns() == ["Standard", "PO pre-planning"]

    planning_step(app, "2026.22", 1)
    assert editor_columns() == ["Standard", "PO pre-planning", "Planning"]

    goto(app, "review")
    app.selectbox(key="review-sprint").set_value("2026.21").run()
    assert editor_columns() == ["Planning", "Done"]


def test_absences_matrix_leaves_cells_of_inactive_people_empty(app: AppTest):
    """The text "Empty cells: the person is not in the team during this sprint.", not "None"."""
    goto(app, "fehltage")
    matrix = next(d for d in app.dataframe if {"id", "Person"} <= set(d.value.columns))
    assert matrix.proto.HasField("placeholder") and matrix.proto.placeholder == ""


def test_other_editors_show_empty_cells_as_empty_not_none(app: AppTest):
    """Products, people and the absences editors of Planning and pre-planning: empty cells
    ("Empty = always", "Empty = still in the team", not in the team) stay empty."""

    def editor(columns: set[str]):
        [found] = [d for d in app.dataframe if columns <= set(d.value.columns)]
        return found

    goto(app, "produktliste")
    products = editor({"Name", "Anteil", "from", "until"})
    assert products.proto.HasField("placeholder") and products.proto.placeholder == ""
    # the data stays empty (None), only the display differs
    assert products.value["until"].isna().any()

    goto(app, "personen")
    people = editor({"Name", "FTE", "from", "until"})
    assert people.proto.HasField("placeholder") and people.proto.placeholder == ""
    assert people.value["until"].isna().any()

    goto(app, "vorplanung")
    expected = editor({"id", "Person"})
    assert expected.proto.HasField("placeholder") and expected.proto.placeholder == ""

    goto(app, "planning")
    absences = editor({"id", "Person"})
    assert absences.proto.HasField("placeholder") and absences.proto.placeholder == ""


def test_blank_product_cells_stay_unrecorded_when_saving(app: AppTest, data_dir: Path):
    """The display "-" does not change the data: empty stays empty (None), 0 stays 0."""
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
    app.session_state["vorplanung-2026.22"] = {
        "edited_rows": {0: {"PO pre-planning": 0.0}, 1: {"PO pre-planning": 3.5}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    click(app, "PO-Vorplanung speichern")
    products = load(data_dir / "demo" / "sprints" / "2026.22.yaml")["products"]
    assert products["webshop"]["preplanned"] == 0  # explicitly recorded as 0
    assert products["webshop"].get("planned") is None  # never recorded: stays empty
    assert products["webshop"].get("done") is None


def test_preplanning_capacity_metric_keeps_the_value_free_of_the_source(app: AppTest):
    """The metric shows only the number (otherwise it is cut off: "50.6 (expected F...");
    the source is shown below it."""
    goto(app, "vorplanung")
    capacity = next(m for m in app.metric if m.label == "Kapazität (PT)")
    assert capacity.value == "30,0"  # 2026.22: absences confirmed
    assert capacity.delta == "Personenliste"
    app.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    capacity = next(m for m in app.metric if m.label == "Kapazität (PT)")
    assert "(" not in capacity.value and "⚠" not in capacity.value
    assert capacity.delta == "erwartete Fehltage"  # absences unknown, estimated from the history


@pytest.mark.parametrize(("digits", "expected"), [(0, "25"), (1, "25,3"), (2, "25,25")])
def test_preplanning_capacity_metric_rounds_like_the_other_pages(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, digits: int, expected: str
):
    """As everywhere: rounding per team setting, commercial (25.25 -> 25.3, not 25.2)."""
    team = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team.read_text())
    raw["capacity"]["rounding"] = digits
    team.write_text(yaml.safe_dump(raw))
    sprint = data_dir / "demo" / "sprints" / "2026.21.yaml"
    content = yaml.safe_load(sprint.read_text())
    content["absences"]["ben"] = 3.5  # 25.25 PD: exactly at the half
    sprint.write_text(yaml.safe_dump(content))
    at = goto(start(data_dir, monkeypatch), "vorplanung")
    at.selectbox(key="vorplanung-sprint").set_value("2026.21").run()
    capacity = next(m for m in at.metric if m.label == "Kapazität (PT)")
    assert capacity.value == expected
    goto(at, "planning")
    assert at.selectbox(key="planning-sprint").value == "2026.21"
    assert any(m.label == "Kapazität (PT)" and m.value == expected for m in at.metric)


def test_preplanning_capacity_metric_marks_an_unsure_source(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    team = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team.read_text())
    raw["capacity"]["absence_history"] = 0  # no estimate: only calendar and people list
    team.write_text(yaml.safe_dump(raw))
    at = goto(start(data_dir, monkeypatch), "vorplanung")
    at.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    capacity = next(m for m in at.metric if m.label == "Kapazität (PT)")
    assert "⚠" not in capacity.value
    assert capacity.delta == "⚠️ Kalender, Fehltage unbekannt"


def test_board_sprint_carries_over_between_boards(app: AppTest):
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.21").run()
    goto(app, "planning")
    assert app.selectbox(key="planning-sprint").value == "2026.21"
    goto(app, "review")
    assert app.selectbox(key="review-sprint").value == "2026.21"
    goto(app, "fehltage")
    assert app.selectbox(key="absences-sprint").value == "2026.21"


def test_manual_update_check_button(app: AppTest, monkeypatch: pytest.MonkeyPatch):
    from sprintforecast import updater

    calls = []

    def fake_check(force: bool = False, timeout: float = 5.0, now=None):
        calls.append(force)
        inst = updater.Installation(repo="x/y", ref="main", pinned=False)
        return updater.Check("0.2.0", "0.2.0", inst)

    monkeypatch.setattr(updater, "check", fake_check)
    click(app, "Nach Updates suchen")
    assert calls == [True]
    assert any("0.2.0" in c.value and "aktuell" in c.value for c in app.caption)


def test_preplanning_whatif_is_not_saved(app: AppTest, data_dir: Path):
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    box = next(
        n
        for n in app.number_input
        if n.key and n.key.startswith("vorplanung-whatif-") and n.key.endswith("-open")
    )
    before = [m.value for m in app.metric]
    box.set_value(6.0).run()
    assert not app.exception
    assert any("Rechnung:" in c.value for c in app.caption)
    assert [m.value for m in app.metric] != before
    assert not (data_dir / "demo" / "sprints" / "2026.23.yaml").exists()
    for sprint_file in (data_dir / "demo" / "sprints").glob("*.yaml"):
        assert "velocity: 2" not in sprint_file.read_text()


def test_preplanning_saves_prognosis_with_comment(app: AppTest, data_dir: Path):
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    box = next(
        n
        for n in app.number_input
        if n.key and n.key.startswith("vorplanung-whatif-") and n.key.endswith("-open")
    )
    box.set_value(3.0).run()
    comment = next(i for i in app.text_input if i.key and i.key.startswith("vorplanung-comment-"))
    comment.set_value("Prognose aus dem Daily").run()
    click(app, "PO-Vorplanung speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    prognosis = sprint["prognoses"][-1]
    assert prognosis["comment"] == "Prognose aus dem Daily"
    assert prognosis["not_done"] == 3
    assert prognosis["expected_done"] == 7  # Commitment 10 - 3
    assert prognosis["target"] == "2026.23"
    assert sprint["velocity"] is None  # the velocity is reserved for the review


def test_review_tracks_not_done_and_additional(app: AppTest, data_dir: Path):
    goto(app, "review")
    app.selectbox(key="review-sprint").set_value("2026.21").run()
    app.number_input(key="velocity-2026.21").set_value(9.0)
    app.number_input(key="not-done-2026.21").set_value(2.0)
    app.number_input(key="additional-done-2026.21").set_value(1.0)
    click(app, "Review speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert (sprint["velocity"], sprint["not_done"], sprint["additional_done"]) == (9, 2, 1)


def test_analysis_warns_when_the_simulation_has_few_samples(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """The simulation draws from 3 instead of the window's 5 sprints: warning with the sample."""
    for path in (data_dir / "demo" / "sprints").glob("*.yaml"):
        if int(path.stem.rsplit(".", 1)[1]) > 3:
            path.unlink()
    at = goto(start(data_dir, monkeypatch), "analyse")
    at.number_input(key="rest").set_value(20.0)
    click(at, "Berechnen")
    assert any(
        "Wenig Daten: Die Simulation zieht aus nur 3 Sprints (ab 5 sind Aussagen" in w.value
        for w in at.warning
    )
    assert any("Stichprobe: 3 Sprints" in c.value for c in at.caption)


def test_small_window_caps_the_sample_and_explains_the_warning(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Window 3: the sample (Forecast page and simulation) is capped at 3, the threshold stays 5;
    the sentence names the sample and all 20 recorded values (not "only 3"), the notice names
    the window."""
    team_file = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    raw.setdefault("forecast", {})["window"] = 3
    team_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert not any("bisher nur 3 Sprints" in w.value for w in at.warning)
    assert any(
        "Wenig Daten: Die Spanne zieht aus nur 3 der 20 erfassten Sprints mit Velocity (ab 5 "
        in w.value
        and "Das Prognosefenster ist auf 3 Sprints gestellt" in w.value
        and "mehr Werte in die Spanne ein." in w.value
        for w in at.warning
    )
    assert any("Spanne aus den letzten 3 Sprints" in c.value for c in at.caption)
    at = goto(at, "analyse")
    at.number_input(key="rest").set_value(20.0)
    click(at, "Berechnen")
    assert any(
        "Wenig Daten: Die Simulation zieht aus nur 3 Sprints (ab 5 sind Aussagen" in w.value
        and "Das Prognosefenster ist auf 3 Sprints gestellt" in w.value
        and "mehr Werte in Spanne und Simulation ein." in w.value
        for w in at.warning
    )
    assert any("Stichprobe: 3 Sprints" in c.value for c in at.caption)


def test_small_window_without_more_values_does_not_blame_the_window(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Window 3, but only 2 values recorded: the window cuts nothing off, a larger one would gain
    nothing. Forecast page and simulation warn about the sample, without the window notice."""
    for path in (data_dir / "demo" / "sprints").glob("*.yaml"):
        if int(path.stem.rsplit(".", 1)[1]) > 2:
            path.unlink()
    team_file = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    raw.setdefault("forecast", {})["window"] = 3
    team_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any(
        "Wenig Daten: bisher nur 2 Sprints mit Velocity (ab 5 " in w.value for w in at.warning
    )
    assert not any("Prognosefenster" in w.value for w in at.warning)
    at = goto(at, "analyse")
    at.number_input(key="rest").set_value(20.0)
    click(at, "Berechnen")
    assert any(
        "Wenig Daten: Die Simulation zieht aus nur 2 Sprints (ab 5 sind Aussagen" in w.value
        for w in at.warning
    )
    assert not any("Prognosefenster" in w.value for w in at.warning)


@pytest.mark.parametrize("count", [3, 5])
@pytest.mark.parametrize("window", [1, 2])
def test_small_window_does_not_claim_there_is_no_forecast(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, window: int, count: int
):
    """The sample is capped at the window (1 or 2), but the availability of the forecast depends
    on all values: with three or more values there is no "No forecast yet" message."""
    from sprintforecast.analysis import available_count, sample_count

    for path in (data_dir / "demo" / "sprints").glob("*.yaml"):
        if int(path.stem.rsplit(".", 1)[1]) > count:
            path.unlink()
    team_file = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    raw.setdefault("forecast", {})["window"] = window
    team_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    fc = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
    assert sample_count(fc) == window and available_count(fc) == count
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert not any("Noch kein Forecast" in i.value for i in at.info)


@pytest.mark.parametrize("window", [1, 2])
def test_no_forecast_notice_counts_all_values_with_only_two_values(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, window: int
):
    """KNOWN, not part of this PR: the fixed threshold ``MIN_THIN_HISTORY`` (3) applies to all
    windows. With exactly two values and window 1 or 2 the engine already computes a plan, yet
    the "No forecast yet" message appears (as before). The text names the number of all
    available values (2), not the capped sample."""
    for path in (data_dir / "demo" / "sprints").glob("*.yaml"):
        if int(path.stem.rsplit(".", 1)[1]) > 2:
            path.unlink()
    team_file = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    raw.setdefault("forecast", {})["window"] = window
    team_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any("Noch kein Forecast: bisher 2 Sprint(s)" in i.value for i in at.info)
    assert any(m.value.endswith("PT") and m.value != "– PT" for m in at.metric)


def test_analysis_too_large_rest_explains_horizon(app: AppTest):
    goto(app, "analyse")
    app.number_input(key="rest").set_value(100000.0)
    click(app, "Berechnen")
    later = [m for m in app.metric if "später als" in m.value]
    assert [m.label for m in later] == ["in 50 % der Simulationen", "in 85 % der Simulationen"]
    for metric in later:
        # only "later than 2027.21" in the value (otherwise cut off), the sprint count below
        assert "(" not in metric.value and "Sprints" not in metric.value
        assert metric.delta.startswith("Simulation über ") and metric.delta.endswith(" Sprints")
    assert any("höchstens" in c.value and "Sprints" in c.value for c in app.caption)


def test_analysis_completion_metrics_show_the_sprint_without_a_note(app: AppTest):
    goto(app, "analyse")
    app.number_input(key="rest").set_value(20.0)
    click(app, "Berechnen")
    reached = [m for m in app.metric if m.label.endswith("der Simulationen")]
    assert len(reached) == 2
    for metric in reached:
        assert "später als" not in metric.value and not metric.delta


def test_absences_page_can_edit_past_sprints(app: AppTest, data_dir: Path):
    goto(app, "fehltage")
    app.number_input(key="absences-past").set_value(1).run()
    assert not app.exception
    assert any("abgeschlossen" in c.value for c in app.caption)


def _pt(text: str) -> float:
    return float(text.replace(" PT", "").replace(",", "."))


def test_forecast_plan_is_consistent_across_pages(app: AppTest):
    """Forecast PLAN of a not yet saved sprint: Forecast page, PO pre-planning (headline number
    and plannable) and product distribution name the same value."""
    sprint = "2026.23"
    goto(app, "forecast")
    forecast = next(m for m in app.metric if m.label.startswith(sprint))
    expected = _pt(forecast.value)

    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value(sprint).run()
    headline = next(m for m in app.metric if m.label == f"Prognose aktuell {sprint}")
    available = next(m for m in app.metric if m.label == "Verteilbar")
    assert _pt(headline.value) == expected
    assert abs(_pt(available.value) - expected) < 0.05

    goto(app, "produkte")
    app.selectbox(key="products-sprint").set_value(sprint).run()
    assert any(f"{expected:.2f}".replace(".", ",") in c.value for c in app.caption)


def test_planning_absences_warns_when_nothing_entered(app: AppTest):
    goto(app, "planning")
    app.selectbox(key="planning-sprint").set_value("2026.23").run()
    assert any("Fehltage für 2026.23: unbekannt" in w.value for w in app.warning)


def test_planning_continue_without_confirmation_keeps_absences_unknown(
    app: AppTest, data_dir: Path
):
    goto(app, "planning")
    app.selectbox(key="planning-sprint").set_value("2026.23").run()
    click(app, "Weiter ohne Bestätigung")
    assert app.radio(key="planning-step").value == 1
    assert not (data_dir / "demo" / "sprints" / "2026.23.yaml").exists()  # nothing confirmed


def test_planning_nobody_absent_needs_explicit_confirmation(app: AppTest, data_dir: Path):
    goto(app, "planning")
    app.selectbox(key="planning-sprint").set_value("2026.23").run()
    click(app, "Niemand fehlt – bestätigen und weiter")
    saved = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert saved["absence_state"] == "confirmed" and saved["absences"] == {}
    assert app.radio(key="planning-step").value == 1


def test_saving_planning_values_keeps_unconfirmed_absences_unknown(app: AppTest, data_dir: Path):
    """Saving the commitment in Planning does not confirm absences (B2)."""
    planning_step(app, "2026.23", 2)
    app.number_input(key="fist-2026.23").set_value(9.0)
    click(app, "Planning speichern")
    saved = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert saved["forecast_ist"] == 9
    assert saved["absence_state"] == "unknown"


def test_formula_expander_fragment_switches_sprint(app: AppTest):
    """Calculation and what-if are fragments: inputs redraw only them."""
    goto(app, "forecast")
    ids = list(app.selectbox(key="formula-sprint").options)
    app.selectbox(key="formula-sprint").set_value(ids[-1]).run()
    assert not app.exception, app.exception
    assert app.selectbox(key="formula-sprint").value == ids[-1]
    assert app.metric  # rest of the page is kept


def test_forecast_shows_gaps_skipped_by_the_average(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    path = data_dir / "demo" / "sprints" / "2026.19.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["velocity"] = None  # gap in the middle of the history
    path.write_text(yaml.safe_dump(raw))
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any("Lücken: 1 Sprint" in i.value for i in at.info)


def test_gap_notice_follows_the_running_sprints_review_value(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """The gap notice looks at the same sprints as the average: with a recorded review value for
    the running sprint (2026.21) the gap in 2026.16 is outside the window of 5 values; without
    it (completed sprints only) it would still be inside."""
    sprints = data_dir / "demo" / "sprints"
    gap = yaml.safe_load((sprints / "2026.16.yaml").read_text())
    gap["velocity"] = None
    (sprints / "2026.16.yaml").write_text(yaml.safe_dump(gap))
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any("Lücken: 1 Sprint" in i.value for i in at.info)  # review value still missing
    running = yaml.safe_load((sprints / "2026.21.yaml").read_text())
    running["velocity"] = 10.0
    (sprints / "2026.21.yaml").write_text(yaml.safe_dump(running))
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert not any("Lücken" in i.value for i in at.info)


def test_absences_page_answers_how_much_fits_into_the_next_sprint(app: AppTest):
    """K2 acceptance: entering absences immediately shows how much fits into the next sprint."""
    goto(app, "fehltage")
    text = " ".join(m.value for m in app.markdown)
    assert "In den nächsten Sprint 2026.22 passen 11,2 PT" in text
    frame = next(d.value for d in app.dataframe if "Kapazität (PT)" in d.value.columns)
    assert frame.loc[frame["Sprint"] == "2026.22", "Forecast PLAN (PT)"].iloc[0] == "11,2"


STEP_ORDER = ["fehltage", "vorplanung", "planning", "review"]


def test_step_bar_order_is_the_order_of_the_sidebar():
    """The step bar follows the sidebar (tasks without "Start"): absences first."""
    assert [key for key in PAGES["Tasks"] if key != "start"] == STEP_ORDER


@pytest.mark.parametrize("page", STEP_ORDER)
def test_board_navigation_highlights_the_active_page(app: AppTest, page: str):
    """Four steps as in the sidebar; exactly the one of the current page is active. All steps
    are built the same way (a link in a container, only the color per CSS distinguishes the
    active one), so nothing jumps on a switch."""
    goto(app, page)
    steps = nav_steps(app)
    assert [key for key, _, _ in steps] == STEP_ORDER
    # Name = sidebar page name (for completed steps the icon is appended)
    assert nav_titles(app) == [t(PAGE_INFO[key][0]) for key in STEP_ORDER]
    assert [key for key, _, active in steps if active] == [page]
    # no handwritten HTML anymore (formerly: Markdown block with its own height)
    assert not any("board-active" in m.value for m in app.markdown)
    assert not any(link.proto.disabled for link in app.main.get("page_link"))


# Default on the Review page: open review 2026.21, absences confirmed, pre-planned,
# recorded in Planning, only the velocity is missing
DONE_2026_21 = {"fehltage": True, "vorplanung": True, "planning": True, "review": False}


def test_step_bar_state_is_taken_from_the_chosen_sprint(app: AppTest):
    goto(app, "review")
    assert app.selectbox(key="review-sprint").value == "2026.21"
    assert nav_done(app) == DONE_2026_21
    app.selectbox(key="review-sprint").set_value("2026.23").run()  # no sprint file yet
    assert not any(nav_done(app).values())


def test_step_bar_marks_only_done_steps_with_a_green_check(app: AppTest):
    """Only "done" carries a mark: a green check icon (Material icon in Markdown color) at the
    end of the step name. Open steps have none, the emojis are gone."""
    goto(app, "review")
    steps = nav_steps(app)
    assert [key for key, _, _ in steps] == STEP_ORDER
    for key, label, _ in steps:
        title = t(PAGE_INFO[key][0])
        assert label == (f"{title} {STEP_DONE_MARK}" if DONE_2026_21[key] else title)
        assert "✅" not in label and "⬜" not in label
    assert STEP_DONE_MARK == ":green[:material/check_circle:]"
    # The open step carries no mark at all in its name (its page icon is in `icon`)
    [open_label] = [label for key, label, _ in steps if not DONE_2026_21[key]]
    assert open_label == "Sprint abschließen (Review)"


def test_step_bar_mark_is_also_on_the_active_step(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """The active step (blue, the icon turns white via CSS) carries the same icon as the other
    steps, on every page, once the sprint is fully recorded."""
    _change_2026_22(data_dir, forecast_ist=10, velocity=9)
    path = data_dir / "demo" / "sprints" / "2026.21.yaml"
    path.write_text(yaml.safe_dump({**load(path), "velocity": 9}))  # both sprints complete
    at = start(data_dir, monkeypatch)
    for page in STEP_ORDER:
        goto(at, page)
        picker = at.selectbox(key=f"{'absences' if page == 'fehltage' else page}-sprint")
        picker.set_value("2026.21" if "2026.21" in picker.options else "2026.22").run()
        assert all(nav_done(at).values()), page
        [(_, label, _)] = [step for step in nav_steps(at) if step[2]]
        assert label.endswith(f" {STEP_DONE_MARK}"), page


def test_step_bar_tooltip_says_whether_the_sprint_is_recorded(app: AppTest):
    goto(app, "review")
    assert nav_help(app) == {
        "fehltage": "erfasst für Sprint 2026.21",
        "vorplanung": "erfasst für Sprint 2026.21",
        "planning": "erfasst für Sprint 2026.21",
        "review": "noch offen für Sprint 2026.21",
    }
    app.selectbox(key="review-sprint").set_value("2026.23").run()
    assert set(nav_help(app).values()) == {"noch offen für Sprint 2026.23"}
    # Mixed state on another page: 2026.22 is prepared (absences, pre-planning) but not scheduled
    # yet. Mark and tooltip match there step by step.
    goto(app, "fehltage")
    app.selectbox(key="absences-sprint").set_value("2026.22").run()
    assert not app.exception, app.exception
    done = nav_done(app)
    assert done == {"fehltage": True, "vorplanung": True, "planning": False, "review": False}
    assert nav_help(app) == {
        "fehltage": "erfasst für Sprint 2026.22",
        "vorplanung": "erfasst für Sprint 2026.22",
        "planning": "noch offen für Sprint 2026.22",
        "review": "noch offen für Sprint 2026.22",
    }
    for page, is_done in done.items():
        assert nav_help(app)[page].startswith("erfasst" if is_done else "noch offen")


def test_step_bar_in_english(data_dir: Path, monkeypatch: pytest.MonkeyPatch, english):
    at = goto(start(data_dir, monkeypatch), "review")
    assert nav_titles(at) == [
        "Prepare the sprint: absences",
        "PO pre-planning",
        "Planning",
        "Close the sprint (review)",
    ]
    assert nav_done(at) == DONE_2026_21  # same icon, only the tooltip is translated
    assert nav_help(at) == {
        "fehltage": "recorded for sprint 2026.21",
        "vorplanung": "recorded for sprint 2026.21",
        "planning": "recorded for sprint 2026.21",
        "review": "still open for sprint 2026.21",
    }


# Only the done icon is a check mark; none of the steps' page icons may be one.
CHECK_ICON_WORDS = ("check", "task_alt", "done", "verified", "approval")


def test_step_icons_are_no_check_marks(app: AppTest):
    """The page icon of the Review step (formerly task_alt) itself looked "done" and made an open
    sprint look checked off. Now it is a flag; no icon is used twice."""
    assert PAGES["Tasks"]["review"][1] == ":material/flag:"
    goto(app, "review")
    icons = {link.proto.page: link.proto.icon for link, _ in nav_links(app)}
    assert icons == {key: PAGE_INFO[key][1] for key in STEP_ORDER}  # as in the sidebar
    assert not [i for i in icons.values() if any(word in i for word in CHECK_ICON_WORDS)]
    assert len(set(icons.values())) == len(icons)
    assert all(icon != ":material/check_circle:" for icon in icons.values())


def test_start_task_icons_are_the_page_icons_and_no_check_marks(app: AppTest):
    """The start page also shows no check mark for "Close sprint" (formerly task_alt
    on the "Open" button although the sprint was open): a task has the same icon everywhere."""
    assert START_TASKS["prepare"][1] == PAGE_INFO["fehltage"][1]
    assert START_TASKS["planning"][1] == PAGE_INFO["planning"][1]
    assert START_TASKS["review"][1] == PAGE_INFO["review"][1] == ":material/flag:"
    # This is how it actually appears on the start page buttons (the review task is still open)
    icons = {key: app.button(key=f"start-{key}").proto.icon for key in START_TASKS}
    assert icons == {key: icon for key, (_, icon) in START_TASKS.items()}
    assert [s.value for s in app.subheader][-1] == "⬜ Sprint abschließen"
    assert not [i for i in icons.values() if any(word in i for word in CHECK_ICON_WORDS)]
    assert len(set(icons.values())) == len(icons)


@pytest.mark.parametrize(
    ("fields", "done"),
    [
        ({}, {"fehltage": True, "vorplanung": True, "planning": False, "review": False}),
        # Planning = forecast state (forecast_ist) recorded
        (
            {"forecast_ist": 10},
            {"fehltage": True, "vorplanung": True, "planning": True, "review": False},
        ),
        # Review = velocity recorded
        (
            {"velocity": 9},
            {"fehltage": True, "vorplanung": True, "planning": False, "review": True},
        ),
        # Pre-planning = product values pre-planned, absences = state confirmed
        (
            {"products": {}, "absences": {}},
            {"fehltage": False, "vorplanung": False, "planning": False, "review": False},
        ),
    ],
)
def test_step_bar_marks_mean_what_the_board_steps_say(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, fields: dict, done: dict
):
    """What counts as done stays as in ``board_steps_done``; the icon only displays it."""
    _change_2026_22(data_dir, **fields)
    at = goto(start(data_dir, monkeypatch), "planning")
    at.selectbox(key="planning-sprint").set_value("2026.22").run()
    assert not at.exception, at.exception
    assert nav_done(at) == done


@pytest.mark.parametrize(
    ("fields", "checked"),
    [
        ({}, True),  # demo: absences entered
        ({"absences": {}}, False),  # nothing entered: unknown
        ({"absences": {}, "absence_state": "confirmed"}, True),  # explicitly "nobody is absent"
        ({"absences": {}, "absence_state": "unknown"}, False),
        ({"absences": {}, "expected_absences": {"cem": 2}}, False),  # announced confirms nothing
    ],
)
def test_step_bar_absences_check_follows_the_absence_state(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, fields: dict, checked: bool
):
    _change_2026_22(data_dir, **fields)
    at = goto(start(data_dir, monkeypatch), "planning")
    assert at.selectbox(key="planning-sprint").value == "2026.22"
    label = next(label for key, label, _ in nav_steps(at) if key == "fehltage")
    assert label == "Sprint vorbereiten: Fehltage" + (f" {STEP_DONE_MARK}" if checked else "")


@pytest.mark.parametrize(
    ("fields", "done"),
    [
        ({}, True),  # demo: absences entered, pre-planning recorded
        ({"absences": {}}, False),  # absences unknown
        ({"absences": {}, "absence_state": "confirmed"}, True),
        ({"absences": {}, "absence_state": "unknown"}, False),
        # announced (PO pre-planning): confirms nothing; start page and step bar agree
        ({"absences": {}, "expected_absences": {"cem": 2}}, False),
    ],
)
def test_start_task_and_step_bar_agree_on_prepared_sprint(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, fields: dict, done: bool
):
    """The "Prepare sprint" task on the start page and the absences step of the bar never
    disagree for the same sprint."""
    _change_2026_22(data_dir, **fields)
    at = start(data_dir, monkeypatch)
    assert at.subheader[0].value == ("✅" if done else "⬜") + " Sprint vorbereiten"
    goto(at, "planning")
    assert at.selectbox(key="planning-sprint").value == "2026.22"
    assert nav_done(at)["fehltage"] == done


@pytest.mark.parametrize(
    ("fields", "mark"),
    [
        ({}, "✅"),
        ({"absences": {}}, "⬜"),  # unknown: sprint file exists, absences not confirmed
        ({"absences": {}, "absence_state": "confirmed"}, "✅"),
        ({"absences": {}, "expected_absences": {"cem": 2}}, "⬜"),
    ],
)
def test_planning_progress_line_agrees_with_the_step_bar(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, fields: dict, mark: str
):
    """The progress line of Planning and the step bar above it name the same state for
    "absences"."""
    _change_2026_22(data_dir, **fields)
    at = goto(start(data_dir, monkeypatch), "planning")
    assert at.selectbox(key="planning-sprint").value == "2026.22"
    line = next(c.value for c in at.caption if c.value.endswith(" Commitment"))
    assert line.startswith(f"{mark} Fehltage")
    assert nav_done(at)["fehltage"] == (mark == "✅")


def test_board_nav_css_follows_the_step_count():
    """The column count and the width from which all steps sit side by side depend on the number
    of steps (four with, three without the Products area)."""
    from sprintforecast.web.ui import _board_nav_css

    four, three = _board_nav_css(4), _board_nav_css(3)
    assert "repeat(4, minmax(0, 1fr))" in four and "min-width: 65.5rem" in four
    assert "repeat(3, minmax(0, 1fr))" in three and "min-width: 49rem" in three
    assert "st-key-board-active-" in four  # the active step gets the color


def test_start_prepare_says_when_absences_are_only_announced(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _change_2026_22(data_dir, absences={}, expected_absences={"cem": 2})
    at = start(data_dir, monkeypatch)
    assert any("angekündigt, noch nicht bestätigt" in w.value for w in at.main.markdown)
    at.button(key="start-prepare").click().run()  # leads to the absences, to confirm them
    assert at.header[0].value == "Planbare Fehltage"
    assert at.selectbox(key="absences-sprint").value == "2026.22"


def test_preplanning_save_updates_the_step_bar_at_once(app: AppTest):
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    assert not nav_done(app)["vorplanung"]
    app.session_state["vorplanung-2026.23"] = {
        "edited_rows": {0: {"PO pre-planning": 2.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    click(app, "PO-Vorplanung speichern")
    assert not nav_done(app)["vorplanung"]  # only one of several products has a value
    app.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    app.session_state["vorplanung-2026.23"] = {
        "edited_rows": {i: {"PO pre-planning": 2.0} for i in range(3)},  # webshop, app, portal
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    click(app, "PO-Vorplanung speichern")
    assert nav_done(app)["vorplanung"]  # already in the same run, without another click
    assert any("Gespeichert" in s.value for s in app.success)  # the message follows in the rebuild


def test_planning_save_updates_the_step_bar_at_once(app: AppTest):
    planning_step(app, "2026.22", 2)
    assert not nav_done(app)["planning"]
    app.number_input(key="carry-2026.22").set_value(1.5)
    app.number_input(key="backlog-2026.22").set_value(11.0)
    click(app, "Planning speichern")
    assert nav_done(app)["planning"]
    assert any("Gespeichert" in s.value for s in app.success)
    assert any("Delta" in i.value for i in app.info)  # the notices also appear in the rebuild


def test_review_save_updates_the_step_bar_at_once(app: AppTest):
    goto(app, "review")
    app.selectbox(key="review-sprint").set_value("2026.21").run()
    assert not nav_done(app)["review"]
    app.number_input(key="velocity-2026.21").set_value(9.25)
    click(app, "Review speichern")
    assert nav_done(app)["review"]
    assert app.session_state["pending_tags"] == ["demo/2026.21"]  # the tag suggestion stays
    assert any("Gespeichert" in s.value for s in app.success)  # the message follows in the rebuild


def add_unknown_absence(data_dir: Path, sprint: str) -> str:
    """Invalidates the sprint file (absences of an unknown person); returns its content."""
    path = data_dir / "demo" / "sprints" / f"{sprint}.yaml"
    content = load(path)
    content["absences"] = {**(content.get("absences") or {}), "niemand": 1}
    path.write_text(yaml.safe_dump(content))
    return path.read_text()


def test_failed_review_save_keeps_the_errors_and_does_not_rerun(app: AppTest, data_dir: Path):
    """If saving fails, the error message stays (a rebuild would discard it) and the step bar
    does not switch."""
    before = add_unknown_absence(data_dir, "2026.21")
    goto(app, "review")
    app.selectbox(key="review-sprint").set_value("2026.21").run()
    assert not nav_done(app)["review"]
    app.number_input(key="velocity-2026.21").set_value(9.25)
    click(app, "Review speichern")
    assert any("unbekannte Person" in e.value for e in app.error)
    assert any("Nicht gespeichert" in e.value for e in app.error)
    assert not nav_done(app)["review"]
    assert (data_dir / "demo" / "sprints" / "2026.21.yaml").read_text() == before
    assert not any("Gespeichert" in s.value for s in app.success)


def test_failed_preplanning_save_keeps_the_errors_and_does_not_rerun(app: AppTest, data_dir: Path):
    before = add_unknown_absence(data_dir, "2026.22")
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
    app.session_state["vorplanung-2026.22"] = {
        "edited_rows": {0: {"PO pre-planning": 2.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    click(app, "PO-Vorplanung speichern")
    assert any("unbekannte Person" in e.value for e in app.error)
    assert any("Nicht gespeichert" in e.value for e in app.error)
    assert (data_dir / "demo" / "sprints" / "2026.22.yaml").read_text() == before
    assert not any("Gespeichert" in s.value for s in app.success)


def test_absences_save_updates_the_step_bar_at_once(app: AppTest, data_dir: Path):
    """After "Save absences" the bar shows the new state immediately (not a click later)."""
    goto(app, "fehltage")
    app.selectbox(key="absences-sprint").set_value("2026.23").run()
    assert not nav_done(app)["fehltage"]  # no sprint file yet
    assert not (data_dir / "demo" / "sprints" / "2026.23.yaml").exists()
    frame = next(d.value for d in app.dataframe if "Niemand fehlt" in d.value.columns)
    rows = {i: {"Niemand fehlt": True} for i, s in enumerate(frame["Sprint"]) if s == "2026.23"}
    app.session_state[f"absence-states-{frame['Sprint'].iloc[0]}-{len(frame)}"] = {
        "edited_rows": rows,
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    click(app, "Fehltage speichern")
    assert (data_dir / "demo" / "sprints" / "2026.23.yaml").exists()
    assert nav_done(app)["fehltage"]
    assert any("Gespeichert" in s.value for s in app.success)  # the message comes after loading


def captions(app: AppTest) -> list[str]:
    return [c.value for c in app.caption]


def test_range_is_shown_at_the_planning_forecast(app: AppTest):
    """Planning step 2: range and sample directly under the tiles, the capacity source under the
    capacity."""
    planning_step(app, "2026.22", 1)
    assert "Spanne 10,0–12,3 aus den letzten 5 Sprints" in captions(app)
    capacity = next(m for m in app.metric if m.label == "Kapazität (PT)")
    assert "Personen" in capacity.delta  # source: calendar and people list


def test_range_is_shown_at_the_absences_forecast_line(app: AppTest):
    goto(app, "fehltage")
    assert any("In den nächsten Sprint" in m.value for m in app.markdown)
    assert any(c.startswith("Spanne ") and "aus den letzten 5 Sprints" in c for c in captions(app))


def test_range_is_shown_at_the_preplanning_forecast(app: AppTest):
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    assert "Spanne 10,2–12,5 aus den letzten 5 Sprints" in captions(app)


def test_range_is_not_shown_for_finished_sprints(app: AppTest):
    """The range belongs to today's history; the forecast of a completed sprint was computed with
    the one at that time. Showing both side by side would contradict each other."""
    planning_step(app, "2026.20", 1)
    assert not any(c.startswith("Spanne ") for c in captions(app))
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.20").run()
    assert not app.exception, app.exception
    assert not any(c.startswith("Spanne ") for c in captions(app))


def test_range_at_the_preplanning_says_when_the_forecast_assumes_something(app: AppTest):
    """The forecast computes with the assumption, the range does not: that is stated."""
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
    assert "Spanne 10,0–12,3 aus den letzten 5 Sprints" in captions(app)
    next(
        n
        for n in app.number_input
        if n.key and n.key.startswith("vorplanung-whatif-") and n.key.endswith("-extra")
    ).set_value(8.0).run()
    assert "Spanne 10,0–12,3 aus den letzten 5 Sprints (ohne die Annahme)" in captions(app)


def test_planning_capacity_tile_shows_no_arrow_before_the_source(app: AppTest):
    planning_step(app, "2026.22", 1)
    capacity = next(m for m in app.metric if m.label == "Kapazität (PT)")
    assert capacity.proto.direction == 2  # NONE: only the source is shown below, no delta


def test_range_at_the_absences_forecast_follows_the_unsaved_preview(app: AppTest):
    """The line under "Fits into the next sprint" belongs to the preview, not to the saved
    state: if someone enters more absences, the capacity drops and the range with it."""
    goto(app, "fehltage")
    before = next(c for c in captions(app) if c.startswith("Spanne "))
    frame = next(d.value for d in app.dataframe if "Person" in d.value.columns)
    sprints = [c for c in frame.columns if c.startswith("2026.")]
    app.session_state[f"absences-demo-{sprints[0]}-{len(sprints)}"] = {
        "edited_rows": {0: {"2026.22": 9.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    assert not app.exception, app.exception
    after = [c for c in captions(app) if c.startswith("Spanne ")]
    assert after and after[0] != before, (before, after)


def test_range_helpers_are_empty_without_enough_data_or_for_finished_sprints(data_dir: Path):
    from datetime import date

    from sprintforecast.forecast import build_forecast
    from sprintforecast.report import band_note, band_range
    from sprintforecast.storage import Repository

    fc = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
    assert band_range(fc, fc.entry("2026.22")) == "10,0–12,3"
    assert band_note(fc, fc.entry("2026.22")) != ""
    assert band_note(fc, fc.entry("2026.20")) == ""  # completed
    assert band_range(fc, fc.entry("2026.20")) == "–"

    for file in (data_dir / "demo" / "sprints").glob("*.yaml"):
        if file.stem != "2026.20":
            file.unlink()
    thin = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
    assert band_note(thin, thin.entry("2026.22")) == ""  # only one measurement
    assert band_range(thin, thin.entry("2026.22")) == "–"


def test_range_note_warns_about_little_data(data_dir: Path):
    """With fewer than five sprints with velocity the notice sits right at the range."""
    from datetime import date

    from sprintforecast.forecast import build_forecast
    from sprintforecast.report import band_note
    from sprintforecast.storage import Repository

    for file in (data_dir / "demo" / "sprints").glob("*.yaml"):
        if file.stem not in ("2026.17", "2026.18", "2026.19", "2026.20", "2026.21"):
            file.unlink()
    fc = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
    note = band_note(fc, fc.entry("2026.22"))
    assert note.startswith("Spanne ") and "aus den letzten 4 Sprints" in note
    assert note.endswith("wenig Daten, grober Hinweis")


def test_absences_page_shows_the_step_bar_and_shares_the_board_sprint(app: AppTest):
    goto(app, "fehltage")
    assert app.selectbox(key="absences-sprint").value == "2026.22"
    assert [key for key, _, active in nav_steps(app) if active] == ["fehltage"]
    assert nav_done(app)["fehltage"]  # 2026.22: absences entered
    app.selectbox(key="absences-sprint").set_value("2026.23").run()
    assert not app.exception, app.exception
    assert not nav_done(app)["fehltage"]  # 2026.23 has no sprint file
    goto(app, "planning")
    assert app.selectbox(key="planning-sprint").value == "2026.23"
    assert [key for key, _, active in nav_steps(app) if active] == ["planning"]
    assert not nav_done(app)["fehltage"]


def test_products_page_is_evaluation_only(app: AppTest):
    """B4: product values are only recorded on the boards; the evaluation has no input."""
    goto(app, "produkte")
    assert not app.main.button  # no "Save product values"
    assert not app.number_input.values or all(
        n.key == "products-n" for n in app.number_input
    )  # only the count for the trend
    assert any("Reine Auswertung" in c.value for c in app.caption)
    assert any(len(d.value) for d in app.dataframe)  # table stays visible
    links = [p.proto.page for p in app.get("page_link")]
    assert {"vorplanung", "planning", "review"} <= set(links)


def test_sprint_selection_is_the_same_on_all_pages(app: AppTest):
    """Same label, order and default; a choice applies on all pages."""
    pages = {
        "planning": "planning-sprint",
        "review": "review-sprint",
        "vorplanung": "vorplanung-sprint",
        "fehltage": "absences-sprint",
        "produkte": "products-sprint",
        "forecast": "formula-sprint",
    }
    seen = []
    for page, key in pages.items():
        goto(app, page)
        box = app.selectbox(key=key)
        assert box.label == "Sprint"
        # Default per task: on Planning pages the next Planning candidate, on Review the open
        # review, on Calculation the running sprint
        assert box.value == {"review-sprint": "2026.21", "formula-sprint": "2026.21"}.get(
            key, "2026.22"
        )
        seen.append(list(box.options))
    # Calculation shows the whole history, otherwise same order and same future
    assert all(options == seen[0] for options in seen[:-1])
    assert seen[-1][-len(seen[0]) :] == seen[0] or set(seen[0]) <= set(seen[-1])
    app.selectbox(key="formula-sprint").set_value("2026.23").run()
    for page, key in pages.items():
        goto(app, page)
        assert app.selectbox(key=key).value == "2026.23"


# --- Page intros: one lead sentence visible, everything else collapsible ---------------------


def test_absences_intro_is_short_and_details_are_in_an_expander(app: AppTest):
    goto(app, "fehltage")
    lead = next(m.value for m in app.markdown if m.value.startswith("Fehltage je Person"))
    assert "Urlaubskalender" not in lead  # source and example are in the expander
    details = next(e for e in app.expander if e.label.startswith("Mehr dazu"))
    assert "Urlaubskalender" in details.markdown[0].value
    assert "2 Tage Urlaub" in details.markdown[0].value
    assert "Teilzeit" in details.markdown[0].value
    # Period and working days per sprint are no longer rows above the table but summarized in
    # one line.
    summary = next(c.value for c in app.caption if "Arbeitstage" in c.value)
    assert summary.startswith("alle Sprints 10 Arbeitstage (Mo–Fr)")
    assert "noch ohne Sprintdatei" in summary
    assert not any(c.value.startswith("**2026.") for c in app.caption)


def test_sprints_summary_names_holidays_and_differing_workdays(data_dir: Path):
    data = Repository(data_dir).load("demo")
    fc = build_forecast(data, date(2026, 10, 15))
    sprints = ui.absence_sprints(data, fc, 6)
    text = ui.sprints_summary(data, sprints, fc.today)
    assert "2026.26: Feiertage 25.12., 01.01." in text
    assert "abgeschlossen" not in text
    shorter = [replace(sprints[0], end=sprints[0].end - timedelta(days=1)), *sprints[1:]]
    text = ui.sprints_summary(data, shorter, sprints[0].end)
    assert f"9 Arbeitstage (Mo–Fr) im Sprint {sprints[0].id}" in text
    assert f"10 Arbeitstage (Mo–Fr) im Sprint {sprints[1].id}" in text
    assert f"abgeschlossen: {sprints[0].id}" in text


def test_calendar_people_and_products_have_a_lead_and_an_expander(app: AppTest):
    goto(app, "sprints")
    assert any(m.value.startswith("Sprints folgen automatisch") for m in app.markdown)
    assert any(e.label.startswith("Abweichende Sprints") for e in app.expander)
    goto(app, "personen")
    assert any(m.value.startswith("Eine Zeile je Person") for m in app.markdown)
    assert any(e.label.startswith("Austritt oder FTE") for e in app.expander)
    goto(app, "produktliste")
    assert any(m.value.startswith("Eine Zeile je Produkt") for m in app.markdown)
    assert any(e.label.startswith("Produkt abgeben") for e in app.expander)


def test_planning_plan_live_capacity_without_products(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    shutil.rmtree(data_dir / "demo" / "products", ignore_errors=True)
    (data_dir / "demo" / "products.yaml").unlink(missing_ok=True)
    _change_2026_22(data_dir, products={})
    at = start(data_dir, monkeypatch)
    planning_step(at, "2026.22", 1)
    plan = next(m.value for m in at.metric if m.label.startswith("Prognose aktuell"))
    plan = float(plan.replace(".", "").replace(",", "."))
    key = "planning-scratch-2026.22"
    assert not any("Eingeplant:" in str(p.proto.text) for p in at.get("progress"))
    at.number_input(key=key).set_value(plan + 1).run()
    assert any("zu viel" in w.value for w in at.warning)
    at.number_input(key=key).set_value(0.25).run()
    assert any("frei" in s.value for s in at.success)
    assert any("Eingeplant:" in str(p.proto.text) for p in at.get("progress"))


def test_planning_plan_gauge_with_products(app: AppTest):
    planning_step(app, "2026.22", 1)
    assert not any(n.key == "planning-scratch-2026.22" for n in app.number_input)
    texts = [str(p.proto.text) for p in app.get("progress")]
    assert any(x.startswith("Eingeplant:") for x in texts), texts
