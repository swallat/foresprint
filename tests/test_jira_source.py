# SPDX-License-Identifier: EUPL-1.2
"""Jira Data Center as ticket source: mapping, paging, field resolution, error mapping, token
handling and the guarantee that the module only reads. No test touches the network: every
request goes to an ``httpx.MockTransport`` with recorded-style answers from tests/data/jira."""

import ast
import json
import logging
import re
import subprocess
import sys
import traceback
import types
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from sprintforecast import sources
from sprintforecast.model import TrackerFields, TrackerSettings
from sprintforecast.sources import SourceError
from sprintforecast.sources import jira as jira_module
from sprintforecast.sources.jira import (
    JiraSource,
    choose_sprint,
    jira_token,
    parse_sprint,
    store_token,
)

DATA = Path(__file__).parent / "data" / "jira"
CANARY = "tok-CANARY-9f8e7d6c5b4a3f2e"
BASE = "https://jira.example.org"
SRC = Path(jira_module.__file__)

Handler = Callable[[httpx.Request], httpx.Response]


def fixture(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def settings(**overrides) -> TrackerSettings:
    values = {
        "kind": "jira",
        "base_url": BASE,
        "query": "project = ABC ORDER BY Rank",
        "fields": TrackerFields(estimate="Story Points", remaining="Remaining", epic="Epic Link"),
    }
    values.update(overrides)
    return TrackerSettings(**values)


class Server:
    """Answers like Jira from the recorded fixtures and records every request. Fails the test on
    any method but GET (the transport is the second line of defence next to the module)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.pages = [fixture("search_page1.json"), fixture("search_page2.json")]
        self.fields = fixture("fields.json")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", f"{request.method} {request.url.path} is not a read"
        self.requests.append(request)
        path = request.url.path.removeprefix("/jira")  # context path of one test
        if path == "/rest/api/2/myself":
            return httpx.Response(200, json=fixture("myself.json"))
        if path == "/rest/api/2/field":
            return httpx.Response(200, json=self.fields)
        if path == "/rest/api/2/search":
            start = int(request.url.params["startAt"])
            for page in self.pages:
                if page["startAt"] == start:
                    return httpx.Response(200, json=page)
            return httpx.Response(200, json={**self.pages[-1], "startAt": start, "issues": []})
        return httpx.Response(404, json={"message": "no such resource"})

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def searches(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/rest/api/2/search"]


def make(handler: Handler | None = None, **overrides) -> tuple[JiraSource, Handler]:
    handler = handler or Server()
    return JiraSource(settings(**overrides), CANARY, httpx.MockTransport(handler)), handler


def fixed(response: httpx.Response | Exception) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if isinstance(response, Exception):
            raise response
        return response

    return handler


def on_search(response: httpx.Response | Exception) -> Handler:
    """Jira answers the field list normally and the search with this response."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/rest/api/2/field":
            return httpx.Response(200, json=fixture("fields.json"))
        if isinstance(response, Exception):
            raise response
        return response

    return handler


# --- Connection and field resolution ---------------------------------------------------------


def test_test_connection_returns_only_the_display_name():
    source, server = make()
    assert source.test_connection() == "Anna Beispiel"
    request = server.requests[0]
    assert request.url == f"{BASE}/rest/api/2/myself"
    assert request.headers["Authorization"] == f"Bearer {CANARY}"
    assert request.headers["User-Agent"].startswith("sprintforecast/")
    assert request.headers["Accept"] == "application/json"


def test_base_url_with_context_path_and_trailing_slash():
    source, server = make(base_url="https://jira.example.org/jira/")
    source.test_connection()
    assert str(server.requests[0].url) == "https://jira.example.org/jira/rest/api/2/myself"


def test_fields_are_resolved_by_name_and_by_schema():
    source, _ = make()
    fields = source.resolve_fields()
    assert (fields.estimate, fields.remaining, fields.epic) == (
        "customfield_10016",
        "customfield_10017",
        "customfield_10014",
    )
    # sprint, rank and epic link are found by their schema (the rank field is called "Rang")
    assert fields.sprint == ("customfield_10020",)
    assert fields.rank == ("customfield_10019",)
    assert fields.epic_link == ("customfield_10014",)


def test_field_names_ignore_case_and_ids_are_accepted():
    source, _ = make(
        fields=TrackerFields(estimate="story points", remaining="customfield_10017", epic=None)
    )
    fields = source.resolve_fields()
    assert fields.estimate == "customfield_10016" and fields.remaining == "customfield_10017"
    assert fields.epic is None


def test_resolution_is_requested_once():
    source, server = make()
    source.resolve_fields()
    source.resolve_fields()
    assert server.paths() == ["/rest/api/2/field"]


def test_unknown_field_names_the_setting_and_similar_fields():
    source, _ = make(fields=TrackerFields(estimate="Story Point"))
    with pytest.raises(SourceError) as e:
        source.resolve_fields()
    text = str(e.value)
    assert "„Story Point“" in text and "tracker.fields.estimate" in text
    assert "Story Points" in text  # the similar name


def test_ambiguous_field_names_all_candidates():
    source, _ = make(fields=TrackerFields(estimate="Business Value"))
    with pytest.raises(SourceError) as e:
        source.resolve_fields()
    text = str(e.value)
    assert "mehrdeutig" in text
    assert "customfield_10100" in text and "customfield_10101" in text
    # the way out works: the id instead of the name
    source, _ = make(fields=TrackerFields(estimate="customfield_10101"))
    assert source.resolve_fields().estimate == "customfield_10101"


def test_epic_field_parent_is_the_system_field():
    source, _ = make(fields=TrackerFields(estimate="Story Points", epic="Parent"))
    assert source.resolve_fields().epic == "parent"


# --- Fetch: mapping --------------------------------------------------------------------------


def tickets_by_key(source: JiraSource) -> dict:
    return {tk.key: tk for tk in source.fetch()}


def test_fetch_reads_all_pages_and_maps_the_tickets():
    source, server = make()
    found = tickets_by_key(source)
    assert list(found) == ["ABC-1", "ABC-2", "ABC-3", "ABC-4", "ABC-5"]
    # Jira returned 3 issues although 100 were asked for: the second request starts after them
    assert [r.url.params["startAt"] for r in server.searches()] == ["0", "3"]
    assert all(r.url.params["maxResults"] == "100" for r in server.searches())
    assert server.paths() == ["/rest/api/2/field", "/rest/api/2/search", "/rest/api/2/search"]

    one = found["ABC-1"]
    assert one.title == "Checkout form"  # whitespace collapsed
    assert (one.status, one.issue_type) == ("In Progress", "Story")
    assert (one.estimate, one.remaining) == (5.0, 3.0)
    assert one.labels == ["Refined", "payment"] and one.components == ["Checkout", "Frontend"]
    assert one.epic == "ABC-100" and one.rank == "0|i0001:"
    assert one.resolved is False
    # only the inward side of the configured link type ("is blocked by")
    assert one.blocked_by == ["ABC-3"]
    assert found["ABC-4"].blocked_by == ["ABC-1"]


def test_fetch_maps_epic_estimates_resolution_and_sprints():
    found = tickets_by_key(make()[0])
    # no epic link, but the parent is an Epic: the parent is the epic
    assert found["ABC-2"].epic == "ABC-100" and found["ABC-2"].estimate is None
    assert found["ABC-2"].remaining is None and found["ABC-2"].sprint_name is None
    # a Story as parent is no epic
    assert found["ABC-4"].epic is None
    assert found["ABC-3"].resolved is True and found["ABC-3"].remaining == 0.0
    assert found["ABC-3"].epic == "ABC-200"
    # toString format with commas and brackets in the name: the active sprint wins
    assert found["ABC-1"].sprint_name == "Sprint 21, Team A [Phase 1]"
    # object format: the first future sprint
    assert found["ABC-4"].sprint_name == "Sprint 22"
    # only a closed sprint: the last one listed
    assert found["ABC-5"].sprint_name == "Sprint 19"


def test_search_asks_only_for_the_needed_fields_with_the_jql():
    source, server = make()
    source.fetch()
    request = server.searches()[0]
    assert request.url.params["jql"] == "project = ABC ORDER BY Rank"
    asked = set(request.url.params["fields"].split(","))
    assert asked == {
        "summary",
        "status",
        "issuetype",
        "priority",
        "labels",
        "components",
        "resolution",
        "issuelinks",
        "parent",
        "customfield_10016",  # estimate
        "customfield_10017",  # remaining
        "customfield_10014",  # epic link
        "customfield_10020",  # sprint
        "customfield_10019",  # rank
    }
    assert "*all" not in asked and "description" not in asked


def test_link_type_is_configurable():
    found = tickets_by_key(make(link_type="Relates")[0])
    assert found["ABC-1"].blocked_by == ["ABC-9"]


def test_parent_as_epic_field_takes_the_parent_of_any_type():
    found = tickets_by_key(make(fields=TrackerFields(estimate="Story Points", epic="Parent"))[0])
    assert found["ABC-2"].epic == "ABC-100"
    assert found["ABC-4"].epic == "ABC-1"  # configured: the parent counts whatever its type


def test_without_epic_setting_the_epic_link_field_is_found_by_schema():
    found = tickets_by_key(make(fields=TrackerFields(estimate="Story Points"))[0])
    assert found["ABC-1"].epic == "ABC-100" and found["ABC-3"].epic == "ABC-200"


def test_more_than_one_page_of_one_hundred(monkeypatch: pytest.MonkeyPatch):
    seen: list[tuple[int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/rest/api/2/field":
            return httpx.Response(200, json=fixture("fields.json"))
        start, size = int(request.url.params["startAt"]), int(request.url.params["maxResults"])
        seen.append((start, size))
        issues = [
            {"key": f"ABC-{n}", "fields": {"summary": f"t{n}", "customfield_10016": n}}
            for n in range(start, min(start + size, 250))
        ]
        return httpx.Response(
            200, json={"startAt": start, "maxResults": size, "total": 250, "issues": issues}
        )

    source, _ = make(handler)
    found = source.fetch()
    assert [tk.key for tk in found] == [f"ABC-{n}" for n in range(250)]
    assert seen == [(0, 100), (100, 100), (200, 100)]
    assert found[7].estimate == 7.0


def test_an_issue_that_moves_between_pages_is_an_error_not_a_short_result():
    """One ticket read twice means another one was missed: nothing may be written."""
    server = Server()
    server.pages[1]["issues"].insert(0, server.pages[0]["issues"][-1])  # ABC-3 again
    server.pages[1]["total"] = server.pages[0]["total"] = 6
    with pytest.raises(SourceError, match="erneut versuchen"):
        make(server)[0].fetch()


def test_a_changing_total_is_an_error():
    server = Server()
    server.pages[1]["total"] = 4
    with pytest.raises(SourceError, match="geändert"):
        make(server)[0].fetch()


def test_an_empty_page_before_the_total_is_an_error():
    server = Server()
    server.pages[1]["issues"] = []
    with pytest.raises(SourceError, match="geändert"):
        make(server)[0].fetch()


def test_fewer_issues_than_the_total_at_the_end_is_an_error():
    server = Server()
    server.pages[0]["total"] = server.pages[1]["total"] = 7
    with pytest.raises(SourceError, match="geändert"):
        make(server)[0].fetch()


def test_a_server_that_ignores_start_at_does_not_loop_forever():
    page = fixture("search_page1.json")
    page["total"] = 9
    source, _ = make(on_search(httpx.Response(200, json=page)))
    with pytest.raises(SourceError, match="geändert"):
        source.fetch()


def test_empty_result_is_valid():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/2/field":
            return httpx.Response(200, json=fixture("fields.json"))
        return httpx.Response(200, json={"startAt": 0, "maxResults": 100, "total": 0, "issues": []})

    assert make(handler)[0].fetch() == []


def test_fetch_needs_a_query():
    source, server = make(query=None)
    with pytest.raises(SourceError, match=r"tracker\.query"):
        source.fetch()
    assert server.requests == []


@pytest.mark.parametrize("value", ["abc", -1, True, "inf"])
def test_an_invalid_estimate_names_ticket_and_field_but_not_the_value(value):
    server = Server()
    server.pages[0]["issues"][0]["fields"]["customfield_10016"] = value
    with pytest.raises(SourceError) as e:
        make(server)[0].fetch()
    assert "ABC-1" in str(e.value) and "Story Points" in str(e.value)
    assert str(value) not in str(e.value).replace("ABC-1", "")


def test_numbers_may_arrive_as_text_or_select_option():
    server = Server()
    server.pages[0]["issues"][0]["fields"]["customfield_10016"] = "8"
    server.pages[0]["issues"][0]["fields"]["customfield_10017"] = {"value": "2.5"}
    found = {tk.key: tk for tk in make(server)[0].fetch()}
    assert (found["ABC-1"].estimate, found["ABC-1"].remaining) == (8.0, 2.5)


# --- Sprint field ----------------------------------------------------------------------------


def toString(id, state, name, tail="goal=<null>,startDate=2026-10-01T08:00:00.000Z"):
    return (
        f"com.atlassian.greenhopper.service.sprint.Sprint@1a{id:02x}"
        f"[id={id},rapidViewId=3,state={state},name={name},{tail},sequence={id}]"
    )


@pytest.mark.parametrize(
    ("value", "name", "state"),
    [
        (toString(12, "CLOSED", "Sprint 21"), "Sprint 21", "CLOSED"),
        (
            toString(12, "ACTIVE", "Sprint 21, Team A [Phase 1]"),
            "Sprint 21, Team A [Phase 1]",
            "ACTIVE",
        ),
        (toString(12, "FUTURE", "Sprint [x]"), "Sprint [x]", "FUTURE"),
        # a goal with commas and even the word "name=" does not confuse the name
        (
            toString(12, "ACTIVE", "S1", tail="goal=Ship it, name is open,startDate=<null>"),
            "S1",
            "ACTIVE",
        ),
        ({"id": 5, "name": " Sprint 5 ", "state": "active"}, "Sprint 5", "ACTIVE"),
        ({"name": "No state"}, "No state", ""),
    ],
)
def test_parse_sprint(value, name, state):
    parsed = parse_sprint(value)
    assert parsed is not None
    assert (parsed.name, parsed.state) == (name, state)


@pytest.mark.parametrize(
    "value",
    [
        None,
        5,
        "",
        "garbage",
        "Sprint@1[id=1,name=<null>]",
        "x[state=ACTIVE]",
        {"id": 1},
        {"name": ""},
    ],
)
def test_parse_sprint_ignores_what_it_does_not_understand(value):
    assert parse_sprint(value) is None


def test_choose_sprint_prefers_active_then_first_future_then_last():
    closed1 = toString(1, "CLOSED", "S1")
    closed2 = toString(2, "CLOSED", "S2")
    active = toString(3, "ACTIVE", "S3")
    future1 = toString(4, "FUTURE", "S4")
    future2 = toString(5, "FUTURE", "S5")
    assert choose_sprint([closed1, future1, active, future2]) == "S3"
    assert choose_sprint([closed1, future1, future2]) == "S4"
    assert choose_sprint([closed1, closed2]) == "S2"
    assert (
        choose_sprint([{"name": "A", "state": "closed"}, {"name": "B", "state": "active"}]) == "B"
    )
    assert choose_sprint([]) is None and choose_sprint(None) is None
    assert choose_sprint(["garbage"]) is None
    assert choose_sprint(closed1) == "S1"  # a single value instead of a list


# --- Errors ----------------------------------------------------------------------------------


def error_cases() -> list:
    ssl_error = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    import ssl

    ssl_error.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed")
    return [
        (
            httpx.Response(401, json={"message": f"Bearer {CANARY} is wrong"}),
            "ungültig oder abgelaufen",
        ),
        (httpx.Response(403, text=f"forbidden for {CANARY}"), "verweigert"),
        (httpx.Response(404, text="<html>SECRET-TICKET-DATA</html>"), "nicht gefunden"),
        (httpx.Response(429, text="slow down"), "zu viele Anfragen"),
        (httpx.Response(500, text="SECRET-TICKET-DATA"), "Serverfehler (500)"),
        (httpx.Response(418, text="SECRET-TICKET-DATA"), "HTTP 418"),
        (
            httpx.Response(302, headers={"Location": "https://sso.example.org/login?next=SECRET"}),
            "leitet um (sso.example.org)",
        ),
        (httpx.Response(200, text="<html>SECRET-TICKET-DATA login</html>"), "nicht mit JSON"),
        (ssl_error, "TLS-Prüfung"),
        (httpx.ConnectError("[Errno -2] Name or service not known"), "nicht erreichbar"),
        (httpx.ReadTimeout("timed out"), "Keine Antwort"),
        (httpx.ConnectTimeout("timed out"), "Keine Antwort"),
        (httpx.ProxyError("proxy refused"), "fehlgeschlagen"),
        (httpx.LocalProtocolError(f"Illegal header value b'Bearer {CANARY}'"), "fehlgeschlagen"),
        (httpx.UnsupportedProtocol("no scheme"), "ungültig"),
    ]


@pytest.mark.parametrize(("response", "expected"), error_cases())
def test_errors_are_understandable_and_leak_nothing(
    response, expected, caplog: pytest.LogCaptureFixture
):
    source, _ = make(fixed(response))
    with caplog.at_level(logging.DEBUG), pytest.raises(SourceError) as e:
        source.test_connection()
    error = e.value
    assert expected in str(error)
    shown = "\n".join(
        [
            str(error),
            repr(error),
            repr(source),
            str(source),
            caplog.text,
            *traceback.format_exception(error),
        ]
    )
    assert CANARY not in shown
    assert "SECRET" not in shown
    assert error.__cause__ is None  # the transport error (and what it carries) is dropped


def test_tls_hint_says_the_check_stays_on_and_names_the_ca_variable():
    import ssl

    error = httpx.ConnectError("boom")
    error.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed")
    with pytest.raises(SourceError) as e:
        make(fixed(error))[0].test_connection()
    assert "nie abgeschaltet" in str(e.value) and "SSL_CERT_FILE" in str(e.value)


def test_400_shows_only_the_error_messages():
    body = {
        "errorMessages": [
            "Error in the JQL Query: The field 'projekt' does not exist.",
            "A second message",
        ],
        "errors": {"customfield_1": "SECRET-TICKET-DATA"},
        "issues": [{"key": "SECRET-1"}],
    }
    source, _ = make(on_search(httpx.Response(400, json=body)))
    with pytest.raises(SourceError) as e:
        source.fetch()
    text = str(e.value)
    assert "Error in the JQL Query: The field 'projekt' does not exist. A second message" in text
    assert "SECRET" not in text and "customfield_1" not in text


def test_400_message_is_cut_at_300_characters():
    body = {"errorMessages": ["x" * 1000]}
    with pytest.raises(SourceError) as e:
        make(on_search(httpx.Response(400, json=body)))[0].fetch()
    detail = str(e.value).split("(400): ", 1)[1]
    assert len(detail) == 300 and detail.endswith("…")


def test_400_without_messages_still_points_at_the_jql():
    with pytest.raises(SourceError, match=r"tracker\.query"):
        make(on_search(httpx.Response(400, text="<html>SECRET</html>")))[0].fetch()


def test_fixture_jql_error_is_shown():
    with pytest.raises(SourceError, match="field 'projekt' does not exist"):
        make(on_search(httpx.Response(400, json=fixture("error_jql.json"))))[0].fetch()


@pytest.mark.parametrize("call", ["test_connection", "resolve_fields"])
def test_a_400_on_myself_or_field_is_not_reported_as_a_jql_problem(call):
    response = httpx.Response(400, json={"errorMessages": ["Something about the JQL query"]})
    with pytest.raises(SourceError) as e:
        getattr(make(fixed(response))[0], call)()
    assert "JQL" not in str(e.value) and "tracker.query" not in str(e.value)
    assert "(400)" in str(e.value) and "base_url" in str(e.value)


def test_429_names_the_wait_when_jira_says_so():
    with pytest.raises(SourceError, match="in 120 Sekunden"):
        make(fixed(httpx.Response(429, headers={"Retry-After": "120"})))[0].test_connection()
    for header in ({}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, {"Retry-After": "-5"}):
        with pytest.raises(SourceError, match="später erneut"):
            make(fixed(httpx.Response(429, headers=header)))[0].test_connection()


def test_407_says_the_proxy_needs_authentication():
    with pytest.raises(SourceError) as e:
        make(fixed(httpx.Response(407)))[0].test_connection()
    assert "Proxy" in str(e.value) and "407" in str(e.value) and "Unerwartete" not in str(e.value)


@pytest.mark.parametrize("body", [[], {"x": 1}, "text", 5])
def test_unexpected_shape_of_myself(body):
    with pytest.raises(SourceError, match="erwartete Format"):
        make(fixed(httpx.Response(200, json=body)))[0].test_connection()


@pytest.mark.parametrize(
    "page",
    [
        [],
        {"issues": "no list", "total": 1},
        {"issues": [], "total": "many"},
        {"issues": [], "total": True},
        {"issues": [5], "total": 1},
        {"issues": [{"key": "A-1"}], "total": 1},
        {"issues": [{"fields": {}}], "total": 1},
    ],
)
def test_unexpected_shape_of_search(page):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/2/field":
            return httpx.Response(200, json=fixture("fields.json"))
        return httpx.Response(200, json=page)

    with pytest.raises(SourceError, match="erwartete Format"):
        make(handler)[0].fetch()


@pytest.mark.parametrize("fields", [{}, [1, 2], "x"])
def test_unexpected_shape_of_fields(fields):
    with pytest.raises(SourceError, match="erwartete Format"):
        make(fixed(httpx.Response(200, json=fields)))[0].resolve_fields()


def test_english_error_texts(english):
    with pytest.raises(SourceError) as e:
        make(fixed(httpx.Response(401)))[0].test_connection()
    assert "rejects the token" in str(e.value)


def test_invalid_base_url():
    for base in (None, "", "jira.example.org", "ftp://jira.example.org", "https://"):
        with pytest.raises(SourceError, match="base_url"):
            JiraSource(settings(base_url=base), CANARY, httpx.MockTransport(Server()))


# --- Token never leaks -----------------------------------------------------------------------


def test_the_token_does_not_show_in_repr_str_vars_or_logs(caplog: pytest.LogCaptureFixture):
    source, _ = make()
    with caplog.at_level(logging.DEBUG):
        source.test_connection()
        source.fetch()
    for text in (repr(source), str(source), repr(source._token), str(source._token), caplog.text):
        assert CANARY not in text
    assert CANARY not in repr(vars(source))


@pytest.mark.parametrize(
    "token", ["", " ", "two words", "line\nbreak", "tab\t", "ümlaut", "a" * 3 + "\x00"]
)
def test_a_malformed_token_is_refused_without_being_shown(token):
    with pytest.raises(SourceError) as e:
        JiraSource(settings(), token, httpx.MockTransport(Server()))
    assert token.strip() not in str(e.value) or not token.strip()
    assert "Token" in str(e.value)


# --- Reading only ----------------------------------------------------------------------------


def test_the_module_contains_no_other_http_verb():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    verbs = {"post", "put", "delete", "patch", "head", "options", "trace", "connect"}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attributes & verbs, attributes & verbs
    strings = {
        n.value.upper()
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    # step 5 adds exactly one write: the PUT that changes planned_for_* labels
    others = {v.upper() for v in verbs} - {"PUT"}
    assert not strings & others, strings & others
    assert {"GET", "PUT"} == jira_module.ALLOWED_METHODS
    text = SRC.read_text(encoding="utf-8")
    assert not re.search(r"\.(post|put|delete|patch)\(", text)
    puts = [m for m in re.findall(r"\"PUT\"", text)]
    assert len(puts) == 5, "a new use of PUT needs a look at the guard in _request"


def test_exactly_one_function_performs_http():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    network = {"request", "send", "stream", "Client"}
    calls: dict[str, list[str]] = {}
    for function in ast.walk(tree):
        if isinstance(function, ast.FunctionDef):
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in network
                ):
                    calls.setdefault(function.name, []).append(node.func.attr)
    # the client is built in one place and used in one place; nothing else touches the network
    assert calls == {"_new_client": ["Client"], "_request": ["request"]}, calls


@pytest.mark.parametrize("method", ["POST", "DELETE", "PATCH", "HEAD", "get", "put", "OPTIONS"])
def test_a_request_with_another_method_is_refused_before_the_network(method):
    source, server = make()
    with pytest.raises(ValueError, match="not allowed"):
        source._request(method, "/rest/api/2/issue/ABC-1")
    assert server.requests == []


LABEL = {"update": {"labels": [{"add": "planned_for_2026.22"}]}}


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/rest/api/2/issue/ABC-1", None),  # PUT without body
        ("/rest/api/2/issue/ABC-1", {}),
        ("/rest/api/2/issue/ABC-1", {"fields": {"summary": "x"}}),  # not labels
        ("/rest/api/2/issue/ABC-1", {"update": {"summary": [{"set": "x"}]}}),
        ("/rest/api/2/issue/ABC-1", {"update": {"labels": [{"set": ["x"]}]}}),
        ("/rest/api/2/issue/ABC-1", {"update": {"labels": [{"add": "Refined"}]}}),  # foreign label
        ("/rest/api/2/issue/ABC-1", {"update": {"labels": [{"add": "planned_for_"}]}}),
        ("/rest/api/2/issue/ABC-1", {"update": {"labels": [{"add": "planned_for_a b"}]}}),
        ("/rest/api/2/issue/ABC-1", {"update": {"labels": []}}),
        ("/rest/api/2/issue/ABC-1", {**LABEL, "fields": {"summary": "x"}}),
        ("/rest/api/2/issue/ABC-1/comment", LABEL),
        ("/rest/api/2/issue/ABC-1?x=1", LABEL),
        ("/rest/api/2/issue/../project", LABEL),
        ("/rest/api/2/issue", LABEL),
        ("/rest/api/2/myself", LABEL),
    ],
)
def test_a_put_that_is_not_a_label_change_is_refused_before_the_network(path, body):
    source, server = make()
    with pytest.raises(ValueError, match="label change"):
        source._request("PUT", path, body=body)
    assert server.requests == []


def test_a_put_with_query_parameters_is_refused():
    source, server = make()
    with pytest.raises(ValueError, match="label change"):
        source._request("PUT", "/rest/api/2/issue/ABC-1", {"notifyUsers": "false"}, LABEL)
    assert server.requests == []


def test_a_get_with_a_body_is_refused():
    source, server = make()
    with pytest.raises(ValueError, match="label change"):
        source._request("GET", "/rest/api/2/myself", body=LABEL)
    assert server.requests == []


def label_server(response: httpx.Response | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response or httpx.Response(204)

    return handler, seen


def test_set_labels_sends_one_update_put_with_only_the_named_labels():
    handler, seen = label_server()
    source, _ = make(handler)
    source.set_labels("ABC-7", ["planned_for_2026.23"], ["planned_for_2026.22"])
    (request,) = seen
    assert (request.method, request.url.path) == ("PUT", "/rest/api/2/issue/ABC-7")
    assert json.loads(request.content) == {
        "update": {"labels": [{"remove": "planned_for_2026.22"}, {"add": "planned_for_2026.23"}]}
    }
    assert request.headers["authorization"] == f"Bearer {CANARY}"


@pytest.mark.parametrize(
    ("status", "text"),
    [(403, "Labels ändern"), (404, "existiert nicht"), (401, "Token"), (500, "Serverfehler")],
)
def test_a_failed_label_write_is_an_understandable_message(status, text):
    handler, _ = label_server(httpx.Response(status, json={"errorMessages": [CANARY]}))
    source, _ = make(handler)
    with pytest.raises(SourceError) as e:
        source.set_labels("ABC-7", ["planned_for_2026.23"], [])
    assert text in str(e.value) and CANARY not in str(e.value)


def test_every_read_operation_only_sends_get():
    source, server = make()
    source.test_connection()
    source.resolve_fields()
    source.fetch()
    assert {r.method for r in server.requests} == {"GET"}


def test_tls_is_verified_with_a_timeout_and_proxies_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    created: list[dict] = []
    real = httpx.Client

    def spy(*args, **kwargs):
        created.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", spy)
    source, _ = make()
    source.test_connection()
    source.fetch()
    assert len(created) == 1  # one client for all requests of the source
    kwargs = created[0]
    assert "verify" not in kwargs and "trust_env" not in kwargs  # httpx defaults: verify, env
    assert kwargs["timeout"] == 30.0
    assert kwargs["follow_redirects"] is False
    text = SRC.read_text(encoding="utf-8")
    assert "verify=" not in text and "trust_env" not in text and "SSLContext" not in text


def test_close_and_context_manager():
    server = Server()
    with JiraSource(settings(), CANARY, httpx.MockTransport(server)) as source:
        source.test_connection()
        client = source._client
    assert client is not None and client.is_closed and source._client is None


# --- Token lookup ----------------------------------------------------------------------------


class FakeKeyring(types.ModuleType):
    def __init__(self, stored: dict | None = None, fail: bool = False) -> None:
        super().__init__("keyring")
        self.stored = dict(stored or {})
        self.fail = fail
        self.calls: list[tuple] = []

    def get_password(self, service: str, user: str):
        self.calls.append(("get", service, user))
        if self.fail:
            raise RuntimeError(f"backend broke while reading {CANARY}")
        return self.stored.get((service, user))

    def set_password(self, service: str, user: str, password: str) -> None:
        self.calls.append(("set", service, user))
        if self.fail:
            raise RuntimeError(f"backend broke while storing {password}")
        self.stored[(service, user)] = password


@pytest.fixture(autouse=True)
def clean_token_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(jira_module.TOKEN_ENV, raising=False)


def test_token_environment_variable_comes_first(monkeypatch: pytest.MonkeyPatch):
    fake = FakeKeyring({("sprintforecast-jira", "jira.example.org"): "from-keychain"})
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setenv(jira_module.TOKEN_ENV, "  from-env \n")
    assert jira_token(BASE) == "from-env"
    assert fake.calls == []  # the keychain is not even asked


def test_token_from_the_keychain_by_host(monkeypatch: pytest.MonkeyPatch):
    fake = FakeKeyring({("sprintforecast-jira", "jira.example.org"): "from-keychain"})
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert jira_token("https://Jira.Example.org:8443/jira") == "from-keychain"
    assert fake.calls == [("get", "sprintforecast-jira", "jira.example.org")]
    assert jira_token("https://other.example.org") is None


def test_empty_environment_variable_falls_through_to_the_keychain(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        FakeKeyring({("sprintforecast-jira", "jira.example.org"): "from-keychain"}),
    )
    monkeypatch.setenv(jira_module.TOKEN_ENV, "   ")
    assert jira_token(BASE) == "from-keychain"


def test_no_token_without_keyring_or_with_a_broken_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # not installed
    assert jira_token(BASE) is None
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring(fail=True))
    assert jira_token(BASE) is None  # the backend error is swallowed, not shown


def test_store_token_writes_to_the_keychain(monkeypatch: pytest.MonkeyPatch):
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    store_token("https://jira.example.org/jira", CANARY)
    assert fake.stored == {("sprintforecast-jira", "jira.example.org"): CANARY}
    assert jira_token(BASE) == CANARY


def test_store_token_errors_do_not_show_the_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(SourceError, match="keyring") as e:
        store_token(BASE, CANARY)
    assert CANARY not in str(e.value) and jira_module.TOKEN_ENV in str(e.value)
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring(fail=True))
    with pytest.raises(SourceError) as e:
        store_token(BASE, CANARY)
    assert CANARY not in str(e.value) and CANARY not in "".join(traceback.format_exception(e.value))
    with pytest.raises(SourceError) as e:
        store_token(BASE, "has space")
    assert "has space" not in str(e.value)


