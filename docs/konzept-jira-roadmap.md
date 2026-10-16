# Konzept: Ticket-Anbindung und Vormerkplanung

Status: Entwurf, noch nichts umgesetzt. Zielgruppe der neuen Funktionen sind Product Owner.

## 1. Ziel

Product Owner sollen

1. Ticketdaten aus dem Ticketsystem direkt in der App nutzen (zunächst Jira Data Center),
2. noch nicht fertig refinete Tickets auf einer Sprint-Zeitleiste **vormerken** können, ohne sie in einen echten Sprint zu legen, und sehen, ob die Vormerkung zur Kapazität passt,
3. perspektivisch eine **Roadmap** über Epics bzw. übergeordnete Vorhaben planen.

Das Ticketsystem bleibt die einzige Quelle der Wahrheit. Die App liest nur und schreibt nie
dorthin zurück.

## 2. Nicht-Ziele

- Kein Ersatz für das Ticketsystem, keine Ticket-Bearbeitung.
- Keine Kopie von Ticketinhalten im Daten-Repo (nur Schlüssel und eigene Planungsdaten).
- Keine Speicherung von Zugangsdaten in den Projektdateien.

## 3. Zeitleisten darstellen

Drei Ansichten werden kombiniert:

| Ansicht | Zweck | Umsetzung |
|---|---|---|
| **Auslastungsbalken je Sprint** (Kern) | Je Zukunfts-Sprint: Forecast PLAN als Linie, darunter gestapelt „zugesagt“, „vorgemerkt“, „frei“. Zeigt sofort, ob eine Vormerkung passt. | Altair oder Plotly, nur Anzeige |
| **Sprint-Spalten mit Karten** | Die Vormerkung selbst: eine Spalte je Sprint mit Ticket-Karten (Schlüssel, Titel, Umfang). | `st.columns`; Verschieben per Auswahlfeld oder Button, später Drag-and-drop über eine Komponente |
| **Roadmap-Gantt** (später) | Balken von Start-Sprint bis voraussichtlichem End-Sprint je Vorhaben, mit Fortschritt. | `plotly.express.timeline` auf dem Sprintkalender |

Streamlit kann kein natives Drag-and-drop. Für den Einstieg genügt die Bedienung per Auswahl;
der Mehrwert liegt in der Auslastungsansicht, nicht in der Interaktion.

## 4. Schätzfelder und Einheiten

### 4.1 Zwei Felder

Das Ticketsystem führt zwei Schätzfelder:

- **Ursprünglicher Umfang** – die Schätzung aus dem Refinement,
- **Restaufwand** – der aktuelle Rest (bei Überläufern mit teilerledigtem Aufwand kleiner).

Daraus folgen:

- Fortschritt eines Tickets oder Vorhabens = `1 − Rest / Ursprünglich`.
- **Last einer Vormerkung** = Restaufwand, sonst ursprünglicher Umfang. Fehlen beide, steht ein
  lokaler **Platzhalter** (T-Shirt-Größe oder Spanne) in der Vormerkdatei, damit nicht refinete
  Tickets nicht mit 0 zählen.

### 4.2 Historische Velocity

Der Restaufwand ändert sich laufend. Die Velocity eines **vergangenen** Sprints darf deshalb
nicht aus dem heutigen Restaufwand abgeleitet werden. Zwei Wege:

1. **Snapshot** beim Planning und beim Review (Stand wird in die Sprint-Datei geschrieben; passt
   zu den vorhandenen Feldern `not_done` und `additional_done`). Normalweg.
2. **Changelog-Auswertung** (`expand=changelog`) für die einmalige Rückwirkung auf die Historie.

### 4.3 Umstellung Personentage ↔ Story Points

Der Forecast rechnet mit normalisierter Velocity; beide Einheiten sind möglich, dürfen aber nie
gemischt werden.

- Team-Einstellung `estimation.unit: PT | SP` (Beschriftung und Interpretation der Felder).
- `estimation.since_sprint`: Sprints davor gelten in der alten Einheit.
- `sp_per_pt`: Umrechnungsfaktor für die Historie, damit die Trendlinie vergleichbar bleibt. Die
  App schlägt ihn aus den ersten Sprints nach der Umstellung vor (Ø Velocity neu / Ø Velocity
  alt); der Wert wird bestätigt, nicht automatisch übernommen.
