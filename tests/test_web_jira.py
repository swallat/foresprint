# SPDX-License-Identifier: EUPL-1.2
"""Page "Jira connection": form, connection test with field suggestions, saving, and the
guarantee that the token is neither asked for nor shown (AppTest)."""

from datetime import date
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from ticketfixtures import enable

from sprintforecast.model import TrackerFields, TrackerSettings
from sprintforecast.sources import SourceError
from sprintforecast.sources.jira import FieldCandidate, FieldSuggestions
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV
from sprintforecast.web import jira_setup
from sprintforecast.web.jira_setup import Probe, field_options, tracker_from_inputs

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
TODAY = date(2026, 10, 15)
CANARY = "tok-CANARY-0a1b2c3d4e5f"
ENV = "SPRINTFORECAST_JIRA_TOKEN"


@pytest.fixture(autouse=True)
def no_token(english, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(jira_setup, "jira_token", lambda base_url=None: None)


def page(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, TODAY.isoformat())
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.switch_page("page_scripts/jira.py").run()
    assert not at.exception, at.exception
    return at


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def texts(at: AppTest) -> str:
    parts = [e.value for e in (*at.markdown, *at.warning, *at.error, *at.success, *at.info)]
    parts += [c.value for c in at.code]
    return "\n".join(str(p) for p in parts)


def tracker_yaml(data_dir: Path) -> dict:
    return yaml.safe_load((data_dir / "demo" / "team.yaml").read_text(encoding="utf-8"))["tracker"]


SUGGESTIONS = FieldSuggestions(
    estimate=[
        FieldCandidate("customfield_10016", "Story Points", "Story Points", 1),
        FieldCandidate("customfield_10100", "Value", "customfield_10100"),
    ],
    remaining=[FieldCandidate("customfield_10017", "Remaining", "Remaining", 2)],
    epic=[
        FieldCandidate("customfield_10014", "Epic Link", "Epic Link"),
        FieldCandidate("parent", "parent", "parent"),
    ],
)


# --- Pure functions ----------------------------------------------------------------------------


def test_tracker_from_inputs_keeps_the_rest():
    base = TrackerSettings(kind="csv", write_labels=True, refined_label="Refined")
    edited = tracker_from_inputs(
        base, "jira", " https://j.example.org ", " project = A ", {"estimate": " SP ", "epic": ""}
    )
    assert edited.kind == "jira" and edited.base_url == "https://j.example.org"
    assert edited.query == "project = A"
    assert edited.fields == TrackerFields(estimate="SP", remaining=None, epic=None)
    assert edited.write_labels and edited.refined_label == "Refined"


def test_field_options_keeps_the_current_value_and_marks_the_suggestion():
    options = field_options(SUGGESTIONS.estimate, "Old Name")
    assert [v for v, _ in options] == ["", "Old Name", "Story Points", "customfield_10100"]
    assert "suggestion" in options[2][1] and "suggestion" not in options[3][1]
    # a current value that is a candidate's value is not listed twice
    assert [v for v, _ in field_options(SUGGESTIONS.estimate, "Story Points")].count(
        "Story Points"
    ) == 1
    # a field stored by its id stays selectable as the current setting (never silently cleared)
    by_id = field_options(SUGGESTIONS.estimate, "customfield_10016")
    assert ("customfield_10016", "customfield_10016 (current setting)") in by_id


# --- Page --------------------------------------------------------------------------------------


def test_switched_off_there_is_no_page(data_dir: Path, monkeypatch):
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, TODAY.isoformat())
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert "jira" not in at.session_state["enabled-pages"]


def test_without_token_the_page_explains_and_never_asks(data_dir: Path, monkeypatch):
    enable(data_dir)
    at = page(data_dir, monkeypatch)
    assert ENV in texts(at)
    assert not any(getattr(w, "type", None) == "password" for w in at.text_input)
    button(at, "Test connection").click().run()
    assert any("No token" in w.value for w in at.warning)


