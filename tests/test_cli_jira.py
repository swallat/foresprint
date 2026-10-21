# SPDX-License-Identifier: EUPL-1.2
"""Command ``tickets`` with Jira: --fetch, --test-connection, --set-token. The Jira side is an
``httpx.MockTransport`` with the recorded-style answers of tests/data/jira (no network)."""

import sys
from pathlib import Path

import httpx
import pytest
import yaml
from test_jira_source import CANARY, FakeKeyring, Server, fixed, on_search
from typer.testing import CliRunner

from foresprint import sources
from foresprint.cli import app
from foresprint.sources import jira as jira_module
from foresprint.sources.jira import JiraSource

runner = CliRunner(env={"COLUMNS": "200"})
DATA = Path(__file__).parent / "data"


def run(data_dir: Path, *args: str, input: str | None = None):
    return runner.invoke(
        app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args], input=input
    )


def write_team(data_dir: Path, **tracker) -> None:
    team = data_dir / "demo"
    doc = yaml.safe_load((team / "team.yaml").read_text(encoding="utf-8"))
    doc["features"]["tickets"] = True
    doc["tracker"] = {
        "kind": "jira",
        "base_url": "https://jira.example.org",
        "query": "project = ABC ORDER BY Rank",
        "fields": {"estimate": "Story Points", "remaining": "Remaining", "epic": "Epic Link"},
        "refined_label": "Refined",
        **tracker,
    }
    (team / "team.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    (team / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": 1,
                "projects": [
                    {
                        "id": "payment",
                        "name": "Payment",
                        "product": "webshop",
                        "target": "2027-03-31",
                        "match": {"epic": ["ABC-100"]},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def jira_dir(data_dir: Path) -> Path:
    write_team(data_dir)
    return data_dir


class Mock:
    """Replaces the source factory so that Jira is answered by a MockTransport."""

    def __init__(self) -> None:
        self.handler = Server()
        self.opened: list[JiraSource] = []


@pytest.fixture
def jira(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock()
    real = sources.open_source

    def fake(settings, path=None, **kwargs):
        if path is None and settings.kind == "jira":
            source = JiraSource(settings, CANARY, httpx.MockTransport(mock.handler))
            mock.opened.append(source)
            return source
        return real(settings, path, **kwargs)

    monkeypatch.setattr(sources, "open_source", fake)
    return mock


def tickets_file(data_dir: Path) -> Path:
    return data_dir / "demo" / "tickets.yaml"


def test_fetch_preview_writes_nothing(jira_dir: Path, jira: Mock):
    result = run(jira_dir, "tickets", "demo", "--fetch")
    assert result.exit_code == 0, result.output
    assert "Jira jira.example.org: 5 Tickets gelesen" in result.output
    assert "ABC-1" in result.output and "ABC-2" in result.output
    assert "Nur Vorschau" in result.output
    assert not tickets_file(jira_dir).exists()
    assert CANARY not in result.output
    assert all(r.method == "GET" for r in jira.handler.requests)
    assert jira.opened[0]._client is None  # closed again


def test_fetch_apply_writes_tickets_yaml(jira_dir: Path, jira: Mock):
    team_before = (jira_dir / "demo" / "team.yaml").read_bytes()
    result = run(jira_dir, "tickets", "demo", "--fetch", "--apply")
    assert result.exit_code == 0, result.output
    written = yaml.safe_load(tickets_file(jira_dir).read_text(encoding="utf-8"))
    assert written["source"] == "jira jira.example.org"
    tickets = {tk["key"]: tk for tk in written["tickets"]}
    assert set(tickets) == {"ABC-1", "ABC-2", "ABC-3", "ABC-4", "ABC-5"}
    assert tickets["ABC-1"]["estimate"] == 5.0 and tickets["ABC-1"]["remaining"] == 3.0
    assert tickets["ABC-1"]["project"] == "payment" and tickets["ABC-4"]["depends_on"] == ["ABC-1"]
    assert tickets["ABC-1"]["depends_on"] == ["ABC-3"]
    # the report follows like after a CSV import
    assert "Payment" in result.output and "Ampel" in result.output
    assert CANARY not in tickets_file(jira_dir).read_text(encoding="utf-8")
    assert (jira_dir / "demo" / "team.yaml").read_bytes() == team_before
    # a second fetch of the same answer changes nothing
    again = run(jira_dir, "tickets", "demo", "--fetch")
    assert "Keine Änderungen" in again.output


def test_fetch_apply_commit_needs_apply(jira_dir: Path, jira: Mock):
    result = run(jira_dir, "tickets", "demo", "--fetch", "--commit")
    assert result.exit_code == 1 and "--commit braucht --apply" in result.output
    assert jira.handler.requests == []


def test_test_connection_shows_account_and_fields_and_writes_nothing(jira_dir: Path, jira: Mock):
    result = run(jira_dir, "tickets", "demo", "--test-connection")
    assert result.exit_code == 0, result.output
    assert "jira.example.org" in result.output and "Anna Beispiel" in result.output
    assert "customfield_10016" in result.output and "customfield_10020" in result.output
    assert CANARY not in result.output
    assert not tickets_file(jira_dir).exists()
    assert jira.handler.paths() == ["/rest/api/2/myself", "/rest/api/2/field"]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401, json={"message": "x"}), "ungültig oder abgelaufen"),
        (httpx.Response(403), "verweigert"),
        (httpx.ConnectError("no route"), "nicht erreichbar"),
    ],
)
def test_test_connection_failure_is_an_understandable_message(
    jira_dir: Path, jira: Mock, response, expected
):
    jira.handler = fixed(response)
    result = run(jira_dir, "tickets", "demo", "--test-connection")
    assert result.exit_code == 1
    assert expected in result.output and "Traceback" not in result.output
    assert CANARY not in result.output
    assert not tickets_file(jira_dir).exists()


