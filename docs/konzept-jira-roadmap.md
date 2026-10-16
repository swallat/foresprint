# Konzept: Ticket-Anbindung und Vormerkplanung

Status: Entwurf, Version 2, noch nichts umgesetzt. Zielgruppe der neuen Funktionen sind
Product Owner (POs). Version 2 arbeitet die Ergebnisse einer kritischen Prüfung und die
Vorgaben aus der Teampraxis ein.

## 1. Ziel

Product Owner sollen

1. Ticketdaten aus dem Ticketsystem direkt in der App nutzen (zunächst Jira Data Center),
2. noch nicht fertig refinete Tickets auf einer Sprint-Zeitleiste **vormerken** können, ohne
   sie in einen echten Sprint zu legen, und sehen, ob die Vormerkung zur Kapazität passt,
3. die nächsten Sprints an einer Stelle vorbereiten (Kapazität, Zusagen, Vormerkungen).

## 2. Grundsätze

- **Allgemein gültig und Open Source.** Die Software enthält keine Annahmen über eine
  bestimmte Jira-Instanz: keine URLs, Feldnamen, Projekte, Labels oder Regeln als Standard.
  Alles Instanz- und Teamspezifische wird im **Einrichtungs-Assistenten** abgefragt und in der
  Konfiguration des Teams im Daten-Repo abgelegt (ohne Geheimnisse).
- **Jede Eigenheit ist abschaltbar.** Nicht jedes Team arbeitet mit einem Pro-forma-
  Refinement-Sprint, und nicht jedes Team verbietet unrefinete Tickets in künftigen Sprints.
  Beides ist eine Einstellung, nie eine Voraussetzung.
- **Nur lesend gegenüber dem Ticketsystem.** Es wird nie nach Jira geschrieben.
- **Wer verantwortet was:** Jira verantwortet Ticketdaten und Sprintzuordnung. Die App
  verantwortet Vormerkungen (unverbindliche Planungsabsicht) und die festgehaltenen
  Planungsstände (Snapshots).
- **Datenhaltung in Git.** Das Daten-Repo ist der Speicher und der Synchronisationsweg; Konflikte
  werden mit Git gelöst (siehe 8).
- **Kapazität und Forecast funktionieren auch ohne Ticketsystem.** Die Anbindung ergänzt, sie
  ist nie Voraussetzung.

## 3. Nicht-Ziele (vorerst)

- Kein Ersatz für das Ticketsystem, keine Ticket-Bearbeitung.
- Kein Import alter Sprints aus dem Ticketsystem (denkbares späteres Feature).
- Keine Roadmap-/Gantt-Ansicht über mehrere Vorhaben oder Teams.
- Keine Umrechnung zwischen Personentagen und Story Points. Eine spätere Umstellung der Einheit
  erfolgt über einen Stichtag (`unit_since`), nicht über einen Umrechnungsfaktor.
- Keine Prüfung von Verknüpfungsregeln im Ticketsystem (die App zeigt nur an, was fehlt).
- Weitere Quellen (GitHub, GitLab) erst, wenn eine zweite Anbindung konkret ansteht.

## 4. Einrichtungs-Assistent

Beim Anlegen eines Teams (und später zum Prüfen/Ändern) führt ein Assistent Schritt für Schritt
durch alle Einstellungen, mit kurzer Erklärung je Schritt und einer Zusammenfassung vor dem
Speichern. Schritte, die nicht gebraucht werden, lassen sich überspringen.

| Schritt | Inhalt |
|---|---|
| 1 Team | Name, Einheit (PT/SP), Sprintlänge |
| 2 Kalender | Land, Region, Arbeitswoche |
| 3 Kapazität | Overhead, erwartete Fehltage, Fenster der Fehltage-Historie |
| 4 Forecast | Trend-Modus, Fenster, Rundung |
| 5 Personen und Produkte | Personen mit FTE, Produkte mit Anteilen |
| 6 Planungsregeln | siehe 4.1 |
| 7 Ticketsystem (optional) | Verbindung, Felder, Abfragen, Zuordnung (siehe 5) |
| 8 Zusammenfassung | Prüfung (bestehende Datenprüfung) und Speichern |

### 4.1 Planungsregeln (alle abschaltbar)

