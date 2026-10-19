# SPDX-License-Identifier: EUPL-1.2
"""Sprint-IDs nachträglich ändern: Planung, Dateien, Befehlszeile und Einstellungsseite."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sprintforecast.cli import app
from sprintforecast.model import Numbering
from sprintforecast.renaming import Rename, apply_renames, plan_renames
from sprintforecast.storage import DataError, Repository

runner = CliRunner()


def run(data_dir: Path, *args: str, input: str | None = None):
    return runner.invoke(
        app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args], input=input
    )


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def ids(data_dir: Path) -> list[str]:
    """Sprint-IDs der Dateien, numerisch sortiert (2026.2 vor 2026.10)."""
    found = (p.stem for p in (data_dir / "demo" / "sprints").glob("*.yaml"))
    return sorted(found, key=lambda s: [int(part) for part in s.split(".")])


# --- Planung ------------------------------------------------------------------------------


def test_following_sprints_count_on_from_the_new_id(data_dir: Path):
    data = Repository(data_dir).load("demo")  # 2026.1 … 2026.22
    renames = plan_renames(data, "2026.20", "2026.30")
    assert renames == [
        Rename("2026.20", "2026.30"),
        Rename("2026.21", "2026.31"),
        Rename("2026.22", "2026.32"),
    ]


def test_earlier_sprints_are_untouched_and_unchanged_ids_are_skipped(data_dir: Path):
    data = Repository(data_dir).load("demo")
    assert plan_renames(data, "2026.22", "2026.22") == []
    # Ab dem ersten Sprint: alle 22 Dateien, in Reihenfolge des Starts.
    renames = plan_renames(data, "2026.1", "2026.15")
    assert [r.old for r in renames] == [f"2026.{n}" for n in range(1, 23)]
    assert [r.new for r in renames] == [f"2026.{n}" for n in range(15, 37)]


def test_renumbering_across_a_year_change(data_dir: Path):
    data = Repository(data_dir).load("demo")
    # 2026.22 beginnt am 28.10.; ein Folgesprint im neuen Jahr fängt mit 2027.1 an.
    data.sprints[-1].start, data.sprints[-1].end = date(2026, 12, 23), date(2027, 1, 6)
    renames = plan_renames(data, "2026.21", "2026.40")
    assert renames == [Rename("2026.21", "2026.40"), Rename("2026.22", "2026.41")]
    data.sprints[-1].start = date(2027, 1, 6)
    assert plan_renames(data, "2026.21", "2026.40")[-1] == Rename("2026.22", "2027.1")


@pytest.mark.parametrize(
    ("sprint", "new", "expected"),
    [
        ("2026.99", "2026.5", "nicht gespeichert"),
        ("2026.21", "", "neue Sprint-ID eingeben"),
        ("2026.21", "a/b", "nicht zulässig"),
        ("2026.21", "x", "schon vergeben"),  # Folgesprint von „x“ wäre 2026.1
        ("2026.21", "2026.3", "schon vergeben"),  # 2026.3 existiert vor 2026.21
    ],
)
def test_rejected_renames(data_dir: Path, sprint: str, new: str, expected: str):
    data = Repository(data_dir).load("demo")
    with pytest.raises(DataError, match=expected):
        plan_renames(data, sprint, new)


def test_a_chain_may_take_over_the_ids_of_later_sprints(data_dir: Path):
    """2026.1 → 2026.0: die Kette nimmt die alten IDs ihrer Nachfolger ein – nur frühere Sprints
    (die nicht umbenannt werden) blockieren."""
    data = Repository(data_dir).load("demo")
    with pytest.raises(DataError, match="schon vergeben"):
        plan_renames(data, "2026.2", "2026.1")  # 2026.1 ist früher: belegt
    renames = plan_renames(data, "2026.1", "2026.0")  # 2026.2 wird 2026.1 usw.
    assert renames[:2] == [Rename("2026.1", "2026.0"), Rename("2026.2", "2026.1")]


def test_sequential_numbering(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    data.team.sprint.numbering = Numbering.SEQUENTIAL
    with pytest.raises(DataError, match="eine Zahl"):
        plan_renames(data, "2026.22", "abc")
    assert plan_renames(data, "2026.21", "41") == [
        Rename("2026.21", "41"),
        Rename("2026.22", "42"),
    ]


# --- Dateien ------------------------------------------------------------------------------


def test_apply_moves_sprint_files_and_minutes(data_dir: Path):
    repo = Repository(data_dir)
    minutes = data_dir / "demo" / "protokolle"
    minutes.mkdir()
    kept = minutes / "2026.19-review-20261001-120000.md"
    moved = minutes / "2026.21-planning-20261013-090000-ab12.md"
    obsolete = minutes / "2026.21-planning-20261012-090000_obsolet_20261013-090000.md"
    for p in (kept, moved, obsolete):
        p.write_text("# minutes\n", encoding="utf-8")
    data = repo.load("demo")
    before = (data_dir / "demo" / "sprints" / "2026.21.yaml").read_text(encoding="utf-8")
    renames = plan_renames(data, "2026.21", "2026.41")
    applied = apply_renames(repo, data, renames)
    paths = applied.files
    assert {p.name for p in applied.touched} == {
        "2026.21.yaml", "2026.22.yaml", "2026.41.yaml", "2026.42.yaml",
        moved.name, obsolete.name,
        "2026.41-planning-20261013-090000-ab12.md",
        "2026.41-planning-20261012-090000_obsolet_20261013-090000.md",
    }  # fmt: skip
    assert [p.name for p in paths] == ["2026.41.yaml", "2026.42.yaml"]
    assert ids(data_dir) == [f"2026.{n}" for n in range(1, 21)] + ["2026.41", "2026.42"]
    renamed = load(paths[0])
    assert renamed["id"] == "2026.41"
    assert renamed["absences"] == {"ben": 3, "cem": 5, "dana": 3}  # Inhalt unverändert
    assert paths[0].read_text(encoding="utf-8").startswith("# Sprint 2026.41.")
    assert before.replace("2026.21", "2026.41") == paths[0].read_text(encoding="utf-8")
    assert sorted(p.name for p in minutes.iterdir()) == [
        "2026.19-review-20261001-120000.md",
        "2026.41-planning-20261012-090000_obsolet_20261013-090000.md",
        "2026.41-planning-20261013-090000-ab12.md",
    ]
    after = repo.load("demo")  # Zwischenspeicher geleert, Team weiterhin ladbar
    assert [s.id for s in after.sprints][-3:] == ["2026.20", "2026.41", "2026.42"]
    assert run(data_dir, "check").exit_code == 0


def test_apply_with_a_chain_that_overlaps_itself(data_dir: Path):
    """2026.20 → 2026.21: die neue ID ist die alte des Nachfolgers; nichts geht verloren."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    velocity = {s.id: s.forecast_ist for s in data.sprints}
    apply_renames(repo, data, plan_renames(data, "2026.20", "2026.21"))
    after = repo.load("demo")
    assert [s.id for s in after.sprints][-3:] == ["2026.21", "2026.22", "2026.23"]
    assert after.sprint("2026.21").forecast_ist == velocity["2026.20"]
    assert after.sprint("2026.22").forecast_ist == velocity["2026.21"]


