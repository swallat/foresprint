# Konzept: Ticket-Anbindung und Vormerkplanung

Status: Entwurf, Version 3, noch nichts umgesetzt. Zielgruppe der neuen Funktionen sind
Product Owner (POs). Version 3 arbeitet die Ergebnisse zweier unabhängiger kritischer
Prüfungen und die Vorgaben aus der Teampraxis ein.

## 1. Ziel

Product Owner sollen

1. Ticketdaten aus dem Ticketsystem direkt in der App nutzen (zunächst Jira Data Center),
2. noch nicht fertig refinete Tickets auf einer Sprint-Zeitleiste **vormerken** können, ohne
   sie in einen echten Sprint zu legen, und sehen, ob die Vormerkung zur Kapazität passt,
3. das Ergebnis eines Sprints (Zusage, Erledigt, nicht erledigt) mit Jira-Daten als Vorschlag
   erfassen.

## 2. Grundsätze

- **Allgemein gültig und Open Source.** Die Software enthält keine Annahmen über eine
  bestimmte Jira-Instanz: keine URLs, Feldnamen, Projekte, Labels oder Regeln als Standard.
  Alles Instanz- und Teamspezifische wird in der Einrichtung abgefragt und in der Konfiguration
  des Teams im Daten-Repo abgelegt (ohne Geheimnisse).
- **Wenige, klare Einstellungen.** Eigenheiten wie ein Pro-forma-Refinement-Sprint sind
  abschaltbar, aber es gibt bewusst nur wenige unabhängige Schalter und sinnvolle Standards.
  Ungültige Kombinationen werden abgelehnt, nicht alle denkbaren unterstützt.
- **Nur lesend gegenüber dem Ticketsystem.** Es wird nie nach Jira geschrieben.
- **Wer verantwortet was:** Jira verantwortet Ticketdaten und Sprintzuordnung. Die App
  verantwortet Vormerkungen (unverbindliche Planungsabsicht) und die festgehaltenen
  Planungs- und Review-Stände (Snapshots).
- **Datenhaltung in Git.** Das Daten-Repo ist Speicher und Synchronisationsweg (siehe 8).
- **Kapazität und Forecast funktionieren auch ohne Ticketsystem.** Die Anbindung ergänzt, sie
  ist nie Voraussetzung.

## 3. Nicht-Ziele (vorerst)

- Kein Ersatz für das Ticketsystem, keine Ticket-Bearbeitung.
- Kein Import alter Sprints aus dem Ticketsystem (denkbares späteres Feature).
- Keine Roadmap-/Gantt-Ansicht über mehrere Vorhaben oder Teams.
- Keine Umrechnung zwischen Personentagen und Story Points. Eine spätere Umstellung der Einheit
  erfolgt über einen Stichtag (`unit_since`), nicht über einen Umrechnungsfaktor.
- Keine Prüfung von Verknüpfungsregeln im Ticketsystem (die App zeigt nur an, was fehlt).
- Keine Ableitung der Vormerkung aus Zielstart/Zielende. Diese Felder tragen teils harte
  Deadlines; höchstens später als reine Anzeige „Zieltermin laut Jira“.
- Weitere Quellen (GitHub, GitLab) erst, wenn eine zweite Anbindung konkret ansteht.
- Der volle Einrichtungs-Assistent über alle Einstellungen und eine PO-Startseite sind nicht
  Voraussetzung für den ersten Nutzen (siehe 4 und 11).

## 4. Einrichtung

### 4.1 Erste Version: Seite „Ticketsystem“

Die Schritte für Team, Kalender, Kapazität, Forecast, Personen und Produkte gibt es bereits als
Seiten. Neu gebraucht wird die Jira-Anbindung als geführte Abfolge:

1. Verbindung testen (Adresse, Token).
2. Projekt und Board wählen.
3. Schätzfelder aus der Instanz wählen (Rest, Ursprünglich).
4. **Kandidaten** festlegen (siehe 4.2).
5. Produkt-Tabelle (siehe 7.1).
6. Zusammenfassung und Speichern in `jira.yaml`.

