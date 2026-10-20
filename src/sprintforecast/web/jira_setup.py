# SPDX-License-Identifier: EUPL-1.2
"""Page "Jira connection": set up the tracker section of team.yaml without editing YAML.

Address, query and field names are edited here and saved to ``team.yaml``; a connection test asks
the instance for the account, the fields (suggestions for the estimate, remaining work and epic)
and the number of tickets the query matches. Only reads happen (``sources.jira``). The page
never takes the token and never stores it: it stays in the environment variable
(``SPRINTFORECAST_JIRA_TOKEN``) or the keychain, and the page only checks whether one is found.
Loaded by ``ui.page_jira`` only (``features.tickets``); the helpers are pure functions so that
tests need no browser."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, replace

import streamlit as st

from sprintforecast.forecast import Forecast
from sprintforecast.i18n import t
from sprintforecast.model import TRACKER_KINDS, TrackerFields, TrackerSettings, base_url_problem
from sprintforecast.sources import SourceError, open_source
from sprintforecast.sources.jira import (
    INSTALL_COMMAND,
    TOKEN_ENV,
    FieldCandidate,
    FieldSuggestions,
    jira_token,
    suggest_fields,
)
from sprintforecast.storage import Repository, TeamData
from sprintforecast.web.ui import page_intro, save

FIELD_SETTINGS = ("estimate", "remaining", "epic")
NOT_SET = ""


@dataclass
class Probe:
    """What the last connection test found (the token is not part of it)."""

    host: str = ""
    account: str = ""
    suggestions: FieldSuggestions | None = None
    tickets: int | None = None
    warnings: list[str] | None = None
    error: str | None = None


def token_source(base_url: str | None) -> str | None:
    """Where a token is found: ``env``, ``keychain`` or None. The value is never returned."""
    if (os.environ.get(TOKEN_ENV) or "").strip():
        return "env"
    return "keychain" if jira_token(base_url) else None


def tracker_from_inputs(
    base: TrackerSettings, kind: str, base_url: str, query: str, fields: dict[str, str]
) -> TrackerSettings:
    """The tracker settings with the edited values; everything else stays as it is."""
    return replace(
        base,
        kind=kind,
        base_url=base_url.strip() or None,
        query=query.strip() or None,
        fields=TrackerFields(**{k: fields.get(k, "").strip() or None for k in FIELD_SETTINGS}),
    )


def field_options(candidates: list[FieldCandidate], current: str | None) -> list[tuple[str, str]]:
    """(value, label) pairs for one field setting: not set, the current value (when it is not a
    candidate), then the candidates, a hint on the first one when the name suggests it."""
    options = [(NOT_SET, t("– not set –"))]
    values = {c.value for c in candidates} | {c.id for c in candidates}
    if current and current not in values:
        options.append((current, t("{name} (current setting)", name=current)))
    for n, c in enumerate(candidates):
        label = f"{c.name} ({c.id})" if c.id != c.name else c.name
        if n == 0 and c.score > 0:
            label += " · " + t("suggestion")
        options.append((c.value, label))
    return options


def run_probe(tracker: TrackerSettings) -> Probe:
    """Connects, asks for the account, the fields and the number of tickets of the query."""
    probe = Probe(warnings=[])
    source = None
    try:
        source = open_source(replace(tracker, kind="jira"))
        probe.host = source.host  # type: ignore[attr-defined]
        probe.account = source.test_connection()  # type: ignore[attr-defined]
        probe.suggestions = suggest_fields(source.list_fields())  # type: ignore[attr-defined]
        assert probe.warnings is not None
        if any(getattr(tracker.fields, k) for k in FIELD_SETTINGS):
            try:
                source.resolve_fields()  # type: ignore[attr-defined]
            except SourceError as e:
                probe.warnings.append(str(e))
        if tracker.query:
            try:
                probe.tickets = source.count_tickets()  # type: ignore[attr-defined]
            except SourceError as e:
                probe.warnings.append(str(e))
    except SourceError as e:
        probe.error = str(e)
    finally:
        if source is not None:
            source.close()  # type: ignore[attr-defined]
    return probe


def _token_section(base_url: str | None) -> None:
    found = token_source(base_url)
    if found == "env":
        st.success(t("A token was found in the environment variable {name}.", name=TOKEN_ENV))
        return
    if found == "keychain":
        st.success(t("A token was found in the keychain."))
        return
    st.warning(
        t(
            "No token found. This page does not take the token and does not store it: set it "
            "yourself, then restart the web interface."
        )
    )
    with st.expander(t("How to set the token"), icon=":material/key:", expanded=True):
        st.markdown(
            t(
                "Create a personal access token in Jira (profile > *Personal Access Tokens* "
                "> *Create token*) and give it to the program as an environment variable "
                "before starting it:"
            )
        )
        st.code(f'export {TOKEN_ENV}="..."          # Linux, macOS', language="bash")
        st.code(f'$env:{TOKEN_ENV} = "..."          # Windows PowerShell', language="powershell")
        st.markdown(
            t(
                "Alternatively store it in the operating system keychain with "
                "`sprintforecast tickets TEAM --set-token` (hidden input in the terminal; "
                "needs the package `keyring`). The environment variable takes precedence."
            )
        )


def _field_inputs(
    key: str, current: TrackerFields, probe: Probe | None, counter: int
) -> dict[str, str]:
    labels = {
        "estimate": t("Estimate (refinement or rough value)"),
        "remaining": t("Remaining work"),
        "epic": t("Epic"),
    }
    helps = {
        "estimate": t(
            "Number field with the estimate made at refinement (often “Original story "
            "points”). Empty = not read."
        ),
        "remaining": t(
            "Number field with the remaining work (often “Story points”). Empty = the estimate "
            "counts."
        ),
        "epic": t(
            "Field that links a ticket to its epic: the epic link, or `parent` when epics are "
            "parents. The project assignment uses it first."
        ),
    }
    suggestions = probe.suggestions if probe else None
    values: dict[str, str] = {}
    for setting in FIELD_SETTINGS:
        widget_key = f"jira-{key}-{setting}-{counter}"
        now = getattr(current, setting) or ""
        if suggestions is None:
            values[setting] = st.text_input(
                labels[setting], value=now, help=helps[setting], key=widget_key
            )
            continue
        options = field_options(getattr(suggestions, setting), now)
        labels_by_value = dict(options)
        values[setting] = st.selectbox(
            labels[setting],
            list(labels_by_value),
            index=list(labels_by_value).index(now) if now in labels_by_value else 0,
            format_func=labels_by_value.__getitem__,
            help=helps[setting],
            key=widget_key,
        )
    return values


def _show_probe(probe: Probe) -> None:
    if probe.error:
        st.error(probe.error)
        return
    st.success(t("Connected to {host} as {name}.", host=probe.host, name=probe.account))
    if probe.tickets is not None:
        st.info(t("The query matches {count} tickets.", count=probe.tickets))
    for warning in probe.warnings or []:
        st.warning(warning)
    if probe.suggestions is not None:
        st.caption(
            t(
                "The field choices in the form now offer the number fields and epic links "
                "of this instance. Components and labels are always read; nothing to set."
            )
        )


def page(repo: Repository, data: TeamData, fc: Forecast) -> None:
    key = data.team.key
    st.header(t("Jira connection"))
    page_intro(
        t(
            "Connect the ticket pre-planning to Jira: address, query and the fields for the "
            "estimates. The connection test only reads."
        ),
        t(
            "The token is **not entered here**. It stays an environment variable (or a "
            "keychain entry) and is never written to the data folder. The test shows the "
            "account of the token, offers the fields of your instance and counts the tickets "
            "of the query. Needs the extra `[jira]`: {command}",
            command=f"`{INSTALL_COMMAND}`",
        ),
    )
    tracker = data.team.tracker
    probe_key, counter_key = f"jira-{key}-probe", f"jira-{key}-n"
    draft_key = f"jira-{key}-draft"
    probe: Probe | None = st.session_state.get(probe_key)
    counter = st.session_state.get(counter_key, 0)
    with st.form(f"jira-{key}-form"):
        kind = st.selectbox(
            t("Ticket source"),
            TRACKER_KINDS,
            index=TRACKER_KINDS.index(tracker.kind) if tracker.kind in TRACKER_KINDS else 0,
            format_func=lambda k: "Jira" if k == "jira" else t("CSV export"),
            key=f"jira-{key}-kind",
        )
        base_url = st.text_input(
            t("Jira address"),
            value=tracker.base_url or "",
            placeholder="https://jira.example.org",
            help=t("Without `/rest/...`; a context path such as `/jira` belongs to it."),
            key=f"jira-{key}-url",
        )
        query = st.text_area(
            t("Query (JQL)"),
            value=tracker.query or "",
            height=100,
            help=t(
                "The tickets to plan. Exclude sub-tasks (`issuetype not in subTaskIssueTypes()`): "
                "they count as tickets of their own."
            ),
            key=f"jira-{key}-query",
        )
        fields = _field_inputs(key, st.session_state.get(draft_key, tracker.fields), probe, counter)
        left, right = st.columns(2)
        test = left.form_submit_button(t("Test connection"), icon=":material/cable:")
        saved = right.form_submit_button(t("Save"), type="primary")
    edited = tracker_from_inputs(tracker, kind, base_url, query, fields)
    if test:
        if problem := _address_problem(edited.base_url):
            st.error(problem)
        elif token_source(edited.base_url) is None:
            st.session_state.pop(probe_key, None)
            st.warning(t("No token found – set it first (see below)."))
        else:
            with st.spinner(t("Asking Jira …")):
                st.session_state[probe_key] = probe = run_probe(edited)
            # new options need new widgets; the typed values stay as the current setting
            st.session_state[counter_key] = counter + 1
            st.session_state[draft_key] = edited.fields
            st.rerun()
    if probe is not None:
        _show_probe(probe)
    _token_section(edited.base_url)
    if saved and _save(repo, data, edited):
        st.session_state.pop(draft_key, None)


def _address_problem(url: str | None) -> str | None:
    if not url:
        return t("Please enter the address of Jira.")
    problem = base_url_problem(url)
    if problem == "credentials":
        return t("The address must not contain credentials.")
    if problem == "extra":
        return t("The address must not contain parameters (?…) or a fragment (#…).")
    if problem is not None:
        return t("The address is not an http or https address.")
    return None


def _save(repo: Repository, data: TeamData, edited: TrackerSettings) -> bool:
    if edited.kind == "jira" and (problem := _address_problem(edited.base_url)):
        st.error(problem)
        return False
    if edited == data.team.tracker:
        st.info(t("No changes."))
        return False
    team = copy.deepcopy(data.team)
    team.tracker = edited
    after = copy.deepcopy(data)
    after.team = team
    return save(after, ["team.yaml"], lambda: [repo.save_team(team)])
