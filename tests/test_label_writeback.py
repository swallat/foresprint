# SPDX-License-Identifier: EUPL-1.2
# ruff: noqa: F811  (fixtures imported from the neighbouring test modules)
"""Step 5: earmarks as ``planned_for_<sprint_id>`` labels in Jira (spec section 6.6): the write
plan, reading labels as earmarks on import, and the command ``tickets --write-labels``."""

import json
from pathlib import Path

import httpx
import pytest
import yaml
from test_cli_jira import (  # noqa: F401
    Mock,
    jira,
    jira_dir,
    run,
    ticket_csv_dir,
    tickets_file,
    write_team,
)
from test_ticket_import import TODAY, data, fc, raw  # noqa: F401

from sprintforecast.forecast import Forecast
from sprintforecast.label_writeback import (
    LabelWrite,
    apply_label_writes,
    plan_label_writes,
    wanted_label,
)
from sprintforecast.model import Earmark, Preplan, Ticket
from sprintforecast.sources import SourceError, label_sprints
from sprintforecast.storage import TeamData
from sprintforecast.ticket_import import plan_import


def ticket(key: str = "A-1", **values) -> Ticket:
    return Ticket(key=key, title=f"Title {key}", **values)


# --- Write plan ------------------------------------------------------------------------------


def test_label_sprints_reads_only_the_prefixed_labels():
    labels = ["Refined", "planned_for_2026.22", "planned_for_", "planned_for_2026.22", "x"]
    assert label_sprints(labels) == ["2026.22"]


def test_an_earmark_adds_its_label_and_only_on_change():
    preplan = Preplan(earmarks=[Earmark("A-1", "2026.23"), Earmark("A-2", "2026.23")])
    tickets = [ticket("A-1"), ticket("A-2", labels=["planned_for_2026.23", "other"]), ticket("A-3")]
    plan = plan_label_writes(tickets, preplan)
    assert plan.writes == [LabelWrite("A-1", "Title A-1", ["planned_for_2026.23"], [])]


def test_a_changed_earmark_replaces_the_old_label():
    preplan = Preplan(earmarks=[Earmark("A-1", "2026.24")])
    plan = plan_label_writes([ticket(labels=["planned_for_2026.23", "x"])], preplan)
    assert plan.writes == [
        LabelWrite("A-1", "Title A-1", ["planned_for_2026.24"], ["planned_for_2026.23"])
    ]


def test_a_released_earmark_removes_the_label():
    plan = plan_label_writes([ticket(labels=["planned_for_2026.23"])], Preplan())
    assert plan.writes == [LabelWrite("A-1", "Title A-1", [], ["planned_for_2026.23"])]


def test_a_real_sprint_wins_and_cleans_up_the_label():
    preplan = Preplan(earmarks=[Earmark("A-1", "2026.23")])
    tk = ticket(in_sprint="2026.22", labels=["planned_for_2026.23"])
    assert wanted_label(tk, preplan) is None
    plan = plan_label_writes([tk], preplan)
    assert plan.writes == [LabelWrite("A-1", "Title A-1", [], ["planned_for_2026.23"])]


def test_done_tickets_are_left_alone():
    preplan = Preplan(earmarks=[Earmark("A-1", "2026.23")])
    assert (
        plan_label_writes([ticket(done=True, labels=["planned_for_2026.22"])], preplan).writes == []
    )


def test_a_sprint_id_with_a_space_cannot_be_a_label():
    plan = plan_label_writes([ticket()], Preplan(earmarks=[Earmark("A-1", "Sprint 23")]))
    assert plan.writes == [] and "Sprint 23" in plan.warnings[0]


def test_nothing_to_do_when_the_tracker_already_matches():
    preplan = Preplan(earmarks=[Earmark("A-1", "2026.23")])
    assert plan_label_writes([ticket(labels=["planned_for_2026.23"])], preplan).writes == []


class Recorder:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, list[str], list[str]]] = []
        self.fail_on = fail_on

    def set_labels(self, key: str, add: list[str], remove: list[str]) -> None:
        if key == self.fail_on:
            raise SourceError("kaputt")
        self.calls.append((key, add, remove))


def test_apply_writes_each_change_and_stops_at_the_first_failure():
    preplan = Preplan(earmarks=[Earmark("A-1", "2026.23"), Earmark("A-2", "2026.23")])
    plan = plan_label_writes([ticket("A-1"), ticket("A-2")], preplan)
    ok = Recorder()
    assert apply_label_writes(ok, plan) == 2
    broken = Recorder(fail_on="A-2")
    with pytest.raises(SourceError, match=r"A-2.*kaputt.*1 von 2"):
        apply_label_writes(broken, plan)
    assert [c[0] for c in broken.calls] == ["A-1"]


# --- Import reads the labels -----------------------------------------------------------------


def with_labels(data: TeamData, on: bool) -> None:
    data.team.tracker.write_labels = on


def test_a_label_becomes_an_earmark(data: TeamData, fc: Forecast):
    with_labels(data, True)
    plan = plan_import(data, fc, [raw("A-1", labels=["planned_for_2026.23"]), raw("A-2")], TODAY)
    assert plan.preplan.earmarks == [Earmark("A-1", "2026.23")] and plan.preplan_changed
    (change,) = plan.of_kind("earmark_from_label")
    assert (change.key, change.new) == ("A-1", "2026.23")


def test_labels_are_ignored_while_write_labels_is_off(data: TeamData, fc: Forecast):
    with_labels(data, False)
    plan = plan_import(data, fc, [raw("A-1", labels=["planned_for_2026.23"])], TODAY)
    assert plan.preplan.earmarks == [] and not plan.of_kind("earmark_from_label")