Ein durchgehender Assistent über alle Einstellungen (Team bis Forecast) folgt später, wenn eine
PO-Startseite entsteht.

### 4.2 Einstellungen (bewusst wenige)

| Einstellung | Werte | Standard |
|---|---|---|
| **Kandidaten** | eine benannte Abfrage: „Sprint X“ (z. B. ein Pro-forma-Refinement-Sprint, per ID), „Status“, „Label“, „Backlog ohne Sprint“ oder eigene JQL | Backlog ohne Sprint |
| **Regel „unrefinete Tickets nicht in echten Sprints“** | an / aus | aus |
| **Vormerkung** | `app` (im Daten-Repo) / `aus` | `app` |

- Der Assistent baut die Kandidaten-Abfrage aus der Auswahl, gespeichert wird die Abfrage.
- Was die Kandidaten-Abfrage trifft, gilt als „nicht ready“. Liegt ein solches Ticket **auch**
  in einem echten Sprint und ist die Regel an, ist das ein **Regelverstoß** (Hinweis, keine
  Sperre). Ein gesonderter „Ready“-Schalter entfällt.
- Teams, die unrefinete Tickets in künftigen Sprints planen, stellen die Vormerkung auf `aus`;
  dann ist Jira selbst die Vormerkung, und die App zeigt nur die Auslastung der künftigen
  Sprints.
- Expertenoptionen: eigene JQL, kombinierte Produktzuordnung, Linkrichtung. Abhängige
  Einstellungen werden nur bei Bedarf gezeigt.
- Die Konfiguration hat ein versioniertes Schema.

## 5. Ticketsystem anbinden

### 5.1 Konfiguration (von der Seite „Ticketsystem“ geschrieben)

```yaml
# teams/<team>/jira.yaml (keine Geheimnisse)
schema: 1
base_url: https://<instanz>
project: <PROJEKT>
board_id: <ID>
fields:
  rest: <customfield_…>         # aktueller Restaufwand
  original: <customfield_…>     # Schätzung aus dem Refinement
candidates:
  query: '…{project}…'          # benannte Vorlage mit Platzhaltern
rule_unrefined_in_sprint: false
vormerkung: app                 # app | aus
product_mapping:
  sources: [label, component]   # Reihenfolge
  table: { <wert>: <produkt> }
parent:                         # optional, nur Lesehilfe
  mode: none                    # none | epic | link
  project: <PROJEKT>
  link_type: <Name>
  direction: outward
```

Die Werte kennt die Seite aus der Instanz: Felder und Linktypen werden über die API
vorgeschlagen und per Auswahl bestätigt. In der Software stehen dafür **keine** Vorgaben.

### 5.2 Abfragen

- Benannte Vorlagen mit Platzhaltern; Platzhalter werden nur aus validierten Werten gefüllt.
- Nur benötigte Felder werden geladen (`fields=`), Paging über `startAt`/`maxResults`.
- Sprints und Boards über die Agile-API, Tickets über `/rest/api/2/search`.
- Freie JQL gehört nicht in die normale PO-Oberfläche.

### 5.3 Anmeldung

- Jira Data Center: **Personal Access Token** je Person, Header `Authorization: Bearer`.
- Das Token liegt im **Betriebssystem-Schlüsselbund**, alternativ in einer Umgebungsvariable;
  nie in YAML, im Daten-Repo, in Logs oder Fehlermeldungen. Eingabe maskiert, mit „Verbindung
  testen“ (`/rest/api/2/myself`).
- **Bewusst in Kauf genommen:** Die Sichtbarkeit richtet sich nach den Rechten der Person;
  Tokens laufen ab. Die App zeigt verständliche Meldungen (401, 403, TLS) und bleibt ohne Jira
  voll benutzbar. „Kein Ergebnis“ gilt nie als „keine Arbeit“; nicht lesbare Tickets werden als
  „nicht prüfbar“ gezeigt.
