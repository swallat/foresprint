# SPDX-License-Identifier: EUPL-1.2
"""The worked example of the excel-import skill must stay a valid data folder."""

from pathlib import Path

from typer.testing import CliRunner

from foresprint.cli import app

SKILL = Path(__file__).parent.parent / "skills" / "excel-import"


def test_skill_has_frontmatter():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert "name: excel-import" in head
    assert "description:" in head


def test_expected_example_passes_check():
    result = CliRunner(env={"COLUMNS": "200"}).invoke(
        app,
        [
            "--data",
            str(SKILL / "examples" / "expected" / "teams"),
            "--as-of",
            "2026-02-16",
            "check",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Error" not in result.output
