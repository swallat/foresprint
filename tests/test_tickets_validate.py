# SPDX-License-Identifier: EUPL-1.2
"""Prüfung der Ticket-Vorplanung (Fehler und Hinweise), nur mit ``features.tickets``."""

from datetime import date
from pathlib import Path

import pytest

from sprintforecast.model import Earmark, ManualEstimate, Project, Rule, Ticket
from sprintforecast.storage import Repository, TeamData
from sprintforecast.validate import Level, check_team, find_cycles

TODAY = date(2026, 10, 15)


def project(id: str = "p", **overrides) -> Project:
    values = {
        "name": id,
        "product": "webshop",
        "target": date(2027, 3, 31),
        "match": Rule(source="epic", values=[f"EPIC-{id}"]),
    }
    values.update(overrides)
    return Project(id=id, **values)


@pytest.fixture
def data(data_dir: Path) -> TeamData:
    loaded = Repository(data_dir).load("demo")
    loaded.team.features.tickets = True
    assert check_team(loaded, TODAY) == [], "demo data must be clean with the feature on"
    return loaded


def errors(data: TeamData) -> list[tuple[str, str]]:
    return [(i.where, i.message) for i in check_team(data, TODAY) if i.level is Level.ERROR]


def warnings(data: TeamData) -> list[tuple[str, str]]:
    return [(i.where, i.message) for i in check_team(data, TODAY) if i.level is Level.WARNING]


def test_feature_off_checks_nothing(data: TeamData):
    data.tickets = [Ticket(key="A", depends_on=["A"], estimate=-1, project="nope")]
    data.team.tracker.dependency_gap = 7
    assert errors(data)
    data.team.features.tickets = False
    assert check_team(data, TODAY) == []


def test_dependency_cycles_are_errors_each_once(data: TeamData):
    data.tickets = [
        Ticket(key="A", depends_on=["B"]),
        Ticket(key="B", depends_on=["C", "A"]),
        Ticket(key="C", depends_on=["A", "X"]),  # X: not in the import, ignored
        Ticket(key="D", depends_on=["D"]),
        Ticket(key="E", depends_on=["A"]),  # leads into the cycle, is no cycle itself
    ]
    assert find_cycles(data.tickets) == [["A", "B", "C"], ["A", "B"], ["D"]]
    assert errors(data) == [
        ("tickets.yaml", "Abhängigkeiten im Kreis: A → B → C → A"),
        ("tickets.yaml", "Abhängigkeiten im Kreis: A → B → A"),
        ("tickets.yaml", "Abhängigkeiten im Kreis: D → D"),
    ]
    assert find_cycles([Ticket(key="A", depends_on=["B"]), Ticket(key="B")]) == []


def test_tickets_need_known_projects_unique_keys_and_non_negative_numbers(data: TeamData):
    data.projects = [project()]
    data.tickets = [
        Ticket(key="A", project="p", estimate=3),
        Ticket(key="A", project="ghost", estimate=-1, remaining=-2),
    ]
    assert errors(data) == [
        ("tickets.yaml: A", "key ist doppelt"),
        ("tickets.yaml: A", "estimate darf nicht negativ sein"),
        ("tickets.yaml: A", "remaining darf nicht negativ sein"),
        ("tickets.yaml: A", "unbekanntes Projekt 'ghost'"),
    ]


def test_projects_need_a_product_only_with_the_product_feature(data: TeamData):
    data.projects = [project("a", product=None), project("b", product="ghost"), project("c")]
    assert errors(data) == [
        ("projects.yaml: a", "product fehlt (die Produktverteilung ist an)"),
        ("projects.yaml: b", "unbekanntes Produkt 'ghost'"),
    ]
    data.team.features.products = False
    assert errors(data) == [
        ("projects.yaml: b", "product muss leer sein (die Produktverteilung ist aus)"),
        ("projects.yaml: c", "product muss leer sein (die Produktverteilung ist aus)"),
    ]


def test_project_ids_target_and_tracker_settings(data: TeamData):
    data.projects = [project("p"), project("p", target=None)]
    data.team.tracker.dependency_gap = 2
    data.team.tracker.project_match_order = ["epic", "epic"]
    data.team.tracker.rough_factor = 0
    assert errors(data) == [
        ("team.yaml", "tracker.dependency_gap muss 0 oder 1 sein"),
        (
            "team.yaml",
            "tracker.project_match_order: nur Quellen aus epic, component, label, status, "
            "issue_type, in_sprint, jede höchstens einmal",
        ),
        ("team.yaml", "tracker.rough_factor muss > 0 sein"),
        ("projects.yaml: p", "id ist doppelt"),
        ("projects.yaml: p", "target fehlt"),
    ]
    data.team.tracker.project_match_order = ["label", "status"]  # a subset in any order is fine
    data.team.tracker.dependency_gap = 0
    data.team.tracker.rough_factor = 1
    data.projects = [project("p")]
    assert errors(data) == []