- Ein PAT hat die Rechte des Kontos, also möglicherweise Schreibrechte. „Die App liest nur“
  wird technisch abgesichert: alle Aufrufe gehen durch eine Funktion, die nur GET zulässt, mit
  einem Test dafür.
- Cache nur im Prozess (zeitbegrenzt, mit Aktualisieren-Knopf), nicht auf Platte; getrennt nach
  Instanz und Konto, damit ein Kontowechsel keine fremden Daten zeigt.
- Die Git-Anmeldung (siehe 8) ist unabhängig vom Jira-Token.

## 6. Schätzfelder, Last und Erledigt

### 6.1 Felder

- **Ursprünglicher Umfang** – Schätzung aus dem Refinement.
- **Restaufwand** – aktueller Rest.

### 6.2 Vorgehen im Team und Definitionen

Am Sprintende schätzt das Team für nicht abgeschlossene Tickets **zwei Zahlen**: den im Sprint
**geleisteten** Anteil und den **neuen Rest**. Der neue Rest wird ins Restfeld geschrieben. Der
geleistete Anteil steht in Jira nicht; er wird in der App je Ticket erfasst. Fertige Tickets
zählen mit ihrem Rest zum Planning als geleistet.

Zwei Momentaufnahmen werden im Daten-Repo festgehalten (nur Ticket-Schlüssel und Zahlen, keine
Titel oder Beschreibungen):

- **Planning-Stand:** je Ticket der Rest zum Planning. Daraus folgt die Zusage.
- **Review-Stand:** je Ticket Status, neuer Rest, geleisteter Anteil, Eintrittsrest bei
  Zugängen. Daraus folgen Erledigt und Nicht erledigt.

Definitionen:

- **Zusage** = Σ Rest zum Planning der Tickets im Sprint.
- **Erledigt** = Σ geleisteter Anteil (fertige Tickets: ihr Rest zum Planning; offene Tickets:
  die Teamangabe).
- **Nicht erledigt** = Σ neuer Rest der nicht abgeschlossenen Tickets.
- **Neuschätzung** je Ticket = neuer Rest + geleistet − Rest zum Planning; positiv heißt
  „Umfang wurde größer“. Sie wird angezeigt, aber nicht als Leistung gezählt.
- **Zugänge** (nach dem Planning hinzugekommen) starten mit ihrem Eintrittsrest; ist er nicht
  bekannt, gilt er als unbekannt und wird vom PO angegeben. Das Original ist dafür kein
  verlässlicher Ersatz.
- **Herausgenommene Tickets** zählen weder zu Erledigt noch zu Nicht erledigt; sie werden mit
  ihrem Rest zum Planning gesondert aufgeführt.

**Bilanz:** Zusage + Zugänge − Herausgenommen = Erledigt + Nicht erledigt − Neuschätzung. Sie
muss aufgehen und ist Gegenstand eines Tests.

**Vorschlag aus Jira:** Aus den Restständen schlägt die App einen geleisteten Anteil vor
(`max(Rest zum Planning − neuer Rest, 0)`) und markiert Tickets, bei denen der neue Rest höher
ist als der Planungsrest. Die PO bestätigt oder ändert. Ohne die Teamangabe gilt das Ergebnis
nicht als bestätigt, und die bisherigen Werte der Sprint-Datei bleiben maßgeblich.

**Last einer Vormerkung** = Restaufwand, sonst ursprünglicher Umfang (als „Schätzung“
gekennzeichnet), sonst ein lokaler Platzhalter in der Einheit des Teams, sonst „ungeschätzt“.
Die Zahl ungeschätzter Tickets wird je Sprint ausgewiesen; ohne sie gibt es keine vollständige
„passt“-Aussage.

