"""Editor for the assignment rule of a project: an expression with a live preview of the
tickets it hits and of the conflicts with the rules of other projects."""

from __future__ import annotations

import copy
import re
from typing import Any

import streamlit as st

from sprintforecast.i18n import t
from sprintforecast.model import RULE_SOURCES, Rule, rule_sources
from sprintforecast.ruleexpr import RuleSyntaxError, format_rule, parse_rule
from sprintforecast.storage import Repository, TeamData
from sprintforecast.validate import rule_problems
from sprintforecast.web.ui import pd, save

EXAMPLE = (
    "component = Database AND NOT label IN (maintenance, hotfix) "
    "AND (epic = ABC-200 OR status = Ready)"
)


def syntax_message(text: str, error: RuleSyntaxError) -> str:
    """The error with the place in the text, e.g. ``... (position 12)``."""
    return t("{message} (position {position})", message=str(error), position=error.position + 1)


def known_values(data: TeamData, source: str) -> list[str]:
    """The values of a field on the open tickets, for the insert helper."""
    found = {v for tk in data.tickets if not tk.done for v in tk.facts().get(source, [])}
    return sorted(found, key=str.lower)


def condition_text(source: str, operator: str, values: list[str]) -> str:
    """One condition for the expression; several values turn ``=`` into ``IN`` (and ``!=`` into
    ``NOT IN``)."""
    leaf = Rule(source=source, values=values, contains=operator in ("~", "!~"))
    text = format_rule(leaf if operator in ("=", "~") else Rule(op="none", children=[leaf]))
    return text


def append_condition(
    text: str, condition: str, joiner: str, sources: tuple[str, ...] = RULE_SOURCES
) -> str:
    """The expression with the condition added; an existing OR expression is bracketed first."""
    text = text.strip()
    if not text:
        return condition
    if joiner == "AND":
        try:
            bracket = parse_rule(text, sources).op == "any"
        except RuleSyntaxError:
            bracket = re.search(r"\bor\b", text, re.IGNORECASE) is not None
        if bracket:
            text = f"({text})"
    return f"{text} {joiner} {condition}"


def rule_hits(data: TeamData, rule: Rule, project_id: str) -> list[dict[str, Any]]:
    """The open tickets the rule hits; ``Also matches`` names other projects whose rule hits the
    ticket too (a conflict the order of precedence or the next import has to settle)."""
    others = [p for p in data.projects if p.id != project_id and p.match is not None]
    rows = []
    for ticket in data.tickets:
        facts = ticket.facts()
        if ticket.done or not rule.matches(facts):
            continue
        also = [p.name for p in others if p.match and p.match.matches(facts)]
        rows.append(
            {
                t("Ticket"): ticket.key,
                t("Title"): ticket.title,
                t("Also matches"): ", ".join(also),
            }
        )
    return rows


def rule_editor(repo: Repository, data: TeamData) -> None:
    key = data.team.key
    st.subheader(t("Assignment rules"))
    if not data.projects:
        st.info(t("There are no projects yet. Create one on the tab Settings."))
        return
    names = {p.id: p.name for p in data.projects}
    chosen = st.selectbox(
        t("Project"), list(names), format_func=lambda i: names[i], key=f"tickets-{key}-rule-project"
    )
    project = data.project(chosen)
    assert project is not None
    st.caption(
        t(
            "One expression per project: fields epic, component, label, status, issue_type, "
            "priority, in_sprint; =, !=, ~ (contains), IN, NOT IN; AND, OR, NOT and parentheses."
        )
    )
    with st.expander(t("Example"), icon=":material/help:"):
        st.code(EXAMPLE, language=None)
    sources = rule_sources(data.team.tracker.rule_fields)
    stored = format_rule(project.match)
    text_key = f"tickets-{key}-rule-{chosen}-{abs(hash(stored))}"
    text = st.text_area(
        t("Rule"),
        value=stored,
        key=text_key,
        help=t("Empty = the project takes no tickets by rule."),
    )
    _insert_helper(data, text_key, sources)
    rule: Rule | None = None
    if text.strip():
        try:
            rule = parse_rule(text, sources)
        except RuleSyntaxError as error:
            st.error(syntax_message(text, error))
            return
        if problems := rule_problems(rule, sources):
            st.error("; ".join(problems))
            return
    if rule is None:
        st.info(t("No rule: no ticket is assigned to this project by rule."))
    else:
        rows = rule_hits(data, rule, chosen)
        conflicts = sum(1 for r in rows if r[t("Also matches")])
        st.write(t("{count} open tickets match.", count=len(rows)))
        if conflicts:
            st.warning(t("{count} of them also match another project.", count=conflicts))
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True)
    if st.button(t("Save rule"), type="primary", key=f"tickets-{key}-rule-save"):
        after = copy.deepcopy(data)
        target = after.project(chosen)
        assert target is not None
        target.match = rule
        if save(
            after,
            ["projects.yaml"],
            lambda: [repo.save_projects(key, after.projects)],
            flash=True,
        ):
            st.rerun()


def _insert_helper(data: TeamData, text_key: str, sources: tuple[str, ...]) -> None:
    """Field, operator and values (from the open tickets) picked from lists and added to the
    expression; the text area has no completion while typing."""
    key = data.team.key
    with st.expander(t("Insert condition"), icon=":material/add:"):
        left, middle, right = st.columns([1, 1, 2])
        source = left.selectbox(t("Field"), sources, key=f"tickets-{key}-ins-field")
        operator = middle.selectbox(
            t("Operator"), ["=", "!=", "~", "!~"], key=f"tickets-{key}-ins-op"
        )
        values = right.multiselect(
            t("Values"),
            known_values(data, source),
            accept_new_options=True,
            key=f"tickets-{key}-ins-values-{source}",
        )
        joiner = st.radio(
            t("Join with"), ["AND", "OR"], horizontal=True, key=f"tickets-{key}-ins-join"
        )

        def insert() -> None:
            if values:
                st.session_state[text_key] = append_condition(
                    st.session_state.get(text_key, ""),
                    condition_text(source, operator, values),
                    joiner,
                    sources,
                )

        st.button(t("Insert"), on_click=insert, key=f"tickets-{key}-ins-go")
