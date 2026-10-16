# Konzept: Ticketsystem-Anbindung und Vormerkplanung (optional)

Status: Entwurf, Version 4, noch nichts umgesetzt. Zielgruppe der Funktionen sind Product
Owner (POs). Dieses Dokument beschreibt **nur die optionale Ticketanbindung**. Alles, was ohne
Ticketsystem gilt (Berechnung, Bedienung, Datenordner und Synchronisation), steht in
[konzept-kern.md](konzept-kern.md).

## 1. Ziel

Product Owner sollen, wenn ein Ticketsystem aktiviert ist (zunächst Jira Data Center, später
z. B. GitLab oder GitHub),

1. Ticketdaten direkt in der App nutzen,
2. noch nicht fertig refinete Tickets auf einer Sprint-Zeitleiste **vormerken** und sehen, ob die
   Vormerkung zur Kapazität passt, ohne die Tickets in einen echten Sprint zu legen,
3. das Ergebnis eines Sprints (Zusage, Erledigt, nicht erledigt) mit Ticketdaten als Vorschlag
   erfassen.

## 2. Grundsätze

- **Das Ticketsystem ist eine Option, kein Muss.** Standard ist „kein Ticketsystem“. Dann gibt es
  weder Ticketseiten noch Menüeinträge noch Vormerkungen, und die App arbeitet wie bisher. Die
  **Ticketplanung der POs auf Sprints** wird nur sichtbar, wenn ein Ticketsystem aktiviert ist.
- **Allgemein gültig und Open Source.** Die Software enthält keine Annahmen über eine bestimmte
  Instanz: keine URLs, Feldnamen, Projekte, Labels oder Regeln als Standard. Alles Instanz- und
  Teamspezifische wird in der Einrichtung abgefragt und in der Konfiguration des Teams im
  Daten-Repo abgelegt (ohne Geheimnisse).
- **Wenige, klare Einstellungen.** Eigenheiten wie ein Pro-forma-Refinement-Sprint sind
  abschaltbar, aber es gibt bewusst nur wenige unabhängige Schalter und sinnvolle Standards.
  Ungültige Kombinationen werden abgelehnt.
- **Nur lesend gegenüber dem Ticketsystem.** Es wird nie dorthin geschrieben.
- **Wer verantwortet was:** Das Ticketsystem verantwortet Ticketdaten und Sprintzuordnung. Die
  App verantwortet Vormerkungen (unverbindliche Planungsabsicht) und die festgehaltenen
  Planungs- und Review-Stände (Snapshots).
- **Kapazität und Forecast funktionieren auch ohne Ticketsystem.** Die Anbindung ergänzt, sie
  ist nie Voraussetzung.

## 3. Nicht-Ziele (vorerst)

- Kein Ersatz für das Ticketsystem, keine Ticket-Bearbeitung.
- Keine Vormerkung ohne Ticketsystem (kein manuelles Ticketlisten-Planen).
- Kein Import alter Sprints aus dem Ticketsystem (denkbares späteres Feature).
- Keine Roadmap-/Gantt-Ansicht über mehrere Vorhaben oder Teams.
- Keine Umrechnung zwischen Personentagen und Story Points. Eine spätere Umstellung der Einheit
  erfolgt über einen Stichtag (`unit_since`), nicht über einen Umrechnungsfaktor.
- Keine Prüfung von Verknüpfungsregeln im Ticketsystem (die App zeigt nur an, was fehlt).
- Keine Ableitung der Vormerkung aus Zielstart/Zielende. Diese Felder tragen teils harte
  Deadlines; höchstens später als reine Anzeige „Zieltermin laut Ticketsystem“.
- Weitere Quellen (GitLab, GitHub) erst, wenn eine zweite Anbindung konkret ansteht.

## 4. Einrichtung

### 4.1 Ticketsystem aktivieren

In den Einstellungen des Teams gibt es `ticket_source: none | jira` (Standard `none`). Erst mit
`jira` erscheint die Seite „Ticketsystem“ und, darauf aufbauend, die Vormerkung. Die Seite führt
durch folgende Schritte:

1. Verbindung testen (Adresse, Token).
2. Projekt und Board wählen.
3. Schätzfelder aus der Instanz wählen (Rest, Ursprünglich).
4. **Kandidaten** festlegen (siehe 4.2).
5. Produkt-Tabelle (siehe 7.1).
6. Zusammenfassung und Speichern in `jira.yaml`.

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
  dann ist das Ticketsystem selbst die Vormerkung, und die App zeigt nur die Auslastung der
  künftigen Sprints.
- Expertenoptionen: eigene JQL, kombinierte Produktzuordnung, Linkrichtung. Abhängige
  Einstellungen werden nur bei Bedarf gezeigt. Die Konfiguration hat ein versioniertes Schema.

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
- Die Git-Anmeldung (siehe [Kern-Konzept, Abschnitt D](konzept-kern.md)) ist unabhängig vom
  Token.

## 6. Schätzfelder, Last und Erledigt

### 6.1 Felder

- **Ursprünglicher Umfang** – Schätzung aus dem Refinement.
- **Restaufwand** – aktueller Rest.