- Die Felder im Ticketsystem behalten ihren Namen; die Einheit kommt allein aus der Konfiguration.
- Die Datenprüfung warnt, wenn ein Sprint Tickets beider Einheiten enthält.

## 5. Abfragen (JQL)

Abfragen werden als **benannte Vorlagen mit Platzhaltern** in der Team-Konfiguration geführt;
zusätzlich gibt es ein „Experten“-Feld für freie JQL.

```yaml
# jira.yaml (keine Geheimnisse)
base_url: https://jira.example.org
board_id: 1234
fields:
  rest: customfield_00001
  original: customfield_00002
use_refinement_sprint: true
refinement_sprint: "Refinement"      # Name des Pro-forma-Sprints, einstellbar
queries:
  backlog: 'project = {project} AND sprint = "{refinement_sprint}" AND resolution = Unresolved ORDER BY Rank'
  closed:  'project = {project} AND sprint = {sprint_id}'
```

- Filter laufen serverseitig; nur benötigte Felder werden geholt (`fields=`), mit Paging über
  `startAt`/`maxResults`.
- Platzhalter werden nur aus validierten Werten (Projekt-Schlüssel, Sprint-ID) gefüllt, nie aus
  freiem Text (keine JQL-Injection).
- Sprints und Boards über die Agile-API (`/rest/agile/1.0`), Tickets über `/rest/api/2/search`.
- Ohne Refinement-Sprint (`use_refinement_sprint: false`) wird das Backlog über eine andere
  Abfrage (Status, Label o. ä.) definiert.

### 5.1 Produktzuordnung und Verknüpfungsregeln

- Zuordnung eines Tickets zum Produkt in konfigurierbarer Reihenfolge, z. B. zuerst Label, dann
  Komponente; eine Tabelle `Label → Produkt` ordnet zu, ohne Treffer gilt „nicht zugeordnet“.
- Die Roadmap kann nach Epic **oder** nach einem verlinkten Eintrag eines anderen Projekts
  gruppieren (`group_by: epic | link:<Projekt>`), falls Vorhaben zentral in einem eigenen Projekt
  geführt werden.
- Verknüpfungsregeln je Tickettyp (`required` / `optional`) werden **in der App** geprüft, nicht
  in JQL: reines JQL kann „kein Link auf Projekt X“ nicht ohne Zusatz-Plugins ausdrücken. Die
  Abfrage holt das Feld `issuelinks`, die App prüft Typ, Zielprojekt und Linktyp und meldet
  Verstöße in der bestehenden Datenprüfung.

## 6. Anmeldung

- Jira Data Center: **Personal Access Token** (ab Version 8.14), Header `Authorization: Bearer`.
- Das Token liegt im **Betriebssystem-Schlüsselbund** (`keyring`), alternativ in einer
  Umgebungsvariable; **nie** in YAML, im Daten-Repo, in Logs oder Fehlermeldungen.
- Eingabe maskiert, mit „Verbindung testen“ (`/rest/api/2/myself`).
- Jede Person sieht nur, was ihr Token sieht.
- Verständliche Meldungen für 401 (abgelaufen), 403 (keine Rechte) und TLS-Fehler;
  Unternehmenszertifikate über den System-Zertifikatsspeicher (`truststore`) oder einen
  konfigurierbaren CA-Pfad.
- Die Weboberfläche lauscht nur auf `localhost`.

## 7. Architektur

```
sprintforecast/
  Kern: capacity, forecast, calendar      (kennt weder Quellen noch Roadmap)
  sources/   neutrales Modell + Schnittstelle TicketSource
  roadmap/   Vormerkungen: Modell + Speicherung
Adapter (Entry-Point-Gruppe sprintforecast.sources):
  jira       im selben Repo, optionaler Zusatz: sprintforecast[jira]
```

- **Neutrales Modell:** `Ticket` (Schlüssel, Titel, Typ, Status, Labels, Komponenten, Ursprünglich,
  Rest, Sprint, Links), `Sprint` (ID, Name, Start, Ende, Status), `Board`.
