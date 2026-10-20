# SPDX-License-Identifier: EUPL-1.2
"""Tab "Assignment" of the page Tickets: which project and product each ticket belongs to."""

from datetime import date
from pathlib import Path

import pytest
from ticketfixtures import enable, seed

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from foresprint.model import Rule
from foresprint.storage import AS_OF_ENV, DATA_ENV, Repository
from foresprint.web.tickets_view import Selection, assignment_rows, assignment_summary

APP = Path(__file__).parent.parent / "src" / "foresprint" / "web" / "app.py"
TODAY = date(2026, 10, 15)


@pytest.fixture(autouse=True)
def in_english(english):
    return None


def loaded(data_dir: Path):
    enable(data_dir)
    seed(data_dir)
    data = Repository(data_dir).load("demo")
    by_key = {tk.key: tk for tk in data.tickets}
    by_key["T-1"].project, by_key["T-1"].epic = "payment", "ABC-100"
    by_key["T-4"].project, by_key["T-4"].epic = "migration", "ABC-200"
    by_key["T-4"].labels = ["x"]
    by_key["T-2"].project, by_key["T-2"].project_candidates = None, ["payment", "migration"]
    by_key["T-3"].project = None
    by_key["T-7"].done = True
    return data


def everything(data) -> Selection:
    return Selection(frozenset(p.id for p in data.projects))


def test_rows_show_project_product_and_the_matching_criterion(data_dir: Path):
    data = loaded(data_dir)
    rows = {r["Ticket"]: r for r in assignment_rows(data, everything(data))}
    assert "T-7" not in rows  # done tickets are not listed
    assert (
        rows["T-1"]["Project"] == "Payment" and rows["T-1"]["Product"] == "Webshop"
    )  # the name, not the id
    assert rows["T-1"]["Matched by"] == "Epic" and rows["T-1"]["Note"] == ""
    assert rows["T-2"]["Project"] == "–"
    assert rows["T-2"]["Note"] == "Contradiction: fits Payment, Migration"
    assert rows["T-3"]["Note"] == "No project matches"


def test_matching_criteria_follow_the_configured_order(data_dir: Path):
    data = loaded(data_dir)
    migration = data.project("migration")
    assert migration is not None
    migration.match = Rule(
        op="any",
        children=[Rule(source="label", values=["x"]), Rule(source="epic", values=["ABC-200"])],
    )
    row = next(r for r in assignment_rows(data, everything(data)) if r["Ticket"] == "T-4")
    assert row["Matched by"] == "Epic, Jira label"  # default order: epic before label
    data.team.tracker.project_match_order = ["label", "epic", "component"]
    row = next(r for r in assignment_rows(data, everything(data)) if r["Ticket"] == "T-4")
    assert row["Matched by"] == "Jira label, Epic"


def test_the_filter_hides_rows_and_the_summary_counts_per_product(data_dir: Path):
    data = loaded(data_dir)
    only_payment = Selection(frozenset({"payment"}), no_project=False, known=frozenset(
        p.id for p in data.projects
    ))  # fmt: skip
    rows = assignment_rows(data, only_payment)
    assert {r["Ticket"] for r in rows} == {"T-1", "T-6"}
    summary = {
        r["Product"]: r["Tickets"]
        for r in assignment_summary(assignment_rows(data, everything(data)))
    }
    # webshop: T-1, T-6 (payment), T-4, T-5 (migration); no project: T-2, T-3
    assert summary == {"Webshop": 4, "No project": 2}


def test_the_tab_is_on_the_page(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, TODAY.isoformat())
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.switch_page("page_scripts/tickets.py").run()
    assert not at.exception, at.exception
    assert "Assignment" in [tab.label for tab in at.tabs]


def test_a_stale_assignment_and_product_names(data_dir: Path):
    data = loaded(data_dir)
    payment = data.project("payment")
    assert payment is not None
    payment.match = None  # the rule was removed after the import
    data.projects.append(type(payment)(id="solo", name="Solo"))  # a project without a product
    by_key = {tk.key: tk for tk in data.tickets}
    by_key["T-3"].project = "solo"
    by_key["T-6"].project = "gone"  # a project that no longer exists
    rows = {r["Ticket"]: r for r in assignment_rows(data, everything(data))}
    assert rows["T-1"]["Project"] == "Payment" and "no longer matches" in rows["T-1"]["Note"]
    assert rows["T-3"]["Product"] == "–"
    assert rows["T-6"]["Note"] == "Unknown project gone"
    summary = {r["Product"]: r["Tickets"] for r in assignment_summary(list(rows.values()))}
    # T-3 has a project without product; T-2 (contradiction) and T-6 (unknown project) have none
    assert summary["No product"] == 1 and summary["No project"] == 2