Ein **Fortschritt** je Ticket oder Vorhaben (z. B. `erledigt / (erledigt + Rest)`) ist
schätzungsabhängig und gehört nicht in die erste Version; später nur als gekennzeichneter
Indikator.

## 7. Vormerkung und Auslastung

- **Speicherung:** eine Datei je Vormerkung, `vormerkungen/<TICKET>.yaml`, mit Ziel-Sprint,
  optionalem Platzhalter und Notiz. Titel und Umfang kommen immer live aus Jira. Der Name
  „Vormerkung“ (statt „Roadmap“) vermeidet die Verwechslung mit dem bestehenden Roadmap-Anteil
  im Forecast.
- **Zuordnung gewinnt Jira:** Ein eindeutig bestimmter aktueller oder künftiger Jira-Sprint
  gilt für die tatsächliche Zuordnung. Die Last zählt **immer beim Jira-Sprint**, nie beim
  vorgemerkten Zielsprint. Eine abweichende Absicht bleibt als Vergleich sichtbar. Geschlossene
  Sprints erzeugen keine neue Zusage, und der eingefrorene Planning-Stand wird durch spätere
  Jira-Änderungen nicht verändert.
- **Abgleich bei jedem Laden:**

| Zustand im Ticketsystem | Reaktion |
|---|---|
| Ticket in aktuellem oder künftigem echten Sprint | Vormerkung „eingeplant“; Last zählt beim Jira-Sprint; Abweichung vom Ziel-Sprint wird gezeigt |
| Ticket in echtem Sprint, trifft Kandidaten-Abfrage, Regel an | Regelverstoß anzeigen |
| Eingeplantes Ticket wieder bei den Kandidaten | Warnung, Ziel-Sprint bleibt |
| Ticket erledigt, nie in einem Sprint | Vormerkung entfällt, Hinweis |
| Ticket weder bei den Kandidaten noch in einem Sprint | Vormerkung bleibt, Warnung |
| Ticket gelöscht oder nicht lesbar | Warnung „nicht prüfbar“, Vormerkung bleibt sichtbar |
| Schätzung geändert | aktuelle Zahl anzeigen |

- **Alterung:** Eine Vormerkung im Status „eingeplant“, deren Sprint abgeschlossen ist, wird
  beim nächsten Laden archiviert und zählt nicht mehr zur Last.
- **Ansichten:**
  - Auslastungsbalken je Zukunfts-Sprint: Forecast PLAN als Linie, darunter gestapelt
    Überläufer-Rest, zugesagt, vorgemerkt, frei; ungeschätzte Tickets ausgewiesen.
  - Sprint-Spalten mit Karten; Verschieben per Auswahlfeld. Drag-and-drop später.
- Streamlit genügt für Tabellen, Auswahl und Diagramme; eine interaktive Planungsfläche ist
  nicht Ziel.

### 7.1 Produktzuordnung und übergeordnete Vorhaben

- Zuordnung eines Tickets zum Produkt in konfigurierbarer Reihenfolge (z. B. Label, dann
  Komponente) über eine Tabelle; widersprüchliche Treffer erscheinen als „mehrdeutig“, keine
  Treffer als „nicht zugeordnet“.
- Übergeordnete Vorhaben (Epic oder verlinkter Eintrag eines anderen Projekts) sind optional und
  nur **Lesehilfe**: Tickets lassen sich filtern und gruppieren, je Vorhaben die vorgemerkte
  Last. Gemeint ist der Anteil des Teams im geladenen Umfang. Fehlende Verknüpfung, nicht
  lesbares Ziel und widersprüchliche Zuordnungen sind unterschiedliche Zustände;
  Mehrfachverknüpfungen vervielfachen keine Last. Kein Bestandteil des ersten Nutzens.

## 8. Datenordner und Synchronisation

- Die App kann den Datenordner im Betrieb wechseln (Seite „Datenordner“: vorhandenen Ordner
  wählen, neues Daten-Repo anlegen, bestehendes klonen). Geplant: aktives Repo und Team
  dauerhaft anzeigen, eine Liste der zuletzt benutzten Ordner als Umschalter; beim Wechsel
  werden ungespeicherte Eingaben behandelt und alte Formularzustände verworfen.
