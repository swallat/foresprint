# SPDX-License-Identifier: EUPL-1.2
"""Command ``tickets``: preview, apply, report and the switch ``features.tickets``."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sprintforecast.cli import app

runner = CliRunner(env={"COLUMNS": "200"})
DATA = Path(__file__).parent / "data"


def run(data_dir: Path, *args: str):
    return runner.invoke(app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args])


@pytest.fixture
def ticket_dir(data_dir: Path) -> Path:
    """Demo data with the ticket pre-planning switched on and two projects."""
    team = data_dir / "demo"
    doc = yaml.safe_load((team / "team.yaml").read_text(encoding="utf-8"))
    doc["features"]["tickets"] = True
    doc["tracker"] = {
        "kind": "csv",
        "fields": {"estimate": "Story Points", "remaining": "Remaining", "epic": "Epic Link"},
        "refined_label": "Refined",
    }
    (team / "team.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    (team / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": 1,
                "projects": [
                    {
                        "id": "payment",
                        "name": "Payment",
                        "product": "webshop",
                        "target": "2027-03-31",
                        "match": {"epic": ["ABC-100"]},
                    },
                    {
                        "id": "migration",
                        "name": "Migration",
                        "product": "webshop",
                        "target": "2026-11-30",
                        "match": {"epic": ["ABC-200"]},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return data_dir


def test_off_by_default(data_dir: Path):
    result = run(data_dir, "tickets", "demo")
    assert result.exit_code == 1
    assert "ausgeschaltet" in result.output
    assert not (data_dir / "demo" / "tickets.yaml").exists()


def test_without_tickets_it_says_how_to_import(ticket_dir: Path):
    result = run(ticket_dir, "tickets", "demo")
    assert result.exit_code == 0, result.output
    assert "--import" in result.output


def test_preview_writes_nothing(ticket_dir: Path):
    result = run(ticket_dir, "tickets", "demo", "--import", str(DATA / "jira_en.csv"))
    assert result.exit_code == 0, result.output
    assert "ABC-1" in result.output and "ABC-2" in result.output
    assert "Nur Vorschau" in result.output
    assert not (ticket_dir / "demo" / "tickets.yaml").exists()


def test_apply_writes_and_reports(ticket_dir: Path):
    path = DATA / "jira_en.csv"
    result = run(ticket_dir, "tickets", "demo", "--import", str(path), "--apply")
    assert result.exit_code == 0, result.output
    written = yaml.safe_load((ticket_dir / "demo" / "tickets.yaml").read_text(encoding="utf-8"))
    assert {tk["key"] for tk in written["tickets"]} >= {"ABC-1", "ABC-2"}
    assert written["source"] == "jira_en.csv"
    # the report follows the import: both projects and a sprint table
    assert "Payment" in result.output and "Migration" in result.output
    assert "Ampel" in result.output
    again = run(ticket_dir, "tickets", "demo")
    assert again.exit_code == 0 and "Payment" in again.output


def test_english_output(ticket_dir: Path, english):
    path = DATA / "jira_en.csv"
    result = run(ticket_dir, "tickets", "demo", "--import", str(path), "--apply")
    assert result.exit_code == 0, result.output
    assert "Traffic light" in result.output and "Projects" in result.output


def test_german_export_is_read(ticket_dir: Path):
    result = run(ticket_dir, "tickets", "demo", "--import", str(DATA / "jira_de.csv"))
    assert result.exit_code == 0, result.output


def test_missing_column_is_an_error(ticket_dir: Path):
    result = run(ticket_dir, "tickets", "demo", "--import", str(DATA / "jira_missing.csv"))
    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_apply_without_import_is_refused(ticket_dir: Path):
    result = run(ticket_dir, "tickets", "demo", "--apply")
    assert result.exit_code == 1
    assert not (ticket_dir / "demo" / "tickets.yaml").exists()


def test_the_core_does_not_import_the_ticket_modules(data_dir: Path, tmp_path: Path):
    """Feature off: running another command loads none of the pre-planning modules."""
    code = (
        "import sys\n"
        "from typer.testing import CliRunner\n"
        "from sprintforecast.cli import app\n"
        "r = CliRunner().invoke(app, ['--data', sys.argv[1], '--as-of', '2026-10-15', "
        "'forecast', 'demo'])\n"
        "assert r.exit_code == 0, r.output\n"
        "bad = [m for m in ('sprintforecast.preplan', 'sprintforecast.ticket_import', "
        "'sprintforecast.sources') if m in sys.modules]\n"
        "print('LOADED', bad)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(data_dir)], capture_output=True, text=True, check=True
    )
    assert "LOADED []" in out.stdout, out.stdout + out.stderr


# --- Review fixes ----------------------------------------------------------------------------


def changed_csv(tmp_path: Path, *replacements: tuple[str, str]) -> Path:
    text = (DATA / "jira_en.csv").read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    path = tmp_path / "changed.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_preview_explains_every_change(ticket_dir: Path, tmp_path: Path):
    team = ticket_dir / "demo" / "team.yaml"
    doc = yaml.safe_load(team.read_text(encoding="utf-8"))
    doc["tracker"]["refined_also_if"] = {"status": ["Ready"]}
    team.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    first_csv = changed_csv(tmp_path, ("To Do,,,,,,,0|i0004", "To Do,,Refined,,,,,0|i0004"))
    first = run(ticket_dir, "tickets", "demo", "--import", str(first_csv))
    # sprint name the tool does not know: the name is what the user has to map
    assert "Sprintname „Sprint 22“" in first.output
    assert "Label ohne Schätzung" in first.output  # ABC-4
    assert "nur über refined_also_if, Label fehlt" in first.output  # ABC-2
    run(ticket_dir, "tickets", "demo", "--import", str(DATA / "jira_en.csv"), "--apply")
    # ABC-1: estimate 5 -> 6; ABC-2 removed from the export; its earmark is kept
    (ticket_dir / "demo" / "preplan.yaml").write_text(
        yaml.safe_dump({"schema": 1, "earmarks": [{"ticket": "ABC-2", "sprint": "2026.23"}]}),
        encoding="utf-8",
    )
    lines = (DATA / "jira_en.csv").read_text(encoding="utf-8").splitlines(keepends=True)
    kept = "".join(line for line in lines if not line.startswith('"Schema change'))
    path = tmp_path / "second.csv"
    path.write_text(kept.replace("Sprint 22,0|i0001:,5,3.5", "Sprint 22,0|i0001:,6,3.5"), "utf-8")
    result = run(ticket_dir, "tickets", "demo", "--import", str(path))
    assert result.exit_code == 0, result.output
    assert "Schätzung" in result.output  # the changed field
    assert "Vormerkung für Sprint 2026.23 bleibt" in result.output  # missing ticket


def test_preview_notes_in_english(ticket_dir: Path, tmp_path: Path, english):
    path = changed_csv(tmp_path, ("To Do,,,,,,,0|i0004", "To Do,,Refined,,,,,0|i0004"))
    result = run(ticket_dir, "tickets", "demo", "--import", str(path))
    assert 'Sprint name "Sprint 22"' in result.output
    assert "label without estimate" in result.output


def test_commit_without_apply_is_refused(ticket_dir: Path):
    result = run(ticket_dir, "tickets", "demo", "--import", str(DATA / "jira_en.csv"), "--commit")
    assert result.exit_code == 1 and "--apply" in result.output
    assert not (ticket_dir / "demo" / "tickets.yaml").exists()


def test_import_without_changes_writes_nothing(ticket_dir: Path):
    path = str(DATA / "jira_en.csv")
    run(ticket_dir, "tickets", "demo", "--import", path, "--apply")
    file = ticket_dir / "demo" / "tickets.yaml"
    before = file.read_text(encoding="utf-8")
    file.write_text(before.replace("imported:", "imported: 2020-01-01 00:00:00\n#", 1), "utf-8")
    stamped = file.read_text(encoding="utf-8")
    result = run(ticket_dir, "tickets", "demo", "--import", path, "--apply")
    assert result.exit_code == 0, result.output
    assert "Keine Änderungen" in result.output
    assert file.read_text(encoding="utf-8") == stamped  # not rewritten, no new time stamp
    assert "Payment" in result.output  # the report still follows


def test_validation_issues_are_printed_once_after_apply(ticket_dir: Path):
    (ticket_dir / "demo" / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": 1,
                "projects": [
                    {"id": "payment", "name": "Payment", "product": "no-such-product",
                     "target": "2027-03-31", "match": {"epic": ["ABC-100"]}},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )  # fmt: skip
    result = run(ticket_dir, "tickets", "demo", "--import", str(DATA / "jira_en.csv"), "--apply")
    assert result.exit_code == 0, result.output
    problems = [line for line in result.output.splitlines() if "no-such-product" in line]
    assert problems and len(problems) == len(set(problems)), result.output


def test_report_says_when_there_is_no_budget(ticket_dir: Path):
    for number in range(1, 21):
        (ticket_dir / "demo" / "sprints" / f"2026.{number}.yaml").unlink()
    path = str(DATA / "jira_en.csv")
    result = run(ticket_dir, "tickets", "demo", "--import", path, "--apply")
    assert result.exit_code == 0, result.output
    assert "Noch kein Budget" in result.output
    assert "kein Budget" in result.output and "zu groß" not in result.output
