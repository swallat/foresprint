# SPDX-License-Identifier: EUPL-1.2
"""Ablage der Ticket-Vorplanung: projects.yaml, tickets.yaml, preplan.yaml und der Abschnitt
``tracker`` in team.yaml – nur mit ``features.tickets`` gelesen, stabil geschrieben."""

from datetime import date, datetime
from pathlib import Path

import pytest

from sprintforecast.model import (
    BudgetBasis,
    Earmark,
    EstimateSource,
    ManualEstimate,
    PlanningUses,
    Preplan,
    Project,
    Rule,
    Team,
    Ticket,
    TrackerFields,
    TrackerSettings,
)
from sprintforecast.storage import (
    DataError,
    Repository,
    TeamData,
    team_from_dict,
    team_to_dict,
    team_version,
)
from sprintforecast.validate import check_team_files

TEAM = "demo"
TODAY = date(2026, 10, 15)


def tracker() -> TrackerSettings:
    return TrackerSettings(
        kind="csv",
        fields=TrackerFields(estimate="Story Points", remaining="Remaining", epic="Epic Link"),
        planning_uses=PlanningUses.REMAINING,
        refined_label="Refined",
        refined_also_if=Rule(
            op="any",
            children=[
                Rule(source="in_sprint", values=["true"]),
                Rule(op="none", children=[Rule(source="status", values=["To Do"])]),
            ],
        ),
        project_match_order=["epic", "component", "label"],
        dependency_gap=1,
        budget_basis=BudgetBasis.ROADMAP_SHARE,
        rough_factor=1.5,
        write_labels=False,
        sprint_names={"Sprint 22": "2026.22"},
    )


def projects() -> list[Project]:
    return [
        Project(
            id="payment-v2",
            name="Payment processing v2",
            product="webshop",
            target=date(2027, 3, 31),
            priority=1,
            budget_basis=BudgetBasis.PLAN,
            match=Rule(
                op="any",
                short=True,
                children=[
                    Rule(source="epic", values=["ABC-100", "ABC-101"]),
                    Rule(source="label", values=["payment"]),
                ],
            ),
        ),
        Project(
            id="migration",
            name="Database migration",
            product="app",
            target=date(2027, 1, 15),
            priority=2,
            match=Rule(
                op="all",
                children=[
                    Rule(source="component", values=["Database"]),
                    Rule(op="none", children=[Rule(source="label", values=["maintenance"])]),
                    Rule(
                        op="any",
                        children=[
                            Rule(source="epic", values=["ABC-200"]),
                            Rule(source="status", values=["Ready"]),
                        ],
                    ),
                ],
            ),
            note="Notiz mit Ümlaut",
        ),
    ]


def tickets() -> list[Ticket]:
    return [
        Ticket(
            key="ABC-1",
            title="Checkout: new payment provider",
            status="To Do",
            issue_type="Story",
            estimate=5,
            remaining=3.5,
            estimate_source=EstimateSource.REFINED,
            in_sprint="2026.22",
            sprint_name="Sprint 22",
            rank="0|i0001:",
            epic="ABC-100",
            labels=["payment", "Refined"],
            components=["Checkout"],
            depends_on=["ABC-2"],
            project="payment-v2",
        ),
        Ticket(
            key="ABC-2",
            title="Schema change",
            status="Ready",
            issue_type="Task",
            estimate=8,
            estimate_source=EstimateSource.ROUGH,
            refined_unclear=True,
            rank="0|i0002:",
            epic="ABC-200",
            components=["Database"],
            project_candidates=["migration", "payment-v2"],
        ),
        Ticket(key="ABC-3", title="Done already", done=True),
    ]


def preplan() -> Preplan:
    return Preplan(
        earmarks=[Earmark(ticket="ABC-2", sprint="2026.23", note="after the schema change")],
        estimates=[ManualEstimate(ticket="ABC-3", estimate=2.5)],
    )


def switch_on(repo: Repository) -> None:
    team = repo.load(TEAM).team
    team.features.tickets = True
    team.tracker = tracker()
    repo.save_team(team)


def write_all(repo: Repository) -> None:
    switch_on(repo)
    repo.save_projects(TEAM, projects())
    repo.save_tickets(TEAM, tickets(), datetime(2026, 10, 15, 9, 30), "export.csv")
    repo.save_preplan(TEAM, preplan())


