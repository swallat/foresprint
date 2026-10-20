# SPDX-License-Identifier: EUPL-1.2
"""Storage of the ticket pre-planning: projects.yaml, tickets.yaml, preplan.yaml and the ``tracker``
section in team.yaml, read only with ``features.tickets``, written stably."""

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
from sprintforecast.settings import SETTINGS
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
            priority="High",
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


# --- Reading and writing --------------------------------------------------------------------


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


# --- Review fixes ----------------------------------------------------------------------------


def test_invalid_tracker_section_is_ignored_while_the_feature_is_off(data_dir: Path):
    """A bad value must not break forecast and check of a team that does not use the area;
    writing team.yaml keeps the section as it was."""
    import yaml

    repo = Repository(data_dir)
    path = data_dir / TEAM / "team.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["tracker"] = {"kind": "csv", "planning_uses": "bogus", "dependency_gap": "one"}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    data = repo.load(TEAM)
    assert not data.team.features.tickets and data.team.tracker == TrackerSettings()
    for _ in range(2):  # the saved file reads (and saves) the same again
        repo.save_team(data.team)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert written["tracker"] == doc["tracker"]
        data = repo.load(TEAM)
    # Switched on, the problem is reported instead of being hidden.
    doc["features"]["tickets"] = True
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(DataError, match="planning_uses"):
        repo.load(TEAM)


