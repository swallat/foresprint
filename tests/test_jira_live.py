# SPDX-License-Identifier: EUPL-1.2
"""Manual check against a real Jira Data Center. Deselected by default (marker ``jira_live``);
run it with ``uv run --extra jira pytest -m jira_live`` and these variables:

  SPRINTFORECAST_JIRA_URL    base address, e.g. https://jira.example.org
  SPRINTFORECAST_JIRA_TOKEN  personal access token
  SPRINTFORECAST_JIRA_JQL    a small query, e.g. ``project = ABC AND sprint in openSprints()``
  SPRINTFORECAST_JIRA_ESTIMATE / _REMAINING / _EPIC   optional display names of the fields

Reads only (GET). Nothing about the tickets is printed, only counts."""

import os

import pytest

from sprintforecast.model import TrackerFields, TrackerSettings
from sprintforecast.sources.jira import TOKEN_ENV, JiraSource

pytestmark = pytest.mark.jira_live

URL = os.environ.get("SPRINTFORECAST_JIRA_URL")
JQL = os.environ.get("SPRINTFORECAST_JIRA_JQL")
TOKEN = os.environ.get(TOKEN_ENV)


@pytest.mark.skipif(
    not (URL and JQL and TOKEN),
    reason="set SPRINTFORECAST_JIRA_URL, SPRINTFORECAST_JIRA_TOKEN and SPRINTFORECAST_JIRA_JQL",
)
def test_live_connection_fields_and_fetch():
    settings = TrackerSettings(
        kind="jira",
        base_url=URL,
        query=JQL,
        fields=TrackerFields(
            estimate=os.environ.get("SPRINTFORECAST_JIRA_ESTIMATE"),
            remaining=os.environ.get("SPRINTFORECAST_JIRA_REMAINING"),
            epic=os.environ.get("SPRINTFORECAST_JIRA_EPIC"),
        ),
    )
    assert TOKEN is not None
    with JiraSource(settings, TOKEN) as source:
        assert source.test_connection()
        fields = source.resolve_fields()
        assert fields.sprint, "no Sprint field found by its schema (Jira Software missing?)"
        tickets = source.fetch()
    keys = [tk.key for tk in tickets]
    assert len(keys) == len(set(keys))
    assert all(tk.key and tk.title is not None for tk in tickets)
    print(f"live: {len(tickets)} tickets read")