def texts(base: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in base.glob("*.yaml")}


# --- Lesen und Schreiben --------------------------------------------------------------------


def test_roundtrip_is_byte_stable_and_keeps_every_field(data_dir: Path):
    repo = Repository(data_dir)
    write_all(repo)
    before = texts(data_dir / TEAM)
    data = repo.load(TEAM)
    assert data.team.tracker == tracker()
    assert data.projects == projects()
    assert data.tickets == tickets()
    assert data.preplan == preplan()
    assert data.tickets_imported == datetime(2026, 10, 15, 9, 30)
    assert data.tickets_source == "export.csv"
    assert data.ticket("ABC-2") is data.tickets[1] and data.ticket("ABC-9") is None
    assert data.project("migration") is data.projects[1] and data.project("x") is None
    repo.save_team(data.team)
    repo.save_projects(TEAM, data.projects)
    repo.save_tickets(TEAM, data.tickets, data.tickets_imported, data.tickets_source)
    repo.save_preplan(TEAM, data.preplan)
    assert texts(data_dir / TEAM) == before


def test_written_files_have_the_documented_form(data_dir: Path):
    repo = Repository(data_dir)
    write_all(repo)
    base = data_dir / TEAM
    assert (base / "projects.yaml").read_text(encoding="utf-8") == (
        "# Projects of the ticket pre-planning: target date, product, priority and assignment "
        "rule.\n"
        "# A ticket belongs to the project whose `match` rule it fulfils "
        "(docs/design/ticket-planning.md).\n"
        "schema: 1\n"
        "projects:\n"
        "- id: payment-v2\n"
        "  name: Payment processing v2\n"
        "  product: webshop\n"
        "  target: 2027-03-31\n"
        "  priority: 1\n"
        "  budget_basis: plan\n"
        "  match:\n"
        "    epic:\n"
        "    - ABC-100\n"
        "    - ABC-101\n"
        "    label:\n"
        "    - payment\n"
        "- id: migration\n"
        "  name: Database migration\n"
        "  product: app\n"
        "  target: 2027-01-15\n"
        "  priority: 2\n"
        "  match:\n"
        "    all:\n"
        "    - component:\n"
        "      - Database\n"
        "    - none:\n"
        "      - label:\n"
        "        - maintenance\n"
        "    - any:\n"
        "      - epic:\n"
        "        - ABC-200\n"
        "      - status:\n"
        "        - Ready\n"
        "  note: Notiz mit Ümlaut\n"
    )
    assert (base / "preplan.yaml").read_text(encoding="utf-8") == (
        "# Pre-planning of the PO: earmarks (ticket → future sprint) and own estimates for "
        "tickets.\n"
        "schema: 1\n"
        "earmarks:\n"
        "- ticket: ABC-2\n"
        "  sprint: '2026.23'\n"
        "  note: after the schema change\n"
        "estimates:\n"
        "- ticket: ABC-3\n"
        "  estimate: 2.5\n"
    )
    tickets_text = (base / "tickets.yaml").read_text(encoding="utf-8")
    assert tickets_text.startswith(
        "# Tickets as last imported from the tracker. Written by the import – do not edit by "
        "hand.\nschema: 1\nimported: 2026-10-15 09:30:00\nsource: export.csv\ntickets:\n"
        "- key: ABC-1\n"
    )
    assert "  refined_unclear: true\n" in tickets_text
    assert "  done: true\n" in tickets_text
    assert "refined_unclear: false" not in tickets_text and "done: false" not in tickets_text
    team_text = (base / "team.yaml").read_text(encoding="utf-8")
    assert "  tickets: true\n" in team_text
    assert (
        "tracker:\n"
        "  kind: csv\n"
        "  fields:\n"
        "    estimate: Story Points\n"
        "    remaining: Remaining\n"
        "    epic: Epic Link\n"
        "  planning_uses: remaining\n"
        "  refined_label: Refined\n"
        "  refined_also_if:\n"
        "    any:\n"
        "    - in_sprint:\n"
        "      - true\n"
        "    - none:\n"
        "      - status:\n"
        "        - To Do\n"
        "  project_match_order:\n"
        "  - epic\n"
        "  - component\n"
        "  - label\n"
        "  dependency_gap: 1\n"
        "  budget_basis: roadmap_share\n"
        "  rough_factor: 1.5\n"
        "  write_labels: false\n"
        "  sprint_names:\n"
        "    Sprint 22: '2026.22'\n"
    ) in team_text