| Einstellung | Werte | Wirkung |
|---|---|---|
| Refinement-Sprint | `sprint` (Pro-forma-Sprint, per ID), `query` (eigene Abfrage), `off` | Quelle der Kandidaten für die Vormerkung; bei `off` nur Abfrage oder manuelle Liste |
| Unrefinete Tickets in künftigen Sprints | `verboten` / `erlaubt` | `verboten`: Tickets, die nicht „ready“ sind, aber in einem echten Sprint liegen, werden als Regelverstoß angezeigt. `erlaubt`: künftige Jira-Sprints zählen als gültige Quelle der Planung |
| „Ready“-Definition | Status, Label, Feld oder „nicht im Refinement-Sprint“ | Grundlage für die obigen Regeln |
| Quelle der Vormerkung | `app` (im Daten-Repo), `jira-sprints` (künftige Sprints lesen), `jira-daten` (Zielstart/Zielende, siehe 6.3) | woher die Zuordnung Ticket → Zielsprint kommt |

Bei `jira-sprints` und `jira-daten` bleibt die Vormerkung ein **Vorschlag**, den die PO
übernimmt; die App überschreibt eigene Vormerkungen nie stillschweigend.

## 5. Ticketsystem anbinden

### 5.1 Konfiguration (vom Assistenten geschrieben)

```yaml
# teams/<team>/jira.yaml (keine Geheimnisse)
base_url: https://<instanz>
project: <PROJEKT>
board_id: <ID>
fields:
  rest: <customfield_…>         # aktueller Restaufwand
  original: <customfield_…>     # Schätzung aus dem Refinement
refinement:
  mode: sprint                  # sprint | query | off
  sprint_id: <ID>               # der Name dient nur der Anzeige
ready:
  by: label                     # status | label | field | not-in-refinement
  value: <…>
product_mapping:
  sources: [label, component]   # Reihenfolge
  table: { <wert>: <produkt> }
parent:
  mode: link                    # none | epic | link
  project: <PROJEKT>
  link_type: <Name>
  direction: outward
queries:
  backlog: '…{project}…'        # benannte Vorlagen mit Platzhaltern
```

Die Werte kennt der Assistent aus der Instanz: Felder und Linktypen werden über die API
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
  Tokens laufen ab. Die App zeigt dafür verständliche Meldungen (401, 403, TLS) und bleibt ohne
  Jira voll benutzbar.
- Ein PAT hat die Rechte des Kontos, also möglicherweise Schreibrechte. „Die App liest nur“
  wird technisch abgesichert: alle Aufrufe gehen durch eine Funktion, die nur GET zulässt, mit
  einem Test dafür.
- Cache nur im Prozess (zeitbegrenzt, mit Aktualisieren-Knopf), nicht auf Platte; getrennt nach
  Instanz und Konto, damit ein Kontowechsel keine fremden Daten zeigt.

## 6. Schätzfelder, Last und Erledigt

### 6.1 Zwei Felder

- **Ursprünglicher Umfang** – Schätzung aus dem Refinement.
- **Restaufwand** – aktueller Rest.

### 6.2 Vorgehen im Team und Definitionen

Am Sprintende wird für nicht abgeschlossene Tickets der Restaufwand neu geschätzt und im
Restfeld eingetragen. Der bereits erledigte Anteil zählt zum „Erledigt“ des Sprints; der
„nicht erledigte“ Anteil spiegelt nur wider, was wirklich noch offen ist. Das bleibt die
Definition. Jira liefert nur einen **Vorschlag**:

- **Last einer Vormerkung** = Restaufwand, sonst ursprünglicher Umfang (als „Schätzung“
  gekennzeichnet), sonst ein lokaler Platzhalter in der Einheit des Teams, sonst „ungeschätzt“.
  Die Zahl ungeschätzter Tickets wird je Sprint ausgewiesen; ohne sie gibt es keine
  vollständige „passt“-Aussage.
- **Zusage** eines Sprints = Σ Restaufwand der Tickets zum Zeitpunkt des Plannings.
- **Erledigt (Vorschlag)** = Σ je Ticket `max(Rest zum Planning − Rest zum Sprintende, 0)`;
  fertige Tickets haben am Ende Rest 0. Wird ein Ticket am Ende höher geschätzt als beim
  Planning, zählt es 0 und wird als „Neuschätzung“ angezeigt. Die PO bestätigt oder korrigiert.
- **Nicht erledigt** = Σ Rest zum Sprintende der nicht abgeschlossenen Tickets.