# --- open_source -----------------------------------------------------------------------------


def test_open_source_by_kind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    csv = tmp_path / "x.csv"
    # a file always means CSV (the offline fallback), also with kind jira
    assert sources.open_source(settings(), csv).kind == "csv"
    assert sources.open_source(TrackerSettings(kind="csv"), csv).kind == "csv"
    with pytest.raises(SourceError, match="--import"):
        sources.open_source(TrackerSettings(kind="csv"))
    with pytest.raises(SourceError, match="Unbekannte"):
        sources.open_source(TrackerSettings(kind="github"))
    with pytest.raises(SourceError, match=jira_module.TOKEN_ENV):
        sources.open_source(settings())
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setenv(jira_module.TOKEN_ENV, CANARY)
    source = sources.open_source(settings())
    assert isinstance(source, JiraSource) and source.kind == "jira"
    assert source.name == "jira jira.example.org"
    assert sources.open_source(settings(), token="given").kind == "jira"


def test_missing_httpx_names_the_extra(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "httpx", None)
    with pytest.raises(SourceError) as e:
        JiraSource(settings(), CANARY)
    text = str(e.value)
    assert "Extra [jira]" in text and "sprintforecast[web,excel,jira]" in text
    assert CANARY not in text


# --- The core does not need httpx ------------------------------------------------------------


