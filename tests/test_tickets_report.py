# SPDX-License-Identifier: EUPL-1.2
"""Ticket pre-planning in the report and in the planning assistant."""

from datetime import date
from pathlib import Path

from ticketfixtures import enable, seed

from sprintforecast.forecast import build_forecast
from sprintforecast.preplan import distribute, sprint_sums
from sprintforecast.report import render
from sprintforecast.storage import Repository

TODAY = date(2026, 10, 15)


def report(data_dir: Path) -> str:
    return render(build_forecast(Repository(data_dir).load("demo"), TODAY))


def test_report_without_the_feature_has_no_ticket_section(data_dir: Path):
    assert "## Tickets" not in report(data_dir)


def test_report_without_tickets_has_no_ticket_section(data_dir: Path):
    enable(data_dir)
    assert "## Tickets" not in report(data_dir)


def test_report_has_projects_and_sprints(data_dir: Path):
    enable(data_dir)
    seed(data_dir)
    text = report(data_dir)
    section = text[text.index("## Tickets") :]
    assert "| Payment |" in section and "| Migration |" in section
    assert "| 2026.22 |" in section
    assert "lassen sich nicht verteilen" in section


def test_report_in_english(data_dir: Path, english):
    enable(data_dir)
    seed(data_dir)
    text = report(data_dir)
    assert "Traffic light" in text[text.index("## Tickets") :]


def test_sprint_sums_are_the_used_budget_per_product(data_dir: Path):
    enable(data_dir)
    seed(data_dir)
    dist = distribute(Repository(data_dir).load("demo"), TODAY)
    sums = sprint_sums(dist, dist.sprints[0])
    assert sums["webshop"] > 0  # T-7 is fixed in 2026.22, other tickets follow
    assert set(sums) <= {b.product for b in dist.budgets}
    assert sprint_sums(dist, "2099.1") == {}
