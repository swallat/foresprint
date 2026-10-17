# SPDX-License-Identifier: EUPL-1.2
"""Weboberfläche: Seiten rendern, Formulare speichern, Commit (ohne Browser via AppTest)."""

import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from webfixtures import STEP_DONE_MARK, nav_done, nav_help, nav_links, nav_steps, nav_titles

from sprintforecast.forecast import build_forecast
from sprintforecast.model import Sprint
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository
from sprintforecast.web.ui import PAGE_INFO, PAGES, START_TASKS

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


def test_start_is_default_page(app: AppTest):
    assert app.header[0].value == "Was möchtest du tun?"
    # 2026.22 ist vorbereitet (Fehltage, Vorplanung), aber noch nicht eingeplant
    assert [s.value for s in app.subheader] == [
        "✅ Sprint vorbereiten",
        "⬜ Planning",
        "⬜ Sprint abschließen",
    ]


def test_start_tasks_lead_to_the_next_sensible_step(app: AppTest):
    """Heute 2026-10-15: 2026.21 läuft (Review offen), 2026.22 ist der nächste Planning-Kandidat."""
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


def test_start_prepare_is_not_stuck_without_products(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Funktionsbereich Produkte an, aber keine Produkte angelegt: keine dauerhafte Vorplanung."""
    import shutil

    shutil.rmtree(data_dir / "demo" / "products", ignore_errors=True)
    (data_dir / "demo" / "products.yaml").unlink(missing_ok=True)
    _change_2026_22(data_dir, products={})
    at = start(data_dir, monkeypatch)
    assert not any("PO-Vorplanung fehlt noch" in w.value for w in at.main.markdown)


def test_forecast_page_shows_the_forecast(app: AppTest):
    goto(app, "forecast")
    values = [m.value for m in app.metric]
    assert values[:2] == ["9,5 PT", "11,2 PT"]  # wie `sprintforecast forecast demo`
    # Mit Personenliste kommt die Kapazität aus Kalender und Personen: keine Trend-Warnung
    assert not any("Trend" in w.value for w in app.warning)


def test_forecast_range_stays_short_and_names_its_samples_below(app: AppTest):
    """Die Zeile unter der Kennzahl wird bei vier Spalten abgeschnitten: nur die Spanne selbst,
    die Zahl der Sprints dahinter steht in der Beschriftung."""
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
    raw["capacity"]["absence_history"] = 0  # keine Schätzung
    team.write_text(yaml.safe_dump(raw))
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any(
        "2026.23" in w.value and "Kalender, Fehltage unbekannt" in w.value for w in at.warning
    )


@pytest.mark.parametrize("page", sorted(PAGE_INFO))
def test_pages_render(app: AppTest, page: str):
    goto(app, page)
    assert not app.error
    assert app.header[0].value


def test_help_shows_workflow_and_terms(app: AppTest):
    goto(app, "hilfe")
    assert [t.label for t in app.tabs] == [
        "Ablauf", "Begriffe", "Eingabefelder", "Team-Einstellungen", "Zusammenarbeit (Git)",
        "Kommandozeile",
    ]  # fmt: skip
    assert any("Commitment" in c.value for c in app.caption)  # Quelle Commitment


def test_absences_save_does_not_confirm_silently(app: AppTest, data_dir: Path):
    """Speichern ohne Eintrag und ohne ausdrückliche Bestätigung legt nichts an (B2)."""
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
    assert saved["absences_confirmed"] is True  # ältere Programmversionen lesen es weiter
    goto(app, "forecast")
    assert not any("Trend" in w.value for w in app.warning)


def test_reset_absences_text_names_calendar_and_people_not_trend(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Nach dem Zurücksetzen bleibt die Kapazität aus Kalender und Personen; nur die Fehltage
    werden nach der Historie geschätzt (Trend gibt es nur ohne Personenliste)."""
    repo = Repository(data_dir)
    nxt = build_forecast(repo.load("demo"), date(2026, 10, 15)).entries[-1].sprint
    repo.save_sprint("demo", Sprint(id=nxt.id, start=nxt.start, end=nxt.end))
    at = goto(start(data_dir, monkeypatch), "fehltage")
    assert "Fehltage zurücksetzen" in [s.value for s in at.subheader]
    caption = next(c.value for c in at.caption if "Zurücksetzen löscht" in c.value)
    assert "Trend" not in caption
    assert "nach der Historie geschätzt" in caption and "Kalender und Personen" in caption


def planning_step(at: AppTest, sprint: str, step: int) -> AppTest:
    """Planning-Seite, Sprint wählen und zum Schritt (0–2) des Ablaufs springen."""
    goto(at, "planning")
    at.selectbox(key="planning-sprint").set_value(sprint).run()
    at.radio(key="planning-step").set_value(step).run()
    assert not at.exception, at.exception
    return at


def test_planning_defaults_to_next_planning(app: AppTest):
    goto(app, "planning")
    # 2026.21 läuft und ist bereits geplant (Commitment) → als Nächstes 2026.22
    assert app.selectbox(key="planning-sprint").value == "2026.22"
    assert app.radio(key="planning-step").value == 0


def test_planning_flow_absences_then_plan(app: AppTest, data_dir: Path):
    goto(app, "planning")
    assert any("Arbeitstage (Mo–Fr)" in c.value for c in app.caption)
    click(app, "Weiter")  # Fehltage unverändert, Sprintdatei existiert
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
    # 14 Kalendertage = 10 Arbeitstage → 1 PT = 10 %
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
    app.text_input(key="new-team-b-capacity.region").set_value("BY")
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
    assert "in 85 % der Simulationen" in labels
    assert "mit 85 % Sicherheit" not in labels  # keine Zusage: modellabhängige Häufigkeit
    # Die Simulation zieht nur aus dem Fenster (5 Sprints): Stichprobe sichtbar, bei Erreichen
    # der Schwelle (5) keine Warnung mehr
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
    app.run()  # die Seite liest die gespeicherte Prognose erst im nächsten Lauf

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
    """B7: Git ist keine Voraussetzung für den Einstieg."""
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
    """B7: Forecast schon ab 3 Sprints (Historie dünn), vorher ein Hinweis statt leerer Seite."""
    sprints = sorted((data_dir / "demo" / "sprints").glob("*.yaml"))
    for f in sprints[3:]:
        f.unlink()
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any(m.value.endswith("PT") and m.value != "– PT" for m in at.metric)
    assert any("Wenig Daten" in w.value for w in at.warning)
    assert not any("Noch kein Forecast" in i.value for i in at.info)
    sprints[2].unlink()  # nur zwei Sprints mit Velocity
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
    # Bearbeiten der Tabelle: Vorplanung für ein Produkt setzen und speichern
    app.session_state["vorplanung-2026.22"] = {
        "edited_rows": {0: {"PO-Vorplanung": 3.5}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    click(app, "PO-Vorplanung speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.22.yaml")
    assert sprint["products"]["webshop"]["preplanned"] == 3.5


def test_product_tables_show_empty_cells_as_dash_not_none(app: AppTest):
    """Vorplanung, Planning, Review (Editoren) und Produktverteilung (Tabelle): leere Zellen
    zeigen einen Strich statt „None“ – nur die Anzeige, die Daten bleiben None."""

    def product_frames() -> list:
        return [d for d in app.dataframe if "Produkt" in d.value.columns]

    goto(app, "vorplanung")
    editors = [d for d in product_frames() if "_id" in d.value.columns]
    assert [d.proto.placeholder for d in editors] == ["–"]
    assert editors[0].value["Planning"].isna().all()  # nicht erfasst ist nicht 0

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


def test_absences_matrix_leaves_cells_of_inactive_people_empty(app: AppTest):
    """„Leere Zellen: Person ist in diesem Sprint nicht im Team.“ – nicht „None“."""
    goto(app, "fehltage")
    matrix = next(d for d in app.dataframe if {"id", "Person"} <= set(d.value.columns))
    assert matrix.proto.HasField("placeholder") and matrix.proto.placeholder == ""


def test_other_editors_show_empty_cells_as_empty_not_none(app: AppTest):
    """Produkte, Personen und die Fehltage-Editoren von Planning und Vorplanung: leere Zellen
    („leer = schon immer“, „Leer = weiterhin im Team“, nicht im Team) bleiben leer."""

    def editor(columns: set[str]):
        [found] = [d for d in app.dataframe if columns <= set(d.value.columns)]
        return found

    goto(app, "produktliste")
    products = editor({"Name", "Anteil", "ab", "bis"})
    assert products.proto.HasField("placeholder") and products.proto.placeholder == ""
    assert products.value["bis"].isna().any()  # die Daten bleiben leer (None), nur die Anzeige

    goto(app, "personen")
    people = editor({"Name", "FTE", "ab", "bis"})
    assert people.proto.HasField("placeholder") and people.proto.placeholder == ""
    assert people.value["bis"].isna().any()

    goto(app, "vorplanung")
    expected = editor({"id", "Person"})
    assert expected.proto.HasField("placeholder") and expected.proto.placeholder == ""

    goto(app, "planning")
    absences = editor({"id", "Person"})
    assert absences.proto.HasField("placeholder") and absences.proto.placeholder == ""


def test_blank_product_cells_stay_unrecorded_when_saving(app: AppTest, data_dir: Path):
    """Die Anzeige „–“ ändert die Daten nicht: Leer bleibt leer (None), 0 bleibt 0."""
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
    app.session_state["vorplanung-2026.22"] = {
        "edited_rows": {0: {"PO-Vorplanung": 0.0}, 1: {"PO-Vorplanung": 3.5}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    click(app, "PO-Vorplanung speichern")
    products = load(data_dir / "demo" / "sprints" / "2026.22.yaml")["products"]
    assert products["webshop"]["preplanned"] == 0  # ausdrücklich 0 erfasst
    assert products["webshop"].get("planned") is None  # nie erfasst: bleibt leer
    assert products["webshop"].get("done") is None


def test_preplanning_capacity_metric_keeps_the_value_free_of_the_source(app: AppTest):
    """Die Kennzahl zeigt nur die Zahl (sonst wird sie abgeschnitten: „50,6 (erwartete F…“);
    die Quelle steht darunter."""
    goto(app, "vorplanung")
    capacity = next(m for m in app.metric if m.label == "Kapazität (PT)")
    assert capacity.value == "30,0"  # 2026.22: Fehltage bestätigt
    assert capacity.delta == "Personenliste"
    app.selectbox(key="vorplanung-sprint").set_value("2026.23").run()
    capacity = next(m for m in app.metric if m.label == "Kapazität (PT)")
    assert "(" not in capacity.value and "⚠" not in capacity.value
    assert capacity.delta == "erwartete Fehltage"  # Fehltage unbekannt, nach Historie geschätzt


@pytest.mark.parametrize(("digits", "expected"), [(0, "25"), (1, "25,3"), (2, "25,25")])
def test_preplanning_capacity_metric_rounds_like_the_other_pages(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, digits: int, expected: str
):
    """Wie überall: Rundung laut Team-Einstellung, kaufmännisch (25,25 → 25,3, nicht 25,2)."""
    team = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team.read_text())
    raw["capacity"]["rounding"] = digits
    team.write_text(yaml.safe_dump(raw))
    sprint = data_dir / "demo" / "sprints" / "2026.21.yaml"
    content = yaml.safe_load(sprint.read_text())
    content["absences"]["ben"] = 3.5  # 25,25 PT: genau auf der Hälfte
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
    raw["capacity"]["absence_history"] = 0  # keine Schätzung: nur Kalender und Personenliste
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
    assert sprint["velocity"] is None  # die Velocity bleibt dem Review vorbehalten


def test_review_tracks_not_done_and_additional(app: AppTest, data_dir: Path):
    goto(app, "review")
    app.selectbox(key="review-sprint").set_value("2026.21").run()
    app.number_input(key="velocity-2026.21").set_value(9.0)
    app.number_input(key="not-done-2026.21").set_value(2.0)
    app.number_input(key="additional-done-2026.21").set_value(1.0)
    click(app, "Review speichern")
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert (sprint["velocity"], sprint["not_done"], sprint["additional_done"]) == (9, 2, 1)


def test_analysis_too_large_rest_explains_horizon(app: AppTest):
    goto(app, "analyse")
    app.number_input(key="rest").set_value(100000.0)
    click(app, "Berechnen")
    later = [m for m in app.metric if "später als" in m.value]
    assert [m.label for m in later] == ["in 50 % der Simulationen", "in 85 % der Simulationen"]
    for metric in later:
        # nur „später als 2027.21“ im Wert (sonst abgeschnitten), die Sprintanzahl darunter
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
    """Forecast PLAN eines noch nicht gespeicherten Sprints: Forecast-Seite, PO-Vorplanung
    (Kopfzahl und Verteilbar) und Produktverteilung nennen denselben Wert."""
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
    assert not (data_dir / "demo" / "sprints" / "2026.23.yaml").exists()  # nichts bestätigt


def test_planning_nobody_absent_needs_explicit_confirmation(app: AppTest, data_dir: Path):
    goto(app, "planning")
    app.selectbox(key="planning-sprint").set_value("2026.23").run()
    click(app, "Niemand fehlt – bestätigen und weiter")
    saved = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert saved["absence_state"] == "confirmed" and saved["absences"] == {}
    assert app.radio(key="planning-step").value == 1


def test_saving_planning_values_keeps_unconfirmed_absences_unknown(app: AppTest, data_dir: Path):
    """Commitment im Planning speichern bestätigt keine Fehltage (B2)."""
    planning_step(app, "2026.23", 2)
    app.number_input(key="fist-2026.23").set_value(9.0)
    click(app, "Planning speichern")
    saved = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert saved["forecast_ist"] == 9
    assert saved["absence_state"] == "unknown"


def test_formula_expander_fragment_switches_sprint(app: AppTest):
    """Rechenweg und Was-wäre-wenn sind Fragmente: Eingaben zeichnen nur sie neu."""
    goto(app, "forecast")
    ids = list(app.selectbox(key="formula-sprint").options)
    app.selectbox(key="formula-sprint").set_value(ids[-1]).run()
    assert not app.exception, app.exception
    assert app.selectbox(key="formula-sprint").value == ids[-1]
    assert app.metric  # Rest der Seite bleibt erhalten


def test_forecast_shows_gaps_skipped_by_the_average(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    path = data_dir / "demo" / "sprints" / "2026.19.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["velocity"] = None  # Lücke mitten in der Historie
    path.write_text(yaml.safe_dump(raw))
    at = goto(start(data_dir, monkeypatch), "forecast")
    assert any("Lücken: 1 Sprint" in i.value for i in at.info)


def test_absences_page_answers_how_much_fits_into_the_next_sprint(app: AppTest):
    """K2-Abnahme: Wer Fehltage einträgt, sieht sofort, wie viel in den nächsten Sprint passt."""
    goto(app, "fehltage")
    text = " ".join(m.value for m in app.markdown)
    assert "In den nächsten Sprint 2026.22 passen 11,2 PT" in text
    frame = next(d.value for d in app.dataframe if "Kapazität (PT)" in d.value.columns)
    assert frame.loc[frame["Sprint"] == "2026.22", "Forecast PLAN (PT)"].iloc[0] == "11,2"


STEP_ORDER = ["fehltage", "vorplanung", "planning", "review"]


def test_step_bar_order_is_the_order_of_the_sidebar():
    """Die Schrittleiste folgt der Seitenleiste (Aufgaben ohne „Start“): Fehltage zuerst."""
    assert [key for key in PAGES["Aufgaben"] if key != "start"] == STEP_ORDER


@pytest.mark.parametrize("page", STEP_ORDER)
def test_board_navigation_highlights_the_active_page(app: AppTest, page: str):
    """Vier Schritte wie in der Seitenleiste; genau der der aktuellen Seite ist der aktive.
    Alle Schritte sind gleich aufgebaut (ein Link in einem Container, nur die Farbe per CSS
    unterscheidet den aktiven) – darum springt beim Wechsel nichts."""
    goto(app, page)
    steps = nav_steps(app)
    assert [key for key, _, _ in steps] == STEP_ORDER
    # Name = Seitenname der Seitenleiste (bei erledigten Schritten hängt das Symbol dahinter)
    assert nav_titles(app) == [PAGE_INFO[key][0] for key in STEP_ORDER]
    assert [key for key, _, active in steps if active] == [page]
    # kein handgeschriebenes HTML mehr (früher: Markdown-Block mit eigener Höhe)
    assert not any("board-active" in m.value for m in app.markdown)
    assert not any(link.proto.disabled for link in app.main.get("page_link"))


# Vorgabe auf der Review-Seite: offener Rückblick 2026.21 – Fehltage bestätigt, vorgeplant,
# im Planning erfasst, nur die Velocity fehlt noch
DONE_2026_21 = {"fehltage": True, "vorplanung": True, "planning": True, "review": False}


def test_step_bar_state_is_taken_from_the_chosen_sprint(app: AppTest):
    goto(app, "review")
    assert app.selectbox(key="review-sprint").value == "2026.21"
    assert nav_done(app) == DONE_2026_21
    app.selectbox(key="review-sprint").set_value("2026.23").run()  # noch ohne Sprintdatei
    assert not any(nav_done(app).values())


def test_step_bar_marks_only_done_steps_with_a_green_check(app: AppTest):
    """Nur „erledigt“ trägt ein Zeichen: ein grünes Haken-Symbol (Material-Icon in Markdown-
    Farbe) am Ende des Schrittnamens. Offene Schritte haben keins, die Emojis sind weg."""
    goto(app, "review")
    steps = nav_steps(app)
    assert [key for key, _, _ in steps] == STEP_ORDER
    for key, label, _ in steps:
        title = PAGE_INFO[key][0]
        assert label == (f"{title} {STEP_DONE_MARK}" if DONE_2026_21[key] else title)
        assert "✅" not in label and "⬜" not in label
    assert STEP_DONE_MARK == ":green[:material/check_circle:]"
    # Der offene Schritt trägt gar kein Zeichen im Namen (sein Seiten-Icon steht in `icon`)
    [open_label] = [label for key, label, _ in steps if not DONE_2026_21[key]]
    assert open_label == "Sprint abschließen (Review)"


def test_step_bar_mark_is_also_on_the_active_step(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Der aktive Schritt (blau, das Symbol wird per CSS weiß) trägt dasselbe Symbol wie die
    übrigen Schritte – auf jeder Seite, wenn der Sprint ganz erfasst ist."""
    _change_2026_22(data_dir, forecast_ist=10, velocity=9)
    path = data_dir / "demo" / "sprints" / "2026.21.yaml"
    path.write_text(yaml.safe_dump({**load(path), "velocity": 9}))  # beide Sprints vollständig
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
    # Gemischter Stand auf einer anderen Seite: 2026.22 ist vorbereitet (Fehltage, Vorplanung),
    # aber noch nicht eingeplant. Zeichen und Tooltip stimmen dort Schritt für Schritt überein.
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
    assert nav_done(at) == DONE_2026_21  # dasselbe Symbol, nur der Tooltip ist übersetzt
    assert nav_help(at) == {
        "fehltage": "recorded for sprint 2026.21",
        "vorplanung": "recorded for sprint 2026.21",
        "planning": "recorded for sprint 2026.21",
        "review": "still open for sprint 2026.21",
    }


# Nur das Erledigt-Symbol ist ein Haken; keines der Seiten-Icons der Schritte darf einer sein.
CHECK_ICON_WORDS = ("check", "task_alt", "done", "verified", "approval")


def test_step_icons_are_no_check_marks(app: AppTest):
    """Das Seiten-Icon des Review-Schritts (früher task_alt) sah selbst wie „erledigt“ aus und
    ließ einen offenen Sprint abgehakt wirken. Jetzt ist es eine Flagge; kein Icon doppelt."""
    assert PAGES["Aufgaben"]["review"][1] == ":material/flag:"
    goto(app, "review")
    icons = {link.proto.page: link.proto.icon for link, _ in nav_links(app)}
    assert icons == {key: PAGE_INFO[key][1] for key in STEP_ORDER}  # wie in der Seitenleiste
    assert not [i for i in icons.values() if any(word in i for word in CHECK_ICON_WORDS)]
    assert len(set(icons.values())) == len(icons)
    assert all(icon != ":material/check_circle:" for icon in icons.values())


def test_start_task_icons_are_the_page_icons_and_no_check_marks(app: AppTest):
    """Auch die Startseite zeigt für „Sprint abschließen“ keinen Haken (früher task_alt am
    „Öffnen“-Knopf, obwohl der Sprint offen war): Eine Aufgabe hat überall dasselbe Icon."""
    assert START_TASKS["prepare"][1] == PAGE_INFO["fehltage"][1]
    assert START_TASKS["planning"][1] == PAGE_INFO["planning"][1]
    assert START_TASKS["review"][1] == PAGE_INFO["review"][1] == ":material/flag:"
    # So steht es tatsächlich an den Knöpfen der Startseite (die Review-Aufgabe ist noch offen)
    icons = {key: app.button(key=f"start-{key}").proto.icon for key in START_TASKS}
    assert icons == {key: icon for key, (_, icon) in START_TASKS.items()}
    assert [s.value for s in app.subheader][-1] == "⬜ Sprint abschließen"
    assert not [i for i in icons.values() if any(word in i for word in CHECK_ICON_WORDS)]
    assert len(set(icons.values())) == len(icons)


@pytest.mark.parametrize(
    ("fields", "done"),
    [
        ({}, {"fehltage": True, "vorplanung": True, "planning": False, "review": False}),
        # Planning = Forecast-Stand (forecast_ist) erfasst
        (
            {"forecast_ist": 10},
            {"fehltage": True, "vorplanung": True, "planning": True, "review": False},
        ),
        # Review = Velocity erfasst
        (
            {"velocity": 9},
            {"fehltage": True, "vorplanung": True, "planning": False, "review": True},
        ),
        # Vorplanung = Produktwerte vorgeplant, Fehltage = Zustand bestätigt
        (
            {"products": {}, "absences": {}},
            {"fehltage": False, "vorplanung": False, "planning": False, "review": False},
        ),
    ],
)
def test_step_bar_marks_mean_what_the_board_steps_say(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, fields: dict, done: dict
):
    """Was als erledigt gilt, bleibt wie in ``board_steps_done`` – das Symbol zeigt es nur an."""
    _change_2026_22(data_dir, **fields)
    at = goto(start(data_dir, monkeypatch), "planning")
    at.selectbox(key="planning-sprint").set_value("2026.22").run()
    assert not at.exception, at.exception
    assert nav_done(at) == done


@pytest.mark.parametrize(
    ("fields", "checked"),
    [
        ({}, True),  # Demo: Fehltage eingetragen
        ({"absences": {}}, False),  # nichts eingetragen: unbekannt
        ({"absences": {}, "absence_state": "confirmed"}, True),  # ausdrücklich „niemand fehlt“
        ({"absences": {}, "absence_state": "unknown"}, False),
        ({"absences": {}, "expected_absences": {"cem": 2}}, False),  # angekündigt bestätigt nichts
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
        ({}, True),  # Demo: Fehltage eingetragen, Vorplanung erfasst
        ({"absences": {}}, False),  # Fehltage unbekannt
        ({"absences": {}, "absence_state": "confirmed"}, True),
        ({"absences": {}, "absence_state": "unknown"}, False),
        # angekündigt (PO-Vorplanung): bestätigt nichts – Startseite und Schrittleiste stimmen
        ({"absences": {}, "expected_absences": {"cem": 2}}, False),
    ],
)
def test_start_task_and_step_bar_agree_on_prepared_sprint(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, fields: dict, done: bool
):
    """„Sprint vorbereiten“ der Startseite und der Fehltage-Schritt der Leiste sind für
    denselben Sprint nie verschiedener Meinung."""
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
        ({"absences": {}}, "⬜"),  # unbekannt: Sprintdatei vorhanden, Fehltage nicht bestätigt
        ({"absences": {}, "absence_state": "confirmed"}, "✅"),
        ({"absences": {}, "expected_absences": {"cem": 2}}, "⬜"),
    ],
)
def test_planning_progress_line_agrees_with_the_step_bar(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, fields: dict, mark: str
):
    """Die Fortschrittszeile des Planning und die Schrittleiste darüber nennen für „Fehltage“
    denselben Stand."""
    _change_2026_22(data_dir, **fields)
    at = goto(start(data_dir, monkeypatch), "planning")
    assert at.selectbox(key="planning-sprint").value == "2026.22"
    line = next(c.value for c in at.caption if c.value.endswith(" Commitment"))
    assert line.startswith(f"{mark} Fehltage")
    assert nav_done(at)["fehltage"] == (mark == "✅")


def test_board_nav_css_follows_the_step_count():
    """Die Spaltenzahl und die Breite, ab der alle Schritte nebeneinander stehen, hängen an der
    Zahl der Schritte (vier mit, drei ohne den Bereich Produkte)."""
    from sprintforecast.web.ui import _board_nav_css

    four, three = _board_nav_css(4), _board_nav_css(3)
    assert "repeat(4, minmax(0, 1fr))" in four and "min-width: 65.5rem" in four
    assert "repeat(3, minmax(0, 1fr))" in three and "min-width: 49rem" in three
    assert "st-key-board-active-" in four  # der aktive Schritt bekommt die Farbe


def test_start_prepare_says_when_absences_are_only_announced(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _change_2026_22(data_dir, absences={}, expected_absences={"cem": 2})
    at = start(data_dir, monkeypatch)
    assert any("angekündigt, noch nicht bestätigt" in w.value for w in at.main.markdown)
    at.button(key="start-prepare").click().run()  # führt zu den Fehltagen, sie zu bestätigen
    assert at.header[0].value == "Planbare Fehltage"
    assert at.selectbox(key="absences-sprint").value == "2026.22"


def test_absences_save_updates_the_step_bar_at_once(app: AppTest, data_dir: Path):
    """Nach „Fehltage speichern“ zeigt die Leiste den neuen Stand sofort (kein Klick später)."""
    goto(app, "fehltage")
    app.selectbox(key="absences-sprint").set_value("2026.23").run()
    assert not nav_done(app)["fehltage"]  # noch keine Sprintdatei
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
    assert any("Gespeichert" in s.value for s in app.success)  # die Meldung kommt nach dem Laden


def test_absences_page_shows_the_step_bar_and_shares_the_board_sprint(app: AppTest):
    goto(app, "fehltage")
    assert app.selectbox(key="absences-sprint").value == "2026.22"
    assert [key for key, _, active in nav_steps(app) if active] == ["fehltage"]
    assert nav_done(app)["fehltage"]  # 2026.22: Fehltage eingetragen
    app.selectbox(key="absences-sprint").set_value("2026.23").run()
    assert not app.exception, app.exception
    assert not nav_done(app)["fehltage"]  # 2026.23 hat keine Sprintdatei
    goto(app, "planning")
    assert app.selectbox(key="planning-sprint").value == "2026.23"
    assert [key for key, _, active in nav_steps(app) if active] == ["planning"]
    assert not nav_done(app)["fehltage"]


def test_products_page_is_evaluation_only(app: AppTest):
    """B4: Produktwerte werden nur auf den Boards erfasst; die Auswertung hat keine Eingabe."""
    goto(app, "produkte")
    assert not app.main.button  # kein „Produktwerte speichern“
    assert not app.number_input.values or all(
        n.key == "products-n" for n in app.number_input
    )  # nur die Anzahl für den Verlauf
    assert any("Reine Auswertung" in c.value for c in app.caption)
    assert any(len(d.value) for d in app.dataframe)  # Tabelle bleibt sichtbar
    links = [p.proto.page for p in app.get("page_link")]
    assert {"vorplanung", "planning", "review"} <= set(links)


def test_sprint_selection_is_the_same_on_all_pages(app: AppTest):
    """Gleiche Beschriftung, Reihenfolge und Vorgabe; eine Wahl gilt auf allen Seiten."""
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
        # Vorgabe je Aufgabe: Planning-Seiten der nächste Planning-Kandidat, Review der offene
        # Rückblick, Rechenweg der laufende Sprint
        assert box.value == {"review-sprint": "2026.21", "formula-sprint": "2026.21"}.get(
            key, "2026.22"
        )
        seen.append(list(box.options))
    # Rechenweg zeigt die ganze Historie, sonst gleiche Reihenfolge und gleiche Zukunft
    assert all(options == seen[0] for options in seen[:-1])
    assert seen[-1][-len(seen[0]) :] == seen[0] or set(seen[0]) <= set(seen[-1])
    app.selectbox(key="formula-sprint").set_value("2026.23").run()
    for page, key in pages.items():
        goto(app, page)
        assert app.selectbox(key=key).value == "2026.23"
