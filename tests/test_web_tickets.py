# SPDX-License-Identifier: EUPL-1.2
"""Page "Tickets": filter, tables, earmarks, import with preview and maintenance (AppTest)."""

from datetime import date
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from ticketfixtures import enable, seed

from sprintforecast.model import BudgetBasis, ManualEstimate, Project, Rule
from sprintforecast.preplan import distribute, handover_rows
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
    timeline_range_rows,
    timeline_rows,
)

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
DATA = Path(__file__).parent / "data"
TODAY = date(2026, 10, 15)
CSV = (DATA / "jira_en.csv").read_bytes()
UPLOADER = "tickets-demo-file-0"


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


def test_timeline_range_covers_sprints_outside_the_median_bar(data_dir: Path):
    import copy

    from sprintforecast.preplan import Variants

    enable(data_dir)
    seed(data_dir)
    data = Repository(data_dir).load("demo")
    median = distribute(data, TODAY)
    axis = median.sprints
    sel = Selection(frozenset({"payment"}), no_project=False)
    placed = [p for p in median.placements if p.project == "payment" and p.sprint in axis]
    assert placed
    last = max(axis.index(p.sprint) for p in placed)
    assert last + 1 < len(axis)
    late = copy.deepcopy(median)
    for p in late.placements:
        if p.project == "payment" and p.sprint == axis[last]:
            p.sprint = axis[last + 1]
    assert timeline_range_rows(data, Variants(median), sel, axis) == []
    rows = timeline_range_rows(
        data, Variants(median, conservative=late, optimistic=median), sel, axis
    )
    assert [r["Sprint"] for r in rows] == [axis[last + 1]]
    assert {r["Projekt"] for r in rows} == {"Payment"}


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


def test_jira_fetch_previews_then_writes(data_dir: Path, monkeypatch):
    from sprintforecast.sources import RawTicket

    class Fake:
        kind, name, host = "jira", "jira.example.org", "jira.example.org"

        def fetch(self):
            return [RawTicket(key="J-1", title="From Jira", estimate=2.0, epic="ABC-100")]

        def close(self):
            pass

    enable(data_dir)
    team = data_dir / "demo" / "team.yaml"
    doc = yaml.safe_load(team.read_text(encoding="utf-8"))
    doc["tracker"]["kind"] = "jira"
    doc["tracker"]["base_url"] = "https://jira.example.org"
    team.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr("sprintforecast.web.tickets_view.open_source", lambda tracker: Fake())
    at = page(data_dir, monkeypatch)
    button(at, "Tickets aus Jira lesen").click().run()
    assert not at.exception, at.exception
    assert not (data_dir / "demo" / "tickets.yaml").exists()
    button(at, "Änderungen übernehmen").click().run()
    assert not at.exception, at.exception
    written = yaml.safe_load((data_dir / "demo" / "tickets.yaml").read_text(encoding="utf-8"))
    assert [tk["key"] for tk in written["tickets"]] == ["J-1"]
    assert written["source"] == "jira.example.org"


