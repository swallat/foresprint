# SPDX-License-Identifier: EUPL-1.2
"""Write and read errors of the data files: understandable message instead of a traceback."""

import os
import shutil
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner
from webfixtures import nav_done

from sprintforecast import storage
from sprintforecast.cli import app as cli_app
from sprintforecast.forecast import build_forecast
from sprintforecast.model import Sprint
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, FileAccessError, Repository

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
runner = CliRunner(env={"COLUMNS": "200"})


def locked(*args, **kwargs):
    raise PermissionError(13, "Permission denied")


def block_report(data_dir: Path) -> None:
    """A folder with the report's name: the file cannot be written."""
    report = data_dir / "demo" / "FORECAST.md"
    report.unlink(missing_ok=True)
    report.mkdir()


def sprint_file(data_dir: Path, sprint: str) -> Path:
    return data_dir / "demo" / "sprints" / f"{sprint}.yaml"


# --- Storage layer --------------------------------------------------------------------------


def test_save_failure_names_file_and_reason_and_changes_nothing(data_dir: Path, monkeypatch):
    repo = Repository(data_dir)
    data = repo.load("demo")
    path = data_dir / "demo" / "team.yaml"
    before = path.read_bytes()
    data.team.name = "Anderer Name"
    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(FileAccessError) as caught:
        repo.save_team(data.team)
    assert str(path) in str(caught.value)
    assert "Permission denied" in str(caught.value)
    assert "nicht gespeichert" in str(caught.value)
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.glob("*.tmp")] == []  # no temporary file left behind


def test_save_failure_when_the_folder_cannot_be_created(data_dir: Path):
    repo = Repository(data_dir)
    sprint = repo.load("demo").sprints[-1]
    blocker = data_dir / "demo" / "sprints"
    shutil.rmtree(blocker)
    blocker.write_text("keine Ordner", encoding="utf-8")  # a file instead of the folder
    with pytest.raises(FileAccessError, match="nicht gespeichert"):
        repo.save_sprint("demo", sprint)


def test_unreadable_file_is_reported_with_the_path(data_dir: Path):
    # A folder with the name of a sprint file: reading fails (Linux: IsADirectoryError,
    # Windows: PermissionError), both are an OSError.
    (data_dir / "demo" / "sprints" / "2026.99.yaml").mkdir()
    with pytest.raises(FileAccessError) as caught:
        Repository(data_dir).load("demo")
    assert "2026.99.yaml" in str(caught.value)
    assert "nicht lesbar" in str(caught.value)


def test_missing_file_is_still_reported_as_missing(tmp_path: Path):
    with pytest.raises(storage.DataError, match="Datei fehlt") as caught:
        storage._read(tmp_path / "gibt-es-nicht.yaml")
    assert not isinstance(caught.value, FileAccessError)  # missing is not an access error


