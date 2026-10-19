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
    "absence_state": Field(
        title="Stand der Fehltage",
        what="Je Sprint gibt es drei Stände: „unbekannt“ (nichts erfasst: die Kapazität kommt "
        "aus Kalender und Personenliste, die Fehltage werden nach den letzten Sprints "
        "geschätzt), „angekündigt“ (Prognose aus der PO-Vorplanung, noch nicht bestätigt) "
        "und „bestätigt“ (Fehltage eingetragen oder ausdrücklich „niemand fehlt“ bestätigt). "
        "„Weiter ohne Bestätigung“ bestätigt nichts: Der Sprint bleibt „unbekannt“.",
        source="Seite „Sprint vorbereiten: Fehltage“ (Spalte „Niemand fehlt“) bzw. Planning, "
        "Schritt 1.",
        example="Sprint 2026.23: keine Einträge, „Niemand fehlt“ angehakt → bestätigt, volle "
        "Besetzung",
    ),
    "fte": Field(
        title="FTE und Arbeitswoche",
        what="FTE ist der Anteil an den Arbeitstagen der Person, den sie im Team arbeitet "
        "(1 = alle ihre Arbeitstage). Die Arbeitswoche (z. B. mon,tue,wed,thu) legt fest, welche "
        "Wochentage ihre Arbeitstage sind. Teilzeit bitte nur einmal abbilden: Entweder die "
        "volle Arbeitswoche mit FTE 0,8 oder die Vier-Tage-Woche mit FTE 1 – nicht beides, sonst "
        "wird doppelt abgezogen (10 Tage → 8 × 0,8 = 6,4 statt 8 PT).",
        source="Arbeitsvertrag bzw. Absprache mit der Person (Seite Personen).",
        example="10 Arbeitstage im Sprint: Mo–Fr + FTE 0,8 → 8 PT · mon,tue,wed,thu + FTE 1 → "
        "8 PT · Mo–Fr + FTE 0,5 (halbtags) → 5 PT",
    ),
    "overhead": Field(
        title="Abzug für Scrum-Termine",
        what="Zeit für Dailys, Planning, Review, Retro und Refinement, die nicht für Tickets "
        "zur Verfügung steht. Wahlweise in Prozent oder als feste PT je Person und Sprint "
        "(× FTE) – beides ist derselbe Abzug in zwei Einheiten, die Felder gleichen sich ab. "
        "Sind PT je Person gesetzt, gelten sie statt der Prozent. Der Abzug wirkt gleich für "
        "bestätigte, angekündigte und erwartete Fehltage: erst Feiertage und Fehltage, dann "
        "der Abzug. Gerundet wird erst bei der Anzeige und beim Einfrieren.",
        source="Team-Einstellungen (Abzug für Scrum-Termine).",
        example="1 PT je Person bei 10 Arbeitstagen entspricht 10 %; Vollzeit: −1 PT, halbtags "
        "(FTE 0,5): −0,5 PT",
    ),
    "capacity": Field(
        title="Kapazität",
        what="Verfügbare Personentage (PT) des Teams im Sprint. Wird normalerweise aus "
        "Personenliste, Feiertagen und Fehltagen berechnet und beim Review eingefroren.",
        source="Automatisch. Nur manuell eintragen, wenn es keine Personenliste gibt.",
        example="5 Personen × 10 Tage − 6.5 Fehltage = 43.5",
    ),
    "forecast_ist": Field(
        title="Commitment",
        what="Die im Sprint Planning für DIESEN Sprint zugesagte Menge: Summe der Schätzungen "
        "aller Tickets, die zu Sprintbeginn im Sprint liegen. Nicht die Velocity des Vorsprints; "
        "später hinzugekommene Tickets zählen zum Scope Creep.",
        source="Direkt nach dem Planning: Summe der Schätzungen auf dem Board bzw. in Jira im "
        "Sprint-Bericht/Velocity-Diagramm der Wert „Commitment“. Entspricht Überkipper + "
        "Backlog; leer gelassen wird es mit dieser Summe aus der Kontrollrechnung vorbelegt.",
        example="15.5",
    ),
    "velocity": Field(
        title="Velocity",
        what="Im Sprint tatsächlich erledigte Menge: Schätzungen der fertigen Tickets plus – "
        "nach Teampraxis – die im Sprint erledigten Teilanteile offener Tickets (Schätzung des "
        "Tickets, nicht der tatsächliche Aufwand). Siehe „Erledigt je Produkt“.",
        source="Im Review: Sprint-Bericht bzw. in Jira im Velocity-Diagramm der Wert „Completed“.",
        example="13.5",
    ),
    "scope_creep": Field(
        title="Scope Creep",
        what="Anteil der Arbeit, die nach dem Planning in den Sprint gekommen ist, bezogen auf "
        "das Commitment (0.3 = 30 %). Leer lassen, wenn unbekannt – nicht 0 eintragen.",
        source="Sprint-Bericht: nachträglich hinzugefügte Schätzungen / Commitment.",
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
        "Kontrollrechnung; Überkipper + Backlog ergibt das Commitment.",
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
        what="Im Sprint für das Produkt tatsächlich erledigte Menge: Schätzungen der fertigen "
        "Tickets plus die im Sprint erledigten Teilanteile offener Tickets (Teampraxis). Die "
        "Summe über die Produkte entspricht höchstens der Velocity. Diese Zählweise sollte im "
        "Team einheitlich sein – sonst sind Velocity und Erledigt zwischen Teams oder über eine "
        "Umstellung hinweg nicht vergleichbar.",
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
        "auch für künftige Sprints. Sind keine bekannt, ausdrücklich „Niemand fehlt“ bestätigen. "
        "Ohne Bestätigung bleiben die Fehltage „unbekannt“ und werden nach den letzten "
        "Sprints geschätzt.",
        page="fehltage",
        cli="sprintforecast fehltage TEAM [SPRINT]",
    ),
    Step(
        when="Vor dem Planning / PO-Planung",
        title="Forecast ansehen",
        text="Zeigt den Forecast PLAN für den laufenden und die kommenden Sprints – die "
        "empfohlene Planungsmenge, aufgeteilt in Roadmap und Kleinkram. Die Startseite führt "
        "über drei Aufgaben (Sprint vorbereiten, Planning, Sprint abschließen) zur jeweils "
        "nächsten sinnvollen Seite.",
        page="forecast",
        cli="sprintforecast forecast TEAM",
    ),
    Step(
        when="Vor dem Planning (POs)",
        title="PO-Vorplanung je Produkt",
        text="Nur mit eingeschalteter Produktverteilung (Einstellungen). Betreut das Team "
        "mehrere Produkte, tragen die POs ein, wie viel sie je Produkt vorsehen – im "
        "Vergleich zum Standard (verfügbare Menge / Anzahl Produkte).",
        page="vorplanung",
        cli="sprintforecast produkte TEAM --vorplanung",
    ),
    Step(
        when="Sprint Planning (Sprintstart)",
        title="Planning in drei Schritten",
        text="1. Bekannte Fehltage für den Sprint eintragen. 2. Mit dem Forecast PLAN die "
        "Tickets einplanen, optional je Produkt. 3. Vor dem Sprintstart das Commitment (die "
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
        "Historie nicht ändern. Produktwerte werden nur auf den Boards (Vorplanung, Planning, "
        "Review) erfasst; die Produktverteilung wertet sie nur aus.",
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
        text="Nur mit eingeschalteter Produktverteilung. Neue Produkte (mit PO, falls "
        "„Zuordnung PO“ an ist) und Beginn anlegen, abgegebene mit „bis“ beenden statt "
        "löschen – so bleiben vergangene Auswertungen erhalten.",
        page="produktliste",
        cli="sprintforecast produktliste TEAM",
    ),
]