def test_planning_assistant_suggests_the_ticket_sums(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    at = page(data_dir, monkeypatch)
    at.switch_page("seiten/planning.py").run()
    radio = at.radio(key="planning-step")
    radio.set_value(radio.options[1]).run()
    assert not at.exception, at.exception
    assert any("Vorschlag aus der Ticket-Vorplanung" in e.label for e in at.expander)


def test_every_change_kind_has_a_title():
    from sprintforecast.ticket_import import KINDS
    from sprintforecast.web.tickets_view import change_titles

    assert set(KINDS) <= set(change_titles())


class LabelSource:
    """Jira stand-in for the label write-back; ``labels`` is what Jira currently carries."""

    kind, name, host = "jira", "jira.example.org", "jira.example.org"

    def __init__(self, labels: list[str] | None = None):
        self.labels = labels or []
        self.calls: list[tuple[str, list[str], list[str]]] = []

    def fetch(self):
        from sprintforecast.sources import RawTicket

        return [RawTicket(key="J-1", title="From Jira", estimate=2.0, labels=list(self.labels))]

    def set_labels(self, key, add, remove):
        self.calls.append((key, add, remove))

    def close(self):
        pass


def label_setup(data_dir: Path, monkeypatch, source: LabelSource, write_labels: bool = True):
    from sprintforecast.model import Earmark, Preplan

    enable(data_dir)
    team = data_dir / "demo" / "team.yaml"
    doc = yaml.safe_load(team.read_text(encoding="utf-8"))
    doc["tracker"]["kind"] = "jira"
    doc["tracker"]["base_url"] = "https://jira.example.org"
    doc["tracker"]["write_labels"] = write_labels
    team.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    Repository(data_dir).save_preplan("demo", Preplan(earmarks=[Earmark("J-1", "2026.24")]))
    monkeypatch.setattr("sprintforecast.web.tickets_view.open_source", lambda tracker: source)
    return page(data_dir, monkeypatch)


def test_label_writeback_previews_then_writes(data_dir: Path, monkeypatch):
    source = LabelSource()
    at = label_setup(data_dir, monkeypatch, source)
    button(at, "Label-Änderungen prüfen").click().run()
    assert not at.exception, at.exception
    assert source.calls == []
    assert any("J-1" in str(df.value.to_dict()) for df in at.dataframe)
    button(at, "In Jira schreiben").click().run()
    assert not at.exception, at.exception
    assert source.calls == [("J-1", ["planned_for_2026.24"], [])]


def test_label_writeback_refuses_a_changed_state(data_dir: Path, monkeypatch):
    source = LabelSource()
    at = label_setup(data_dir, monkeypatch, source)
    button(at, "Label-Änderungen prüfen").click().run()
    source.labels = ["planned_for_2026.23"]  # somebody else changed the ticket meanwhile
    button(at, "In Jira schreiben").click().run()
    assert not at.exception, at.exception
    assert source.calls == []
    assert any("seit der Vorschau geändert" in w.value for w in at.warning)


def test_label_writeback_needs_the_switch(data_dir: Path, monkeypatch):
    at = label_setup(data_dir, monkeypatch, LabelSource(), write_labels=False)
    assert not any(b.label == "Label-Änderungen prüfen" for b in at.button)


def test_label_writeback_failure_drops_the_preview(data_dir: Path, monkeypatch):
    from sprintforecast.sources import SourceError

    class Failing(LabelSource):
        def set_labels(self, key, add, remove):
            raise SourceError("kaputt")

    at = label_setup(data_dir, monkeypatch, Failing())
    button(at, "Label-Änderungen prüfen").click().run()
    button(at, "In Jira schreiben").click().run()
    assert not at.exception, at.exception
    assert any("kaputt" in e.value for e in at.error)
    at.run()  # the next run no longer offers the out-of-date preview
    assert not any(b.label == "In Jira schreiben" for b in at.button)


def test_label_writeback_with_an_empty_query_writes_nothing(data_dir: Path, monkeypatch):
    class Empty(LabelSource):
        def fetch(self):
            return []

    source = Empty()
    at = label_setup(data_dir, monkeypatch, source)
    button(at, "Label-Änderungen prüfen").click().run()
    assert not at.exception, at.exception
    assert any("keine Tickets" in e.value for e in at.error)
    assert source.calls == []


def test_overview_shows_the_range_or_says_why_not(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    at = page(data_dir, monkeypatch)
    assert not at.exception, at.exception
    data = Repository(data_dir).load("demo")
    from sprintforecast.preplan import distribute_variants

    variants = distribute_variants(data, TODAY)
    columns = {c for df in at.dataframe for c in df.value.columns}
    if variants.available:
        assert "Letzter Sprint optimistisch" in columns
    else:
        assert "Letzter Sprint" in columns
        assert any("Keine Bandbreite" in c.value for c in at.caption)


def test_handover_previews_then_writes_only_empty_values(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    data = Repository(data_dir).load("demo")
    rows = handover_rows(data, distribute(data, TODAY), 6)
    assert rows
    at = page(data_dir, monkeypatch)
    assert any("Übergabe an die PO-Vorplanung" in s.value for s in at.subheader)
    button(at, "In die PO-Vorplanung übernehmen").click().run()
    assert not at.exception, at.exception
    after = Repository(data_dir).load("demo")
    for row in rows:
        values = after.sprint(row.sprint).products[row.product]
        assert values.preplanned == (row.current if row.current is not None else row.proposed)


def test_handover_sprints_keep_a_different_value_unless_overwritten(data_dir: Path):
    from sprintforecast.preplan import HandoverRow
    from sprintforecast.web.tickets_view import handover_sprints

    data = Repository(data_dir).load("demo")
    sprint = data.sprints[-1]
    product = data.products[0].id
    rows = [
        HandoverRow(sprint.id, product, proposed=5.0, current=3.0),
        HandoverRow(sprint.id, product, proposed=4.0, current=4.0),
    ]
    assert handover_sprints(data, rows, overwrite=False) == []
    (written,) = handover_sprints(data, rows[:1], overwrite=True)
    assert written.products[product].preplanned == 5.0
    new = HandoverRow("2099.01", product, proposed=2.0)
    assert handover_sprints(data, [new], overwrite=False) == []  # unknown sprint: skipped


def test_handover_overwrite_checkbox_replaces_the_po_value(data_dir: Path, monkeypatch):
    enable(data_dir)
    seed(data_dir)
    data = Repository(data_dir).load("demo")
    rows = handover_rows(data, distribute(data, TODAY), 6)
    differing = next(r for r in rows if r.current is not None and r.current != r.proposed)
    at = page(data_dir, monkeypatch)
    at.checkbox(key="tickets-demo-handover-overwrite").check().run()
    button(at, "In die PO-Vorplanung übernehmen").click().run()
    assert not at.exception, at.exception
    after = Repository(data_dir).load("demo")
    assert after.sprint(differing.sprint).products[differing.product].preplanned == (
        differing.proposed
    )


def test_handover_sprints_create_the_calendar_sprints_in_between(data_dir: Path):
    from sprintforecast.preplan import HandoverRow
    from sprintforecast.web.tickets_view import handover_sprints

    data = Repository(data_dir).load("demo")
    product = data.products[0].id
    last = data.sprints[-1]
    from sprintforecast.calendar import following_sprint

    first = following_sprint(data.team, last)
    third = following_sprint(data.team, following_sprint(data.team, first))
    written = handover_sprints(data, [HandoverRow(third.id, product, 2.0)], False)
    assert [s.id for s in written][-1] == third.id
    assert first.id in {s.id for s in written}
    assert written[-1].products[product].preplanned == 2.0