def test_unreadable_sprint_file_is_not_overwritten_when_pinning_the_state(
    data_dir: Path, monkeypatch
):
    """When saving, ``save_sprint`` reads the existing file to take over the absences status.
    If it is not readable, this must not silently turn into "confirmed"."""
    repo = Repository(data_dir)
    sprint = repo.load("demo").sprint("2026.21")
    sprint.absence_state = None
    path = sprint_file(data_dir, "2026.21")
    before = path.read_bytes()
    real = Path.read_text

    def unreadable(self, *args, **kwargs):
        if self == path:
            raise PermissionError(13, "Permission denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(FileAccessError, match="nicht lesbar"):
        repo.save_sprint("demo", sprint)
    assert path.read_bytes() == before


def test_import_checks_unreadable_files_with_a_message(data_dir: Path, monkeypatch):
    repo = Repository(data_dir)
    data = repo.load("demo")
    team_file = data_dir / "demo" / "team.yaml"
    real = Path.read_text

    def unreadable(self, *args, **kwargs):
        if self == team_file:
            raise PermissionError(13, "Permission denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(FileAccessError, match="nicht lesbar"):
        storage.import_sprints(repo, data.team, data.sprints[:1])


def test_delete_failure_is_reported(data_dir: Path, monkeypatch):
    real_unlink = Path.unlink

    def unlink(self, *args, **kwargs):
        if self.suffix == ".yaml":
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(FileAccessError, match="nicht gelöscht"):
        Repository(data_dir).delete_sprint("demo", "2026.21")
    assert sprint_file(data_dir, "2026.21").exists()


def test_write_text_reports_failures(tmp_path: Path):
    target = tmp_path / "FORECAST.md"
    target.mkdir()  # file cannot be written (folder with this name)
    with pytest.raises(FileAccessError, match=r"FORECAST\.md: nicht gespeichert"):
        storage.write_text(target, "# Bericht")


def test_write_text_is_atomic(tmp_path: Path, monkeypatch):
    """The report is replaced via a temporary file: if that fails, the old one is kept
    (the message "not changed" is true)."""
    target = tmp_path / "FORECAST.md"
    target.write_text("# alt", encoding="utf-8")
    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(FileAccessError, match="nicht verändert"):
        storage.write_text(target, "# neu")
    assert target.read_text(encoding="utf-8") == "# alt"
    assert [p.name for p in tmp_path.iterdir()] == ["FORECAST.md"]  # no temporary file
    monkeypatch.undo()
    storage.write_text(target, "# neu")
    assert target.read_text(encoding="utf-8").strip() == "# neu"


# --- Web UI --------------------------------------------------------------------------


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


def test_web_save_shows_the_error_and_keeps_the_page(
    app: AppTest, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    goto(app, "review")
    app.selectbox(key="review-sprint").set_value("2026.21").run()
    app.number_input(key="velocity-2026.21").set_value(9.25)
    before = sprint_file(data_dir, "2026.21").read_bytes()
    monkeypatch.setattr(storage, "_write_atomic", locked)
    click(app, "Review speichern")
    assert not app.exception
    assert any("nicht gespeichert" in e.value and "Permission denied" in e.value for e in app.error)
    assert not any("Gespeichert" in s.value for s in app.success)
    assert not nav_done(app)["review"]
    assert sprint_file(data_dir, "2026.21").read_bytes() == before


def test_web_page_keeps_rendering_after_a_failed_save(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """save() catches the error itself: the page keeps rendering afterwards (here the
    "Reset absences" section below the save button) instead of aborting in run_page."""
    repo = Repository(data_dir)
    last = build_forecast(repo.load("demo"), date(2026, 10, 15)).entries[-1].sprint
    repo.save_sprint("demo", Sprint(id=last.id, start=last.start, end=last.end))
    app = start(data_dir, monkeypatch)
    goto(app, "fehltage")
    assert any("Fehltage zurücksetzen" in h.value for h in app.subheader)
    frame = next(d.value for d in app.dataframe if "Niemand fehlt" in d.value.columns)
    rows = {i: {"Niemand fehlt": True} for i, s in enumerate(frame["Sprint"]) if s == "2026.23"}
    app.session_state[f"absence-states-{frame['Sprint'].iloc[0]}-{len(frame)}"] = {
        "edited_rows": rows,
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    monkeypatch.setattr(storage, "_write_atomic", locked)
    click(app, "Fehltage speichern")
    assert any("nicht gespeichert" in e.value for e in app.error)
    assert any("Fehltage zurücksetzen" in h.value for h in app.subheader)


def test_web_report_button_shows_the_error(app: AppTest, data_dir: Path):
    block_report(data_dir)
    goto(app, "forecast")
    click(app, "Bericht FORECAST.md schreiben")
    assert not app.exception
    assert any("FORECAST.md: nicht gespeichert" in e.value for e in app.error)


def test_web_reset_absences_shows_the_error(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    repo = Repository(data_dir)
    data = repo.load("demo")
    following = build_forecast(data, date(2026, 10, 15)).entries[-1].sprint
    repo.save_sprint("demo", Sprint(id=following.id, start=following.start, end=following.end))
    app = start(data_dir, monkeypatch)
    goto(app, "fehltage")
    real_unlink = Path.unlink

    def unlink(self, *args, **kwargs):
        if self.suffix == ".yaml":
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    click(app, "Auf „keine Informationen“ zurücksetzen")
    assert not app.exception
    assert any("nicht gelöscht" in e.value for e in app.error)
    assert sprint_file(data_dir, following.id).exists()


# --- Command line --------------------------------------------------------------------------


def run(data_dir: Path, *args: str, input: str | None = None):
    return runner.invoke(
        cli_app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args], input=input
    )


def test_cli_write_failure_is_a_message_with_exit_code_1(data_dir: Path, monkeypatch):
    monkeypatch.setattr(storage, "_write_atomic", locked)
    result = run(data_dir, "absences", "demo", "2026.23", input="2\n0\n1,5\n0\n")
    assert result.exit_code == 1, result.output
    assert "nicht gespeichert" in result.output and "Permission denied" in result.output
    assert "Traceback" not in result.output
    assert not sprint_file(data_dir, "2026.23").exists()


def test_every_cli_command_is_guarded():
    """Commands from extensions (registered separately) also report access errors as a
    message."""
    assert cli_app.registered_commands
    for command in cli_app.registered_commands:
        assert getattr(command.callback, "_guarded", False), command.name


def test_cli_report_failure_is_a_message(data_dir: Path):
    block_report(data_dir)
    result = run(data_dir, "report", "demo")
    assert result.exit_code == 1, result.output
    assert "FORECAST.md: nicht gespeichert" in result.output


def test_cli_read_failure_is_a_message(data_dir: Path):
    (data_dir / "demo" / "sprints" / "2026.99.yaml").mkdir()
    result = run(data_dir, "forecast", "demo")
    assert result.exit_code == 1, result.output
    assert "2026.99.yaml" in result.output and "nicht lesbar" in result.output