def test_test_connection_reports_an_unknown_field(data_dir: Path, jira: Mock):
    write_team(data_dir, fields={"estimate": "Story Pointz"})
    result = run(data_dir, "tickets", "demo", "--test-connection")
    assert result.exit_code == 1
    assert "Story Pointz" in result.output and "Story Points" in result.output


def test_fetch_error_is_shown_without_traceback(jira_dir: Path, jira: Mock):
    jira.handler = on_search(
        httpx.Response(400, json={"errorMessages": ["Error in the JQL Query: x"]})
    )
    result = run(jira_dir, "tickets", "demo", "--fetch", "--apply")
    assert result.exit_code == 1
    assert "Error in the JQL Query: x" in result.output and "Traceback" not in result.output
    assert not tickets_file(jira_dir).exists()


def empty_result(jira: Mock) -> None:
    server = jira.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/2/search":
            return httpx.Response(
                200, json={"startAt": 0, "maxResults": 100, "total": 0, "issues": []}
            )
        return server(request)

    jira.handler = handler


def test_an_empty_result_never_wipes_the_last_import(jira_dir: Path, jira: Mock):
    assert run(jira_dir, "tickets", "demo", "--fetch", "--apply").exit_code == 0
    before = tickets_file(jira_dir).read_bytes()
    empty_result(jira)
    for args in (("--fetch", "--apply"), ("--fetch",), ("--fetch", "--apply", "--commit")):
        result = run(jira_dir, "tickets", "demo", *args)
        assert result.exit_code == 1, result.output
        assert "nichts geschrieben" in result.output and "JQL" in result.output
        assert "0 Tickets gelesen" in result.output
        assert tickets_file(jira_dir).read_bytes() == before


def test_an_empty_result_without_earlier_import_is_fine(jira_dir: Path, jira: Mock):
    empty_result(jira)
    result = run(jira_dir, "tickets", "demo", "--fetch", "--apply")
    assert result.exit_code == 0, result.output
    assert "0 Tickets gelesen" in result.output
    written = yaml.safe_load(tickets_file(jira_dir).read_text(encoding="utf-8"))
    assert written["tickets"] == [] and written["source"] == "jira jira.example.org"


def test_fetch_with_kind_csv_is_refused(ticket_csv_dir: Path):
    result = run(ticket_csv_dir, "tickets", "demo", "--fetch")
    assert result.exit_code == 1
    assert "--fetch" in result.output and "tracker.kind: jira" in result.output
    for option in ("--test-connection", "--set-token"):
        assert run(ticket_csv_dir, "tickets", "demo", option).exit_code == 1


