# SPDX-License-Identifier: EUPL-1.2
"""Hilfetexte als strukturierte Daten – dargestellt von CLI (`hilfe`) und Weboberfläche."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    title: str
    what: str
    source: str
    example: str


FIELDS: dict[str, Field] = {
    "absences": Field(
        title="Planbare Fehltage",
        what="Arbeitstage, an denen eine Person im Sprint nicht für Sprintarbeit verfügbar ist: "
        "Urlaub, Gleitzeit, Schulung, Konferenz, andere Projekte. Feiertage NICHT eintragen – "
        "die werden automatisch über das Bundesland berücksichtigt.",
        source="Urlaubskalender bzw. Abfrage im Team. Halbe Tage als 0.5.",
        example="2 Tage Urlaub + halber Tag Schulung → 2.5",
    ),
    "capacity": Field(
        title="Kapazität",
        what="Verfügbare Personentage (PT) des Teams im Sprint. Wird normalerweise aus "
        "Personenliste, Feiertagen und Fehltagen berechnet und beim Review eingefroren.",
        source="Automatisch. Nur manuell eintragen, wenn es keine Personenliste gibt.",
        example="5 Personen × 10 Tage − 6.5 Fehltage = 43.5",
    ),
    "forecast_ist": Field(
        title="Forecast IST",
        what="Die im Sprint Planning für DIESEN Sprint zugesagte Menge: Summe der Schätzungen "
        "aller Tickets, die zu Sprintbeginn im Sprint liegen. Nicht die Velocity des Vorsprints; "
        "später hinzugekommene Tickets zählen zum Scope Creep.",
        source="Direkt nach dem Planning: Summe der Schätzungen auf dem Board bzw. in Jira im "
        "Sprint-Bericht/Velocity-Diagramm der Wert „Commitment“. Entspricht Überkipper + "
        "Backlog; leer gelassen wird er mit dieser Summe aus der Kontrollrechnung vorbelegt.",
        example="15.5",
    ),
    "velocity": Field(
        title="Velocity",
        what="Im Sprint tatsächlich fertiggestellte Menge (nur Tickets, die 'Done' sind; "
        "Schätzung des Tickets, nicht der tatsächliche Aufwand).",
        source="Im Review: Sprint-Bericht bzw. in Jira im Velocity-Diagramm der Wert „Completed“.",
        example="13.5",
    ),
    "scope_creep": Field(
        title="Scope Creep",
        what="Anteil der Arbeit, die nach dem Planning in den Sprint gekommen ist, bezogen auf "
        "den Forecast IST (0.3 = 30 %). Leer lassen, wenn unbekannt – nicht 0 eintragen.",
        source="Sprint-Bericht: nachträglich hinzugefügte Schätzungen / Forecast IST.",
        example="4.5 nachträglich bei 15 zugesagt → 0.3",
    ),
    "carryover": Field(
        title="Überkipper (Restaufwand)",
        what="Restaufwand der aus dem Vorsprint übernommenen, nicht fertigen Tickets. "
        "Teil der optionalen Kontrollrechnung – wirkt nur auf das Planning-Delta.",
        source="Sprint-Board beim Planning.",
        example="1.5",
    ),
    "backlog": Field(
        title="Backlog",
        what="Summe der im Planning neu eingeplanten Tickets. Teil der optionalen "
        "Kontrollrechnung; Überkipper + Backlog ergibt den Forecast IST.",
        source="Sprint-Board beim Planning.",
        example="33.6",
    ),
    "corrections": Field(
        title="Korrektur Restaufwände",
        what="Bereits erledigte Anteile von Tickets, die im Planning-Wert noch enthalten sind "
        "(werden abgezogen). Mehrere Werte mit Leerzeichen trennen. Teil der optionalen "
        "Kontrollrechnung – wirkt nur auf das Planning-Delta.",
        source="Tickets mit Teilfortschritt.",
        example="4.25 4.5",
    ),
}


@dataclass(frozen=True)
class Step:
    when: str
    title: str
    text: str
    # Seite der Weboberfläche (Dateiname unter web/seiten ohne .py)
    page: str
    cli: str


WORKFLOW: list[Step] = [
    Step(
        when="Einmalig",
        title="Team einrichten",
        text="Neues Team anlegen (oder die Historie über ein Import-Plugin übernehmen), "
        "dann die Personen mit ihrem FTE-Anteil erfassen.",
        page="neues_team",
        cli="sprintforecast init TEAM",
    ),
    Step(
        when="Jederzeit",
        title="Fehltage pflegen",
        text="Sobald Urlaub, Schulungen o. Ä. bekannt sind, je Person und Sprint eintragen – "
        "auch für künftige Sprints. Ohne Fehltage ist die Kapazität nur geschätzt (Trend).",
        page="fehltage",
        cli="sprintforecast fehltage TEAM [SPRINT]",
    ),
    Step(
        when="Vor dem Planning / PO-Planung",
        title="Forecast ansehen",
        text="Zeigt den Forecast PLAN für den laufenden und die kommenden Sprints – die "
        "empfohlene Planungsmenge, aufgeteilt in Roadmap und Kleinkram.",
        page="forecast",
        cli="sprintforecast forecast TEAM",
    ),
    Step(
        when="Sprint Planning (Sprintstart)",
        title="Planning erfassen",
        text="Forecast IST (die zugesagte Menge) eintragen. Optional die Kontrollrechnung "
        "aus Überkipper, Backlog und Korrekturen: Sie zeigt als Delta, ob die Planung in den "
        "Forecast PLAN passt, und wirkt sich auf keine andere Kennzahl aus.",
        page="planning",
        cli="sprintforecast planning TEAM",
    ),
    Step(
        when="Sprint Review (Sprintende)",
        title="Review erfassen",
        text="Velocity und Scope Creep eintragen. Die Kapazität des Sprints wird dabei "
        "eingefroren, damit spätere Änderungen an der Personenliste die Historie nicht ändern.",
        page="review",
        cli="sprintforecast review TEAM --commit",
    ),
    Step(
        when="Bei Teamänderungen",
        title="Personen und Einstellungen",
        text="Eintritt, Austritt und FTE-Änderungen erfassen; Team-Einstellungen wie "
        "Bundesland oder Referenzkapazität anpassen.",
        page="personen",
        cli="sprintforecast personen TEAM · sprintforecast einstellungen TEAM",
    ),
]


TERMS: list[tuple[str, str]] = [
    ("Kapazität", "Verfügbare Personentage im Sprint (immer PT, auch bei SP-Teams)."),
    ("Forecast IST", "Im Planning zugesagte Menge."),
    ("Velocity", "Im Sprint erledigte Menge."),
    (
        "Normierte Velocity",
        "Velocity / Kapazität × Referenzkapazität. Macht Sprints mit Urlaub und voll "
        "besetzte Sprints vergleichbar.",
    ),
    ("Ø (gleitend)", "Durchschnitt der letzten Sprints (Standard 5, einstellbar)."),
    ("Trend", "Fortschreibung des Durchschnitts in die Zukunft."),
    (
        "Forecast PLAN",
        "Empfohlene Planungsmenge: n. Velocity-Trend / Referenzkapazität × Kapazität, abgerundet.",
    ),
    ("Roadmap", "Anteil des Forecast PLAN für Roadmap-Themen (Standard 80 %)."),
    ("Kleinkram", "Rest des Forecast PLAN für Bugs, Support und Kleinigkeiten."),
    ("Fulfillment", "Velocity / Forecast IST – wie gut wurde die Zusage gehalten?"),
    (
        "Delta",
        "Forecast PLAN − Planning-Summe (Überkipper + Backlog − Korrekturen). Optionale "
        "Kontrollrechnung im Planning; beeinflusst keine andere Kennzahl.",
    ),
]

CAPACITY_SOURCES: list[tuple[str, str]] = [
    ("erfasst", "Wert steht in der Sprintdatei (beim Review eingefroren oder manuell)."),
    ("Personenliste", "Aus Personen, Feiertagen und Fehltagen berechnet."),
    ("Trend", "Für den Sprint sind noch keine Fehltage erfasst – Kapazität geschätzt."),
]

COMMANDS: list[tuple[str, str]] = [
    ("sprintforecast web", "Weboberfläche im Browser starten"),
    ("sprintforecast web --app", "Weboberfläche als App in eigenem Fenster"),
    ("sprintforecast forecast TEAM", "Prognose für laufenden und kommende Sprints"),
    ("sprintforecast fehltage TEAM [SPRINT]", "Fehltage je Person erfassen"),
    ("sprintforecast planning TEAM", "Forecast IST und Planning-Werte erfassen"),
    ("sprintforecast review TEAM", "Velocity und Scope Creep erfassen, Kapazität einfrieren"),
    ("sprintforecast personen TEAM", "Personen pflegen"),
    ("sprintforecast einstellungen TEAM", "Team-Einstellungen ändern"),
    ("sprintforecast kapazitaet TEAM [SPRINT]", "Kapazitätsberechnung im Detail"),
    ("sprintforecast bericht [TEAM]", "FORECAST.md erzeugen"),
    ("sprintforecast init TEAM", "Neues Team anlegen"),
    ("sprintforecast pruefen", "Alle Daten prüfen (für CI und vor dem Commit)"),
    ("sprintforecast hilfe [THEMA]", "Diese Hilfe"),
]

TOPICS: dict[str, str] = {
    "ablauf": "Was ist wann zu tun?",
    "begriffe": "Begriffe und Kapazitätsquellen",
    "felder": "Eingabefelder: Bedeutung, Quelle, Beispiel",
    "team": "Team-Einstellungen",
    "befehle": "Alle Befehle",
}