- Wer die App für ein Team ohne gemeinsame POs nutzt, verwendet ein eigenes Daten-Repo.
- Fehltage je Person sind für POs zugänglich, weil sie zur Sprintplanung gehören.
- **Synchronisation über Git.** Heute gibt es Commit in der App. Mindestumfang, damit es für
  Nicht-Techniker alltagstauglich ist:
  1. Ein Knopf „Speichern und teilen“ (Pull, Commit, Push) mit Anzeige des Stands (voraus,
     hinterher, offline) und der Änderungen anderer seit dem letzten Laden.
  2. Veraltete Formulare vor dem Speichern erkennen; eigene Änderungen sichern, bevor
     synchronisiert wird.
  3. Konfliktdateien erkennen, **bevor** die YAML geladen wird; die betroffene Bearbeitung ist
     gesperrt, eine geführte Wiederherstellung wird angeboten.
  4. Ein Zusammenführen auf Schlüsselebene (verschiedene Schlüssel derselben Datei werden
     vereinigt); nur echte Wertkonflikte gehen an den Menschen, in der App mit „meine/andere
     Änderung“, danach läuft die Datenprüfung.
  5. Die Vormerkung liegt in einer Datei je Ticket, und die App schreibt Dateien stabil
     formatiert und sortiert, damit Konflikte selten werden.
  6. Die Git-Anmeldung wird eigens eingerichtet (Credential Manager, SSH-Rückfragen,
     Dateisperren, Zeilenenden unter Windows).
- Alternativ nennt der Pilot einen erreichbaren Git-Ansprechpartner. Die Abnahme erfolgt mit
  zwei gleichzeitig arbeitenden POs und absichtlich erzeugten Konflikten.

## 9. Architektur

```
sprintforecast/
  Kern: capacity, forecast, calendar      (kennt weder Quellen noch Vormerkung)
  sources/   neutrales Ticketmodell + Schnittstelle TicketSource
  vormerkung/ Vormerkungen: Modell + Speicherung
  Adapter jira  im selben Repo, optionaler Zusatz: sprintforecast[jira]
```

- Neutrales Modell: `Ticket` (Schlüssel, Titel, Typ, Status, Labels, Komponenten, Original,
  Rest, Sprint, Links, übergeordnetes Vorhaben), `Sprint`, `Board`.
- Die Schnittstelle bleibt schmal (Sprints laden, Tickets nach benannter Abfrage laden,
  Verbindung testen) und wächst erst bei der zweiten Quelle. Der Jira-Adapter ist ein optionales
  Extra, das beim Import geprüft wird; ein eigenes Plugin-Registrierungsverfahren oder ein
  privates Paket ist nicht nötig, weil die Software nichts Instanzspezifisches enthält.
- Der Kern importiert nie aus `sources/` oder `vormerkung/` (per Test erzwungen).

## 10. Voraussetzung: Forecast-Kern

Die Vormerkung vergleicht Last mit dem Forecast PLAN 2 bis 6 Sprints im Voraus. Eine Prüfung
des bestehenden Kerns ergab Punkte, die davor geklärt werden sollten (Empfehlungen, noch zu
entscheiden):

- Der Standard-Trend (`classic`/`linear`) extrapoliert Rauschen und kann sinken oder negativ
  werden; vorgeschlagen ist `flat` (oder Median) als Standard.
- Kapazität in Sprints ohne bestätigte Fehltage aus Kalender und Personen berechnen, nicht per
  Trend; nur die Fehltage schätzen.
- Bandbreite direkt an der Forecast-Kachel, Stichprobengröße nennen, Formulierungen wie „85 %
  Sicherheit“ abschwächen.
- Eigenschaftstests: konstante Velocity ergibt konstanten Forecast; Plan liegt in der
  Bandbreite; ein Feiertagssprint hat weniger Kapazität als ein Normalsprint.
