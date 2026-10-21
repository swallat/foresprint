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
    assert rows["T-3"]["Note"] == "No product matches"


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
    assert summary == {"Webshop": 4, "No product": 2}


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
    assert summary["No product"] == 3


def test_product_rules_show_in_rows_backlog_and_timeline():
    from test_preplan import TODAY, team_data

    from foresprint.model import EstimateSource, Product, Rule, Ticket
    from foresprint.preplan import distribute
    from foresprint.web.tickets_view import (
        Selection,
        assignment_rows,
        project_rows,
        timeline_rows,
    )

    data = team_data(
        products=[Product("shop", "Shop", match=Rule(source="label", values=["shop"]))]
    )
    data.tickets = [
        Ticket(key="B-1", estimate=3, labels=["shop"], estimate_source=EstimateSource.REFINED),
        Ticket(key="X-1", estimate=3),
    ]
    sel = Selection(frozenset())
    rows = {r["Ticket"]: r for r in assignment_rows(data, sel)}
    assert rows["B-1"]["Product"] == "Shop" and rows["B-1"]["Matched by"] == "Jira label"
    assert rows["X-1"]["Note"] == "No product matches"
    dist = distribute(data, TODAY)
    table = project_rows(data, dist, sel)
    assert [r["Project"] for r in table] == ["Shop without project"]
    assert table[0]["Outstanding"] == 1
    bars, _ = timeline_rows(data, dist, sel, dist.sprints)
    assert {b["Project"] for b in bars} == {"Shop without project"}


def test_the_rule_editor_saves_a_product_rule(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, TODAY.isoformat())
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.switch_page("page_scripts/tickets.py").run()
    kind = next(r for r in at.radio if r.label == "Rule for")
    kind.set_value("Product").run()
    assert not at.exception, at.exception
    area = next(a for a in at.text_area if a.label == "Rule")
    area.set_value("label = shop").run()
    next(b for b in at.button if b.label == "Save rule").click().run()
    assert not at.exception, at.exception
    products = Repository(data_dir).load("demo").products
    assert any(p.match is not None for p in products)


def test_the_product_filter_hides_the_lines_without_project():
    from test_preplan import TODAY, team_data

    from foresprint.model import EstimateSource, Product, Rule, Ticket
    from foresprint.preplan import distribute
    from foresprint.web.tickets_view import project_rows, timeline_rows

    data = team_data(
        products=[Product("shop", "Shop", match=Rule(source="label", values=["shop"]))]
    )
    data.tickets = [
        Ticket(key="B-1", estimate=3, labels=["shop"], estimate_source=EstimateSource.REFINED)
    ]
    dist = distribute(data, TODAY)
    off = Selection(frozenset(), True, None, frozenset())
    assert project_rows(data, dist, off) == []
    assert timeline_rows(data, dist, off, dist.sprints) == ([], [])
    assert assignment_rows(data, off) == []
    on = Selection(frozenset(), True, None, frozenset({"shop"}))
    assert len(project_rows(data, dist, on)) == 1
    assert project_rows(data, dist, on)[0]["Last sprint"] == dist.sprints[0]


def test_a_card_button_earmarks_and_releases(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, TODAY.isoformat())
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.switch_page("page_scripts/tickets.py").run()
    assert not at.exception, at.exception
    pins = [b for b in at.button if b.key and b.key.endswith("-pin")]
    assert pins, "no ticket card with buttons"
    pins[0].click().run()
    assert not at.exception, at.exception
    assert Repository(data_dir).load("demo").preplan.earmarks
    release = next(b for b in at.button if b.key and b.key.endswith("-pin"))
    release.click().run()
    assert not Repository(data_dir).load("demo").preplan.earmarks
