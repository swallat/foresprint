# SPDX-License-Identifier: EUPL-1.2
"""Manual check against a real Jira Data Center. Deselected by default (marker ``jira_live``);
run it with ``uv run --extra jira pytest -m jira_live`` and these variables:

  FORESPRINT_JIRA_URL    base address, e.g. https://jira.example.org
  FORESPRINT_JIRA_TOKEN  personal access token
  FORESPRINT_JIRA_JQL    a small query, e.g. ``project = ABC AND sprint in openSprints()``
  FORESPRINT_JIRA_ESTIMATE / _REMAINING / _EPIC   optional display names of the fields

Reads only (GET). Nothing about the tickets is printed, only counts."""

import os

import pytest

from sprintforecast.model import TrackerFields, TrackerSettings, base_url_problem
from sprintforecast.sources import SourceError
from sprintforecast.sources.jira import JiraSource, jira_token

pytestmark = pytest.mark.jira_live


def test_live_connection_fields_and_fetch():
    url = (os.environ.get("FORESPRINT_JIRA_URL") or "").strip()
    jql = (os.environ.get("FORESPRINT_JIRA_JQL") or "").strip()
    if not (url and jql):
        pytest.skip("set FORESPRINT_JIRA_URL, FORESPRINT_JIRA_TOKEN and ..._JQL")
    if base_url_problem(url) is not None:  # checked before the token becomes an argument
        pytest.fail("FORESPRINT_JIRA_URL is not a plain http(s) address", pytrace=False)
    token = jira_token(url)  # environment variable (stripped), else the keychain
    if not token:
        pytest.skip("no token: set FORESPRINT_JIRA_TOKEN or store one with --set-token")
    settings = TrackerSettings(
        kind="jira",
        base_url=url,
        query=jql,
        fields=TrackerFields(
            estimate=os.environ.get("FORESPRINT_JIRA_ESTIMATE"),
            remaining=os.environ.get("FORESPRINT_JIRA_REMAINING"),
            epic=os.environ.get("FORESPRINT_JIRA_EPIC"),
        ),
    )
    # No local variable holds anything that pytest could print on a failure but the settings
    # and the source (whose repr hides the token); a SourceError carries no token or ticket data.
    try:
        with JiraSource(settings, token) as source:
            del token
            assert source.test_connection()
            fields = source.resolve_fields()
            if not fields.sprint:
                pytest.fail("no Sprint field found by its schema (Jira Software?)", pytrace=False)
            tickets = source.fetch()
    except SourceError as e:
        pytest.fail(str(e), pytrace=False)
    keys = [tk.key for tk in tickets]
    assert len(keys) == len(set(keys))
    print(f"live: {len(tickets)} tickets read")
