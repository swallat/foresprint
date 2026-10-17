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
    assert values[:2] == ["9,5 PT", "11,2 PT"]  # wie `sprintforecast forecast demo`
    # Mit Personenliste kommt die Kapazität aus Kalender und Personen: keine Trend-Warnung
    assert not any("Trend" in w.value for w in app.warning)


def test_forecast_warns_when_absences_unknown_and_no_history(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    team = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team.read_text())
    raw["capacity"]["absence_history"] = 0  # keine Schätzung
    team.write_text(yaml.safe_dump(raw))
    at = start(data_dir, monkeypatch)
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
    assert any("Arbeitstage Mo–Fr" in c.value for c in app.caption)
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
    assert "in 85 % der Simulationen" in labels
    assert "mit 85 % Sicherheit" not in labels  # keine Zusage: modellabhängige Häufigkeit
    # Die Simulation zieht nur aus dem Fenster (5 Sprints): Warnung und Stichprobe sichtbar
    assert any("Wenig Daten" in w.value and "5 Sprints" in w.value for w in app.warning)
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
    at = start(data_dir, monkeypatch)
    assert any(m.value.endswith("PT") and m.value != "– PT" for m in at.metric)
    assert any("Wenig Daten" in w.value for w in at.warning)
    assert not any("Noch kein Forecast" in i.value for i in at.info)
    sprints[2].unlink()  # nur zwei Sprints mit Velocity
    at = start(data_dir, monkeypatch)
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
    assert app.selectbox(key="vorplanung-sprint").value == "2026.22"
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


def test_board_sprint_carries_over_between_boards(app: AppTest):
    goto(app, "vorplanung")
    app.selectbox(key="vorplanung-sprint").set_value("2026.21").run()
    goto(app, "planning")
    assert app.selectbox(key="planning-sprint").value == "2026.21"
    goto(app, "review")
    assert app.selectbox(key="review-sprint").value == "2026.21"


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
    assert any("später als" in m.value for m in app.metric)
    assert any("höchstens" in c.value and "Sprints" in c.value for c in app.caption)


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
    at = start(data_dir, monkeypatch)
    assert any("Lücken: 1 Sprint" in i.value for i in at.info)


def test_absences_page_answers_how_much_fits_into_the_next_sprint(app: AppTest):
    """K2-Abnahme: Wer Fehltage einträgt, sieht sofort, wie viel in den nächsten Sprint passt."""
    goto(app, "fehltage")
    text = " ".join(m.value for m in app.markdown)
    assert "In den nächsten Sprint 2026.22 passen 11,2 PT" in text
    frame = next(d.value for d in app.dataframe if "Kapazität (PT)" in d.value.columns)
    assert frame.loc[frame["Sprint"] == "2026.22", "Forecast PLAN (PT)"].iloc[0] == "11,2"


@pytest.mark.parametrize("page", ["vorplanung", "planning", "review"])
def test_board_navigation_highlights_the_active_page(app: AppTest, page: str):
    """Die aktive Board-Seite ist hervorgehoben (kein ausgegrauter Link); die anderen sind Links."""
    goto(app, page)
    active = [m.value for m in app.markdown if "board-active" in m.value]
    assert len(active) == 1
    title = {"vorplanung": "PO-Vorplanung", "planning": "Planning", "review": "Sprint abschließen"}
    assert title[page] in active[0]
