# SPDX-License-Identifier: EUPL-1.2
"""Hilfetexte als strukturierte Daten – dargestellt von CLI (`hilfe`) und Weboberfläche."""

from __future__ import annotations

import re
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
    "preplanned": Field(
        title="PO-Vorplanung je Produkt",
        what="Menge, die der PO eines Produkts für den Sprint vorsieht – vor dem Planning, als "
        "Grundlage für die Abstimmung zwischen den POs. Im Vergleich steht der Standard "
        "(verfügbare Menge / Anzahl betreuter Produkte).",
        source="PO-Runde bzw. Vorbereitung der POs, z. B. Summe der vorgesehenen Tickets.",
        example="4",
    ),
    "planned": Field(
        title="Planning je Produkt",
        what="Im Sprint Planning für das Produkt eingeplante Menge (Summe der Tickets des "
        "Produkts im Sprint).",
        source="Sprint-Board beim Planning, gefiltert nach Produkt (Komponente, Label, Epic …).",
        example="4.5",
    ),
    "done": Field(
        title="Erledigt je Produkt",
        what="Im Sprint für das Produkt tatsächlich erledigte Menge (Schätzungen der fertigen "
        "Tickets). Die Summe entspricht höchstens der Velocity.",
        source="Im Review: Sprint-Bericht, gefiltert nach Produkt.",
        example="3.75",
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
        title="Künftige Sprints anlegen",
        text="Folgesprints entstehen automatisch aus Sprintlänge und Ende des Vorgängers. Im "
        "Sprintkalender lassen sie sich vorab anlegen und abweichende Längen (z. B. über "
        "Weihnachten) über den letzten Tag festlegen; die folgenden Sprints verschieben sich "
        "mit. Die Kapazität zählt die Arbeitstage des Sprints, der Forecast PLAN skaliert daher "
        "mit der Länge. Brückentage als Fehltage eintragen.",
        page="sprints",
        cli="sprintforecast sprints TEAM [--anlegen] [--ende SPRINT=DATUM]",
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
        when="Vor dem Planning (POs)",
        title="PO-Vorplanung je Produkt",
        text="Betreut das Team mehrere Produkte, tragen die POs ein, wie viel sie je Produkt "
        "vorsehen – im Vergleich zum Standard (verfügbare Menge / Anzahl Produkte).",
        page="vorplanung",
        cli="sprintforecast produkte TEAM --vorplanung",
    ),
    Step(
        when="Sprint Planning (Sprintstart)",
        title="Planning in drei Schritten",
        text="1. Bekannte Fehltage für den Sprint eintragen. 2. Mit dem Forecast PLAN die "
        "Tickets einplanen, optional je Produkt. 3. Vor dem Sprintstart den Forecast IST (die "
        "zugesagte Menge) eintragen; der Forecast PLAN wird dabei eingefroren. Optional die "
        "Kontrollrechnung aus Überkipper, Backlog und Korrekturen (Delta zum Forecast PLAN).",
        page="planning",
        cli="sprintforecast planning TEAM",
    ),
    Step(
        when="Sprint Review (Sprintende)",
        title="Review erfassen",
        text="Velocity, Scope Creep und optional Erledigt je Produkt eintragen. Die Kapazität "
        "des Sprints wird dabei eingefroren, damit spätere Änderungen an der Personenliste die "
        "Historie nicht ändern.",
        page="review",
        cli="sprintforecast review TEAM --commit",
    ),
    Step(
        when="Bei Roadmap-Fragen",
        title="Analyse",
        text="Ergänzend zum Forecast: Bandbreite (konservativ/optimistisch), Fokusfaktor, "
        "Puffer-Empfehlung und „Wann ist es fertig?“ für eine Restmenge.",
        page="analyse",
        cli="sprintforecast analyse TEAM [--rest MENGE]",
    ),
    Step(
        when="Bei Teamänderungen",
        title="Personen und Einstellungen",
        text="Eintritt, Austritt und FTE-Änderungen erfassen; Team-Einstellungen wie "
        "Bundesland oder Referenzkapazität anpassen.",
        page="personen",
        cli="sprintforecast personen TEAM · sprintforecast einstellungen TEAM",
    ),
    Step(
        when="Wenn sich die Produkte ändern",
        title="Produkte pflegen",
        text="Neue Produkte mit PO und Beginn anlegen, abgegebene mit „bis“ beenden statt "
        "löschen – so bleiben vergangene Auswertungen erhalten.",
        page="produktliste",
        cli="sprintforecast produktliste TEAM",
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
        "Standard je Produkt",
        "Verfügbare Menge / Anzahl betreuter Produkte. Verfügbar = Forecast PLAN (beim "
        "Planning eingefroren) oder nur dessen Roadmap-Anteil (Einstellung).",
    ),
    ("Saldo je Produkt", "Σ Erledigt − Σ Standard über mehrere Sprints."),
    (
        "Delta",
        "Forecast PLAN − Planning-Summe (Überkipper + Backlog − Korrekturen). Optionale "
        "Kontrollrechnung im Planning; beeinflusst keine andere Kennzahl.",
    ),
]

