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