def test_warnings_for_targets_products_and_empty_projects(data: TeamData):
    data.projects = [
        project("past", target=date(2026, 10, 14)),
        project("today", target=TODAY),
        project("old", product="altsystem"),  # ended 2026-09-15 in the demo data
        project("empty", match=None),
        project("filled", match=None),
    ]
    data.tickets = [Ticket(key="A", project="filled")]
    assert warnings(data) == [
        ("projects.yaml: past", "target 2026-10-14 liegt in der Vergangenheit"),
        ("projects.yaml: old", "Produkt 'altsystem' ist seit 2026-09-15 beendet"),
        ("projects.yaml: empty", "weder eine match-Regel noch zugeordnete Tickets"),
    ]
    assert errors(data) == []


def test_preplan_entries_refer_to_known_tickets_and_sprints(data: TeamData):
    data.tickets = [Ticket(key="A"), Ticket(key="B", in_sprint="2026.30"), Ticket(key="C")]
    data.preplan.earmarks = [
        Earmark(ticket="A", sprint="2026.24"),  # a future sprint without a file is known
        Earmark(ticket="Z", sprint="2026.23"),
        Earmark(ticket="B", sprint="2031.7"),
        Earmark(ticket="A", sprint="2026.25"),
    ]
    data.preplan.estimates = [
        ManualEstimate(ticket="C", estimate=3),
        ManualEstimate(ticket="Y", estimate=1),
        ManualEstimate(ticket="C", estimate=None),
        ManualEstimate(ticket="A", estimate=-1),
    ]
    assert warnings(data) == [
        ("tickets.yaml: B", "in_sprint '2026.30' ist kein bekannter Sprint"),
        ("preplan.yaml: Z", "Vormerkung für ein unbekanntes Ticket (nicht im letzten Import)"),
        ("preplan.yaml: B", "Sprint '2031.7' ist nicht bekannt"),
        ("preplan.yaml: Y", "Schätzung für ein unbekanntes Ticket (nicht im letzten Import)"),
    ]
    assert errors(data) == [
        ("preplan.yaml: A", "mehrere Vormerkungen für dasselbe Ticket"),
        ("preplan.yaml: C", "mehrere Schätzungen für dasselbe Ticket"),
        ("preplan.yaml: C", "estimate fehlt"),
        ("preplan.yaml: A", "estimate darf nicht negativ sein"),
    ]


def test_cli_check_passes_with_the_feature_on(data_dir: Path):
    from typer.testing import CliRunner

    from sprintforecast.cli import app

    repo = Repository(data_dir)
    team = repo.load("demo").team
    team.features.tickets = True
    repo.save_team(team)
    repo.save_projects("demo", [project("p")])
    repo.save_tickets("demo", [Ticket(key="A", project="p", estimate=3)])
    result = CliRunner().invoke(app, ["--data", str(data_dir), "--as-of", "2026-10-15", "check"])
    assert result.exit_code == 0, result.output
    repo.save_tickets("demo", [Ticket(key="A", project="nope", estimate=3)])
    result = CliRunner().invoke(app, ["--data", str(data_dir), "--as-of", "2026-10-15", "check"])
    assert result.exit_code != 0
    assert "unbekanntes Projekt 'nope'" in result.output


def test_earmark_for_a_past_sprint_is_a_warning(data: TeamData):
    data.tickets = [Ticket(key="A-1", title="x", project="p")]
    data.projects = [project("p")]
    data.preplan.earmarks = [Earmark("A-1", "2026.20")]  # ended on 14 October
    found = [w for w in warnings(data) if w[0] == "preplan.yaml: A-1"]
    assert found and "vergangenen Sprint '2026.20'" in found[0][1]
    data.preplan.earmarks = [Earmark("A-1", "2026.21")]  # the current sprint
    assert not [w for w in warnings(data) if w[0] == "preplan.yaml: A-1"]


def test_unreadable_tracker_section_blocks_switching_the_feature_on(data_dir: Path):
    loaded = Repository(data_dir).load("demo")
    loaded.team.tracker_raw = {"planning_uses": "bogus"}
    assert errors(loaded) == []  # feature off: not checked
    loaded.team.features.tickets = True
    found = errors(loaded)
    assert found and found[0][0] == "team.yaml" and "planning_uses" in found[0][1]