CAPACITY_SOURCES: list[tuple[str, str]] = [
    ("erfasst", "Wert steht in der Sprintdatei (beim Review eingefroren oder manuell)."),
    ("Personenliste", "Aus Personen, Feiertagen und Fehltagen berechnet."),
    (
        "Kalender, Fehltage unbekannt",
        "Fehltage noch unbekannt und noch keine Historie: Kapazität laut Personenliste und "
        "Kalender (Feiertage, Sprintlänge), ohne Abzug für Fehltage.",
    ),
    (
        "Trend",
        "Nur für Teams ohne Personenliste: Kapazität wie die normierte Velocity fortgeschrieben.",
    ),
    (
        "voraussichtliche Fehltage",
        "Fehltage noch nicht bestätigt: Kapazität laut Personenliste mit den in der "
        "PO-Vorplanung eingetragenen voraussichtlichen Fehltagen.",
    ),
    (
        "erwartete Fehltage",
        "Fehltage unbekannt: Kapazität laut Personenliste und Kalender, gemindert um die "
        "durchschnittlichen Fehltage der letzten Sprints mit bestätigten Fehltagen "
        "(Einstellung „Fehltage-Historie“).",
    ),
]

COMMANDS: list[tuple[str, str]] = [
    ("sprintforecast web", "Weboberfläche im Browser starten"),
    ("sprintforecast web --app", "Weboberfläche als App in eigenem Fenster"),
    ("sprintforecast verknuepfung", "Starter zum Doppelklicken anlegen (Desktop/Startmenü)"),
    ("sprintforecast forecast TEAM", "Prognose für laufenden und kommende Sprints"),
    ("sprintforecast fehltage TEAM [SPRINT]", "Fehltage je Person erfassen"),
    ("sprintforecast sprints TEAM [--anlegen]", "Sprintkalender: kommende Sprints, Enddaten"),
    ("sprintforecast planning TEAM", "Forecast IST und Planning-Werte erfassen"),
    ("sprintforecast review TEAM", "Velocity und Scope Creep erfassen, Kapazität einfrieren"),
    ("sprintforecast personen TEAM", "Personen pflegen"),
    ("sprintforecast produktliste TEAM", "Produkte pflegen (PO, Zeitraum)"),
    (
        "sprintforecast produkte TEAM [SPRINT] [--vorplanung]",
        "Verteilung je Produkt anzeigen, PO-Vorplanung erfassen, Saldo",
    ),
    ("sprintforecast einstellungen TEAM", "Team-Einstellungen ändern"),
    ("sprintforecast kapazitaet TEAM [SPRINT]", "Kapazitätsberechnung im Detail"),
    (
        "sprintforecast analyse TEAM [--rest MENGE]",
        "Bandbreite, Fokusfaktor, Puffer, Fertigstellung",
    ),
    ("sprintforecast bericht [TEAM]", "FORECAST.md erzeugen"),
    ("sprintforecast init TEAM", "Neues Team anlegen"),
    ("sprintforecast pruefen", "Alle Daten prüfen (für CI und vor dem Commit)"),
    ("sprintforecast datenordner [PFAD]", "Gemerkten Datenordner anzeigen bzw. setzen"),
    (
        "sprintforecast aktualisieren",
        "Auf die neueste Version aktualisieren (--auto an|hinweis|aus)",
    ),
    ("sprintforecast hilfe [THEMA]", "Diese Hilfe"),
]

TOPICS: dict[str, str] = {
    "ablauf": "Was ist wann zu tun?",
    "begriffe": "Begriffe und Kapazitätsquellen",
    "felder": "Eingabefelder: Bedeutung, Quelle, Beispiel",
    "team": "Team-Einstellungen",
    "befehle": "Alle Befehle",
}


# Englische Namen der Befehle (deutsch → englisch); beide funktionieren immer.
COMMAND_ALIASES: dict[str, str] = {
    "hilfe": "help",
    "fehltage": "absences",
    "personen": "people",
    "einstellungen": "settings",
    "analyse": "analysis",
    "bericht": "report",
    "pruefen": "check",
    "kapazitaet": "capacity",
    "produkte": "products",
    "produktliste": "product-list",
    "aktualisieren": "update",
    "verknuepfung": "shortcut",
    "datenordner": "data-dir",
    "sprache": "language",
}
# Englische Themen der Hilfe (englisch → deutsch).
TOPIC_ALIASES: dict[str, str] = {
    "workflow": "ablauf",
    "terms": "begriffe",
    "fields": "felder",
    "commands": "befehle",
}
OPTION_ALIASES: dict[str, str] = {
    "--daten": "--data",
    "--stichtag": "--as-of",
    "--ehemalige": "--former",
    "--verlauf": "--history",
    "--rechenweg": "--explain",
    "--rest": "--remaining",
    "--gesamt": "--total",
    "--anteil": "--share",
    "--ausgabe": "--output",
    "--streng": "--strict",
    "--anzahl": "--count",
    "--anlegen": "--create",
    "--ende": "--end",
    "--vorplanung": "--preplanning",
    "--pruefen": "--check",
    "--erzwingen": "--force",
}
_PLACEHOLDERS = {"MENGE": "AMOUNT", "THEMA": "TOPIC", "PFAD": "PATH", "DATUM": "DATE"}


def command_text(text: str) -> str:
    """Befehle und Optionen in der Schreibweise der eingestellten Sprache."""
    from sprintforecast.i18n import is_english

    if not is_english():
        return text
    text = re.sub(
        r"sprintforecast (\w+)",
        lambda m: f"sprintforecast {COMMAND_ALIASES.get(m.group(1), m.group(1))}",
        text,
    )
    text = re.sub(r"--[a-z]+", lambda m: OPTION_ALIASES.get(m.group(0), m.group(0)), text)
    text = re.sub(
        r"\b(" + "|".join(_PLACEHOLDERS) + r")\b", lambda m: _PLACEHOLDERS[m.group(1)], text
    )
    return re.sub(
        r"(sprintforecast help) (\w+)",
        lambda m: f"{m.group(1)} {_topic_en(m.group(2))}",
        text,
    )


def _topic_en(topic: str) -> str:
    english = {de: en for en, de in TOPIC_ALIASES.items()}
    return english.get(topic, topic)