def run_python(code: str, *args: str) -> str:
    out = subprocess.run(
        [sys.executable, "-c", code, *args], capture_output=True, text=True, check=True
    )
    return out.stdout + out.stderr


def test_importing_the_sources_loads_neither_httpx_nor_keyring():
    code = (
        "import sys\n"
        "import sprintforecast.sources, sprintforecast.sources.csv, sprintforecast.ticket_import\n"
        "import sprintforecast.sources.jira\n"
        "bad = [m for m in ('httpx', 'keyring') if m in sys.modules]\n"
        "print('LOADED', bad)\n"
    )
    assert "LOADED []" in run_python(code)


def test_csv_import_works_without_httpx(data_dir: Path):
    """httpx is not importable at all: the CSV path (and a Jira team's offline fallback) works."""
    code = (
        "import sys\n"
        "sys.modules['httpx'] = None\n"
        "from typer.testing import CliRunner\n"
        "from sprintforecast.cli import app\n"
        "csv = sys.argv[2]\n"
        "r = CliRunner().invoke(app, ['--data', sys.argv[1], '--as-of', '2026-10-15', "
        "'tickets', 'demo', '--import', csv])\n"
        "print('EXIT', r.exit_code)\n"
        "print(r.output)\n"
    )
    import yaml

    team = data_dir / "demo"
    doc = yaml.safe_load((team / "team.yaml").read_text(encoding="utf-8"))
    doc["features"]["tickets"] = True
    doc["tracker"] = {
        "kind": "jira",
        "base_url": BASE,
        "query": "project = ABC",
        "fields": {"estimate": "Story Points", "remaining": "Remaining", "epic": "Epic Link"},
    }
    (team / "team.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    out = run_python(code, str(data_dir), str(DATA.parent / "jira_en.csv"))
    assert "EXIT 0" in out, out
    assert "ABC-1" in out


# --- Review fixes ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://anna:s3cret@jira.example.org", "Zugangsdaten"),
        ("https://anna@jira.example.org", "Zugangsdaten"),
        ("https://:s3cret@jira.example.org", "Zugangsdaten"),
        ("https://jira.example.org/jira?token=s3cret", "Parameter"),
        ("https://jira.example.org/jira#s3cret", "Fragment"),
        ("https://[jira.example.org/jira", "http- oder https-Adresse"),
        ("https://jira.example.org:notaport", "http- oder https-Adresse"),
    ],
)
def test_a_base_url_with_credentials_query_or_fragment_is_refused_without_echo(url, expected):
    with pytest.raises(SourceError) as e:
        JiraSource(settings(base_url=url), CANARY, httpx.MockTransport(Server()))
    assert expected in str(e.value)
    assert "s3cret" not in str(e.value) and "s3cret" not in repr(e.value)