Dazu wird beim Planning ein **Snapshot** festgehalten: Ticket-Schlüssel und Rest je Ticket
(keine Titel, keine Beschreibungen), damit der Vorschlag ohne Changelog-Auswertung berechnet
werden kann. Tickets, die später in den Sprint kommen, nutzen ihren ursprünglichen Umfang als
Startwert und sind als solche markiert.

Der **Fortschritt** eines Tickets oder Vorhabens ist `erledigt / (erledigt + Rest)` mit
`erledigt = max(Original − Rest, 0)`; ohne Original ist er undefiniert, nicht 0.

### 6.3 Zielstart und Zielende als Quelle (optional)

Zielstart/Zielende können als Vormerkquelle dienen, wenn ein Team keine eigenen Felder
anlegen kann. Weil sie teils für harte Deadlines genutzt werden, ist diese Quelle **aus** und
nur ein Vorschlag, der je Ticket bestätigt wird; welches der beiden Felder gilt, legt der
Assistent fest.

## 7. Vormerkung und Auslastung

- **Daten-Repo:** `roadmap.yaml` je Team mit Ticket-Schlüssel, Ziel-Sprint, optionalem
  Platzhalter und Notiz. Titel und Umfang kommen immer live aus Jira.
- **Übernahme:** Wird ein Ticket aus dem Refinement genommen und in einem echten Sprint
  eingeplant, übernimmt die App Sprint und Werte aus Jira, markiert die Vormerkung als
  „eingeplant“ und zählt das Ticket nur einmal. Die ursprüngliche Absicht bleibt sichtbar.
- **Abgleich bei jedem Laden:**

| Zustand im Ticketsystem | Reaktion |
|---|---|
| Ticket in echtem Sprint | Vormerkung „eingeplant“, Last zählt als zugesagt; Abweichung vom Ziel-Sprint wird gezeigt |
| Ticket erledigt, nie in einem Sprint | Vormerkung entfällt, Hinweis |
| Ticket weder im Refinement noch in einem Sprint | Vormerkung bleibt, Warnung |
| Ticket gelöscht oder nicht lesbar | Warnung, Vormerkung bleibt sichtbar |
| Schätzung geändert | aktuelle Zahl anzeigen |
| Nicht-ready Ticket in echtem Sprint (Regel `verboten`) | Regelverstoß anzeigen |

- **Ansichten:**
  - Auslastungsbalken je Zukunfts-Sprint: Forecast PLAN als Linie, darunter gestapelt
    Überläufer-Rest, zugesagt, vorgemerkt, frei; ungeschätzte Tickets ausgewiesen.
  - Sprint-Spalten mit Karten; Verschieben per Auswahlfeld. Drag-and-drop später.
- Streamlit genügt für Tabellen, Auswahl und Diagramme. Eine interaktive Planungsfläche wäre
  ein anderer Technologieeinsatz und ist nicht Ziel.

### 7.1 Produktzuordnung und übergeordnete Vorhaben

- Zuordnung eines Tickets zum Produkt in konfigurierbarer Reihenfolge (z. B. Label, dann
  Komponente) über eine Tabelle; widersprüchliche Treffer erscheinen als „mehrdeutig“, keine
  Treffer als „nicht zugeordnet“.
- Übergeordnete Vorhaben (Epic oder verlinkter Eintrag eines anderen Projekts) dienen nur als
  **Lesehilfe**: Tickets lassen sich danach filtern und gruppieren; je Vorhaben werden die
  vorgemerkte Last und offene Datenprobleme gezeigt. Gemeint ist der Anteil des Teams im
  geladenen Umfang, keine Gesamtmenge oder Termin.
- Fehlende Verknüpfung, nicht lesbares Ziel und widersprüchliche Zuordnungen sind
  unterschiedliche Zustände; Mehrfachverknüpfungen vervielfachen keine Last.

## 8. Datenordner und Synchronisation

- Die App kann den Datenordner im Betrieb wechseln (Seite „Datenordner“: vorhandenen Ordner
  wählen, neues Daten-Repo anlegen, bestehendes klonen). Geplant: eine Liste der zuletzt
  benutzten Ordner als schneller Umschalter.