- PO-Begriffe: z. B. „Forecast IST“ → „Zusage“; der Begriff „Roadmap“ (derzeit ein
  reservierter Anteil) ist umzubenennen, wenn er frei werden soll.

## 11. Phasen

| Phase | Inhalt | Abnahmekriterium |
|---|---|---|
| **0 Kern und Definitionen** | Punkte aus 10; Definitionen aus 6.2 festschreiben; Format von Planning- und Review-Stand | Eigenschaftstests grün; Bilanz aus 6.2 als Test, auch mit Hochschätzung, Zugang und Entfernung |
| **1 Jira-Spike** | Verbindung, Felder, Kandidaten-Abfrage, Produktzuordnung gegen die echte Instanz auf dem PO-Arbeitsplatz | Σ Rest der Kandidaten stimmt mit dem Jira-Board überein; Produktzuordnung trifft ≥ 95 % der Tickets; Token nur im Schlüsselbund |
| **2 Minimale Einrichtung und Sync** | Seite „Ticketsystem“ (4.1), Umschalter für Datenordner, „Speichern und teilen“, Konflikterkennung | Zwei POs arbeiten parallel, einschließlich absichtlicher Konflikte, ohne Terminal und ohne Datenverlust |
| **3 Vormerkung und Auslastung** | `vormerkungen/`, Balken, Spalten, Abgleich, Übernahme, Alterung; Planning-Stand wird ab hier mitgeschrieben | Eine PO bereitet zwei Sprints vor; jedes Ticket zählt einmal; Unbekanntes bleibt sichtbar |
| **4 Review-Vorschlag** | Vorschlag für geleistet/Erledigt aus dem Review-Stand, Bestätigung durch die PO | Über drei reale Sprints stimmen bestätigte Werte mit den manuellen Werten bis auf erklärbare Differenzen überein; gezielte Fälle für Hochschätzung, Zugang, Entfernung |

Spätere Kandidaten: durchgehender Assistent für alle Einstellungen, PO-Startseite,
Vorhaben-Gruppierung, Anzeige „Zieltermin laut Jira“, Import alter Sprints, Export des
Forecasts je Sprint (CSV/JSON), Drag-and-drop, weitere Quellen.

Jede Phase ist ein eigener, kleiner Pull Request (oder ein Stapel).

## 12. Tests

- Keine echten Netzaufrufe in der CI: gefälschter Server (`httpx.MockTransport`) mit
  aufgezeichneten Antworten; ein manuell auslösbarer Test gegen eine echte Instanz, weil
  Feld-IDs je Instanz verschieden sind.
- Ein Test je Abgleichfall aus 7, Tests für Last, Zusage, Erledigt und die Bilanz (Hochschätzung,
  Zugang, Entfernung, fehlender Eintrittsrest), Tests für die Einstellungen aus 4.2 einschließlich
  ungültiger Kombinationen, AppTest für die neuen Seiten.
- Tests, dass nur GET gesendet wird und dass Token und Ticketdaten nie in Logs oder
  Fehlermeldungen auftauchen. In Dateien dürfen ausdrücklich nur Ticket-Schlüssel und die
  Zahlen der Snapshots stehen, keine Titel oder Beschreibungen.
- Ein Zwei-PO-Test mit absichtlich erzeugten Konflikten (Phase 2).

## 13. Offene Punkte

- Wie wird der Eintrittsrest von Zugängen erfasst, wenn Jira nur den aktuellen Wert kennt
  (Teamangabe beim Review)?
- Reicht ein Datenordner-Umschalter mit Liste der letzten Ordner, oder soll er Teams mehrerer
  Daten-Repos gleichzeitig zeigen?
- Welche Kandidaten-Auswahlen soll die Seite „Ticketsystem“ anbieten (Sprint, Status, Label,
  Backlog ohne Sprint, eigene JQL)?
