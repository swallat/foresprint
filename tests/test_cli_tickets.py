# SPDX-License-Identifier: EUPL-1.2
"""Command ``tickets``: preview, apply, report and the switch ``features.tickets``."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from gitrepos import git
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
        "'sprintforecast.sources', 'sprintforecast.sources.jira', 'httpx', 'keyring') "
        "if m in sys.modules]\n"
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


# --- Step 4: range, variants and handover ----------------------------------------------------


def write_tickets(data_dir: Path, tickets: list[dict]) -> None:
    """tickets.yaml with the given tickets (key and project; the rest has defaults)."""
    rows = []
    for i, spec in enumerate(tickets):
        rows.append(
            {"title": spec["key"], "status": "To Do", "estimate": 1.0, "estimate_source": "refined"}
            | {"rank": f"0|{i:04d}"}
            | spec
        )
    (data_dir / "demo" / "tickets.yaml").write_text(
        yaml.safe_dump(
            {"schema": 1, "imported": "2026-10-15 09:00:00", "source": "test.csv", "tickets": rows},
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def migration_tickets(count: int) -> list[dict]:
    """``count`` refined tickets of 1 in the project "migration" (target sprint 2026.23)."""
    return [{"key": f"M-{i}", "project": "migration"} for i in range(count)]


def test_project_table_shows_the_range_of_the_variants(ticket_dir: Path):
    write_tickets(ticket_dir, migration_tickets(5))
    result = run(ticket_dir, "tickets", "demo")
    assert result.exit_code == 0, result.output
    for header in ("Letzter Sprint optimistisch", "Letzter Sprint Median", "konservativ"):
        assert header in result.output
    row = next(line for line in result.output.splitlines() if "Migration" in line)
    # last sprint optimistic / median / conservative; median light with the range in brackets
    cells = [cell.strip() for cell in row.split("│")]
    assert cells[4:7] == ["2026.23", "2026.23", "2026.24"]
    assert cells[7] == "knapp (knapp – verfehlt)"
    assert "Keine Bandbreite" not in result.output


def test_a_project_is_on_track_in_the_range_sense_only_when_all_variants_are(ticket_dir: Path):
    write_tickets(ticket_dir, migration_tickets(1))
    result = run(ticket_dir, "tickets", "demo")
    row = next(line for line in result.output.splitlines() if "Migration" in line)
    assert [cell.strip() for cell in row.split("│")][7] == "im Plan"
    write_tickets(ticket_dir, migration_tickets(3))  # optimistic on track, median tight
    result = run(ticket_dir, "tickets", "demo")
    row = next(line for line in result.output.splitlines() if "Migration" in line)
    assert [cell.strip() for cell in row.split("│")][7] == "knapp (im Plan – knapp)"


def test_range_in_english(ticket_dir: Path, english):
    write_tickets(ticket_dir, migration_tickets(5))
    result = run(ticket_dir, "tickets", "demo")
    assert "Last sprint optimistic" in result.output and "Last sprint conservative" in result.output
    assert "tight (tight – missed)" in result.output


def test_without_enough_history_only_the_median_is_shown(ticket_dir: Path):
    for number in range(1, 21):
        (ticket_dir / "demo" / "sprints" / f"2026.{number}.yaml").unlink()
    write_tickets(ticket_dir, migration_tickets(2))
    result = run(ticket_dir, "tickets", "demo")
    assert result.exit_code == 0, result.output
    assert result.output.count("Keine Bandbreite") == 1
    assert "optimistisch" not in result.output and "Letzter Sprint" in result.output
    assert "Nur die Median" not in result.output  # no second hint
    result = run(ticket_dir, "tickets", "demo", "--variant", "conservative")
    assert result.exit_code == 0 and result.output.count("Keine Bandbreite") == 1


def test_variant_option_selects_the_sprint_table(ticket_dir: Path):
    write_tickets(ticket_dir, migration_tickets(14))

    def budgets(*args: str) -> dict[str, str]:
        result = run(ticket_dir, "tickets", "demo", *args)
        assert result.exit_code == 0, result.output
        lines = [row.split("│") for row in result.output.splitlines() if row.startswith("│ 20")]
        return {cells[1].strip(): cells[2].strip() for cells in lines if len(cells) > 2}

    median = budgets()
    assert budgets("--variant", "median") == median
    conservative = budgets("--variant", "conservative")
    optimistic = budgets("--variant", "optimistic")
    # The first horizon sprint: the budget follows the plan of the variant.
    first = next(iter(median))
    assert float(conservative[first]) < float(median[first]) < float(optimistic[first])
    result = run(ticket_dir, "tickets", "demo", "--variant", "conservative")
    assert "Variante konservativ" in result.output
    # The project table stays on the median variant and shows the range either way.
    assert "Letzter Sprint Median" in result.output
    assert "Variante" not in run(ticket_dir, "tickets", "demo").output
    result = run(ticket_dir, "tickets", "demo", "--variant", "sloppy")
    assert result.exit_code == 2 and "Variante erwartet" in result.output


def test_variant_option_lists_the_tickets_a_variant_cannot_place(ticket_dir: Path):
    write_tickets(ticket_dir, [{"key": "R-1", "project": "payment", "estimate": 2.5,
                                "estimate_source": "rough"}])  # fmt: skip
    median = run(ticket_dir, "tickets", "demo")
    assert "zu groß" not in median.output
    conservative = run(ticket_dir, "tickets", "demo", "--variant", "conservative")
    assert "zu groß" in conservative.output  # 2.5 × 1.5 exceeds the conservative budget
    assert "zu groß" not in run(ticket_dir, "tickets", "demo", "--variant", "optimistic").output


# --- Handover ---------------------------------------------------------------------------------


def sprint_file(data_dir: Path, sprint: str) -> Path:
    return data_dir / "demo" / "sprints" / f"{sprint}.yaml"


def preplanned(data_dir: Path, sprint: str) -> dict:
    doc = yaml.safe_load(sprint_file(data_dir, sprint).read_text(encoding="utf-8"))
    return {pid: v.get("preplanned") for pid, v in (doc.get("products") or {}).items()}


@pytest.fixture
def handover_dir(ticket_dir: Path) -> Path:
    """14 tickets of 1 in the product "webshop" -> about 3 per sprint from 2026.22 on; the sprint
    file 2026.22 holds 3 (a PO value), 2026.23 and later exist only in the calendar."""
    write_tickets(ticket_dir, migration_tickets(14))
    assert not sprint_file(ticket_dir, "2026.23").exists()
    assert preplanned(ticket_dir, "2026.22")["webshop"] == 3
    return ticket_dir


def test_handover_preview_writes_nothing(handover_dir: Path):
    before = sprint_file(handover_dir, "2026.22").read_bytes()
    result = run(handover_dir, "tickets", "demo", "--handover", "--sprints", "4")
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if "Webshop" in line]
    assert len(lines) == 4  # one row per shown sprint
    row = [cell.strip() for cell in lines[0].split("│")]
    assert row[1:5] == ["2026.22", "Webshop", "3", "2"]  # PO value 3, proposal 2
    assert "PO-Wert bleibt" in lines[0]
    row = [cell.strip() for cell in lines[1].split("│")]
    assert row[1:5] == ["2026.23", "Webshop", "–", "3"] and row[5] == "neu"
    assert "Nur Vorschau" in result.output and "Median" in result.output
    assert sprint_file(handover_dir, "2026.22").read_bytes() == before
    assert not sprint_file(handover_dir, "2026.23").exists()


def test_handover_apply_creates_calendar_sprints_and_keeps_po_values(handover_dir: Path):
    kept = preplanned(handover_dir, "2026.22")
    result = run(handover_dir, "tickets", "demo", "--handover", "--sprints", "4", "--apply")
    assert result.exit_code == 0, result.output
    assert "Gespeichert" in result.output and "2026.23.yaml" in result.output
    assert preplanned(handover_dir, "2026.22") == kept  # the value of the PO stays
    for sprint, value in (("2026.23", 3), ("2026.24", 3), ("2026.25", 3)):
        assert preplanned(handover_dir, sprint) == {"webshop": value}
    assert not sprint_file(handover_dir, "2026.26").exists()  # outside the sprints shown
    # The written sprints are valid and the next run finds nothing left to do.
    assert run(handover_dir, "check").exit_code == 0
    again = run(handover_dir, "tickets", "demo", "--handover", "--sprints", "4", "--apply")
    assert again.exit_code == 0 and "unverändert" in again.output
    assert "Nichts zu schreiben" in again.output and "Gespeichert" not in again.output


def test_handover_overwrite_replaces_the_value_of_the_po(handover_dir: Path):
    command = ("tickets", "demo", "--handover", "--sprints", "2")
    kept = preplanned(handover_dir, "2026.22")
    preview = run(handover_dir, *command, "--overwrite")
    assert "würde ersetzt" in preview.output
    assert preplanned(handover_dir, "2026.22")["webshop"] == 3
    result = run(handover_dir, *command, "--apply", "--overwrite")
    assert result.exit_code == 0, result.output
    assert "wird ersetzt" in result.output
    assert preplanned(handover_dir, "2026.22") == kept | {"webshop": 2}
    assert preplanned(handover_dir, "2026.23") == {"webshop": 3}


def test_handover_does_not_rewrite_an_equal_value(handover_dir: Path):
    path = sprint_file(handover_dir, "2026.22")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "webshop:\n    preplanned: 3\n", "webshop:\n    preplanned: 2\n"
        ),
        encoding="utf-8",
    )
    assert preplanned(handover_dir, "2026.22")["webshop"] == 2
    before = path.read_bytes()
    result = run(handover_dir, "tickets", "demo", "--handover", "--sprints", "1", "--apply")
    assert result.exit_code == 0, result.output
    assert "unverändert" in result.output and "Nichts zu schreiben" in result.output
    assert path.read_bytes() == before


def test_handover_only_creates_sprint_files_it_writes(handover_dir: Path):
    write_tickets(handover_dir, migration_tickets(2))  # everything fits into 2026.22
    result = run(handover_dir, "tickets", "demo", "--handover", "--sprints", "6", "--apply")
    assert result.exit_code == 0, result.output
    assert "PO-Wert bleibt" in result.output  # 2026.22: the PO entered 3, the proposal is 2
    assert "Nichts zu schreiben" in result.output
    assert not any(sprint_file(handover_dir, f"2026.{n}").exists() for n in range(23, 27))
    assert not sprint_file(handover_dir, "2027.1").exists()


def test_handover_nothing_distributed(ticket_dir: Path):
    write_tickets(ticket_dir, [{"key": "N-1", "project": "migration", "estimate": None,
                                "estimate_source": "none"}])  # fmt: skip
    result = run(ticket_dir, "tickets", "demo", "--handover")
    assert result.exit_code == 0 and "Nichts zu übergeben" in result.output
    assert "Nichts zu übergeben" in run(ticket_dir, "tickets", "demo", "--handover").output


def test_handover_without_tickets_says_how_to_import(ticket_dir: Path):
    result = run(ticket_dir, "tickets", "demo", "--handover")
    assert result.exit_code == 0 and "--import" in result.output


def test_handover_needs_the_product_distribution(handover_dir: Path):
    team = handover_dir / "demo" / "team.yaml"
    doc = yaml.safe_load(team.read_text(encoding="utf-8"))
    doc["features"]["products"] = False
    team.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    result = run(handover_dir, "tickets", "demo", "--handover", "--apply")
    assert result.exit_code == 1
    assert "Produktverteilung ist für dieses Team ausgeschaltet" in result.output
    assert not sprint_file(handover_dir, "2026.23").exists()


def test_handover_without_products_is_refused(handover_dir: Path):
    (handover_dir / "demo" / "products.yaml").write_text("products: []\n", encoding="utf-8")
    result = run(handover_dir, "tickets", "demo", "--handover")
    assert result.exit_code == 1 and "Keine Produkte erfasst" in result.output


def test_handover_needs_the_ticket_feature(data_dir: Path):
    result = run(data_dir, "tickets", "demo", "--handover")
    assert result.exit_code == 1 and "ausgeschaltet" in result.output


@pytest.mark.parametrize(
    "other",
    [
        ("--import", str(DATA / "jira_en.csv")),
        ("--fetch",),
        ("--test-connection",),
        ("--set-token",),
    ],
)
def test_handover_excludes_the_import_and_jira_actions(handover_dir: Path, other: tuple[str, ...]):
    result = run(handover_dir, "tickets", "demo", "--handover", *other)
    assert result.exit_code == 1
    assert "schließen einander aus" in result.output and "--handover" in result.output
    assert not sprint_file(handover_dir, "2026.23").exists()


def test_handover_option_combinations(handover_dir: Path):
    result = run(handover_dir, "tickets", "demo", "--overwrite")
    assert result.exit_code == 1 and "--overwrite gehört zu --handover" in result.output
    result = run(handover_dir, "tickets", "demo", "--handover", "--variant", "optimistic")
    assert result.exit_code == 1 and "--variant" in result.output
    result = run(handover_dir, "tickets", "demo", "--handover", "--commit")
    assert result.exit_code == 1 and "--commit braucht --apply" in result.output
    result = run(handover_dir, "tickets", "demo", "--apply")
    assert result.exit_code == 1 and "--handover" in result.output
    result = run(handover_dir, "tickets", "demo", "--test-connection", "--overwrite")
    assert result.exit_code == 1 and "--overwrite" in result.output


def test_handover_commits_the_sprint_files(handover_dir: Path):
    root = handover_dir.parent
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "T")
    git(root, "config", "user.email", "t@example.org")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Start")
    result = run(
        handover_dir, "tickets", "demo", "--handover", "--sprints", "3", "--apply", "--commit"
    )
    assert result.exit_code == 0, result.output
    assert "Committet" in result.output
    log = git(root, "log", "-1", "--format=%s", "--name-only")
    assert "PO-Vorplanung aus den Tickets" in log and "2026.23.yaml" in log


def test_handover_in_english(handover_dir: Path, english):
    result = run(handover_dir, "tickets", "demo", "--handover", "--sprints", "2")
    assert result.exit_code == 0, result.output
    assert "Handover to the PO pre-planning (median variant)" in result.output
    assert "Proposal" in result.output and "PO value stays" in result.output
    assert "Preview only" in result.output


def test_handover_keeps_the_sprint_sequence_gapless(ticket_dir: Path):
    """Tickets fixed in 2026.24 while nothing is placed in 2026.23: writing 2026.24 alone would
    make the calendar sprint 2026.23 disappear from the forecast, so it is created as well."""
    write_tickets(
        ticket_dir,
        [{"key": f"F-{i}", "project": "migration", "in_sprint": "2026.24"} for i in range(2)],
    )
    assert not sprint_file(ticket_dir, "2026.23").exists()
    result = run(ticket_dir, "tickets", "demo", "--handover", "--sprints", "4", "--apply")
    assert result.exit_code == 0, result.output
    assert sprint_file(ticket_dir, "2026.24").exists()
    assert sprint_file(ticket_dir, "2026.23").exists()
    forecast = run(ticket_dir, "forecast", "demo")
    assert forecast.exit_code == 0, forecast.output
    assert "2026.23" in forecast.output
