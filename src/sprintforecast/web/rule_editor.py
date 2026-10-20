"""Editor for the assignment rule of a project: an expression with a live preview of the
tickets it hits and of the conflicts with the rules of other projects."""

from __future__ import annotations

import copy
from typing import Any

import streamlit as st

from sprintforecast.i18n import t
from sprintforecast.model import Rule
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
            "in_sprint; =, !=, ~ (contains), IN, NOT IN; AND, OR, NOT and parentheses."
        )
    )
    with st.expander(t("Example"), icon=":material/help:"):
        st.code(EXAMPLE, language=None)
    stored = format_rule(project.match)
    text = st.text_area(
        t("Rule"),
        value=stored,
        key=f"tickets-{key}-rule-{chosen}-{abs(hash(stored))}",
        help=t("Empty = the project takes no tickets by rule."),
    )
    rule: Rule | None = None
    if text.strip():
        try:
            rule = parse_rule(text)
        except RuleSyntaxError as error:
            st.error(syntax_message(text, error))
            return
        if problems := rule_problems(rule):
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
