# SPDX-License-Identifier: EUPL-1.2
"""Texte aus Datenstrukturen, die erst bei der Anzeige mit ``t(...)`` übersetzt werden.

Dient dem Test auf Vollständigkeit der Übersetzungen (tests/test_i18n.py).
"""

from __future__ import annotations

# Spaltennamen, Status und Wörter, die über eine Variable an t() gehen.
WORDS = [
    "Person", "Arbeitstage", "Feiertage", "Fehltage", "PT", "Wann", "Was", "Befehl", "Feld",
    "Bedeutung", "Quelle", "Beispiel", "Einstellung", "Schlüssel in team.yaml", "bisher", "neu",
    "Name", "Bundesland", "FTE heute", "Zeiträume im Team", "Kennzahl", "Formel", "Rechnung",
    "Produkt", "Sprints", "Σ Standard", "Σ Erledigt", "Saldo", "PO", "ab", "bis", "Sprint",
    "Start", "Letzter Tag", "Status", "abgeschlossen", "laufend", "geplant", "noch ohne Datei",
    "an", "hinweis", "aus", "Sprint-Daten aktualisiert", "Trend",
]  # fmt: skip


def all_static_texts() -> list[str]:
    from sprintforecast.engine import CapacitySource
    from sprintforecast.formulas import GENERAL
    from sprintforecast.guide import CAPACITY_SOURCES, COMMANDS, FIELDS, TERMS, TOPICS, WORKFLOW
    from sprintforecast.products import MEASURES
    from sprintforecast.settings import _REGION, SETTINGS
    from sprintforecast.validate import Level

    texts = list(WORDS)
    for f in FIELDS.values():
        texts += [f.title, f.what, f.source, f.example]
    for step in WORKFLOW:
        texts += [step.when, step.title, step.text]
    for left, right in [*TERMS, *CAPACITY_SOURCES]:
        texts += [left, right]
    texts += [purpose for _, purpose in COMMANDS]
    texts += list(TOPICS.values())
    for s in SETTINGS:
        texts += [s.label, s.help]
        if s.choices and s is not _REGION:
            texts += list(s.choices.values())
    texts += list(MEASURES.values())
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
