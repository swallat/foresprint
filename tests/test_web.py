# SPDX-License-Identifier: EUPL-1.2
"""Weboberfläche: Seiten rendern, Formulare speichern, Commit (ohne Browser via AppTest)."""

import subprocess
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from sprintforecast.storage import DATA_ENV, STICHTAG_ENV
from sprintforecast.web.ui import PAGE_INFO

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


def test_forecast_is_default_page(app: AppTest):
    values = [m.value for m in app.metric]
    assert values[:2] == ["9,0 PT", "10,1 PT"]  # wie `sprintforecast forecast demo`
    assert any("2026.23" in w.value and "Trend" in w.value for w in app.warning)


@pytest.mark.parametrize("page", sorted(PAGE_INFO))
def test_pages_render(app: AppTest, page: str):
    goto(app, page)
    assert not app.error
    assert app.header[0].value


def test_help_shows_workflow_and_terms(app: AppTest):
    goto(app, "hilfe")
    assert [t.label for t in app.tabs] == [
        "Ablauf", "Begriffe", "Eingabefelder", "Team-Einstellungen", "Kommandozeile",
    ]  # fmt: skip
    assert any("Commitment" in c.value for c in app.caption)  # Quelle Forecast IST


def test_absences_save_creates_missing_sprint_files(app: AppTest, data_dir: Path):
    goto(app, "fehltage")
    assert any("2026.23, 2026.24 angelegt" in c.value for c in app.caption)
    click(app, "Fehltage speichern")
    assert load(data_dir / "demo" / "sprints" / "2026.24.yaml")["absences"] == {}
    goto(app, "forecast")
    assert not any("Trend" in w.value for w in app.warning)


def planning_step(at: AppTest, sprint: str, step: int) -> AppTest:
    """Planning-Seite, Sprint wählen und zum Schritt (0–2) des Ablaufs springen."""
    goto(at, "planning")
    at.selectbox(key="planning-sprint").set_value(sprint).run()
    at.radio(key="planning-step").set_value(step).run()
    assert not at.exception, at.exception
    return at


def test_planning_defaults_to_next_planning(app: AppTest):
    goto(app, "planning")
    # 2026.21 läuft und ist bereits geplant (Forecast IST) → als Nächstes 2026.22
    assert app.selectbox(key="planning-sprint").value == "2026.22"
    assert app.radio(key="planning-step").value == 0


def test_planning_flow_absences_then_plan(app: AppTest, data_dir: Path):
    goto(app, "planning")
    assert any("Arbeitstage Mo–Fr" in c.value for c in app.caption)
    click(app, "Weiter")  # Fehltage unverändert, Sprintdatei existiert
    assert app.radio(key="planning-step").value == 1
    assert any(m.label.startswith("Forecast PLAN") for m in app.metric)
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
    app.selectbox(key="settings-demo-forecast.trend_mode").set_value("flat")
    app.number_input(key="settings-demo-forecast.roadmap_share").set_value(70.0)
    click(app, "Speichern")
    team = load(data_dir / "demo" / "team.yaml")
    assert team["forecast"]["trend_mode"] == "flat"
    assert team["forecast"]["roadmap_share"] == pytest.approx(0.7)
    assert any("rückwirkend" in w.value for w in app.warning)


def test_new_team(app: AppTest, data_dir: Path):
    goto(app, "neues_team")
    app.text_input[0].set_value("team-b").run()
    app.selectbox(key="new-team-b-capacity.region").set_value("BY")
    click(app, "Team anlegen")
    team = load(data_dir / "team-b" / "team.yaml")
    assert team["capacity"]["region"] == "BY"
    assert team["sprint"]["first"]["id"] == "2026.1"
    assert app.session_state["selected_team"] == "team-b"


def test_without_any_team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    at = start(tmp_path, monkeypatch)
    assert any("Noch kein Team" in i.value for i in at.info)
    for page in ("neues_team", "hilfe", "personen"):
        goto(at, page)


def test_team_without_history(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression: leeres Diagramm ließ die Forecast-Seite abstürzen."""
    team = data_dir / "aaa-neu"
    team.mkdir()
    (team / "team.yaml").write_text(
        "name: Neu\nsprint:\n  first: {id: '2026.20', start: 2026-10-14}\n"
    )
    at = start(data_dir, monkeypatch)
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

    # Neuer Durchlauf über das Hauptskript (AppTest rendert nach Seitenwechseln die
    # Seitenleiste nicht erneut); vorgemerkte Tags leben im Session State.
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.session_state["pending_tags"] = ["demo/2026.21"]
    at.run()
    assert any("1 offene Änderung" in e.label for e in at.sidebar.expander)
    at.text_input(key="commit_message").set_value("Review 2026.21")
    next(b for b in at.button if b.label == "Änderungen committen").click().run()
    assert git(data_dir, "log", "-1", "--format=%s") == "Review 2026.21"
    assert git(data_dir, "tag") == "demo/2026.21"
    assert git(data_dir, "status", "--porcelain") == ""
    assert at.session_state["pending_tags"] == []


def test_planning_prefills_forecast_ist(app: AppTest, data_dir: Path):
    planning_step(app, "2026.22", 2)
    assert app.number_input(key="fist-2026.22").value is None  # nicht der Wert von 2026.21
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
    """Regression: ein Ordner `pages/` aktivierte Streamlits alte Seitenerkennung –
    Direktaufrufe liefen dann ohne Navigation und Teamauswahl."""
    for page in ("planning", "hilfe", "pruefung"):
        goto(app, page)
        assert app.sidebar.selectbox[1].value == "demo"


def test_people_page_toggle_former(app: AppTest):
    goto(app, "personen")
    assert any("1 ehemalige Person" in c.value for c in app.caption)
    app.toggle(key="show_former").set_value(True).run()
    assert not any("ehemalige Person" in c.value for c in app.caption)
    click(app, "Personen speichern")  # unverändert speichern geht ohne Rückfrage
    assert any("Gespeichert" in s.value for s in app.success)


def test_analysis_page(app: AppTest):
    goto(app, "analyse")
    assert app.header[0].value == "Analyse"
    app.number_input(key="rest").set_value(40.0)
    app.number_input(key="project_share").set_value(50.0)
    click(app, "Berechnen")
    assert any("40 % des Forecasts" in m.label for m in app.metric)
    labels = [m.label for m in app.metric]
    assert "mit 85 % Sicherheit" in labels
    assert any(m.value.startswith("2026.") or m.value.startswith("2027.") for m in app.metric)


def test_planning_freezes_forecast_plan(app: AppTest, data_dir: Path):
    planning_step(app, "2026.22", 2)
    app.number_input(key="fist-2026.22").set_value(10.0)
    click(app, "Planning speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.22.yaml")
    assert sprint["forecast_plan"] == 10.1
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


def test_choose_folder_requires_git(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    at = start(data_dir, monkeypatch)
    goto(at, "datenordner")
    plain = tmp_path / "ohne-git"
    plain.mkdir()
    at.text_input(key="data-path").set_value(str(plain)).run()
    click(at, "Übernehmen")
    assert any("in keinem Git-Repository" in e.value for e in at.error)
    click(at, f"Git-Repository in {plain} anlegen")
    assert (plain / ".git").is_dir()
