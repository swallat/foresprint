# SPDX-License-Identifier: EUPL-1.2
"""Page "Tickets": filter, tables, earmarks, import with preview and maintenance (AppTest)."""

from datetime import date
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

import math  # noqa: F401

from streamlit.testing.v1 import AppTest

from sprintforecast.model import BudgetBasis, ManualEstimate, Project, Rule
from sprintforecast.preplan import distribute
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository
from sprintforecast.web.tickets_view import (
    Selection,
    apply_project_rows,
    editable_columns,
    estimates_from_rows,
    open_rows,
    project_rows,
    refinement_rows,
    rule_from_columns,
    split_values,
    timeline_rows,
)

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
DATA = Path(__file__).parent / "data"
TODAY = date(2026, 10, 15)
CSV = (DATA / "jira_en.csv").read_bytes()
UPLOADER = "tickets-demo-file-0"


def enable(data_dir: Path, projects: bool = True) -> None:
    team = data_dir / "demo"
    doc = yaml.safe_load((team / "team.yaml").read_text(encoding="utf-8"))
    doc["features"]["tickets"] = True
    doc["tracker"] = {
        "kind": "csv",
        "fields": {"estimate": "Story Points", "remaining": "Remaining", "epic": "Epic Link"},
        "refined_label": "Refined",
    }
    (team / "team.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    if projects:
        (team / "projects.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema": 1,
                    "projects": [
                        {
                            "id": "payment", "name": "Payment", "product": "webshop",
                            "target": "2027-03-31", "match": {"epic": ["ABC-100"]},
                        },
                        {
                            "id": "migration", "name": "Migration", "product": "webshop",
                            "target": "2026-11-30", "match": {"epic": ["ABC-200"]},
                        },
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )  # fmt: skip


def seed(data_dir: Path) -> None:
    """Tickets small enough for the budget of the demo team (3 per sprint and product)."""
    from sprintforecast.model import EstimateSource, Ticket

    refined, rough = EstimateSource.REFINED, EstimateSource.ROUGH

    def ticket(key: str, project: str, size: float | None, source=refined, **kw) -> Ticket:
        return Ticket(
            key=key, title=f"Title of {key}", project=project, estimate=size, remaining=None,
            estimate_source=source if size is not None else EstimateSource.NONE, rank=key, **kw,
        )  # fmt: skip

    Repository(data_dir).save_tickets(
        "demo",
        [
            ticket("T-1", "payment", 2),
            ticket("T-2", "payment", 2, rough),
            ticket("T-3", "payment", 1, rough),
            ticket("T-4", "migration", 3),
            ticket("T-5", "migration", 2, rough, depends_on=["T-4"]),
            ticket("T-6", "payment", None),
            ticket("T-7", "payment", 1, in_sprint="2026.22"),
        ],
        None,
        "seed",
    )


def imported(data_dir: Path) -> None:
    """tickets.yaml as the CSV import would write it."""
    from sprintforecast.forecast import build_forecast
    from sprintforecast.sources.csv import CsvSource
    from sprintforecast.ticket_import import apply_import, plan_import

    repo = Repository(data_dir)
    data = repo.load("demo")
    raws = CsvSource(DATA / "jira_en.csv", data.team.tracker.fields).fetch()
    apply_import(repo, "demo", plan_import(data, build_forecast(data, TODAY), raws, TODAY, "x.csv"))


def page(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, TODAY.isoformat())
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.switch_page("seiten/tickets.py").run()
    assert not at.exception, at.exception
    return at


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


# --- Pure functions ----------------------------------------------------------------------------


def test_rule_columns_round_trip():
    assert editable_columns(None) == {}
    rule = rule_from_columns({"epic": ["A-1", "A-2"], "label": ["x"], "component": []})
    assert rule is not None and rule.short
    assert editable_columns(rule) == {"epic": ["A-1", "A-2"], "label": ["x"]}
    one = rule_from_columns({"epic": ["A-1"]})
    assert one is not None and one.op == "leaf" and editable_columns(one) == {"epic": ["A-1"]}
    assert rule_from_columns({}) is None
    nested = Rule(op="all", children=[Rule(source="epic", values=["A-1"])])
    assert editable_columns(nested) is None
    status = Rule(source="status", values=["Ready"])
    assert editable_columns(status) is None


def test_split_values():
    assert split_values(" A-1, ,A-2 ,") == ["A-1", "A-2"]
    assert split_values(None) == []


def test_filter_only_hides(data_dir: Path):
    enable(data_dir)
    seed(data_dir)
    data = Repository(data_dir).load("demo")
    dist = distribute(data, TODAY)
    everything = Selection(frozenset({"payment", "migration"}))
    only_payment = Selection(frozenset({"payment"}), no_project=False)
    assert {r["Projekt"] for r in project_rows(data, dist, everything)} == {"Payment", "Migration"}
    assert {r["Projekt"] for r in project_rows(data, dist, only_payment)} == {"Payment"}
    # The distribution is untouched by the filter (shared budget).
    assert distribute(data, TODAY).placements == dist.placements
    assert all(r["Projekt"] != "Migration" for r in refinement_rows(data, dist, only_payment))
    assert all(r["Projekt"] == "Payment" for r in open_rows(data, dist, only_payment))
    axis = dist.sprints
    bars, marks = timeline_rows(data, dist, only_payment, axis)
    assert {b["Projekt"] for b in bars} <= {"Payment"}
    assert all(m["Projekt"] == "Payment" for m in marks)


# --- Page --------------------------------------------------------------------------------------


def test_switched_off_there_is_no_page(data_dir: Path, monkeypatch):
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, TODAY.isoformat())
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    with pytest.raises(ValueError, match="Could not find a navigation page"):
        at.switch_page("seiten/tickets.py")


def test_no_tickets_yet_points_to_the_import(data_dir: Path, monkeypatch):
    enable(data_dir)
    at = page(data_dir, monkeypatch)
    assert any("Import" in i.value for i in at.info)
    assert at.file_uploader


def test_overview_shows_projects_and_timeline(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    at = page(data_dir, monkeypatch)
    frame = at.dataframe[0].value
    assert set(frame["Projekt"]) == {"Payment", "Migration"}
    assert "Ampel" in frame.columns
    assert at.caption and any("Zielsprint des Projekts" in c.value for c in at.caption)


def test_filter_hides_a_project(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    at = page(data_dir, monkeypatch)
    multi = next(m for m in at.multiselect if m.label == "Projekte")
    multi.set_value(["payment"]).run()
    assert not at.exception, at.exception
    assert set(at.dataframe[0].value["Projekt"]) == {"Payment"}


def test_import_previews_then_writes(data_dir: Path, monkeypatch):
    enable(data_dir)
    at = page(data_dir, monkeypatch)
    at.file_uploader(key=UPLOADER).upload("jira_en.csv", CSV).run()
    assert not at.exception, at.exception
    assert not (data_dir / "demo" / "tickets.yaml").exists()
    assert any("Neue Tickets" in e.label for e in at.expander)
    button(at, "Änderungen übernehmen").click().run()
    assert not at.exception, at.exception
    written = yaml.safe_load((data_dir / "demo" / "tickets.yaml").read_text(encoding="utf-8"))
    assert {tk["key"] for tk in written["tickets"]} >= {"ABC-1", "ABC-2"}
    assert any("tickets.yaml" in s.value for s in at.success)


def test_import_of_a_bad_file_writes_nothing(data_dir: Path, monkeypatch):
    enable(data_dir)
    at = page(data_dir, monkeypatch)
    at.file_uploader(key=UPLOADER).upload("bad.csv", (DATA / "jira_missing.csv").read_bytes()).run()
    assert not at.exception, at.exception
    assert at.error
    assert not (data_dir / "demo" / "tickets.yaml").exists()


def test_earmark_and_release(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    at = page(data_dir, monkeypatch)
    dist = distribute(Repository(data_dir).load("demo"), TODAY)
    movable = next(
        p for p in dist.placements if p.reason == "placed" and p.sprint != dist.sprints[-1]
    )
    at.selectbox(key="tickets-demo-earmark-ticket").set_value(movable.ticket).run()
    target = dist.sprints[-1]
    at.selectbox(key=f"tickets-demo-earmark-sprint-{movable.ticket}").set_value(target).run()
    button(at, "Vormerken").click().run()
    assert not at.exception, at.exception
    stored = yaml.safe_load((data_dir / "demo" / "preplan.yaml").read_text(encoding="utf-8"))
    assert {"ticket": movable.ticket, "sprint": target} == {
        k: v for k, v in stored["earmarks"][0].items() if k in ("ticket", "sprint")
    }
    at.selectbox(key="tickets-demo-earmark-ticket").set_value(movable.ticket).run()
    at.selectbox(key=f"tickets-demo-earmark-sprint-{movable.ticket}").set_value("").run()
    button(at, "Freigeben").click().run()
    assert not at.exception, at.exception
    assert not Repository(data_dir).load("demo").preplan.earmarks


def test_fixed_ticket_cannot_be_moved(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    data = Repository(data_dir).load("demo")
    fixed = next(p for p in distribute(data, TODAY).placements if p.reason == "fixed_sprint")
    assert fixed.ticket == "T-7"
    at = page(data_dir, monkeypatch)
    at.selectbox(key="tickets-demo-earmark-ticket").set_value(fixed.ticket).run()
    assert any("lässt sich hier nicht verschieben" in i.value for i in at.info)


def test_add_edit_and_remove_project(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    at = page(data_dir, monkeypatch)
    for label, value in {
        "Id": "reporting",
        "Name": "Reporting",
        "Epics": "ABC-300, ABC-301",
    }.items():
        next(t for t in at.text_input if t.label == label).set_value(value)
    next(b for b in at.selectbox if b.label == "Produkt").set_value("webshop")
    next(d for d in at.date_input if d.label == "Ziel").set_value(date(2027, 2, 1))
    next(b for b in at.button if b.label == "Projekt anlegen").click().run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    data = Repository(data_dir).load("demo")
    assert [p.id for p in data.projects] == ["payment", "migration", "reporting"]
    assert editable_columns(data.projects[-1].match) == {"epic": ["ABC-300", "ABC-301"]}
    assert data.projects[-1].target == date(2027, 2, 1)
    at = page(data_dir, monkeypatch)
    at.selectbox(key="tickets-demo-rm").set_value("reporting").run()
    button(at, "Projekt entfernen").click().run()
    assert not at.exception, at.exception
    assert [p.id for p in Repository(data_dir).load("demo").projects] == ["payment", "migration"]


def test_project_rows_update_everything_but_the_id_and_nested_rules():
    nested = Rule(op="all", children=[Rule(source="epic", values=["A-1"])])
    projects = [
        Project(id="a", name="A", product="webshop", target=date(2027, 1, 1), match=None),
        Project(id="b", name="B", match=nested),
    ]
    rows = [
        ("zzz", " New A ", "", date(2027, 5, 1), 2.0, "plan", "E-1, E-2", "", "x"),
        ("b", "B", None, None, float("nan"), "", "ignored", "", ""),
    ]
    a, b = apply_project_rows(projects, rows)
    assert (a.id, a.name, a.product, a.target, a.priority) == (
        "a",
        "New A",
        None,
        date(2027, 5, 1),
        2,
    )
    assert a.budget_basis is BudgetBasis.PLAN
    assert editable_columns(a.match) == {"epic": ["E-1", "E-2"], "label": ["x"]}
    assert b.match is nested and b.priority == 0 and b.budget_basis is None and b.target is None
    assert projects[0].name == "A"  # the input is not changed


def test_estimate_rows():
    rows = [("T-1", 2.5, " why "), ("", 1.0, ""), (None, None, None), ("T-2", float("nan"), "")]
    assert estimates_from_rows(rows) == [
        ManualEstimate("T-1", 2.5, "why"),
        ManualEstimate("T-2", None, None),
    ]
    with pytest.raises(ValueError):
        estimates_from_rows([("T-1", 1.0, ""), ("T-1", 2.0, "")])


def test_unestimated_ticket_is_listed_on_the_open_points(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    at = page(data_dir, monkeypatch)
    rows = [df.value for df in at.dataframe if "Grund" in df.value.columns]
    assert rows and "T-6" in set(rows[0]["Ticket"])


def test_removing_a_project_releases_its_tickets(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    at = page(data_dir, monkeypatch)
    at.selectbox(key="tickets-demo-rm").set_value("payment").run()
    button(at, "Projekt entfernen").click().run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    data = Repository(data_dir).load("demo")
    assert [p.id for p in data.projects] == ["migration"]
    assert all(tk.project != "payment" for tk in data.tickets)
    assert data.ticket("T-1").project is None
    # the released tickets stay visible under "open points"
    at = page(data_dir, monkeypatch)
    rows = [df.value for df in at.dataframe if "Grund" in df.value.columns]
    assert "T-1" in set(rows[0]["Ticket"])


def test_unknown_project_counts_as_without_project():
    sel = Selection(frozenset({"a"}), no_project=True, known=frozenset({"a", "b"}))
    assert sel.shows("a") and sel.shows(None) and sel.shows("gone")
    assert not sel.shows("b")
    assert not Selection(frozenset({"a"}), no_project=False).shows("gone")