@pytest.fixture
def ticket_csv_dir(data_dir: Path) -> Path:
    write_team(data_dir, kind="csv", base_url=None, query=None)
    return data_dir


@pytest.mark.parametrize(
    "args",
    [
        ("--fetch", "--import", str(DATA / "jira_en.csv")),
        ("--fetch", "--test-connection"),
        ("--import", str(DATA / "jira_en.csv"), "--set-token"),
        ("--test-connection", "--set-token"),
    ],
)
def test_the_sources_exclude_each_other(jira_dir: Path, jira: Mock, args):
    result = run(jira_dir, "tickets", "demo", *args)
    assert result.exit_code == 1
    assert "schließen einander aus" in result.output
    assert jira.handler.requests == [] and not tickets_file(jira_dir).exists()


def test_apply_with_test_connection_is_refused(jira_dir: Path, jira: Mock):
    result = run(jira_dir, "tickets", "demo", "--test-connection", "--apply")
    assert result.exit_code == 1 and jira.handler.requests == []


def test_import_file_still_works_when_the_tracker_is_jira(jira_dir: Path, jira: Mock):
    """The CSV export is the offline fallback: no request goes to Jira."""
    result = run(jira_dir, "tickets", "demo", "--import", str(DATA / "jira_en.csv"), "--apply")
    assert result.exit_code == 0, result.output
    written = yaml.safe_load(tickets_file(jira_dir).read_text(encoding="utf-8"))
    assert written["source"] == "jira_en.csv"
    assert jira.handler.requests == []


def test_without_tickets_a_jira_team_is_pointed_to_fetch(jira_dir: Path, jira: Mock):
    result = run(jira_dir, "tickets", "demo")
    assert result.exit_code == 0 and "--fetch" in result.output


def test_apply_alone_is_refused(jira_dir: Path, jira: Mock):
    assert run(jira_dir, "tickets", "demo", "--apply").exit_code == 1


# --- Token and missing pieces -----------------------------------------------------------------


