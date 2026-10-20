# SPDX-License-Identifier: EUPL-1.2
"""Check of the ticket pre-planning (errors and notes), only with ``features.tickets``."""

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
    assert not found[0][1].startswith("team.yaml")  # no doubled location


# --- Jira (step 2) ---------------------------------------------------------------------------


def jira(data: TeamData, **overrides) -> None:
    tr = data.team.tracker
    tr.kind, tr.base_url, tr.query = "jira", "https://jira.example.org", "project = ABC"
    tr.fields.estimate = "Story Points"
    for name, value in overrides.items():
        setattr(tr, name, value)


def test_a_complete_jira_tracker_is_clean(data: TeamData):
    jira(data)
    assert errors(data) == [] and warnings(data) == []


def test_jira_needs_an_address_and_a_query(data: TeamData):
    jira(data, base_url=None, query=None)
    assert errors(data) == [
        ("team.yaml", "tracker.base_url fehlt (Adresse des Jira-Servers, http oder https)"),
        ("team.yaml", "tracker.query fehlt (JQL-Abfrage der Tickets)"),
    ]
    jira(data, query="   ")  # blank is not a query either
    data.team.tracker.query = ""
    assert ("team.yaml", "tracker.query fehlt (JQL-Abfrage der Tickets)") in errors(data)


@pytest.mark.parametrize(
    "url", ["jira.example.org", "ftp://jira.example.org", "https://", "//jira.example.org"]
)
def test_jira_address_must_be_http_or_https(data: TeamData, url: str):
    jira(data, base_url=url)
    assert errors(data) == [
        ("team.yaml", "tracker.base_url muss eine http- oder https-Adresse sein")
    ]


def test_jira_address_must_not_carry_credentials_and_http_is_a_hint(data: TeamData):
    jira(data, base_url="https://anna:secret@jira.example.org")
    assert errors(data) == [("team.yaml", "tracker.base_url darf keine Zugangsdaten enthalten")]
    jira(data, base_url="http://jira.example.org")
    assert errors(data) == []
    assert warnings(data) == [
        ("team.yaml", "tracker.base_url ist unverschlüsselt (http): das Token wäre mitlesbar")
    ]


def test_a_missing_estimate_field_is_a_warning(data: TeamData):
    jira(data)
    data.team.tracker.fields.estimate = None
    assert errors(data) == []
    assert warnings(data) == [
        ("team.yaml", "tracker.fields.estimate fehlt: ohne Schätzung lässt sich nichts verteilen")
    ]


def test_csv_needs_no_address_or_query(data: TeamData):
    data.team.tracker.kind = "csv"
    assert errors(data) == []


def test_unknown_tracker_kind_is_an_error(data: TeamData):
    data.team.tracker.kind = "github"
    assert errors(data) == [("team.yaml", "tracker.kind: nur csv, jira")]


def test_link_type_must_not_be_empty(data: TeamData):
    data.team.tracker.link_type = "  "
    assert errors(data) == [("team.yaml", "tracker.link_type darf nicht leer sein")]
    data.team.tracker.link_type = "Depends"
    assert errors(data) == []


def test_jira_rules_apply_only_with_the_feature(data: TeamData):
    jira(data, base_url=None, query=None)
    data.team.features.tickets = False
    assert check_team(data, TODAY) == []


def test_a_secret_kept_while_the_feature_was_off_is_an_error_when_switched_on(data: TeamData):
    data.team.tracker_raw = {"kind": "jira", "token": "tok-CANARY-123456"}
    found = errors(data)
    assert len(found) == 1 and found[0][0] == "team.yaml"
    assert "token" in found[0][1] and "tok-CANARY" not in found[0][1]
    assert "Schlüsselbund" in found[0][1]


@pytest.mark.parametrize(
    ("url", "message"),
    [
        (
            "https://jira.example.org/jira?x=1",
            "darf keine Parameter (?…) und kein Fragment (#…) enthalten",
        ),
        (
            "https://jira.example.org/jira#top",
            "darf keine Parameter (?…) und kein Fragment (#…) enthalten",
        ),
        ("https://jira.example.org?", "darf keine Parameter (?…) und kein Fragment (#…) enthalten"),
        ("https://:pw@jira.example.org", "darf keine Zugangsdaten enthalten"),
        ("https://[jira.example.org/jira", "muss eine http- oder https-Adresse sein"),
        ("https://jira.example.org:notaport", "muss eine http- oder https-Adresse sein"),
    ],
)
def test_jira_address_problems_are_errors_without_echoing_the_address(
    data: TeamData, url: str, message: str
):
    jira(data, base_url=url)
    found = errors(data)
    assert found == [("team.yaml", f"tracker.base_url {message}")]
    assert "pw" not in found[0][1]