def test_keychain_user_survives_a_malformed_address():
    for url in ("https://[jira.example.org/jira", "", "no-scheme-at-all"):
        with pytest.raises(SourceError, match="base_url"):
            jira_module.keychain_user(url)
    assert jira_token("https://[jira.example.org/jira") is None  # no crash, just no token


def test_the_install_hints_carry_the_full_address(monkeypatch: pytest.MonkeyPatch):
    """sprintforecast is not on PyPI: a bare `sprintforecast[jira]` does not install."""
    monkeypatch.setitem(sys.modules, "httpx", None)
    with pytest.raises(SourceError) as missing_httpx:
        JiraSource(settings(), CANARY)
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(SourceError) as missing_keyring:
        store_token(BASE, CANARY)
    for error in (missing_httpx.value, missing_keyring.value):
        text = str(error)
        assert '"sprintforecast[web,excel,jira] @ https://' in text
        assert "pip install" not in text and "Installer erneut" in text
    assert jira_module.INSTALL_URL.startswith("https://github.com/swallat/foresprint/")


def test_an_unreadable_ca_bundle_is_a_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No transport: httpx builds its own TLS context from SSL_CERT_FILE and fails right there."""
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-ca.pem"))
    source = JiraSource(settings(), CANARY)
    with pytest.raises(SourceError) as e:
        source.test_connection()
    text = str(e.value)
    assert "SSL_CERT_FILE" in text and "SSL_CERT_DIR" in text and "missing-ca.pem" not in text
    assert e.value.__context__ is None and e.value.__cause__ is None
    bad = tmp_path / "bad.pem"
    bad.write_text("this is no certificate\n", encoding="utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", str(bad))  # an ssl.SSLError (an OSError) while loading
    with pytest.raises(SourceError, match="SSL_CERT_FILE"):
        JiraSource(settings(), CANARY).test_connection()


def test_a_client_that_cannot_be_built_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch):
    import ssl

    for error in (FileNotFoundError("/etc/x.pem"), ssl.SSLError("bad pem"), PermissionError("x")):

        def broken(*args, error=error, **kwargs):
            raise error

        monkeypatch.setattr(httpx, "Client", broken)
        with pytest.raises(SourceError, match="SSL_CERT_FILE"):
            make()[0].test_connection()


@pytest.mark.parametrize(("response", "expected"), error_cases())
def test_no_original_exception_is_reachable_from_the_error(response, expected):
    """The transport error references the request and its headers (the token): it must be neither
    __cause__ nor __context__ of what the caller sees."""
    source, _ = make(fixed(response))
    with pytest.raises(SourceError) as e:
        source.test_connection()
    assert e.value.__cause__ is None and e.value.__context__ is None


def test_store_token_error_hides_the_backend_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring(fail=True))
    with pytest.raises(SourceError) as e:
        store_token(BASE, CANARY)
    assert e.value.__cause__ is None and e.value.__context__ is None


def test_a_body_that_is_no_json_is_not_kept_in_the_error_chain():
    with pytest.raises(SourceError) as e:
        make(fixed(httpx.Response(200, text="<html>SECRET-TICKET-DATA</html>")))[
            0
        ].test_connection()
    assert e.value.__cause__ is None and e.value.__context__ is None


def test_other_tls_errors_do_not_claim_a_certificate_problem():
    import ssl

    handshake = httpx.ConnectError("[SSL: WRONG_VERSION_NUMBER] wrong version number")
    handshake.__cause__ = ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")
    with pytest.raises(SourceError) as e:
        make(fixed(handshake))[0].test_connection()
    text = str(e.value)
    assert "TLS-Verbindungsaufbau" in text and "http statt https" in text
    assert "Zertifikat" not in text and "SSL_CERT_FILE" not in text

    cert = httpx.ConnectError("boom")
    cert.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed")
    with pytest.raises(SourceError, match="Zertifikats"):
        make(fixed(cert))[0].test_connection()


def test_repr_works_when_init_failed_early():
    half_built = JiraSource.__new__(JiraSource)  # what a traceback may hold after a failed init
    assert "JiraSource(" in repr(half_built) and str(half_built) == repr(half_built)


def test_english_texts_of_the_review_fixes(english):
    with pytest.raises(SourceError, match="changed while reading"):
        server = Server()
        server.pages[1]["total"] = 4
        make(server)[0].fetch()
    with pytest.raises(SourceError, match="requires authentication"):
        make(fixed(httpx.Response(407)))[0].test_connection()
    with pytest.raises(SourceError, match="credentials"):
        JiraSource(settings(base_url="https://a:b@x.org"), CANARY, httpx.MockTransport(Server()))


# --- Setup page: field suggestions and query count -------------------------------------------


def test_suggest_fields_orders_number_fields_and_epic_links():
    found = jira_module.suggest_fields(fixture("fields.json"))
    assert found.estimate[0].id == "customfield_10016"
    assert found.estimate[0].score > 0  # "Story Points" hints at an estimate
    assert found.remaining[0].id == "customfield_10017"  # "Remaining" hints at the rest
    assert {c.name for c in found.estimate} == {"Story Points", "Remaining", "Business Value"}
    assert [c.id for c in found.epic] == ["customfield_10014", "parent"]
    # two fields share the name "Business Value": the id goes to team.yaml, the name is unique
    values = {c.id: c.value for c in found.estimate}
    assert values["customfield_10100"] == "customfield_10100"
    assert values["customfield_10016"] == "Story Points"


def test_suggest_fields_ignores_unusable_entries():
    found = jira_module.suggest_fields([{"id": "x"}, {"name": "n", "schema": "oops"}])
    assert found.estimate == found.remaining == found.epic == []


def test_list_fields_and_count_tickets_only_read():
    source, server = make()
    assert any(f["id"] == "customfield_10016" for f in source.list_fields())
    assert source.count_tickets() == 5
    [search] = server.searches()
    assert search.url.params["maxResults"] == "1"
    assert {r.method for r in server.requests} == {"GET"}


def test_count_tickets_needs_a_query():
    source, _ = make(query=None)
    with pytest.raises(SourceError):
        source.count_tickets()


def test_keychain_usable_tells_a_real_backend_from_the_fail_backend(monkeypatch):
    keyring = pytest.importorskip("keyring")
    from keyring.backend import KeyringBackend
    from keyring.backends import fail

    class Memory(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def __init__(self) -> None:
            super().__init__()
            self.store: dict[tuple[str, str], str] = {}

        def get_password(self, service, username):
            return self.store.get((service, username))

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def delete_password(self, service, username):
            self.store.pop((service, username), None)

    previous = keyring.get_keyring()
    try:
        keyring.set_keyring(fail.Keyring())
        assert not jira_module.keychain_usable()
        memory = Memory()
        keyring.set_keyring(memory)
        # a backend that is not the operating system's own is a substitute store: not usable
        assert not jira_module.keychain_usable()
        monkeypatch.setattr(jira_module, "OS_KEYCHAIN_MODULES", (Memory.__module__,))
        assert jira_module.keychain_usable()
        jira_module.store_token(BASE, CANARY)
        assert jira_module.stored_token_exists(BASE) and jira_token(BASE) == CANARY
        jira_module.delete_token(BASE)
        jira_module.delete_token(BASE)  # no entry any more: not an error
        assert not jira_module.stored_token_exists(BASE)
    finally:
        keyring.set_keyring(previous)


def test_delete_token_reports_a_failed_delete(monkeypatch):
    class Stuck:
        def get_password(self, service, user):
            return "still-there"

        def delete_password(self, service, user):
            raise RuntimeError("keychain locked: secret detail")

    monkeypatch.setattr(jira_module, "_keyring", lambda: Stuck())
    with pytest.raises(SourceError) as error:
        jira_module.delete_token(BASE)
    assert "secret detail" not in str(error.value) and "still-there" not in str(error.value)