def test_missing_token_says_how_to_provide_it(jira_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(jira_module.TOKEN_ENV, raising=False)
    monkeypatch.setitem(sys.modules, "keyring", None)
    result = run(jira_dir, "tickets", "demo", "--fetch")
    assert result.exit_code == 1
    assert "FORESPRINT_JIRA_TOKEN" in result.output and "--set-token" in result.output
    assert "Traceback" not in result.output


def test_the_environment_token_reaches_jira(jira_dir: Path, monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []
    server = Server()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        return server(request)

    real = JiraSource.__init__

    def init(self, settings, token, transport=None):
        real(self, settings, token, httpx.MockTransport(handler))

    monkeypatch.setattr(JiraSource, "__init__", init)
    monkeypatch.setenv(jira_module.TOKEN_ENV, CANARY)
    monkeypatch.setitem(sys.modules, "keyring", None)
    result = run(jira_dir, "tickets", "demo", "--test-connection")
    assert result.exit_code == 0, result.output
    assert set(seen) == {f"Bearer {CANARY}"}
    assert CANARY not in result.output


def test_missing_httpx_names_the_extra(jira_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(jira_module.TOKEN_ENV, CANARY)
    monkeypatch.setitem(sys.modules, "httpx", None)
    for option in ("--fetch", "--test-connection"):
        result = run(jira_dir, "tickets", "demo", option)
        assert result.exit_code == 1
        assert "Extra [jira]" in result.output and "Traceback" not in result.output
        assert CANARY not in result.output


def test_set_token_prompts_hidden_and_stores_in_the_keychain(
    jira_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    result = run(jira_dir, "tickets", "demo", "--set-token", input=f"{CANARY}\n")
    assert result.exit_code == 0, result.output
    assert fake.stored == {("foresprint-jira", "jira.example.org"): CANARY}
    assert CANARY not in result.output  # not echoed, not repeated
    assert "jira.example.org" in result.output and "--test-connection" in result.output


def test_set_token_prompt_uses_hidden_input(jira_dir: Path, monkeypatch: pytest.MonkeyPatch):
    import typer

    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring())
    asked: list[dict] = []
    real = typer.prompt

    def spy(*args, **kwargs):
        asked.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(typer, "prompt", spy)
    run(jira_dir, "tickets", "demo", "--set-token", input=f"{CANARY}\n")
    assert asked and asked[0]["hide_input"] is True


def test_set_token_without_keyring_is_a_clear_message(
    jira_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setitem(sys.modules, "keyring", None)
    result = run(jira_dir, "tickets", "demo", "--set-token", input=f"{CANARY}\n")
    assert result.exit_code == 1
    assert "keyring" in result.output and "FORESPRINT_JIRA_TOKEN" in result.output
    assert CANARY not in result.output


def test_set_token_with_a_backend_error_does_not_show_the_token(
    jira_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring(fail=True))
    result = run(jira_dir, "tickets", "demo", "--set-token", input=f"{CANARY}\n")
    assert result.exit_code == 1 and CANARY not in result.output
    assert "Traceback" not in result.output


def test_english_output(jira_dir: Path, jira: Mock, english):
    result = run(jira_dir, "tickets", "demo", "--fetch")
    assert result.exit_code == 0, result.output
    assert "Jira jira.example.org: 5 tickets read" in result.output
    jira.handler = fixed(httpx.Response(401))
    result = run(jira_dir, "tickets", "demo", "--test-connection")
    assert result.exit_code == 1 and "rejects the token" in result.output


def test_check_rejects_a_token_in_team_yaml(jira_dir: Path):
    team = jira_dir / "demo" / "team.yaml"
    doc = yaml.safe_load(team.read_text(encoding="utf-8"))
    doc["tracker"]["token"] = CANARY
    team.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    result = run(jira_dir, "check")
    assert result.exit_code == 1
    assert "token" in result.output and "Schlüsselbund" in result.output
    assert CANARY not in result.output


# --- Review fixes ----------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["--test-connection", "--set-token"])
@pytest.mark.parametrize("extra", [["--apply"], ["--commit"], ["--sprints", "3"], ["--sprints=6"]])
def test_options_that_do_not_belong_to_test_connection_and_set_token_are_refused(
    jira_dir: Path, jira: Mock, action, extra
):
    result = run(jira_dir, "tickets", "demo", action, *extra)
    assert result.exit_code == 1, result.output
    assert "gehören nicht zu" in result.output and extra[0].split("=")[0] in result.output
    assert jira.handler.requests == []


def test_sprints_alone_still_works_with_the_report(jira_dir: Path, jira: Mock):
    assert run(jira_dir, "tickets", "demo", "--sprints", "3").exit_code == 0


def test_set_token_warns_when_the_environment_variable_wins(
    jira_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring())
    quiet = run(jira_dir, "tickets", "demo", "--set-token", input=f"{CANARY}\n")
    assert "Vorrang" not in quiet.output
    monkeypatch.setenv(jira_module.TOKEN_ENV, "from-env")
    loud = run(jira_dir, "tickets", "demo", "--set-token", input=f"{CANARY}\n")
    assert loud.exit_code == 0, loud.output
    assert loud.output.count("Vorrang") == 1 and "FORESPRINT_JIRA_TOKEN" in loud.output
    assert CANARY not in loud.output and "from-env" not in loud.output


def test_set_token_with_an_unusable_address_fails_before_the_prompt(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    write_team(data_dir, base_url="https://[jira.example.org/jira")
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring())
    result = run(data_dir, "tickets", "demo", "--set-token", input=f"{CANARY}\n")
    assert result.exit_code == 1 and "base_url" in result.output
    assert "Traceback" not in result.output and CANARY not in result.output


def test_check_reports_a_malformed_base_url_without_a_crash(data_dir: Path):
    write_team(data_dir, base_url="https://[jira.example.org/jira")
    result = run(data_dir, "check")
    assert result.exit_code == 1
    assert "http- oder https-Adresse" in result.output and "Traceback" not in result.output


def test_fetch_with_credentials_in_the_address_is_refused(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    write_team(data_dir, base_url="https://anna:s3cret@jira.example.org")
    monkeypatch.setenv(jira_module.TOKEN_ENV, CANARY)
    result = run(data_dir, "tickets", "demo", "--fetch")
    assert result.exit_code == 1 and "Zugangsdaten" in result.output
    assert "s3cret" not in result.output
    check = run(data_dir, "check")
    assert "Zugangsdaten" in check.output and "s3cret" not in check.output