def test_overlapping_chain_keeps_every_minutes_file(data_dir: Path):
    """2026.20 → 2026.21 → 2026.22: gleich benannte Protokolle (Termin, Zeitpunkt) dürfen sich
    beim Weiterreichen nicht überschreiben."""
    repo = Repository(data_dir)
    minutes = data_dir / "demo" / "protokolle"
    minutes.mkdir()
    name = "{}-review-20261001-120000.md"
    for sid in ("2026.20", "2026.21", "2026.22"):
        (minutes / name.format(sid)).write_text(f"minutes of {sid}\n", encoding="utf-8")
    data = repo.load("demo")
    apply_renames(repo, data, plan_renames(data, "2026.20", "2026.21"))
    found = {p.name: p.read_text(encoding="utf-8") for p in minutes.iterdir()}
    assert found == {
        name.format("2026.21"): "minutes of 2026.20\n",
        name.format("2026.22"): "minutes of 2026.21\n",
        name.format("2026.23"): "minutes of 2026.22\n",
    }


def test_apply_refuses_a_stray_minutes_file(data_dir: Path):
    repo = Repository(data_dir)
    minutes = data_dir / "demo" / "protokolle"
    minutes.mkdir()
    (minutes / "2026.22-review-20261001-120000.md").write_text("a", encoding="utf-8")
    (minutes / "2026.42-review-20261001-120000.md").write_text("stray", encoding="utf-8")
    data = repo.load("demo")
    with pytest.raises(DataError, match="existiert bereits"):
        apply_renames(repo, data, plan_renames(data, "2026.21", "2026.41"))
    assert ids(data_dir) == [f"2026.{n}" for n in range(1, 23)]
    assert (minutes / "2026.42-review-20261001-120000.md").read_text(encoding="utf-8") == "stray"


