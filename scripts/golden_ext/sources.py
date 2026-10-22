# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the ticket sources: the CSV export of Jira and the Jira Data Center
client (``foresprint.sources``). Everything below ``expected/sources/``.

CSV: every case is a folder ``csv/<case>/`` with ``input.csv``, the settings and the result
(``ok`` = the raw tickets, or ``error`` = the message; the path in a message is ``input.csv``).

Jira: every scenario is a file ``jira/<scenario>.json`` with the settings, the recorded answers of
the server (``routes``, matched in order by method, path and the listed query parameters), the
operation, the requests the client made (``requests``) and the result. No test talks to a real
server; the recorded answers are the fixtures of ``tests/data/jira`` and small invented ones.

Further files: ``csv/numbers.json`` (number and delimiter parsing), ``jira/sprints.json``
(sprint values), ``jira/field-texts.json``, ``jira/label-writes.json`` (what the one write is
allowed to be), ``jira/urls.json`` (base address checks, keychain user, token check).
"""

from __future__ import annotations

import copy
import difflib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from foresprint.model import TrackerFields, TrackerSettings, base_url_problem
from foresprint.sources import SourceError
from foresprint.sources import jira as jira_module
from foresprint.sources.csv import CsvSource, parse_number, sniff_delimiter
from foresprint.sources.jira import JiraSource, suggest_fields

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = ROOT / "tests" / "data" / "jira"
CSV_FIXTURES = ROOT / "tests" / "data"
BASE = "https://jira.example.org"
TOKEN = "tok-GOLDEN-9f8e7d6c5b4a3f2e"

FIELDS = {"estimate": "Story Points", "remaining": "Remaining", "epic": "Epic Link"}


def generate(ctx: Any) -> None:
    csv_cases(ctx)
    jira_cases(ctx)


# --- CSV ------------------------------------------------------------------------------------


def _fixture_text(name: str) -> str:
    return (CSV_FIXTURES / name).read_text(encoding="utf-8")


HEADER = "Issue key,Summary,Status,Custom field (Story Points),Custom field (Remaining)"

CSV_CASES: dict[str, dict[str, Any]] = {
    "jira-en": {"text": _fixture_text("jira_en.csv"), "fields": FIELDS},
    "jira-de": {
        "text": _fixture_text("jira_de.csv"),
        "fields": {"estimate": "Story Points", "remaining": "Remaining", "epic": None},
    },
    "missing-columns": {"text": _fixture_text("jira_missing.csv"), "fields": FIELDS},
    "empty": {"text": "", "fields": FIELDS},
    "no-estimate-field": {
        "text": f"{HEADER}\nA-1,One,To Do,3,\n",
        "fields": {"estimate": None, "remaining": "Remaining", "epic": None},
    },
    "bom-crlf": {
        "text": "﻿" + HEADER.replace(",", ";") + "\r\nA-1;One;To Do;3,5;\r\nA-2;Two;;;2\r\n",
        "fields": FIELDS,
    },
    "decimal-comma-quoted": {
        "text": f'{HEADER}\nA-1,"Two, lines\nin one cell",Done,"1.234,5","2,5"\n',
        "fields": FIELDS,
    },
    "negative": {"text": f"{HEADER}\nA-1,One,To Do,-3,\n", "fields": FIELDS},
    "negative-zero": {"text": f"{HEADER}\nA-1,One,To Do,-0,0\n", "fields": FIELDS},
    "not-a-number": {"text": f"{HEADER}\nA-1,One,To Do,abc,\n", "fields": FIELDS},
    "infinite": {"text": f"{HEADER}\nA-1,One,To Do,inf,\n", "fields": FIELDS},
    "key-missing": {"text": f"{HEADER}\n,One,To Do,3,\n", "fields": FIELDS},
    "unclosed-quote": {"text": f'{HEADER}\nA-1,"One,To Do,3,\n', "fields": FIELDS},
    "blank-rows-short-rows": {
        "text": f"{HEADER}\nA-1,One\n\n , , , ,\nA-2,Two,Open,1,\n",
        "fields": FIELDS,
    },
    "german-headers-all": {
        "text": (
            "Vorgangsschlüssel;Zusammenfassung;Vorgangstyp;Priorität;Stichwörter;Stichwörter;"
            "Komponente/n;Sprint;Sprint;Benutzerdefiniertes Feld (Rang);Lösung;"
            "Eingehende Vorgangsverknüpfung (Blocks);Eingehende Vorgangsverknüpfung (Blocks);"
            "Übergeordnet;Benutzerdefiniertes Feld (Story Points);Benutzerdefiniertes Feld (Team)\n"
            "G-1;Ein  Titel;Story;Hoch;a;b;Kern;S1;S2;0|x:;Fertig;G-2;G-2;G-100;8;Alpha\n"
        ),
        "fields": {"estimate": "Story Points", "remaining": None, "epic": None},
        "rule_fields": {"team": "Team"},
    },
    "rule-field-missing": {
        "text": f"{HEADER}\nA-1,One,To Do,3,\n",
        "fields": FIELDS,
        "rule_fields": {"team": "Team"},
    },
    "quote-then-text": {"text": f'{HEADER}\nA-1,"x"y,To Do,3,\n', "fields": FIELDS},
    "quote-then-text-semicolon": {
        "text": f'{HEADER.replace(",", ";")}\nA-1;"x"y;To Do;3;\n',
        "fields": FIELDS,
    },
    "lone-cr": {"text": f"{HEADER}\rA-1,One,To Do,3,\n", "fields": FIELDS},
    "cr-after-field": {"text": f"{HEADER}\nA-1,One,To Do,3,\rx\n", "fields": FIELDS},
    "field-limit": {"text": f"{HEADER}\nA-1,{'x' * 131073},To Do,3,\n", "fields": FIELDS},
    "doubled-quotes": {
        "text": f'{HEADER}\nA-1,"say ""hi"" there",To Do,3,\n',
        "fields": FIELDS,
    },
    "space-before-quote": {"text": f'{HEADER}\nA-1, "x",To Do,3,\n', "fields": FIELDS},
    "case-insensitive-header": {
        "text": "ISSUE KEY,summary,STATUS,custom field (story points)\nA-1,One,Open,2\n",
        "fields": {"estimate": "Story Points", "remaining": None, "epic": None},
    },
    "duplicate-sprint-columns": {
        "text": "Issue key,Summary,Sprint,Sprint,Sprint,Story Points\nA-1,One,S1,,S3,2\n",
        "fields": {"estimate": "Story Points", "remaining": None, "epic": None},
    },
    "epic-field-and-parent": {
        "text": (
            "Issue key,Summary,Parent,Custom field (Epic Link),Story Points\nA-1,One,P-1,E-1,2\n"
        ),
        "fields": {"estimate": "Story Points", "remaining": None, "epic": "Epic Link"},
    },
    "plain-estimate-header": {
        "text": "Issue key,Summary,Story Points\nA-1,One,3\n",
        "fields": {"estimate": "Story Points", "remaining": None, "epic": None},
    },
}

NUMBERS = [
    "",
    " ",
    "3",
    "3.5",
    "3,5",
    "1.234,5",
    "1,234.5",
    "1.234",
    "1,234",
    "-2",
    "-0",
    "+4",
    "1e3",
    " 7 ",
    "inf",
    "nan",
    "abc",
    "1,2,3",
    "0,5.5",
    "٣",
    "١٢٣",
    "1_000",
    "1__0",
    "_1",
    "1_",
    ".5",
    "5.",
    "1e",
    "1e+2",
    "-.5e-1",
    "infinity",
    "-Infinity",
    "+nan",
    "0x10",
    "1\u00a02",
    "\u00a05\u00a0",
    "1,000,000",
    "1.000.000",
    "1.000.000,5",
]
DELIMITER_LINES = ["a,b,c", "a;b;c", "a;b,c", "a;b;c,d", "", "abc", ";;,"]


def _run_csv(name: str, case: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "input.csv"
        path.write_text(case["text"], encoding="utf-8", newline="")
        source = CsvSource(path, TrackerFields(**case["fields"]), case.get("rule_fields"))
        try:
            return {"ok": ctx_json(source.fetch())}
        except SourceError as e:
            return {"error": str(e).replace(f"{tmp}/", "")}


def ctx_json(value: Any) -> Any:
    import dataclasses

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: ctx_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, list | tuple):
        return [ctx_json(v) for v in value]
    if isinstance(value, dict):
        return {k: ctx_json(v) for k, v in value.items()}
    return value


def csv_cases(ctx: Any) -> None:
    names = []
    for name, case in CSV_CASES.items():
        names.append(name)
        ctx.write(f"sources/csv/{name}/input.csv", case["text"])
        record = {
            "fields": case["fields"],
            "rule_fields": case.get("rule_fields", {}),
            **_run_csv(name, case),
        }
        ctx.write(f"sources/csv/{name}/case.json", ctx.dump_json(record))
    ctx.write("sources/csv/index.json", ctx.dump_json(names))
    numbers = []
    for text in NUMBERS:
        try:
            numbers.append({"text": text, "ok": parse_number(text)})
        except ValueError:
            numbers.append({"text": text, "error": True})
    delimiters = [{"line": line, "delimiter": sniff_delimiter(line)} for line in DELIMITER_LINES]
    ctx.write(
        "sources/csv/numbers.json", ctx.dump_json({"numbers": numbers, "delimiters": delimiters})
    )


# --- Jira -----------------------------------------------------------------------------------


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def settings_dict(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "base_url": BASE,
        "query": "project = ABC ORDER BY Rank",
        "fields": dict(FIELDS),
        "rule_fields": {},
        "link_type": "Blocks",
    }
    values.update(overrides)
    return values


def to_settings(values: dict[str, Any]) -> TrackerSettings:
    return TrackerSettings(
        kind="jira",
        base_url=values["base_url"],
        query=values["query"],
        fields=TrackerFields(**values["fields"]),
        rule_fields=dict(values["rule_fields"]),
        link_type=values["link_type"],
    )


def route(path: str, body: Any = None, status: int = 200, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"method": extra.pop("method", "GET"), "path": path, "status": status}
    if body is not None:
        entry["json"] = body
    entry.update(extra)
    return entry


def search(start: int, body: Any, status: int = 200) -> dict[str, Any]:
    return route("/rest/api/2/search", body, status, query={"startAt": str(start)})


def standard_routes() -> list[dict[str, Any]]:
    return [
        route("/rest/api/2/myself", fixture("myself.json")),
        route("/rest/api/2/field", fixture("fields.json")),
        search(0, fixture("search_page1.json")),
        search(3, fixture("search_page2.json")),
    ]


class Replay:
    """The transport: answers from the recorded routes and logs what the client sent."""

    def __init__(self, routes: list[dict[str, Any]]) -> None:
        self.routes = routes
        self.log: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params.multi_items())
        entry: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "query": query,
            "authorization": request.headers.get("Authorization") == f"Bearer {TOKEN}",
        }
        if request.content:
            entry["body"] = json.loads(request.content)
        self.log.append(entry)
        for r in self.routes:
            if (
                r["method"] == request.method
                and r["path"] == request.url.path
                and all(query.get(k) == v for k, v in r.get("query", {}).items())
            ):
                if "fault" in r:
                    raise {
                        "timeout": httpx.ReadTimeout("t"),
                        "connect": httpx.ConnectError("refused"),
                        "network": httpx.ReadError("reset"),
                        "protocol": httpx.UnsupportedProtocol("p"),
                    }[r["fault"]]
                headers = r.get("headers", {})
                if "json" in r:
                    return httpx.Response(r["status"], json=r["json"], headers=headers)
                return httpx.Response(r["status"], text=r.get("text", ""), headers=headers)
        return httpx.Response(404, json={"message": "no such resource"})


Operation = Callable[[JiraSource], Any]

OPERATIONS: dict[str, Operation] = {
    "fetch": lambda s: s.fetch(),
    "test_connection": lambda s: s.test_connection(),
    "count": lambda s: s.count_tickets(),
    "resolve_fields": lambda s: s.resolve_fields(),
    "list_fields": lambda s: s.list_fields(),
    "suggest": lambda s: suggest_fields(s.list_fields()),
}


def _run_jira(scenario: dict[str, Any]) -> dict[str, Any]:
    replay = Replay(scenario["routes"])
    source = JiraSource(to_settings(scenario["settings"]), TOKEN, httpx.MockTransport(replay))
    op = scenario["operation"]
    try:
        if op == "set_labels":
            args = scenario["args"]
            source.set_labels(args["key"], args["add"], args["remove"])
            result: dict[str, Any] = {"ok": None}
        else:
            result = {"ok": ctx_json(OPERATIONS[op](source))}
    except SourceError as e:
        result = {"error": str(e)}
    except ValueError as e:
        result = {"refused": str(e)}
    return {**scenario, "requests": replay.log, **result}


def _fields_with(*extra: dict[str, Any]) -> list[dict[str, Any]]:
    return [*fixture("fields.json"), *extra]


def _issue(key: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"id": key, "key": key, "fields": fields}


def _page(issues: list[Any], total: int | None = None, start: int = 0) -> dict[str, Any]:
    return {
        "startAt": start,
        "maxResults": 100,
        "total": len(issues) if total is None else total,
        "issues": issues,
    }


def scenarios() -> dict[str, dict[str, Any]]:
    std = standard_routes
    out: dict[str, dict[str, Any]] = {}

    def add(name: str, operation: str, routes: list[dict[str, Any]], **kw: Any) -> None:
        out[name] = {
            "operation": operation,
            "settings": kw.pop("settings", settings_dict()),
            "routes": routes,
            **kw,
        }

    add("fetch", "fetch", std())
    add("test-connection", "test_connection", std())
    add("count", "count", std())
    add("list-fields", "list_fields", std())
    add("suggest-fields", "suggest", std())
    add("resolve-fields", "resolve_fields", std())
    add(
        "fetch-context-path",
        "fetch",
        [{**r, "path": "/jira" + r["path"]} for r in std()],
        settings=settings_dict(base_url=BASE + "/jira/"),
    )
    add(
        "resolve-case-and-id",
        "resolve_fields",
        std(),
        settings=settings_dict(
            fields={"estimate": "story points", "remaining": "customfield_10017", "epic": None}
        ),
    )
    add(
        "resolve-parent-epic",
        "resolve_fields",
        std(),
        settings=settings_dict(
            fields={"estimate": "Story Points", "remaining": None, "epic": "Parent"}
        ),
    )
    add(
        "resolve-unknown",
        "resolve_fields",
        std(),
        settings=settings_dict(fields={"estimate": "Story Point", "remaining": None, "epic": None}),
    )
    add(
        "resolve-unknown-far",
        "resolve_fields",
        std(),
        settings=settings_dict(fields={"estimate": "Zzzzz", "remaining": None, "epic": None}),
    )
    add(
        "resolve-ambiguous",
        "resolve_fields",
        std(),
        settings=settings_dict(
            fields={"estimate": "Business Value", "remaining": None, "epic": None}
        ),
    )
    add(
        "resolve-ambiguous-by-id",
        "resolve_fields",
        std(),
        settings=settings_dict(
            fields={"estimate": "customfield_10101", "remaining": None, "epic": None}
        ),
    )
    add(
        "resolve-rule-fields",
        "resolve_fields",
        std(),
        settings=settings_dict(rule_fields={"team": "Business Value", "area": "Nope"}),
    )
    add("fetch-no-query", "fetch", std(), settings=settings_dict(query="  "))
    add("count-no-query", "count", std(), settings=settings_dict(query=None))

    # --- shape of the answers
    add("fetch-fields-not-a-list", "fetch", [route("/rest/api/2/field", {"a": 1})])
    add("fetch-field-entry-not-object", "fetch", [route("/rest/api/2/field", [1, 2])])
    base = [route("/rest/api/2/field", fixture("fields.json"))]
    add("fetch-page-without-issues", "fetch", [*base, route("/rest/api/2/search", {"total": 1})])
    add(
        "fetch-total-invalid",
        "fetch",
        [*base, route("/rest/api/2/search", {"issues": [], "total": "x"})],
    )
    add(
        "fetch-total-negative",
        "fetch",
        [*base, route("/rest/api/2/search", {"issues": [], "total": -1})],
    )
    add(
        "fetch-total-bool",
        "fetch",
        [*base, route("/rest/api/2/search", {"issues": [], "total": True})],
    )
    add("fetch-empty", "fetch", [*base, search(0, _page([]))])
    add(
        "fetch-issue-without-key",
        "fetch",
        [*base, search(0, _page([{"fields": {}}]))],
    )
    add(
        "fetch-issue-without-fields",
        "fetch",
        [*base, search(0, _page([{"key": "A-1"}]))],
    )
    one = _issue("A-1", {"summary": "One"})
    two = _issue("A-2", {"summary": "Two"})
    add(
        "fetch-total-changes",
        "fetch",
        [*base, search(0, _page([one], 3)), search(1, _page([two], 4, 1))],
    )
    add(
        "fetch-short-read",
        "fetch",
        [*base, search(0, _page([one], 3)), search(1, _page([], 3, 1))],
    )
    add(
        "fetch-ignores-start-at",
        "fetch",
        [*base, search(0, _page([one], 2)), search(1, _page([one], 2, 1))],
    )
    add(
        "fetch-duplicate-in-page",
        "fetch",
        [*base, search(0, _page([one, one, two], 2))],
    )
    add(
        "fetch-count-mismatch",
        "fetch",
        [*base, search(0, _page([one, one], 2))],
    )
    add(
        "count-total-invalid",
        "count",
        [route("/rest/api/2/search", {"total": "x"})],
    )
    add("myself-no-name", "test_connection", [route("/rest/api/2/myself", {"name": ""})])
    add("myself-login-name", "test_connection", [route("/rest/api/2/myself", {"name": "anna"})])
    add("myself-not-object", "test_connection", [route("/rest/api/2/myself", [])])

    # --- value mapping
    mapped = _issue(
        "M-1",
        {
            "summary": "  Spaced \n out  ",
            "status": {"name": "Open"},
            "issuetype": {"name": "Story"},
            "priority": {"name": "High"},
            "labels": ["a", "a", 3, "b"],
            "components": [{"name": "X"}, {"name": ""}, {"nope": 1}, {"name": "X"}],
            "customfield_10016": {"value": "5"},
            "customfield_10017": 0,
            "customfield_10020": [
                "com.atlassian.greenhopper.service.sprint.Sprint@1[id=9,name=Old,state=CLOSED]",
                {"id": 10, "name": "Now", "state": "active"},
            ],
            "customfield_10019": "0|zz:",
            "customfield_10014": "M-100",
            "resolution": {"name": "Done"},
            "issuelinks": [
                {"type": {"name": "blocks"}, "inwardIssue": {"key": "M-2"}},
                {"type": {"name": "Blocks"}, "inwardIssue": {"key": "M-2"}},
                {"type": {"name": "Blocks"}, "inwardIssue": {"nokey": 1}},
                {"type": {"name": "Blocks"}, "outwardIssue": {"key": "M-3"}},
                "junk",
            ],
        },
    )
    add("map-values", "fetch", [*base, search(0, _page([mapped]))])
    add(
        "map-link-type",
        "fetch",
        [*base, search(0, _page([mapped]))],
        settings=settings_dict(link_type=" BLOCKS "),
    )
    add(
        "map-link-type-other",
        "fetch",
        [*base, search(0, _page([mapped]))],
        settings=settings_dict(link_type="Relates"),
    )
    parent_epic = _issue(
        "E-1",
        {
            "summary": "p",
            "parent": {"key": "E-100", "fields": {"issuetype": {"name": "Epos"}}},
        },
    )
    parent_story = _issue(
        "E-2",
        {"summary": "p", "parent": {"key": "E-200", "fields": {"issuetype": {"name": "Story"}}}},
    )
    link_only = _issue("E-3", {"summary": "p", "customfield_10014": {"key": "E-300"}})
    add("epic-sources", "fetch", [*base, search(0, _page([parent_epic, parent_story, link_only]))])
    add(
        "epic-parent-configured",
        "fetch",
        [*base, search(0, _page([parent_epic, parent_story, link_only]))],
        settings=settings_dict(
            fields={"estimate": "Story Points", "remaining": None, "epic": "Parent"}
        ),
    )
    rule_issue = _issue(
        "R-1",
        {
            "summary": "r",
            "customfield_10100": {"value": "Alpha"},
            "customfield_10101": [{"name": "x"}, {"displayName": "y"}, "z", 4, 2.5, True, None],
        },
    )
    add(
        "rule-fields",
        "fetch",
        [*base, search(0, _page([rule_issue]))],
        settings=settings_dict(
            rule_fields={"first": "customfield_10100", "second": "customfield_10101"}
        ),
    )
    for bad in ("abc", -1, True, "nan", "inf"):
        issue = _issue("N-1", {"summary": "n", "customfield_10016": bad})
        add(
            f"number-invalid-{json.dumps(bad)}".replace('"', ""),
            "fetch",
            [*base, search(0, _page([issue]))],
        )
    for text in ("5", "2,5", " 3 ", ""):
        issue = _issue("N-2", {"summary": "n", "customfield_10016": text})
        add(
            f"number-text-{text.strip() or 'empty'}".replace(",", "comma"),
            "fetch",
            [*base, search(0, _page([issue]))],
        )

    # --- HTTP errors, each on the first request and on the search
    statuses: list[tuple[str, int, dict[str, Any]]] = [
        ("401", 401, {}),
        ("403", 403, {}),
        ("404", 404, {}),
        ("400", 400, {"json": {"errorMessages": ["bad"]}}),
        ("407", 407, {}),
        ("429-wait", 429, {"headers": {"retry-after": "30"}}),
        ("429-junk", 429, {"headers": {"retry-after": "soon"}}),
        ("429-none", 429, {}),
        ("302", 302, {"headers": {"location": "https://sso.example.org/login"}}),
        ("302-nolocation", 302, {}),
        ("500", 500, {}),
        ("418", 418, {}),
    ]
    for label, status, extra in statuses:
        add(
            f"http-{label}",
            "test_connection",
            [
                {
                    "method": "GET",
                    "path": "/rest/api/2/myself",
                    "status": status,
                    **{k: v for k, v in extra.items()},
                }
            ],
        )
    add(
        "http-200-not-json",
        "test_connection",
        [route("/rest/api/2/myself", status=200, text="<html>")],
    )
    add(
        "http-400-jql",
        "fetch",
        [*base, search(0, fixture("error_jql.json"), 400)],
    )
    add("http-400-jql-empty", "fetch", [*base, search(0, {"errorMessages": []}, 400)])
    add("http-400-jql-no-json", "fetch", [*base, search(0, None, 400)])
    add(
        "http-400-jql-long",
        "fetch",
        [*base, search(0, {"errorMessages": ["x" * 400]}, 400)],
    )
    add(
        "http-400-jql-mixed",
        "fetch",
        [*base, search(0, {"errorMessages": [" a ", 3, "", "b"]}, 400)],
    )
    for fault in ("timeout", "connect", "network", "protocol"):
        add(
            f"fault-{fault}",
            "test_connection",
            [{"method": "GET", "path": "/rest/api/2/myself", "status": 0, "fault": fault}],
        )

    # --- the one write
    for label, key, add_l, rem, status in [
        ("ok", "ABC-1", ["planned_for_2026.22"], ["planned_for_2026.21"], 204),
        ("forbidden", "ABC-1", ["planned_for_2026.22"], [], 403),
        ("not-found", "ABC-1", [], ["planned_for_2026.21"], 404),
        ("server-error", "ABC-1", ["planned_for_x"], [], 500),
        ("ok-200", "ABC-1", ["planned_for_x"], [], 200),
    ]:
        add(
            f"set-labels-{label}",
            "set_labels",
            [{"method": "PUT", "path": f"/rest/api/2/issue/{key}", "status": status, "text": ""}],
            args={"key": key, "add": add_l, "remove": rem},
        )
    for label, key, add_l, rem in [
        ("foreign-label", "ABC-1", ["urgent"], []),
        ("space", "ABC-1", ["planned_for_a b"], []),
        ("empty-suffix", "ABC-1", ["planned_for_"], []),
        ("nothing", "ABC-1", [], []),
        ("lowercase-key", "abc-1", ["planned_for_x"], []),
        ("key-with-path", "ABC-1/../X-1", ["planned_for_x"], []),
    ]:
        add(
            f"set-labels-refused-{label}",
            "set_labels",
            [],
            args={"key": key, "add": add_l, "remove": rem},
        )
    return out


def jira_cases(ctx: Any) -> None:
    names = []
    for name, scenario in scenarios().items():
        names.append(name)
        ctx.write(f"sources/jira/{name}.json", ctx.dump_json(_run_jira(copy.deepcopy(scenario))))
    ctx.write("sources/jira/index.json", ctx.dump_json(names))

    sprint_values: list[Any] = [
        "com.atlassian.greenhopper.service.sprint.Sprint@1a2b[id=12,rapidViewId=3,state=ACTIVE,"
        "name=Sprint 21, Team A [Phase 1],goal=,startDate=2026-01-01,sequence=12]",
        "x[id=1,state=future,name=Plain]",
        "x[name=Only name]",
        "x[state=ACTIVE]",
        "x[id=1,name=<null>,state=ACTIVE]",
        "x[id=1,name=A=B,state=CLOSED]",
        "x[name= Spaced ,state=active]  ",
        "no brackets",
        "[name=Bare,state=FUTURE]",
        "x[name=Open",
        {"id": 5, "name": " Obj ", "state": "future"},
        {"name": "NoState"},
        {"name": " "},
        {"name": 3},
        {"id": 5},
        5,
        None,
    ]
    parsed = []
    for value in sprint_values:
        found = jira_module.parse_sprint(value)
        parsed.append({"value": value, "ok": ctx_json(found)})
    choose_inputs: list[Any] = [
        None,
        [],
        "x[name=One,state=CLOSED]",
        {"name": "Dict", "state": "FUTURE"},
        ["x[name=A,state=CLOSED]", "x[name=B,state=FUTURE]", "x[name=C,state=ACTIVE]"],
        ["x[name=A,state=CLOSED]", "x[name=B,state=FUTURE]", "x[name=C,state=FUTURE]"],
        ["x[name=A,state=CLOSED]", "x[name=B,state=CLOSED]"],
        ["junk", "x[name=A,state=CLOSED]", 3],
        ["junk"],
        "junk",
        7,
    ]
    chosen = [{"values": v, "ok": jira_module.choose_sprint(v)} for v in choose_inputs]
    ctx.write("sources/jira/sprints.json", ctx.dump_json({"parse": parsed, "choose": chosen}))

    texts_inputs: list[Any] = [
        None,
        True,
        "",
        "  a ",
        0,
        3,
        2.5,
        1e20,
        {"value": "V", "name": "N"},
        {"name": " N "},
        {"displayName": "D"},
        {"value": " "},
        {"other": 1},
        ["a", "a", {"value": "b"}, ["c", "a"], None, 4],
        [],
        {"value": 3},
    ]
    ctx.write(
        "sources/jira/field-texts.json",
        ctx.dump_json([{"value": v, "ok": jira_module.field_texts(v)} for v in texts_inputs]),
    )

    label_paths = [
        "/rest/api/2/issue/ABC-1",
        "/rest/api/2/issue/A_b1-22",
        "/rest/api/2/issue/1-2",
        "/rest/api/2/issue/ABC-1/",
        "/rest/api/2/issue/ABC-1/comment",
        "/rest/api/2/search",
    ]
    label_bodies: list[Any] = [
        {"update": {"labels": [{"add": "planned_for_x"}]}},
        {"update": {"labels": [{"add": "planned_for_x"}, {"remove": "planned_for_y"}]}},
        {"update": {"labels": [{"set": "planned_for_x"}]}},
        {"update": {"labels": [{"add": "planned_for_x", "remove": "planned_for_y"}]}},
        {"update": {"labels": [{"add": "other"}]}},
        {"update": {"labels": [{"add": "planned_for_"}]}},
        {"update": {"labels": [{"add": "planned_for_a b"}]}},
        {"update": {"labels": [{"add": 3}]}},
        {"update": {"labels": []}},
        {"update": {"labels": "x"}},
        {"update": {"summary": [{"set": "x"}]}},
        {"update": {"labels": [{"add": "planned_for_x"}], "summary": []}},
        {"fields": {"labels": ["planned_for_x"]}},
        {"update": {"labels": [{"add": "planned_for_x"}]}, "fields": {}},
        {"update": "x"},
        [],
        None,
    ]
    writes = [
        {"path": p, "body": b, "ok": jira_module._is_label_write(p, b)}
        for p in label_paths
        for b in label_bodies
    ]
    ctx.write("sources/jira/label-writes.json", ctx.dump_json(writes))

    urls = [
        BASE,
        BASE + "/jira/",
        "http://jira.example.org:8080/x",
        "HTTPS://Jira.Example.ORG",
        "ftp://jira.example.org",
        "jira.example.org",
        "",
        "   ",
        "https://",
        "https://user:pw@jira.example.org",
        "https://user@jira.example.org",
        "https://jira.example.org?x=1",
        "https://jira.example.org#frag",
        "https://jira.example.org/?",
        "https://jira.example.org/#",
        "https://jira.example.org:notaport",
        "https://jira.example.org:99999",
        "https://[::1]:8443/jira",
        " https://jira.example.org/jira ",
    ]
    url_rows = []
    for url in urls:
        row: dict[str, Any] = {"url": url, "problem": base_url_problem(url)}
        try:
            row["keychain_user"] = jira_module.keychain_user(url)
        except SourceError as e:
            row["keychain_error"] = str(e)
        url_rows.append(row)
    tokens = ["abc", "tok-1.2_3~x", "", " ", "a b", "a\nb", "ä", "a\tb", "x" * 300, "a\x7fb", "!~"]
    token_rows = []
    for token in tokens:
        try:
            jira_module._check_token(token)
            token_rows.append({"token": token, "ok": True})
        except SourceError as e:
            token_rows.append({"token": token, "error": str(e)})
    close_inputs: list[tuple[str, list[str]]] = [
        ("Story Point", ["Story Points", "Summary", "Status", "Original Story Points"]),
        ("Zzzzz", ["Story Points", "Summary"]),
        ("Business Value", ["Business Value", "Business Value", "Value", "Business"]),
        ("story points", ["Story Points", "Story points", "Points story"]),
        ("abcd", ["abcd", "abcde", "abcdef", "bcd", "xabcdx", "abc"]),
        ("Remaining", ["Remaining Estimate", "Time Remaining", "Rest", "Remain"]),
        ("Épic Link", ["Epic Link", "Epic Name", "Épic Name", "Epic Status"]),
        ("", ["a", ""]),
        ("a", []),
        ("aaaa", ["aaab", "aaba", "abaa", "baaa", "aaaa "]),
        ("Rang", ["Rank", "Range", "Rang", "Orang", "Rangliste"]),
        ("x" * 250, ["x" * 250, "x" * 249 + "y", "y" * 250, "x" * 120]),
        ("ab" * 120, ["ab" * 119, "ba" * 120, "ab" * 120 + "c"]),
        ("Sprint Goal", ["Sprint", "Goal", "Sprint goal", "Goal Sprint", "Sprint Goals"]),
    ]
    close = [
        {"word": w, "possibilities": p, "ok": difflib.get_close_matches(w, p, n=3, cutoff=0.6)}
        for w, p in close_inputs
    ]
    ctx.write("sources/jira/close-matches.json", ctx.dump_json(close))
    ctx.write("sources/jira/urls.json", ctx.dump_json({"urls": url_rows, "tokens": token_rows}))