- **Schnittstelle `TicketSource`:** Sprints laden, Tickets nach benannter Abfrage laden,
  Verbindung testen; dazu **Fähigkeiten** (`has_sprints`, `has_remaining_estimate`, `has_links`),
  weil andere Systeme (GitHub, GitLab) andere Konzepte haben (Meilensteine/Iterationen statt
  Sprints, keine Story Points ohne Zusatzfelder).
- **Plugin-Mechanismus:** Es gibt bereits Entry-Points (`sprintforecast.plugins`). Quellen
  bekommen eine eigene Gruppe `sprintforecast.sources`; der Jira-Adapter registriert sich wie ein
  fremdes Paket. Weitere Quellen sind später ohne Änderung am Kern möglich.
- Die Schnittstelle bleibt bewusst schmal und wird erst bei der zweiten Quelle erweitert.
- **Konfiguration:** `sources:` in der Team-Konfiguration mit `type: jira`; Token je Quelle im
  Schlüsselbund (Dienstname pro Quelle).
- **Cache:** kurzer Zeitspeicher (z. B. 5 Minuten) plus „Aktualisieren“, im Benutzer-Cache-
  Verzeichnis, **nicht** im Daten-Repo (Tickettitel können sensibel sein). Offline-Betrieb mit
  letztem Stand und deutlichem Hinweis.
- **Daten-Repo:** `roadmap.yaml` enthält nur Ticket-Schlüssel, Ziel-Sprint, Platzhalter-
  Schätzung und Notiz. Titel und Umfang kommen immer live aus dem Ticketsystem.

### 7.1 Abgleich bei jedem Laden

| Zustand im Ticketsystem | Reaktion |
|---|---|
| Ticket in echtem Sprint | Vormerkung entfällt, Last zählt als „zugesagt“ |
| Ticket erledigt oder geschlossen | Vormerkung entfällt, Hinweis |
| Ticket gelöscht oder keine Berechtigung | Warnung, Vormerkung bleibt sichtbar |
| Schätzung geändert | Differenz anzeigen |
| Rest größer als Kapazität des Ziel-Sprints | Warnung „passt nicht“ |

## 8. Roadmap (perspektivisch)

- Ebene über den Tickets: Vorhaben (Epic oder verlinkter Eintrag) mit Summe aus Ursprünglich und
  Rest sowie Fortschritt.
- **Prognose des End-Sprints:** Rest ÷ Forecast PLAN der folgenden Sprints, optional anteilig je
  Produkt (`Product.share`).
- Mehrere Teams später durch Zusammenführen mehrerer Team-Verzeichnisse.

## 9. Phasen

| Phase | Inhalt | Ergebnis |
|---|---|---|
| **0 Spike** | Zugriff prüfen: Jira-Version, PAT, Agile-API, Feld-IDs, JQL, TLS, Rate-Limits | Gewissheit, dass alles möglich ist |
| **1 Lesen** | Neutrales Modell und Schnittstelle, Jira-Adapter, Import abgeschlossener Sprints als **Vorschlag** für Review-Werte | sofort nützlich, geringes Risiko |
| **2 Vormerkung** | Backlog laden, Sprint-Spalten, Auslastungsbalken, Abgleich, Einheiten-Umstellung | Kern des Wunsches |
| **3 Roadmap** | Vorhaben, Fortschritt, Gantt, End-Sprint-Prognose | Perspektive |
| **4 Ausbau** | Drag-and-drop, mehrere Teams, weitere Quellen | Komfort |

Jede Phase ist ein eigener, kleiner Pull Request (oder ein Stapel).

## 10. Tests

- Keine echten Netzaufrufe in der CI: gefälschter Server (`httpx.MockTransport`) mit
  aufgezeichneten Antworten.
- Kontrakttest für das Feld-Mapping, ein Test je Abgleichfall aus 7.1, AppTest für die neuen
  Seiten, Tests für die Verknüpfungsregeln und die Einheiten-Umrechnung.
- Test, dass das Token nie in Logs, Fehlermeldungen oder Dateien auftaucht.

## 11. Offene Punkte

- Wie wird der Pro-forma-Sprint zuverlässig erkannt (Name, ID, Board)?
- Was bedeutet „ready“ (Status, Label, Feld) – soll die App nicht-ready-Tickets markieren?
- Wie werden Überläufer in der Last gewichtet, wenn der Restaufwand noch nicht gepflegt ist?
- Wer pflegt Konfiguration und Abfragen (Team oder POs)?