def test_the_earmark_of_the_tool_wins_over_the_label(data: TeamData, fc: Forecast):
    with_labels(data, True)
    data.preplan = Preplan(earmarks=[Earmark("A-1", "2026.24")])
    plan = plan_import(data, fc, [raw("A-1", labels=["planned_for_2026.23"])], TODAY)
    assert plan.preplan.earmarks == [Earmark("A-1", "2026.24")]
    assert not plan.of_kind("earmark_from_label")
    writes = plan_label_writes(plan.tickets, plan.preplan).writes
    assert writes == [
        LabelWrite("A-1", "Title A-1", ["planned_for_2026.24"], ["planned_for_2026.23"])
    ]


def test_the_jira_sprint_wins_over_the_label(data: TeamData, fc: Forecast):
    with_labels(data, True)
    plan = plan_import(
        data, fc, [raw("A-1", sprint_name="2026.22", labels=["planned_for_2026.23"])], TODAY
    )
    assert plan.preplan.earmarks == []
    assert plan_label_writes(plan.tickets, plan.preplan).writes[0].remove == ["planned_for_2026.23"]


@pytest.mark.parametrize(
    "labels",
    [
        ["planned_for_2026.01"],
        ["planned_for_nonsense"],
        ["planned_for_2026.22", "planned_for_2026.23"],
    ],
)
def test_unusable_labels_are_reported_and_not_adopted(data: TeamData, fc: Forecast, labels):
    with_labels(data, True)
    plan = plan_import(data, fc, [raw("A-1", labels=labels)], TODAY)
    assert plan.preplan.earmarks == [] and not plan.preplan_changed
    assert any("A-1" in w and "planned_for_" in w for w in plan.warnings)


def test_a_done_ticket_does_not_adopt_its_label(data: TeamData, fc: Forecast):
    with_labels(data, True)
    plan = plan_import(data, fc, [raw("A-1", resolved=True, labels=["planned_for_2026.23"])], TODAY)
    assert plan.preplan.earmarks == []


# --- Command ---------------------------------------------------------------------------------


class Board:
    """Jira with labels that follow the PUTs: the handler of the CLI mock plus a write side."""

    def __init__(self, mock: Mock) -> None:
        self.mock = mock
        self.reads = mock.handler
        self.puts: list[tuple[str, dict]] = []
        self.fail: int | None = None
        mock.handler = self

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            if self.fail:
                return httpx.Response(self.fail)
            self.puts.append((request.url.path, json.loads(request.content)))
            return httpx.Response(204)
        return self.reads(request)


@pytest.fixture
def board(jira: Mock) -> Board:
    return Board(jira)


def earmark(data_dir: Path, ticket: str, sprint: str) -> None:
    path = data_dir / "demo" / "preplan.yaml"
    path.write_text(
        yaml.safe_dump(
            {"schema": 1, "earmarks": [{"ticket": ticket, "sprint": sprint}], "estimates": []}
        ),
        encoding="utf-8",
    )


def test_write_labels_needs_the_setting(jira_dir: Path, board: Board):
    result = run(jira_dir, "tickets", "demo", "--write-labels")
    assert result.exit_code == 1 and "write_labels" in result.output
    assert board.puts == []


def test_write_labels_previews_without_writing(jira_dir: Path, board: Board):
    write_team(jira_dir, write_labels=True)
    earmark(jira_dir, "ABC-2", "2026.23")
    result = run(jira_dir, "tickets", "demo", "--write-labels")
    assert result.exit_code == 0, result.output
    assert "planned_for_2026.23" in result.output and "ABC-2" in result.output
    assert "Nur Vorschau" in result.output
    assert board.puts == []
    assert not tickets_file(jira_dir).exists()


def test_write_labels_apply_puts_only_the_label_change(jira_dir: Path, board: Board):
    write_team(jira_dir, write_labels=True)
    earmark(jira_dir, "ABC-2", "2026.23")
    result = run(jira_dir, "tickets", "demo", "--write-labels", "--apply")
    assert result.exit_code == 0, result.output
    assert board.puts == [
        (
            "/rest/api/2/issue/ABC-2",
            {"update": {"labels": [{"add": "planned_for_2026.23"}]}},
        )
    ]
    assert "1 Tickets in Jira geändert" in result.output
    assert not tickets_file(jira_dir).exists()


def test_write_labels_without_changes_writes_nothing(jira_dir: Path, board: Board):
    write_team(jira_dir, write_labels=True)
    result = run(jira_dir, "tickets", "demo", "--write-labels", "--apply")
    assert result.exit_code == 0 and "Keine Label-Änderungen" in result.output
    assert board.puts == []


def test_write_labels_failure_is_a_message_not_a_traceback(jira_dir: Path, board: Board):
    write_team(jira_dir, write_labels=True)
    earmark(jira_dir, "ABC-2", "2026.23")
    board.fail = 403
    result = run(jira_dir, "tickets", "demo", "--write-labels", "--apply")
    assert result.exit_code == 1 and "Labels ändern" in result.output
    assert "Traceback" not in result.output and "ABC-2" in result.output


@pytest.mark.parametrize("extra", [["--fetch"], ["--test-connection"], ["--import", "x.csv"]])
def test_write_labels_excludes_the_other_actions(jira_dir: Path, board: Board, extra):
    write_team(jira_dir, write_labels=True)
    result = run(jira_dir, "tickets", "demo", "--write-labels", *extra)
    assert result.exit_code == 1 and "schließen einander aus" in result.output


def test_write_labels_needs_jira(ticket_csv_dir: Path):
    result = run(ticket_csv_dir, "tickets", "demo", "--write-labels")
    assert result.exit_code == 1 and "tracker.kind: jira" in result.output