### 6.2 Vorgehen im Team und Definitionen

Ohne Ticketsystem tragen die POs Zusage, Erledigt und Nicht erledigt wie bisher von Hand ein.
Mit Ticketsystem entstehen daraus **Vorschläge**:

Am Sprintende schätzt das Team für nicht abgeschlossene Tickets **zwei Zahlen**: den im Sprint
**geleisteten** Anteil und den **neuen Rest**. Der neue Rest wird ins Restfeld geschrieben. Der
geleistete Anteil steht im Ticketsystem nicht; er wird in der App je Ticket erfasst. Fertige
Tickets zählen mit ihrem Rest zum Planning als geleistet.

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

**Vorschlag aus dem Ticketsystem:** Aus den Restständen schlägt die App einen geleisteten Anteil
vor (`max(Rest zum Planning − neuer Rest, 0)`) und markiert Tickets, bei denen der neue Rest
höher ist als der Planungsrest. Die PO bestätigt oder ändert. Ohne die Teamangabe gilt das
Ergebnis nicht als bestätigt, und die bisherigen Werte der Sprint-Datei bleiben maßgeblich.

**Last einer Vormerkung** = Restaufwand, sonst ursprünglicher Umfang (als „Schätzung“
gekennzeichnet), sonst ein lokaler Platzhalter in der Einheit des Teams, sonst „ungeschätzt“.
Die Zahl ungeschätzter Tickets wird je Sprint ausgewiesen; ohne sie gibt es keine vollständige
„passt“-Aussage.

Ein **Fortschritt** je Ticket oder Vorhaben ist schätzungsabhängig und gehört nicht in die erste
Version; später nur als gekennzeichneter Indikator.

## 7. Vormerkung und Auslastung (nur mit aktiviertem Ticketsystem)

- **Speicherung:** eine Datei je Vormerkung, `vormerkungen/<TICKET>.yaml`, mit Ziel-Sprint,
  optionalem Platzhalter und Notiz. Titel und Umfang kommen immer live aus dem Ticketsystem. Der
  Name „Vormerkung“ (statt „Roadmap“) vermeidet die Verwechslung mit dem bestehenden
  Roadmap-Anteil im Forecast.
- **Zuordnung gewinnt das Ticketsystem:** Ein eindeutig bestimmter aktueller oder künftiger
  Sprint gilt für die tatsächliche Zuordnung. Die Last zählt **immer beim Sprint des
  Ticketsystems**, nie beim vorgemerkten Zielsprint. Eine abweichende Absicht bleibt als
  Vergleich sichtbar. Geschlossene Sprints erzeugen keine neue Zusage, und der eingefrorene
  Planning-Stand wird durch spätere Änderungen im Ticketsystem nicht verändert.
- **Abgleich bei jedem Laden:**

| Zustand im Ticketsystem | Reaktion |
|---|---|
| Ticket in aktuellem oder künftigem echten Sprint | Vormerkung „eingeplant“; Last zählt beim Sprint des Ticketsystems; Abweichung vom Ziel-Sprint wird gezeigt |
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
  Komponente) über eine Tabelle; keine Treffer ergeben „nicht zugeordnet“.
- **Tickets mit mehreren Produkten** (Querschnittsthemen) zählen im Gesamtwert immer **einmal
  und unverändert**. Für die Sicht je Produkt gilt:
  - **Standard: gleichmäßige Aufteilung** auf alle Produkte, die das Ticket trifft. Das Ticket
    ist als „geteilt“ markiert.
  - **Option: eigene Aufteilung je Ticket** (Prozent oder Einheiten je Produkt). Sie wird in der
    Vormerkung bzw. im Planning- und Review-Stand gespeichert, nicht im Ticketsystem. Auch
    „produktübergreifend“ (ganz ohne Produktzuordnung) ist ein zulässiger Wert; so lässt sich
    das heutige Vorgehen abbilden, solche Tickets ohne Produkttracking mitzunehmen.
  - Die Summe der Anteile muss genau den Wert des Tickets ergeben; Rundungsreste gehen an das
    erste Produkt, eine Prüfung lehnt Aufteilungen ab, die nicht aufgehen. Dieselbe Aufteilung
    gilt für Last, Zusage und Erledigt, damit Produkt- und Gesamtbilanz zusammenpassen.
  - Widersprüchliche Treffer, die kein echtes Mehrprodukt-Ticket sind (z. B. zwei Labels
    derselben Produktfamilie), erscheinen als „mehrdeutig“, bis die PO es klärt.
  - Ohne Ticketsystem ändert sich nichts: Produktwerte werden wie bisher von Hand erfasst.
- Übergeordnete Vorhaben (Epic oder verlinkter Eintrag eines anderen Projekts) sind optional und
  nur **Lesehilfe**: Tickets lassen sich filtern und gruppieren, je Vorhaben die vorgemerkte
  Last. Gemeint ist der Anteil des Teams im geladenen Umfang. Fehlende Verknüpfung, nicht
  lesbares Ziel und widersprüchliche Zuordnungen sind unterschiedliche Zustände;
  Mehrfachverknüpfungen vervielfachen keine Last. Kein Bestandteil des ersten Nutzens.