def test_apply_refuses_a_stray_file_and_changes_nothing(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    stray = data_dir / "demo" / "sprints" / "2026.42.yaml"
    stray.write_text("broken", encoding="utf-8")
    renames = plan_renames(data, "2026.21", "2026.41")
    with pytest.raises(DataError, match="existiert bereits"):
        apply_renames(repo, data, renames)
    assert ids(data_dir) == [f"2026.{n}" for n in range(1, 23)] + ["2026.42"]


def test_apply_rolls_back_when_a_file_cannot_be_written(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = Repository(data_dir)
    data = repo.load("demo")
    minutes = data_dir / "demo" / "protokolle"
    minutes.mkdir()
    (minutes / "2026.21-planning-20261013-090000.md").write_text("x", encoding="utf-8")
    original = Repository.save_sprint

    def failing(self, key, sprint):
        if sprint.id == "2026.42":
            raise OSError("disk full")
        return original(self, key, sprint)

    monkeypatch.setattr(Repository, "save_sprint", failing)
    before = {p.name: p.read_bytes() for p in (data_dir / "demo" / "sprints").iterdir()}
    with pytest.raises(OSError, match="disk full"):
        apply_renames(repo, data, plan_renames(data, "2026.21", "2026.41"))
    assert {p.name: p.read_bytes() for p in (data_dir / "demo" / "sprints").iterdir()} == before
    assert [p.name for p in minutes.iterdir()] == ["2026.21-planning-20261013-090000.md"]


# --- Befehlszeile -------------------------------------------------------------------------


def test_cli_renames_and_shows_the_chain(data_dir: Path):
    result = run(data_dir, "rename-sprint", "demo", "2026.21", "2026.41")
    assert result.exit_code == 0, result.output
    for part in ("2026.21", "2026.41", "2026.22", "2026.42", "Gespeichert: 2026.41.yaml"):
        assert part in result.output
    assert ids(data_dir)[-2:] == ["2026.41", "2026.42"]
    assert run(data_dir, "forecast", "demo").exit_code == 0


def test_cli_rejects_bad_ids(data_dir: Path):
    result = run(data_dir, "rename-sprint", "demo", "2026.21", "2026.3")
    assert result.exit_code == 1
    assert "schon vergeben" in result.output
    assert ids(data_dir) == [f"2026.{n}" for n in range(1, 23)]
    result = run(data_dir, "rename-sprint", "demo", "2026.22", "2026.22")
    assert result.exit_code == 0
    assert "Nichts zu ändern" in result.output


def test_cli_commit_records_the_move(data_dir: Path, tmp_path: Path):
    import subprocess

    git = ["git", "-C", str(tmp_path)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "config", "user.name", "T"], check=True)
    subprocess.run([*git, "config", "user.email", "t@example.org"], check=True)
    subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], check=True)
    subprocess.run(
        [*git, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"], check=True
    )
    minutes = data_dir / "demo" / "protokolle"
    minutes.mkdir()
    (minutes / "2026.22-review-20261028-120000.md").write_text("x", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run(
        [*git, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "minutes"], check=True
    )
    # Eine Sprintdatei, die nie committet wurde (z. B. mit „sprints --create“ angelegt).
    assert run(data_dir, "sprints", "demo", "--create").exit_code == 0
    assert (data_dir / "demo" / "sprints" / "2026.23.yaml").is_file()
    result = run(data_dir, "rename-sprint", "demo", "2026.22", "2026.30", "--commit")
    assert result.exit_code == 0, result.output
    assert "Committet" in result.output
    assert (minutes / "2026.30-review-20261028-120000.md").is_file()
    status = subprocess.run([*git, "status", "--porcelain"], capture_output=True, text=True)
    # Sprintdateien und Protokolle umbenannt committet; offen sind nur die übrigen mit
    # „--create“ angelegten (nie committeten) Sprintdateien unter ihrem neuen Namen nicht.
    assert "protokolle" not in status.stdout
    assert " 2026.22.yaml" not in status.stdout and "2026.30.yaml" not in status.stdout
    log = subprocess.run([*git, "log", "-1", "--format=%s"], capture_output=True, text=True)
    assert log.stdout.strip() == "Demo-Team: Sprint 2026.22 heißt jetzt 2026.30"


# --- Weboberfläche ------------------------------------------------------------------------


def test_settings_page_renames(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from sprintforecast.storage import DATA_ENV, STICHTAG_ENV

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    app_path = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=30)
    at.run()
    at.switch_page("seiten/einstellungen.py").run()
    assert not at.exception, at.exception
    assert at.selectbox(key="rename-demo-sprint").value == "2026.21"  # laufender Sprint
    button = next(b for b in at.button if b.label == "Sprint-IDs ändern")
    assert button.disabled  # noch keine neue ID
    at.text_input(key="rename-demo-new").set_value("2026.3").run()
    assert any("schon vergeben" in e.value for e in at.error)
    at.text_input(key="rename-demo-new").set_value("2026.41").run()
    assert not at.error
    assert at.dataframe[0].value.to_dict("list") == {
        "bisher": ["2026.21", "2026.22"],
        "neu": ["2026.41", "2026.42"],
    }
    next(b for b in at.button if b.label == "Sprint-IDs ändern").click().run()
    assert not at.exception, at.exception
    assert any("2026.41.yaml" in s.value for s in at.success)
    assert ids(data_dir)[-2:] == ["2026.41", "2026.42"]


def test_settings_page_without_sprints_has_no_rename_section(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from sprintforecast.storage import DATA_ENV, STICHTAG_ENV

    for p in (data_dir / "demo" / "sprints").glob("*.yaml"):
        p.unlink()
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    app_path = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=30)
    at.run()
    at.switch_page("seiten/einstellungen.py").run()
    assert not at.exception, at.exception
    assert not [b for b in at.button if b.label == "Sprint-IDs ändern"]
    assert at.text_input(key="settings-demo-sprint.first_id").value == "2026.1"
