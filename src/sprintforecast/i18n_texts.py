# SPDX-License-Identifier: EUPL-1.2
"""Texte aus Datenstrukturen, die erst bei der Anzeige mit ``t(...)`` übersetzt werden.

Dient dem Test auf Vollständigkeit der Übersetzungen (tests/test_i18n.py).
"""

from __future__ import annotations

# Spaltennamen, Status und Wörter, die über eine Variable an t() gehen.
WORDS = [
    "Person", "Working days", "Holidays", "Absences", "PT", "When", "What", "Command", "Field",
    "Meaning", "Source", "Example", "Setting", "Key in team.yaml", "before", "new",
    "Name", "State", "FTE today", "Periods in the team", "Metric", "Formula", "Calculation",
    "Product", "Sprints", "Σ standard", "Σ done", "Balance", "PO", "from", "until", "Sprint",
    "Start", "Last day", "Status", "finished", "running", "planned", "no file yet",
    "on", "notice", "off", "Sprint data updated", "Trend", "changed", "deleted",
    "new, then deleted", "renamed", "renamed and changed",
    "renamed, then deleted", "copied", "copied and changed",
]  # fmt: skip


def all_static_texts() -> list[str]:
    from sprintforecast.engine import CapacitySource
    from sprintforecast.formulas import GENERAL
    from sprintforecast.guide import (
        CAPACITY_SOURCES,
        COMMANDS,
        FIELDS,
        GIT_HELP,
        TERMS,
        TOPICS,
        WORKFLOW,
    )
    from sprintforecast.preplan import LIGHTS, REASONS, SOURCES, VARIANT_NAMES
    from sprintforecast.products import MEASURES, PRODUCTION_MEASURES
    from sprintforecast.settings import _COUNTRY, SETTINGS
    from sprintforecast.validate import Level

    texts = list(WORDS)
    for f in FIELDS.values():
        texts += [f.title, f.what, f.source, f.example]
    for step in WORKFLOW:
        texts += [step.when, step.title, step.text]
    for left, right in [*TERMS, *CAPACITY_SOURCES]:
        texts += [left, right]
    texts += [purpose for _, purpose in COMMANDS]
    for left, right in GIT_HELP:
        texts += [left, right]
    texts += list(TOPICS.values())
    for s in SETTINGS:
        texts += [s.label, s.help]
        if s.choices and s is not _COUNTRY:
            texts += list(s.choices.values())
    texts += list(MEASURES.values())
    texts += list(PRODUCTION_MEASURES.values())
    texts += [*LIGHTS.values(), *REASONS.values(), *SOURCES.values(), *VARIANT_NAMES.values()]
    texts += list(GENERAL.values())
    texts += [level.value for level in Level]
    texts += [source.value for source in CapacitySource]
    try:
        from sprintforecast.web.ui import PAGES, PLANNING_STEPS
    except ImportError:  # ohne Streamlit
        pass
    else:
        texts += list(PAGES)
        texts += [title for group in PAGES.values() for title, _ in group.values()]
        texts += PLANNING_STEPS
    return list(dict.fromkeys(texts))