def test_feature_off_reads_none_of_the_three_files(data_dir: Path):
    repo = Repository(data_dir)
    write_all(repo)
    team = repo.load(TEAM).team
    team.features.tickets = False
    repo.save_team(team)
    # Even unreadable content is not touched while the feature is off.
    (data_dir / TEAM / "tickets.yaml").write_text("schema: 2\ntickets: [", encoding="utf-8")
    data = repo.load(TEAM)
    assert not data.team.features.tickets
    assert data.tickets == [] and data.projects == [] and data.preplan == Preplan()
    assert data.tickets_imported is None and data.tickets_source is None


def test_flag_is_written_only_when_on_and_existing_files_stay_unchanged(data_dir: Path):
    team = Team(key="t", name="T")
    assert "tickets" not in team_to_dict(team)["features"]
    assert "tracker" not in team_to_dict(team)
    team.features.tickets = True
    assert team_to_dict(team)["features"]["tickets"] is True
    assert team_to_dict(team)["tracker"]["kind"] == "csv"
    # Missing flag reads as off; the demo team is untouched by a save.
    assert not team_from_dict("x", {"name": "X", "features": {"po": True}}, "x").features.tickets
    repo = Repository(data_dir)
    before = (data_dir / TEAM / "team.yaml").read_bytes()
    repo.save_team(repo.load(TEAM).team)
    assert (data_dir / TEAM / "team.yaml").read_bytes() == before


def test_tracker_section_survives_switching_the_feature_off(data_dir: Path):
    """Switching the area off (settings page) must not throw away the configuration."""
    repo = Repository(data_dir)
    switch_on(repo)
    team = repo.load(TEAM).team
    team.features.tickets = False
    repo.save_team(team)
    assert "tracker:" in (data_dir / TEAM / "team.yaml").read_text(encoding="utf-8")
    assert repo.load(TEAM).team.tracker == tracker()


def test_missing_schema_means_one_and_defaults_fill_the_rest(data_dir: Path):
    repo = Repository(data_dir)
    switch_on(repo)
    base = data_dir / TEAM
    (base / "projects.yaml").write_text(
        "projects:\n- id: p\n  target: 2027-01-01\n  match:\n    epic: ABC-1\n", encoding="utf-8"
    )
    (base / "tickets.yaml").write_text("tickets:\n- key: ABC-1\n", encoding="utf-8")
    (base / "preplan.yaml").write_text("schema:\n", encoding="utf-8")
    data = repo.load(TEAM)
    project = data.projects[0]
    assert project.name == "p" and project.priority == 0 and project.budget_basis is None
    assert project.match == Rule(source="epic", values=["ABC-1"])
    ticket = data.tickets[0]
    assert ticket.estimate is None and ticket.estimate_source is EstimateSource.NONE
    assert ticket.labels == [] and ticket.depends_on == [] and not ticket.done
    assert data.preplan == Preplan()


@pytest.mark.parametrize("name", ["projects.yaml", "tickets.yaml", "preplan.yaml"])
def test_a_newer_schema_is_refused(data_dir: Path, name: str):
    repo = Repository(data_dir)
    write_all(repo)
    path = data_dir / TEAM / name
    path.write_text(path.read_text(encoding="utf-8").replace("schema: 1", "schema: 2"))
    with pytest.raises(DataError, match=rf"{name}: .*neueren Programmversion.*schema 2"):
        repo.load(TEAM)
    path.write_text(path.read_text(encoding="utf-8").replace("schema: 2", "schema: x"))
    with pytest.raises(DataError, match="schema muss eine ganze Zahl sein"):
        repo.load(TEAM)