def test_saving_writes_kind_address_query_and_fields(data_dir: Path, monkeypatch):
    enable(data_dir)
    at = page(data_dir, monkeypatch)
    at.selectbox(key="jira-demo-kind").select("jira")
    at.text_input(key="jira-demo-url").set_value("https://jira.example.org")
    at.text_area(key="jira-demo-query").set_value("project = ABC")
    at.text_input(key="jira-demo-estimate-0").set_value("Story Points")
    button(at, "Save").click().run()
    assert not at.exception and not at.error, at.error
    saved = tracker_yaml(data_dir)
    assert saved["kind"] == "jira" and saved["base_url"] == "https://jira.example.org"
    assert saved["query"] == "project = ABC"
    assert saved["fields"]["estimate"] == "Story Points"
    assert saved["fields"]["epic"] == "Epic Link"  # untouched
    assert saved["refined_label"] == "Refined"
    assert not any(ENV in k for k in saved)


def test_an_unusable_address_is_refused(data_dir: Path, monkeypatch):
    enable(data_dir)
    at = page(data_dir, monkeypatch)
    at.selectbox(key="jira-demo-kind").select("jira")
    at.text_input(key="jira-demo-url").set_value("https://user:secret@jira.example.org")
    button(at, "Save").click().run()
    assert any("credentials" in e.value for e in at.error)
    assert tracker_yaml(data_dir)["kind"] == "csv"


def test_connection_test_offers_fields_and_saves_the_choice(data_dir: Path, monkeypatch):
    enable(data_dir)
    calls: list[TrackerSettings] = []

    def fake(tracker: TrackerSettings) -> Probe:
        calls.append(tracker)
        return Probe(
            host="jira.example.org", account="Ada", suggestions=SUGGESTIONS, tickets=42,
            warnings=[],
        )  # fmt: skip

    monkeypatch.setattr(jira_setup, "run_probe", fake)
    monkeypatch.setattr(jira_setup, "token_source", lambda base_url=None: "env")
    at = page(data_dir, monkeypatch)
    at.text_input(key="jira-demo-url").set_value("https://jira.example.org")
    at.text_area(key="jira-demo-query").set_value("project = ABC")
    button(at, "Test connection").click().run()
    assert not at.exception, at.exception
    assert calls and calls[0].base_url == "https://jira.example.org"
    shown = texts(at)
    assert "Ada" in shown and "42" in shown
    [estimate] = [s for s in at.selectbox if s.label.startswith("Estimate")]
    assert "suggestion" in estimate.options[1] and "suggestion" not in estimate.options[2]
    # the saved epic name stays the current setting although it is a candidate by name
    epic = next(s for s in at.selectbox if s.label == "Epic")
    assert epic.value == "Epic Link"
    estimate.select("customfield_10100")
    button(at, "Save").click().run()
    assert not at.error, at.error
    saved = tracker_yaml(data_dir)
    assert saved["fields"]["estimate"] == "customfield_10100"
    assert saved["base_url"] == "https://jira.example.org"


def test_connection_error_is_shown_without_the_token(data_dir: Path, monkeypatch):
    enable(data_dir)
    monkeypatch.setenv(ENV, CANARY)
    monkeypatch.setattr(jira_setup, "token_source", lambda base_url=None: "env")

    def failing(tracker: TrackerSettings) -> Probe:
        return Probe(error=str(SourceError("Jira rejects the token (401)")))

    monkeypatch.setattr(jira_setup, "run_probe", failing)
    at = page(data_dir, monkeypatch)
    at.text_input(key="jira-demo-url").set_value("https://jira.example.org")
    button(at, "Test connection").click().run()
    assert any("401" in e.value for e in at.error)
    assert CANARY not in texts(at) and CANARY not in str([e.value for e in at.get("text_input")])
    assert "environment variable" in texts(at)  # found in the environment: reported, not shown