TERMS: list[tuple[str, str]] = [
    ("Kapazität", "Verfügbare Personentage im Sprint (immer PT, auch bei SP-Teams)."),
    (
        "Commitment",
        "Die im Planning zugesagte Menge – die Zusage zu Sprintbeginn, kein Ergebnis (früher "
        "„Forecast IST“; die Datei-Schlüssel heißen weiter forecast_ist).",
    ),
    ("Velocity", "Im Sprint erledigte Menge."),
    (
        "Normierte Velocity",
        "Velocity / Kapazität × Referenzkapazität. Macht Sprints mit Urlaub und voll "
        "besetzte Sprints vergleichbar. Dieselbe Größe wie der Fokusfaktor, nur mit "
        "Referenzkapazität skaliert; die Referenzkapazität ändert den Forecast PLAN nicht.",
    ),
    (
        "Fokusfaktor",
        "Velocity / Kapazität (= normierte Velocity / Referenzkapazität). Nicht zwischen Teams "
        "vergleichbar, da er von der Schätzeinheit abhängt; sinnvoll ist der Verlauf im eigenen "
        "Team.",
    ),
    (
        "Ø (gleitend)",
        "Durchschnitt der letzten Sprints mit Wert (Standard 5, einstellbar). Sprints ohne "
        "Wert zählen nicht mit, das Fenster reicht dann weiter zurück.",
    ),
    (
        "Trend",
        "Fortschreibung des Durchschnitts in die Zukunft. Standard „konstant“ (letzter "
        "Durchschnitt). „Linear“ und „klassisch“ schreiben auch Rauschen fort und müssen "
        "ausdrücklich gewählt werden; bei dünner Historie gilt „konstant“.",
    ),
    (
        "Trend-Modi",
        "Beispiel: Der Durchschnitt war zuletzt 44, davor 40. "
        "Konstant (Standard): die nächsten Sprints bleiben bei 44, 44, 44. Robust, folgt aber "
        "keiner Entwicklung. "
        "Linear: der letzte Schritt (+4) wird fortgesetzt: 48, 52, 56. "
        "Klassisch: erst linear (48), dann prozentual wie zuletzt (+10 %: 52,8), danach "
        "wieder linear (57,6). "
        "Linear und klassisch schreiben auch zufällige Schwankungen fort; die Prognose kann dann "
        "steigen oder fallen und liegt bei längerem Horizont schnell außerhalb der Spanne. Sie "
        "passen nur bei einem belegten, stabilen Trend. Reicht die Historie nicht (weniger "
        "Sprints mit Wert als für den Modus nötig), gilt „konstant“; das steht dann als Hinweis "
        "dabei. Die Prognose wird nie negativ. Den Modus kann man jederzeit unter Team "
        "verwalten → Einstellungen wechseln; es gehen keine Daten verloren, nur die Prognose "
        "wird neu berechnet.",
    ),
    (
        "Prognose aktuell / beim Planning",
        "Prognose aktuell: der heute berechnete Forecast PLAN. Prognose beim Planning: der im "
        "Planning eingefrorene Stand (Basis der Verteilung je Produkt). Die Differenz zeigt, "
        "wie sich die Prognose seitdem verändert hat.",
    ),
    (
        "Spanne",
        "Forecast mit der niedrigsten und höchsten normierten Velocity der letzten Sprints. "
        "Bei weniger als 5 Sprints mit Velocity nur ein grober Hinweis.",
    ),
    (
        "Erledigt",
        "Fertige Tickets plus im Sprint erledigte Teilanteile offener Tickets (Teampraxis).",
    ),
    (
        "Forecast PLAN",
        "Empfohlene Planungsmenge: n. Velocity-Trend / Referenzkapazität × Kapazität, abgerundet. "
        "Nie negativ.",
    ),
    (
        "Roadmap",
        "Reservierter Anteil des Forecast PLAN für Roadmap-Themen (Standard 80 %). Es ist eine "
        "Aufteilung der Prognose, kein weiterer Wert: Roadmap + Kleinkram = Forecast PLAN.",
    ),
    (
        "Funktionsbereiche",
        "Drei optionale Bereiche, unabhängig voneinander in den Einstellungen zuschaltbar "
        "(bei neuen Teams aus): Produktverteilung (mehrere Produkte), Zuordnung PO "
        "(Product Owner je Produkt) und Produktionszugriff (nur ein Teil der Personen darf "
        "bestimmte Tickets bearbeiten). Ausgeschaltete Bereiche blenden Seiten, Spalten und "
        "Hinweise aus; erfasste Werte bleiben in den Dateien erhalten.",
    ),
    (
        "Angekündigte Fehltage",
        "Von den POs in der Vorplanung eingetragene Fehltage (Prognose, noch nicht bestätigt). "
        "Nicht zu verwechseln mit den erwarteten Fehltagen.",
    ),
    (
        "Erwartete Fehltage",
        "Schätzung nach der Historie (Ø der letzten Sprints mit bestätigten Fehltagen) für "
        "Sprints, deren Fehltage unbekannt sind. Rechnerisch, nicht von jemandem eingetragen.",
    ),
    ("Kleinkram", "Rest des Forecast PLAN für Bugs, Support und Kleinigkeiten."),
    ("Fulfillment", "Velocity / Commitment – wie gut wurde die Zusage gehalten?"),
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

# Zusammenarbeit über Git: Erklärungen für die Hilfeseite (Titel, Text).
GIT_HELP: list[tuple[str, str]] = [
    (
        "Speichern und teilen",
        "Der Knopf in der Seitenleiste sichert zuerst deine Änderungen (als Commit), holt dann "
        "die Änderungen der anderen vom Server, führt beides zusammen und lädt das Ergebnis "
        "hoch. Deine eigenen Änderungen sind dadurch immer gesichert, bevor etwas Fremdes "
        "dazukommt. Es gilt das einfache Modell „ein Branch, immer synchron halten“.",
    ),
    (
        "Stand in der Seitenleiste",
        "„noch nicht geteilt“ sind eigene Commits, die der Server noch nicht kennt; „neu von "
        "anderen“ sind Commits auf dem Server, die du noch nicht hast. Der Serverstand wird "
        "nur beim Klick auf „Stand prüfen“ und beim Teilen abgefragt; die Angabe „geprüft vor "
        "… Min.“ zeigt, wie aktuell er ist.",
    ),
    (
        "Änderungen anderer",
        "Vor dem Teilen listet die Seitenleiste, was andere seit deinem letzten Abgleich "
        "geändert haben (wer, wann, welche Dateien). Nach dem Teilen steht dort, was "
        "übernommen wurde.",
    ),
    (
        "Zusammenführen und Konflikte",
        "Ändern zwei Personen verschiedene Werte derselben Datei (z. B. Fehltage von Anna und "
        "von Ben im selben Sprint), werden sie automatisch vereinigt. Nur wenn beide denselben "
        "Wert unterschiedlich geändert haben, fragt die App auf der Seite „Konflikte lösen“ "
        "je Eintrag: „Meine Änderung“ oder „Andere Änderung“. Solange ein Konflikt offen ist, "
        "ist die Bearbeitung gesperrt. Nichts geht verloren; „Zusammenführen abbrechen“ "
        "verwirft das Zusammenführen und behält die eigenen Änderungen.",
    ),
    (
        "Prüfung nach dem Zusammenführen",
        "Nach jedem Zusammenführen läuft die Gesamtvalidierung: Ein Zusammenführen kann "
        "technisch gelingen und fachlich ungültig sein (z. B. zwei feste Produktanteile von "
        "je 60 %). Neue Fehler halten das Hochladen an, die Liste zeigt sie; nach der "
        "Korrektur genügt „Speichern und teilen“, oder bewusst „Trotzdem teilen“.",
    ),
    (
        "Veraltete Eingaben",
        "Ändern sich die Dateien, während eine Seite offen ist (Teilen, andere Programme), "
        "verwirft die App nicht gespeicherte Eingaben mit einem Hinweis und lädt neu, statt "
        "fremde Änderungen zu überschreiben.",
    ),
    (
        "Änderungen verwerfen",
        "Auf der Seite „Änderungen und Verlauf“ lassen sich einzelne Dateien oder alle offenen "
        "Änderungen verwerfen. Vorher zeigt die App, was verloren geht (Datei, Status, "
        "Zeilen), und verlangt eine Bestätigung. Zur Sicherheit landet eine Kopie im "
        "Papierkorb unter `.git`.",
    ),
    (
        "Verlauf und früheren Stand wiederherstellen",
        "Der Verlauf zeigt je Team, Sprint oder Datei, wer wann was geändert hat. Ein "
        "früherer Stand lässt sich wiederherstellen; das ist selbst eine neue Änderung und "
        "kann über „Diese Änderung zurücknehmen“ rückgängig gemacht werden. Offene "
        "Änderungen im betroffenen Bereich müssen vorher gespeichert oder verworfen werden.",
    ),
    (
        "Tags verwalten",
        "Tags (z. B. `team/2026.21`) markieren abgeschlossene Reviews. Sie lassen sich "
        "anzeigen, nachträglich an einen beliebigen Stand setzen und löschen; die App gleicht "
        "sie mit dem Server ab und meldet, wenn das nicht gelang (der Tag bleibt dann lokal). "
        "Mit „Mit dem Server abgleichen“ (fragt den Server, nur auf Klick) zeigt die Liste, "
        "ob ein Tag nur lokal, nur auf dem Server oder an einem anderen Stand existiert. "
        "Ein nur lokaler Tag lässt sich mit „Zum Server übertragen“ nachholen; gelöscht "
        "werden können auch Tags, die es nur auf einer Seite gibt.",
    ),
    (
        "Server mit fremder Historie",
        "Enthält der Server eine ganz andere Historie als der Datenordner (meist ist ein "
        "falsches Repository verbunden, z. B. ein Code-Repository), führt „Speichern und "
        "teilen“ nichts zusammen und lädt nichts hoch; die eigenen Änderungen bleiben lokal "
        "gesichert. Die Seitenleiste nennt Server und Branch. Ist es das falsche Repository, "
        "lässt sich die Adresse auf der Seite „Datenordner“ unter „Server (Remote)“ ändern "
        "(der Link „Server-Adresse ändern“ führt dorthin). Nur wenn der Server wirklich das "
        "richtige Daten-Repository ist, lässt sich das Zusammenführen mit dem Kästchen „Ja, "
        "beide Historien zusammenführen“ und dem Knopf darunter bewusst bestätigen; "
        "„Abbrechen“ ändert nichts.",
    ),
    (
        "Zwischen Datenordnern umschalten",
        "Oben in der Seitenleiste stehen der aktive Datenordner (mit dem übergeordneten "
        "Ordner) und sein Branch. Unter „Datenordner wechseln“ und auf der Seite „Datenordner“ "
        "lassen sich die zuletzt benutzten Ordner umschalten. Der Datenordner gilt je "
        "Browser-Fenster: Wechselt ein Fenster, arbeiten andere offene Fenster in ihrem Ordner "
        "weiter; neu geöffnete Fenster starten im zuletzt gewählten. Beim Wechsel werden nicht "
        "gespeicherte Eingaben in Formularen und alle Zwischenspeicher des alten Ordners "
        "verworfen; vorgemerkte Tags, die Commit-Nachricht und offene Änderungen im alten Ordner "
        "bleiben dort erhalten und erscheinen beim Zurückwechseln wieder.",
    ),
    (
        "Server nicht erreichbar (offline)",
        "Deine Änderungen werden trotzdem lokal gesichert. Später erneut „Speichern und "
        "teilen“ wählen, wenn Internet bzw. VPN wieder da ist. Stimmt die Adresse nicht "
        "(Tippfehler, Server umgezogen), lässt sie sich auf der Seite „Datenordner“ unter "
        "„Server (Remote)“ ändern.",
    ),
    (
        "Repository nicht gefunden",
        "Antwortet der Server, kennt unter der eingetragenen Adresse aber kein Repository (oder "
        "verschweigt es, weil dir die Berechtigung fehlt), meldet die App „Repository nicht "
        "gefunden“ statt „Server nicht erreichbar“: bei „Verbindung prüfen“, beim Abgleich, "
        "beim Hochladen und beim Klonen. Dann hilft es nicht, Internet oder VPN zu prüfen. "
        "Adresse (Tippfehler, umbenanntes oder verschobenes Repository) und Berechtigung "
        "prüfen; die Adresse lässt sich auf der Seite „Datenordner“ unter „Server (Remote)“ "
        "ändern. Liegt das Repository in einem Ordner oder auf einem Netzlaufwerk, das gerade "
        "nicht verbunden ist, meldet die App dagegen „Server nicht erreichbar“.",
    ),
    (
        "Zertifikat des Servers nicht anerkannt",
        "Antwortet der Server, aber dieser Rechner erkennt sein Sicherheitszertifikat nicht an "
        "(häufig ein Firmenzertifikat oder ein selbst ausgestelltes Zertifikat), meldet die App "
        "das so. Internet oder VPN zu prüfen hilft nicht. Bitte die IT, das Zertifikat auf dem "
        "Rechner zu hinterlegen. Die App ändert dazu keine Git-Einstellungen und speichert "
        "eine Adresse, deren Zertifikat nicht anerkannt wird, nicht.",
    ),
    (
        "Server (Remote) einrichten",
        "Auf der Seite „Datenordner“ zeigt der Abschnitt „Server (Remote)“, welcher Server zum "
        "Datenordner gehört. Dort wird die Adresse eingetragen oder geändert; „Verbindung "
        "prüfen“ testet sie, ohne etwas zu ändern, und „Speichern“ prüft noch einmal und "
        "übernimmt sie nur, wenn die Verbindung klappt. Erlaubt sind https://…, ssh://…, "
        "git@server:pfad und ein vollständiger Ordnerpfad; http:// nur nach ausdrücklicher "
        "Bestätigung. Benutzername, Kennwort und Token gehören nicht in die Adresse (siehe "
        "„Anmeldung“). Ist der Server nicht erreichbar oder fehlt ihm der Branch, lässt sich "
        "die Adresse nur mit ausdrücklicher Bestätigung trotzdem speichern. Wer einem "
        "bestehenden Team beitritt, wählt besser „Repository klonen“ auf derselben Seite.",
    ),
    (
        "Anmeldung",
        "Die Anmeldung übernimmt der Anmeldedienst deines Rechners; die App richtet sie nicht "
        "ein und fragt selbst nicht nach einem Kennwort. Fehlt sie, erklärt die App den "
        "nächsten Schritt. Bei https braucht der Server meist einen Zugangstoken (GitHub: "
        "Personal access token, GitLab: Zugriffstoken mit „write_repository“), den du einmal im "
        "Anmeldedienst deines Rechners hinterlegst (Windows: Anmeldeinformationsverwaltung, "
        "macOS: Schlüsselbund); mit der GitHub-CLI richtet `gh auth setup-git` die Anmeldung "
        "ein. Bei SSH muss der Schlüssel beim Server hinterlegt und im ssh-agent verfügbar "
        "sein.",
    ),
    (
        "SSH-Server noch nicht bekannt (Fingerabdruck)",
        "Verbindet sich der Rechner zum ersten Mal per SSH mit einem Server, oder hat sich "
        "dessen Schlüssel geändert, verlangt SSH, den Fingerabdruck des Servers zu bestätigen. "
        "Die App kann das nicht und fragt auch nicht danach (Git läuft im Hintergrund ohne "
        "Rückfragen); sie meldet es bei „Verbindung prüfen“, beim Abgleich, beim Hochladen, "
        "beim Klonen und bei den Tags. Bitte einmal mit einem SSH- oder Git-Programm zum Server "
        "verbinden und den Fingerabdruck bestätigen, oder die https-Adresse des Repositorys "
        "verwenden; danach noch einmal versuchen. Hat sich der Schlüssel eines bekannten "
        "Servers geändert, vorher beim Betreiber des Servers nachfragen.",
    ),
    (
        "Name und E-Mail-Adresse",
        "Git braucht beides für jeden Commit. Fehlt es, fragt die App danach und trägt es auf "
        "deinen Wunsch in die globale Git-Konfiguration deines Benutzers ein; sonst ändert sie "
        "keine globale Git-Einstellung.",
    ),
    (
        "Gesperrte Datei",
        "Benutzt ein anderes Programm (Git-Client, Editor, Virenscanner, Cloud-Ordner) eine "
        "Datei im Repository, kann Git sie nicht ändern. Andere Programme schließen und "
        "erneut versuchen. Bleibt es dabei, ist nach einem Absturz vielleicht eine Sperrdatei "
        "(`index.lock` im versteckten Ordner `.git`) übrig geblieben. Die App entfernt sie "
        "nicht selbst: Bitte bei der Betreuung des Rechners oder des Repositorys nachfragen, "
        "bevor sie gelöscht wird (läuft noch ein Git-Programm, stört das Löschen dessen "
        "Arbeit). Lässt sich beim automatischen Zusammenführen eine Datendatei nicht "
        "schreiben, hilft Ähnliches: Programme schließen, Schreibschutz prüfen und noch "
        "einmal „Speichern und teilen“ wählen; das Zusammenführen bleibt offen und wird dann "
        "fortgesetzt.",
    ),
    (
        "Datei oder Ordner nicht beschreibbar",
        "Darf Git im Datenordner (oder im versteckten Ordner `.git` darin) nichts schreiben, "
        "meldet die App „Datei oder Ordner nicht beschreibbar“. Meist hat das Benutzerkonto "
        "dort keine Schreibrechte, der Ordner ist schreibgeschützt, oder ein Netzlaufwerk bzw. "
        "Cloud-Ordner ist nicht verbunden oder nur lesbar. Rechte, Schreibschutz und "
        "Verbindung prüfen; hilft das nicht, bei der Betreuung des Rechners nachfragen. Ein "
        "„Permission denied“ bei der Verbindung zum Server betrifft dagegen die Anmeldung "
        "oder die Rechte auf dem Server (siehe „Anmeldung“).",
    ),
    (
        "Git hält den Ordner für unsicher",
        "Lehnt Git einen Ordner ab, weil er einem anderen Benutzerkonto gehört als dem, mit dem "
        "die App läuft („detected dubious ownership“; häufig bei Netzlaufwerken, kopierten "
        "Ordnern oder nach einem Kontowechsel), meldet die App diesen Grund statt „liegt in "
        "keinem Git-Repository“: in der Seitenleiste, im Verlauf, auf der Seite „Datenordner“ "
        "und im Befehl `sprintforecast datenordner`. In einem solchen Ordner legt die App "
        "kein Repository an und schreibt nichts; beim Übernehmen bleibt „Ohne Git "
        "verwenden“. Die App ändert keine Git-Einstellungen und rät auch nicht dazu. Bitte bei "
        "der Betreuung des Rechners nachfragen: Sie kann den Ordner dem eigenen Konto "
        "zuordnen oder ihn bewusst als sicher eintragen.",
    ),
    (
        "Unvollständiges Zusammenführen, detached HEAD",
        "Ist ein früheres Zusammenführen unterbrochen worden, bietet die Seitenleiste „Zusammen"
        "führen abbrechen“ an. Steht das Repository auf keinem Branch (detached HEAD), führt "
        "„Zurück auf den Branch“ zurück; Commits ohne Branch werden vorher auf einem "
        "Rettungsbranch gesichert, dessen Namen die Meldung nennt. Offene Änderungen im "
        "Datenordner werden vor dem Wechsel ebenfalls dort gesichert (als eigener Commit "
        "„Offene Änderungen vor dem Wechsel gesichert“); der Hauptbranch enthält sie nicht, sie "
        "liegen nur auf dem Rettungsbranch (einem eigenen Zweig nur für Gesichertes). Würde "
        "der Wechsel Änderungen außerhalb des Datenordners überschreiben, bleibt alles, wie "
        "es ist: Die App fasst nur den Datenordner an. Diese Änderungen dort in Git sichern oder "
        "verwerfen (die Dateien nennt die „Technische Meldung“). Danach noch einmal "
        "„Zurück auf den Branch“ wählen; der Rettungsbranch "
        "bleibt bestehen und wird dann wieder genannt.",
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
        "angekündigte Fehltage",
        "Fehltage noch nicht bestätigt: Kapazität laut Personenliste mit den in der "
        "PO-Vorplanung eingetragenen angekündigten Fehltagen.",
    ),
    (
        "erwartete Fehltage",
        "Fehltage unbekannt: Kapazität laut Personenliste und Kalender, gemindert um die "
        "durchschnittlichen Fehltage der letzten Sprints mit bestätigten Fehltagen "
        "(Einstellung „Fehltage-Historie“).",
    ),
]

COMMANDS: list[tuple[str, str]] = [
    ("sprintforecast web", "Weboberfläche als App in eigenem Fenster starten"),
    ("sprintforecast web --no-app", "Weboberfläche in einem Browser-Tab statt als App"),
    ("sprintforecast web --no-browser", "Server starten, ohne ein Fenster zu öffnen"),
    ("sprintforecast verknuepfung", "Starter zum Doppelklicken anlegen (Desktop/Startmenü)"),
    (
        "sprintforecast forecast TEAM [--rechenweg SPRINT]",
        "Prognose für laufenden und kommende Sprints",
    ),
    ("sprintforecast fehltage TEAM [SPRINT]", "Fehltage je Person erfassen"),
    (
        "sprintforecast sprints TEAM [--anlegen] [--ende SPRINT=DATUM]",
        "Sprintkalender: kommende Sprints, Enddaten",
    ),
    ("sprintforecast planning TEAM [SPRINT]", "Commitment und Planning-Werte erfassen"),
    (
        "sprintforecast review TEAM [SPRINT] [--commit]",
        "Velocity und Scope Creep erfassen, Kapazität einfrieren",
    ),
    ("sprintforecast personen TEAM [--ehemalige]", "Personen pflegen"),
    ("sprintforecast produktliste TEAM", "Produkte pflegen (PO, Zeitraum)"),
    (
        "sprintforecast produkte TEAM [SPRINT] [--vorplanung]",
        "Verteilung je Produkt anzeigen, PO-Vorplanung erfassen, Saldo",
    ),
    ("sprintforecast einstellungen TEAM", "Team-Einstellungen ändern"),
    ("sprintforecast kapazitaet TEAM [SPRINT]", "Kapazitätsberechnung im Detail"),
    (
        "sprintforecast analyse TEAM [--rest MENGE] [--gesamt] [--anteil PROZENT]",
        "Bandbreite, Fokusfaktor, Puffer, Fertigstellung",
    ),
    ("sprintforecast bericht [TEAM] [--ausgabe PFAD]", "FORECAST.md erzeugen"),
    ("sprintforecast excel TEAM [--ausgabe PFAD]", "Excel-Liste mit Formeln und Trend-Diagramm"),
    (
        "sprintforecast excel-import TEAM DATEI [--uebernehmen]",
        "Excel-Liste einlesen (Vorschau, dann schreiben)",
    ),
    ("sprintforecast init TEAM", "Neues Team anlegen"),
    (
        "sprintforecast pruefen [--streng]",
        "Alle Daten prüfen (für CI und vor dem Commit); meldet auch doppelte Schlüssel und "
        "leere Zahlenfelder",
    ),
    ("sprintforecast datenordner [PFAD]", "Gemerkten Datenordner anzeigen bzw. setzen"),
    ("sprintforecast sprache [de|en]", "Sprache der Oberfläche anzeigen oder einstellen"),
    (
        "sprintforecast aktualisieren",
        "Auf die neueste Version aktualisieren (--auto an|hinweis|aus)",
    ),
    ("sprintforecast hilfe [THEMA]", "Diese Hilfe"),
    (
        "sprintforecast --daten PFAD …",
        "Vor dem Befehl: Datenverzeichnis vorgeben (sonst SPRINTFORECAST_DATEN, das aktuelle "
        "oder das gemerkte Verzeichnis)",
    ),
    (
        "sprintforecast --stichtag DATUM …",
        "Vor dem Befehl: Datum (JJJJ-MM-TT) vorgeben, das als „heute“ gilt – für Rückblicke",
    ),
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
_PLACEHOLDERS = {
    "MENGE": "AMOUNT",
    "THEMA": "TOPIC",
    "PFAD": "PATH",
    "DATUM": "DATE",
    "PROZENT": "PERCENT",
}


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