## 8. Architektur

```
sprintforecast/
  Kern: capacity, forecast, calendar      (kennt weder Quellen noch Vormerkung)
  sources/    neutrales Ticketmodell + Schnittstelle TicketSource
  vormerkung/ Vormerkungen: Modell + Speicherung
  Adapter jira  im selben Repo, optionaler Zusatz: sprintforecast[jira]
```

- Neutrales Modell: `Ticket` (Schlüssel, Titel, Typ, Status, Labels, Komponenten, Original,
  Rest, Sprint, Links, übergeordnetes Vorhaben), `Sprint`, `Board`.
- Die Schnittstelle bleibt schmal (Sprints laden, Tickets nach benannter Abfrage laden,
  Verbindung testen) und wächst erst bei der zweiten Quelle. Der Jira-Adapter ist ein optionales
  Extra, das beim Import geprüft wird; ein eigenes Plugin-Registrierungsverfahren oder ein
  privates Paket ist nicht nötig, weil die Software nichts Instanzspezifisches enthält.
- Der Kern importiert nie aus `sources/` oder `vormerkung/` (per Test erzwungen). Ohne
  installiertes Extra und mit `ticket_source: none` wird nichts davon geladen.

## 9. Phasen (Ticketsystem)

Voraussetzung ist das Kern-Konzept: Phase K1 (Berechnung) vor der Vormerkung, Phase K3
(Datenordner und Synchronisation) vor dem Betrieb mit mehreren POs.

| Phase | Inhalt | Abnahmekriterium |
|---|---|---|
| **T0 Definitionen** | Definitionen aus 6.2 festschreiben; Format von Planning- und Review-Stand | Bilanz aus 6.2 als Test, auch mit Hochschätzung, Zugang und Entfernung |
| **T1 Spike** | Verbindung, Felder, Kandidaten-Abfrage, Produktzuordnung gegen die echte Instanz auf dem PO-Arbeitsplatz | Σ Rest der Kandidaten stimmt mit dem Board überein; Produktzuordnung trifft ≥ 95 % der Tickets; Token nur im Schlüsselbund |
| **T2 Einrichtung** | `ticket_source`, Seite „Ticketsystem“ (4.1), Nur-GET-Absicherung | Mit `none` ändert sich nichts; mit `jira` lassen sich Verbindung und Felder in der App einrichten |
| **T3 Vormerkung und Auslastung** | `vormerkungen/`, Balken, Spalten, Abgleich, Übernahme, Alterung; Planning-Stand wird ab hier mitgeschrieben | Eine PO bereitet zwei Sprints vor; jedes Ticket zählt einmal; Unbekanntes bleibt sichtbar |
| **T4 Review-Vorschlag** | Vorschlag für geleistet/Erledigt aus dem Review-Stand, Bestätigung durch die PO | Über drei reale Sprints stimmen bestätigte Werte mit den manuellen Werten bis auf erklärbare Differenzen überein; gezielte Fälle für Hochschätzung, Zugang, Entfernung |

Spätere Kandidaten: Vorhaben-Gruppierung, Anzeige „Zieltermin laut Ticketsystem“, Import alter
Sprints, Export des Forecasts je Sprint (CSV/JSON), Drag-and-drop, weitere Quellen.

Jede Phase ist ein eigener, kleiner Pull Request (oder ein Stapel).

## 10. Tests

- Keine echten Netzaufrufe in der CI: gefälschter Server (`httpx.MockTransport`) mit
  aufgezeichneten Antworten; ein manuell auslösbarer Test gegen eine echte Instanz, weil
  Feld-IDs je Instanz verschieden sind.
- Ein Test je Abgleichfall aus 7, Tests für Last, Zusage, Erledigt und die Bilanz (Hochschätzung,
  Zugang, Entfernung, fehlender Eintrittsrest), Tests für die Einstellungen aus 4.2 einschließlich
  ungültiger Kombinationen, AppTest für die neuen Seiten.
- Test, dass mit `ticket_source: none` keine Ticketseite, kein Menüeintrag und keine Vormerkung
  erscheint und kein Ticketmodul geladen wird.
- Tests, dass nur GET gesendet wird und dass Token und Ticketdaten nie in Logs oder
  Fehlermeldungen auftauchen. In Dateien dürfen ausdrücklich nur Ticket-Schlüssel und die
  Zahlen der Snapshots stehen, keine Titel oder Beschreibungen.

## 11. Offene Punkte

- Wie wird der Eintrittsrest von Zugängen erfasst, wenn das Ticketsystem nur den aktuellen Wert
  kennt (Teamangabe beim Review)?
- Welche Kandidaten-Auswahlen soll die Seite „Ticketsystem“ anbieten (Sprint, Status, Label,
  Backlog ohne Sprint, eigene JQL)?
- Soll die App Tickets mit sehr vielen Produkten oder häufig geänderter Aufteilung als Kandidat
  zum Teilen im Refinement melden (Hinweis, keine Pflicht)?