- Wer die App für ein Team ohne gemeinsame POs nutzt, verwendet ein eigenes Daten-Repo.
- Synchronisation erfolgt über Git. Heute gibt es Commit in der App; geplant sind Anzeige des
  Stands (voraus/hinterher), **Pull** vor dem Bearbeiten und **Push** nach dem Commit. Konflikte
  werden mit den üblichen Git-Werkzeugen gelöst; die App erkennt sie, erklärt den Zustand und
  lädt danach neu. Ein Sprint pro Datei hält Konflikte selten.
- Fehltage je Person sind für POs zugänglich, weil sie zur Sprintplanung gehören.

## 9. Architektur

```
sprintforecast/
  Kern: capacity, forecast, calendar      (kennt weder Quellen noch Vormerkung)
  sources/   neutrales Ticketmodell + Schnittstelle TicketSource
  roadmap/   Vormerkungen: Modell + Speicherung
  Adapter jira  im selben Repo, optionaler Zusatz: sprintforecast[jira]
```

- Neutrales Modell: `Ticket` (Schlüssel, Titel, Typ, Status, Labels, Komponenten, Original,
  Rest, Sprint, Links, übergeordnetes Vorhaben), `Sprint`, `Board`.
- Die Schnittstelle bleibt schmal (Sprints laden, Tickets nach benannter Abfrage laden,
  Verbindung testen) und wächst erst bei der zweiten Quelle. Der Jira-Adapter registriert sich
  über die vorhandenen Entry-Points; ein eigenes privates Paket ist nicht nötig, weil die
  Software nichts Instanzspezifisches enthält.
- Der Kern importiert nie aus `sources/` oder `roadmap/` (per Test erzwungen).

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
- Eine PO-Startseite „Nächsten Sprint vorbereiten“ statt vieler Teamseiten.

## 11. Phasen

| Phase | Inhalt | Abnahmekriterium |
|---|---|---|
| **0 Kern und Begriffe** | Punkte aus 10 | Eigenschaftstests grün; Plan liegt in der Bandbreite |
| **1 Assistent und Datenordner** | Einrichtungs-Assistent (ohne Ticketsystem), Planungsregeln, Umschalter für Datenordner, Pull/Push-Knöpfe | Ein neues Team lässt sich ohne Handbuch einrichten; Wechsel zwischen zwei Daten-Repos in der App |
| **2 Jira-Spike und lesender Anschluss** | Schritt 7 des Assistenten, Verbindung, Felder, Refinement, Produkt- und Vorhabenzuordnung, GET-only-Test | Echte Beispieldaten werden korrekt gelesen; Token erscheint nirgends außer im Schlüsselbund |
| **3 Vormerkung und Auslastung** | `roadmap.yaml`, Balken, Spalten, Abgleich, Übernahme | Eine PO bereitet zwei Sprints vor; jedes Ticket zählt einmal; Unbekanntes bleibt sichtbar |
| **4 Review-Vorschlag** | Zusage- und Erledigt-Vorschlag aus Jira, Snapshot beim Planning | Vorschlag stimmt in drei realen Sprints bis auf erklärbare Differenzen mit den manuellen Werten überein |

Spätere Kandidaten: Import alter Sprints, Vorhaben-Tabelle mit frühestem Sprint, Export des
Forecasts je Sprint (CSV/JSON), Drag-and-drop, weitere Quellen.

Jede Phase ist ein eigener, kleiner Pull Request (oder ein Stapel).

## 12. Tests

- Keine echten Netzaufrufe in der CI: gefälschter Server (`httpx.MockTransport`) mit
  aufgezeichneten Antworten; ein manuell auslösbarer Test gegen eine echte Instanz, weil
  Feld-IDs je Instanz verschieden sind.
- Ein Test je Abgleichfall aus 7, Tests für Last, Zusage, Erledigt und Fortschritt (auch
  Hochschätzung, fehlendes Original, Rest 0), Tests für alle Schalter aus 4.1 in beiden
  Stellungen, AppTest für den Assistenten und die neuen Seiten.
- Tests, dass nur GET gesendet wird und dass Token und Ticketdaten nie in Logs, Fehlermeldungen
  oder Dateien auftauchen.

## 13. Offene Punkte

- Welche Ready-Definitionen soll der Assistent anbieten (Status, Label, Feld)?
- Wie werden Tickets erkannt, die nach dem Planning zum Sprint hinzukamen (Startwert)?
- Reicht ein Datenordner-Umschalter mit Liste der letzten Ordner, oder soll er Teams mehrerer
  Daten-Repos gleichzeitig zeigen?