def test_cli_works_with_an_invalid_tracker_section_while_off(data_dir: Path):
    import yaml
    from typer.testing import CliRunner

    from sprintforecast.cli import app

    path = data_dir / TEAM / "team.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["tracker"] = {"planning_uses": "bogus"}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    (data_dir / TEAM / "tickets.yaml").write_text("schema: [unclosed\n", encoding="utf-8")
    for command in (["forecast", TEAM], ["check"]):
        result = CliRunner().invoke(
            app, ["--data", str(data_dir), "--as-of", "2026-10-15", *command]
        )
        assert result.exit_code == 0, result.output


def test_check_team_files_skips_the_ticket_files_while_the_feature_is_off(data_dir: Path):
    repo = Repository(data_dir)
    write_all(repo)
    base = data_dir / TEAM
    for name in ("projects.yaml", "tickets.yaml", "preplan.yaml"):
        (base / name).write_text("schema: 1\nitems:\n  a: 1\n  a: 2\n", encoding="utf-8")
    assert any(i.where == "tickets.yaml" for i in check_team_files(base))
    text = (base / "team.yaml").read_text(encoding="utf-8")
    (base / "team.yaml").write_text(text.replace("tickets: true", "tickets: false"), "utf-8")
    assert not [i for i in check_team_files(base) if i.where.endswith("s.yaml")]
    assert not [i for i in check_team_files(base, tickets=False) if i.where == "preplan.yaml"]


def test_unquoted_float_in_rule_values_and_sprint_names_is_refused():
    from sprintforecast.storage import _rule_from, _tracker_from

    with pytest.raises(DataError, match="Anführungszeichen"):
        _rule_from({"in_sprint": [2026.20]}, "projects.yaml")
    with pytest.raises(DataError, match="Anführungszeichen"):
        _rule_from({"any": [{"in_sprint": 2026.2}]}, "projects.yaml")
    with pytest.raises(DataError, match="Anführungszeichen"):
        _tracker_from({"sprint_names": {"Sprint 20": 2026.20}}, "team.yaml")
    assert _rule_from({"in_sprint": [True], "epic": ["2026.20"]}, "x") is not None
    assert _tracker_from({"sprint_names": {"Sprint 20": "2026.20"}}, "t").sprint_names == {
        "Sprint 20": "2026.20"
    }


def bad_tracker_dir(data_dir: Path) -> Repository:
    import yaml

    path = data_dir / TEAM / "team.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["tracker"] = {"kind": "csv", "planning_uses": "bogus"}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return Repository(data_dir)


def test_excel_import_keeps_an_unreadable_tracker_section(data_dir: Path):
    pytest.importorskip("xlsxwriter")
    pytest.importorskip("openpyxl")
    from sprintforecast.excel import build_workbook
    from sprintforecast.excel_import import plan_import, read_workbook
    from sprintforecast.forecast import build_forecast

    repo = bad_tracker_dir(data_dir)
    existing = repo.load(TEAM)
    assert existing.team.tracker_raw == {"kind": "csv", "planning_uses": "bogus"}
    data = read_workbook(build_workbook(build_forecast(existing, TODAY)), TEAM)
    plan = plan_import(repo, data, TODAY)
    assert plan.data.team.tracker_raw == existing.team.tracker_raw
    assert plan.files == []  # team.yaml would not change


def test_cli_settings_refuse_to_switch_on_with_an_unreadable_tracker(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    import yaml
    from typer.testing import CliRunner

    import sprintforecast.cli as cli

    bad_tracker_dir(data_dir)
    real = cli._ask_setting

    def ask(setting, team, **kw):
        if setting.key == "features.tickets":
            team.features.tickets = True
        else:
            real(setting, team, **kw)

    monkeypatch.setattr(cli, "_ask_setting", ask)
    monkeypatch.setattr(
        cli, "applicable", lambda **kw: [s for s in SETTINGS if s.key == "features.tickets"]
    )
    result = CliRunner().invoke(
        cli.app, ["--data", str(data_dir), "--as-of", "2026-10-15", "settings", TEAM], input="y\n"
    )
    assert result.exit_code == 1 and "Nicht gespeichert" in result.output, result.output
    doc = yaml.safe_load((data_dir / TEAM / "team.yaml").read_text(encoding="utf-8"))
    assert not doc["features"].get("tickets")
    Repository(data_dir).load(TEAM)  # still loads


# --- Jira (step 2): link_type and secrets ----------------------------------------------------


def test_link_type_defaults_to_blocks_and_is_written_only_when_different(data_dir: Path):
    import yaml

    assert TrackerSettings().link_type == "Blocks"
    assert "link_type" not in team_to_dict(Team(key="t", name="T", tracker=tracker()))["tracker"]
    repo = Repository(data_dir)
    switch_on(repo)
    assert "link_type" not in (data_dir / TEAM / "team.yaml").read_text(encoding="utf-8")
    custom = tracker()
    custom.kind, custom.base_url, custom.query = "jira", "https://jira.example.org", "project = A"
    custom.link_type = "Depends"
    team = repo.load(TEAM).team
    team.tracker = custom
    repo.save_team(team)
    path = data_dir / TEAM / "team.yaml"
    written = yaml.safe_load(path.read_text(encoding="utf-8"))["tracker"]
    assert written["link_type"] == "Depends" and written["base_url"] == "https://jira.example.org"
    assert repo.load(TEAM).team.tracker == custom
    before = path.read_bytes()  # byte-stable roundtrip
    repo.save_team(repo.load(TEAM).team)
    assert path.read_bytes() == before


def test_an_empty_link_type_is_read_as_empty_so_that_the_check_reports_it():
    raw = {"name": "T", "features": {"tickets": True}, "tracker": {"kind": "csv", "link_type": ""}}
    assert team_from_dict("t", raw, "t").tracker.link_type == ""
    raw["tracker"] = {"kind": "csv"}
    assert team_from_dict("t", raw, "t").tracker.link_type == "Blocks"


@pytest.mark.parametrize("key", ["token", "api_token", "Password", "client_secret", "TOKEN_FILE"])
def test_a_secret_in_the_tracker_section_is_refused_without_showing_it(key: str):
    raw = {
        "name": "T",
        "features": {"tickets": True},
        "tracker": {"kind": "jira", key: "tok-CANARY-123456"},
    }
    with pytest.raises(DataError) as e:
        team_from_dict("t", raw, "team.yaml")
    assert "tok-CANARY" not in str(e.value) and "Schlüsselbund" in str(e.value)
    assert key in str(e.value)


def test_a_secret_while_the_feature_is_off_is_kept_unread_and_reported_when_switched_on(
    data_dir: Path,
):
    import yaml

    path = data_dir / TEAM / "team.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["tracker"] = {"kind": "jira", "token": "tok-CANARY-123456"}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    data = Repository(data_dir).load(TEAM)  # feature off: does not break the team
    assert data.team.tracker == TrackerSettings() and data.team.tracker_raw == doc["tracker"]


@pytest.mark.parametrize(
    "tracker_section",
    [
        {"kind": "jira", "auth": {"token": "tok-CANARY"}},  # nested
        {"kind": "jira", "fields": {"estimate": "Story Points", "api_token": "tok-CANARY"}},
        {"kind": "jira", "refined_also_if": [{"credentials": "tok-CANARY"}]},  # inside a list
        {"kind": "jira", "key": "tok-CANARY"},
        {"kind": "jira", "API-Key": "tok-CANARY"},
        {"kind": "jira", "apikey": "tok-CANARY"},
        {"kind": "jira", "PAT": "tok-CANARY"},
        {"kind": "jira", "credential": "tok-CANARY"},
        {"kind": "jira", "authorization": "Bearer tok-CANARY"},
        {"kind": "jira", "my_credentials_file": "tok-CANARY"},
    ],
)
def test_secret_like_keys_anywhere_in_the_tracker_section_are_refused(tracker_section):
    raw = {"name": "T", "features": {"tickets": True}, "tracker": tracker_section}
    with pytest.raises(DataError) as e:
        team_from_dict("t", raw, "team.yaml")
    assert "tok-CANARY" not in str(e.value) and "Schlüsselbund" in str(e.value)


def test_ordinary_keys_and_sprint_names_are_not_taken_for_secrets():
    """Only whole names like `key`/`pat` count; `package`, `patch_level` or a sprint called
    "Secret Santa" are fine (sprint_names holds free text as keys)."""
    raw = {
        "name": "T",
        "features": {"tickets": True},
        "tracker": {
            "kind": "csv",
            "refined_label": "Key",  # a value, not a key
            "sprint_names": {"Secret Santa": "2026.20", "Token Sprint": "2026.21"},
        },
    }
    tr = team_from_dict("t", raw, "team.yaml").tracker
    assert tr.sprint_names == {"Secret Santa": "2026.20", "Token Sprint": "2026.21"}


def test_rule_fields_and_ticket_values_round_trip():
    from sprintforecast.storage import (
        _tracker_from,
        _tracker_to,
        tickets_from_dict,
        tickets_to_dict,
    )

    settings = TrackerSettings(rule_fields={"customer": "Customer"})
    assert _tracker_from(_tracker_to(settings), "team.yaml").rule_fields == {"customer": "Customer"}
    ticket = Ticket(key="K-1", extra={"customer": ["Acme"]})
    [back], _, _ = tickets_from_dict(tickets_to_dict([ticket]), "tickets.yaml")
    assert back.extra == {"customer": ["Acme"]} and back.facts()["customer"] == ["Acme"]