def test_unquoted_sprint_ids_and_bad_values_are_explained(data_dir: Path):
    repo = Repository(data_dir)
    write_all(repo)
    base = data_dir / TEAM
    (base / "preplan.yaml").write_text(
        "schema: 1\nearmarks:\n- ticket: ABC-2\n  sprint: 2026.20\n", encoding="utf-8"
    )
    with pytest.raises(DataError, match="sprint bitte in Anführungszeichen"):
        repo.load(TEAM)
    (base / "preplan.yaml").write_text("schema: 1\nearmarks:\n- ticket: ABC-2\n", encoding="utf-8")
    with pytest.raises(DataError, match="Feld 'sprint' fehlt"):
        repo.load(TEAM)
    (base / "preplan.yaml").write_text("schema: 1\n", encoding="utf-8")
    (base / "tickets.yaml").write_text(
        "schema: 1\ntickets:\n- key: ABC-1\n  estimate_source: guess\n", encoding="utf-8"
    )
    with pytest.raises(DataError, match="estimate_source 'guess' unbekannt \\(erlaubt: refined"):
        repo.load(TEAM)
    (base / "tickets.yaml").write_text("schema: 1\ntickets:\n- title: no key\n", encoding="utf-8")
    with pytest.raises(DataError, match="Feld 'key' fehlt"):
        repo.load(TEAM)
    (base / "tickets.yaml").write_text("schema: 1\n", encoding="utf-8")
    (base / "projects.yaml").write_text(
        "schema: 1\nprojects:\n- id: p\n  priority: 1.5\n", encoding="utf-8"
    )
    with pytest.raises(DataError, match="'priority' muss eine ganze Zahl sein"):
        repo.load(TEAM)
    (base / "projects.yaml").write_text(
        "schema: 1\nprojects:\n- id: p\n  match:\n    epic:\n      nested: 1\n", encoding="utf-8"
    )
    with pytest.raises(DataError, match="'epic' muss eine Liste von Werten sein"):
        repo.load(TEAM)
    team_path = base / "team.yaml"
    team_path.write_text(
        team_path.read_text(encoding="utf-8").replace("dependency_gap: 1", "dependency_gap: 1.5")
    )
    with pytest.raises(DataError, match="'dependency_gap' muss eine ganze Zahl sein"):
        repo.load(TEAM)


def test_file_version_changes_when_a_ticket_file_changes(data_dir: Path):
    repo = Repository(data_dir)
    write_all(repo)
    base = data_dir / TEAM
    for name, change in (
        ("tickets.yaml", lambda: repo.save_tickets(TEAM, tickets()[:1])),
        ("projects.yaml", lambda: repo.save_projects(TEAM, projects()[:1])),
        ("preplan.yaml", lambda: repo.save_preplan(TEAM, Preplan())),
    ):
        before = team_version(base)
        change()
        after = team_version(base)
        assert before != after, name
        assert [entry[0] for entry in after if entry[0] == name] == [name]
    # The cache follows the files: a changed tickets.yaml is read again.
    assert len(repo.load_cached(TEAM).tickets) == 1
    repo.save_tickets(TEAM, tickets())
    assert len(repo.load_cached(TEAM).tickets) == 3


def test_check_team_files_covers_the_new_files(data_dir: Path):
    repo = Repository(data_dir)
    write_all(repo)
    base = data_dir / TEAM
    text = (base / "projects.yaml").read_text(encoding="utf-8")
    (base / "projects.yaml").write_text(
        text.replace("  priority: 2\n", "  priority:\n  priority: 2\n"), encoding="utf-8"
    )
    found = [i for i in check_team_files(base) if i.where == "projects.yaml"]
    assert any("projects[1].priority" in i.message for i in found), found


def test_team_data_defaults_are_empty():
    data = TeamData(team=Team(key="t", name="T"))
    assert data.projects == [] and data.tickets == [] and data.preplan == Preplan()
    assert data.ticket("x") is None and data.project("x") is None


# --- Excel ----------------------------------------------------------------------------------


def test_excel_export_omits_the_tracker_and_the_import_keeps_it(data_dir: Path):
    pytest.importorskip("xlsxwriter")
    pytest.importorskip("openpyxl")
    import io

    import openpyxl

    from sprintforecast.excel import SHEET_SETTINGS, build_workbook
    from sprintforecast.excel_import import plan_import, read_workbook
    from sprintforecast.forecast import build_forecast

    repo = Repository(data_dir)
    write_all(repo)
    content = build_workbook(build_forecast(repo.load(TEAM), TODAY))
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=True)[SHEET_SETTINGS]
    paths = [row[2] for row in sheet.iter_rows(values_only=True) if isinstance(row[2], str)]
    assert "features.tickets" in paths
    assert not any(p.startswith("tracker") for p in paths)
    data = read_workbook(content, TEAM)
    assert data.team.features.tickets
    plan = plan_import(repo, data, TODAY)
    assert plan.changes == [] and plan.files == []
    assert plan.data.team.tracker == tracker()
