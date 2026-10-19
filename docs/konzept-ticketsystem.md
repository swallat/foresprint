# Konzept: Ticket-Vorplanung und Tracker-Anbindung (optional)

Status: Entwurf, Version 6 (19. Oktober 2026), noch nichts umgesetzt. Diese Version **ersetzt
Version 5 vollständig**; sie ist das einzige gültige Konzept zur Jira-Anbindung. Die Umsetzung
beginnt nach dem Merge der offenen PR-Welle (#96 bis #106), siehe Abschnitt 10. Alles, was ohne
Ticketsystem gilt (Berechnung, Bedienung, Datenordner, Synchronisation), steht in
[konzept-kern.md](konzept-kern.md).

Was gegenüber Version 5 wegfällt: das Snapshot-Modell (Planning- und Review-Stand), der
Review-Vorschlag aus Ticket-Restständen, die Bilanz, die Mehrprodukt-Gewichtung und die Phasen
T0 bis T4. Was neu ist: Projekte mit Zieldatum, die automatische Verteilung der Tickets auf
künftige Sprints, der Zeitstrahl, die Refinement-Liste, konfigurierbare Zuordnungsregeln und das
spätere Rückschreiben eines Labels.

## 1. Ausgangslage und Ziel

In Jira dürfen Tickets, die noch nicht refined sind, nicht mehr in künftige Sprints gezogen
werden. Die bisherige Vormerkung („dieses Ticket kommt in Sprint 44“) hat damit keinen Ort mehr.
Gleichzeitig hat jedes Ticket eine Schätzung (aus dem Refinement, aus der Grobschätzung oder vom
PO vergeben), eine Projektzuordnung, und jedes Projekt ein Zieldatum.

Das Tool soll deshalb beantworten:

1. **In welchen Sprint muss ein Ticket spätestens, damit das Zieldatum seines Projekts hält?**
   Dazu verteilt das Tool die Tickets automatisch auf künftige Sprints, unter Beachtung von
   Abhängigkeiten und des Sprint-Budgets aus dem Forecast.
2. **Hält ein Projekt sein Zieldatum?** Ampel je Projekt und Zeitstrahl über alle Projekte.
3. **Was muss bis wann refined sein?** Refinement-Liste je Sprint.
4. **Welche Vormerkung gilt?** Hand-Vormerkungen des POs, der echte Jira-Sprint und (später) ein
   Label in Jira werden in einer klaren Rangfolge zusammengeführt.

Zielgruppe sind Product Owner. Der Forecast-Kern bleibt unverändert; die Vorplanung liest seine
Ergebnisse (Forecast PLAN, Standardverteilung je Produkt, Produktionszugriff) und schreibt
höchstens die Summen je Produkt als Vorschlag in die PO-Vorplanung (Abschnitt 10, Schritt 4).

## 2. Grundsätze

- **Abschaltbar.** `features.tickets` (Standard `false`). Ohne den Schalter gibt es keine Seite,
  keinen Menüeintrag, keine Dateien und kein geladenes Modul; die App arbeitet wie bisher.
- **Allgemein gültig und Open Source.** Der Code enthält keine Annahmen über eine Instanz: keine
  URLs, Feldnamen, Projekte, Labels oder Regeln als Vorgabe. Alles Instanz- und Teamspezifische
  steht in der Konfiguration des Teams im Daten-Repo (ohne Geheimnisse).
- **Quelle austauschbar.** Tickets kommen aus einer Schnittstelle `TicketSource`: CSV-Import und
  Jira zuerst, GitHub und GitLab später (Abschnitt 7.4). Hand-Pflege ist gleichwertig. Der
  Rechenkern (Verteilung) kennt keine Quelle.
- **Lesend, mit einer Ausnahme.** Gegenüber dem Tracker wird nur gelesen. Einziges Schreiben,
  erst in Schritt 5 und abschaltbar: das Label `planned_for_<sprint_id>` (Abschnitt 6.6).
- **Wer verantwortet was.** Der Tracker verantwortet Ticketdaten und die echte Sprintzuordnung.
  Das Tool verantwortet Projekte, Vormerkungen (Planungsabsicht) und die Verteilung.
- **Deterministisch und erklärbar.** Die Verteilung ist eine feste Reihenfolge ohne Zufall; zu
  jedem Ticket lässt sich sagen, warum es in seinem Sprint liegt.
- **Kapazität und Forecast funktionieren ohne Tracker.** Die Anbindung ergänzt, sie ist nie
  Voraussetzung.

## 3. Nicht-Ziele (vorerst)

- Kein Ersatz für das Ticketsystem, keine Ticket-Bearbeitung über das Label hinaus.
- Kein Import alter Sprints, kein Review-Vorschlag aus Ticketdaten (die Sprint-Datei bleibt die
  einzige Quelle für Zusage, Erledigt und Nicht erledigt).
- Keine Umrechnung zwischen Personentagen und Story Points.
- Keine Optimierung (keine „beste“ Verteilung); die Greedy-Verteilung aus Abschnitt 5 genügt und
  bleibt nachvollziehbar.
- Kein Mehrprodukt-Ticket: ein Ticket gehört zu genau einem Projekt und damit einem Produkt;
  Widersprüche werden angezeigt, nicht gewichtet.
- Keine Faustregel „spätester Sprint“ aus der Fulfillment-Historie (verworfen).
- Epic-Roadmap mit Monte-Carlo: zurückgestellt; sie ergibt sich später aus den Projekten.

## 4. Fachliches Modell

### 4.1 Begriffe

| Begriff | Bedeutung |
|---|---|
| **Ticket** | Arbeitseinheit aus dem Tracker oder von Hand: Schlüssel, Titel, Status, Projekt, Schätzung, Rest, Herkunft der Schätzung (`refined`, `rough`, `manual`, `none`), echter Sprint laut Tracker (`in_sprint`), Rank, Abhängigkeiten (`depends_on`), Labels, Komponenten, Epic |
| **Projekt** | Vorhaben mit Zieldatum, Produkt, Priorität und Zuordnungsregeln (`match:`); ein Projekt gehört genau einem Produkt. „Projekt“ ist hier kein Jira-Projekt, sondern ein Thema des POs |
| **Vormerkung** | Absicht des POs, ein Ticket in einen künftigen Sprint zu legen, ohne es in Jira dorthin zu ziehen. Entsteht von Hand oder durch die Verteilung |
| **Budget** | Was ein Sprint für Vorplanung noch aufnehmen kann, je Produkt (Abschnitt 5.1) |
| **Zielsprint** | Letzter Sprint, dessen Ende vor dem Zieldatum des Projekts liegt |

### 4.2 Schätzung und Rest

Zwei Werte je Ticket, beide mit einstellbarer Quelle (Abschnitt 6.2):

- **Schätzung** (`estimate`): Refinement- oder Grobwert, ändert sich während der Arbeit nicht.
- **Rest** (`remaining`): aktueller Restaufwand; bis zum Arbeitsbeginn gleich der Schätzung.

Die Verteilung rechnet mit `planning_uses: remaining` (Rest, falls gefüllt, sonst Schätzung;
Standard) oder `planning_uses: estimate`. Ein Ticket ohne beides gilt als **ungeschätzt**, wird
nicht verteilt und oben auf der Seite angezeigt. Der PO kann eine eigene Schätzung in
`preplan.yaml` hinterlegen (`manual`).

### 4.3 Ablage im Daten-Repo (je Team)

| Datei | Inhalt | Schreibt |
|---|---|---|
| `team.yaml`, Abschnitt `tracker:` | Quelle, Abfrage, Feldnamen, Regeln (Abschnitt 6.1) | Einrichtung |
| `projects.yaml` | Projekte mit Zieldatum, Produkt, Priorität, `match:` | PO |
| `tickets.yaml` | letzter Importstand: Schlüssel, Titel, Zahlen, Status, Sprint, Abhängigkeiten, Zuordnung | Import (CSV oder Tracker) |
| `preplan.yaml` | Hand-Vormerkungen (Ticket → Sprint, Notiz) und eigene Schätzungen | PO |

Die Verteilung selbst wird **nicht gespeichert**; sie wird aus diesen Dateien und dem Forecast bei
jedem Laden neu berechnet. Geheimnisse (Token) stehen nie in diesen Dateien.

## 5. Verteilung

### 5.1 Budget je Sprint und Produkt

```
Budget[s, p] = Standardanteil[p] × Basis[s]  −  Σ (Tickets laut Tracker bereits in Sprint s, Produkt p)
```

- `Basis[s]` ist je **Produkt und Projekt** einstellbar: der verplanbare Anteil des Forecast PLAN
  (`roadmap_share`, Standard) oder der ganze Forecast PLAN. Projektbudget = Standardanteil seines
  Produkts aus `products.distribution`. Produktionszugriff kommt als `production_available` hinzu,
  wenn das Feature aktiv ist.
- Horizont wie `analysis.completion`: bis 26 Sprints; jenseits der Personenliste gilt als
  Kapazität der Durchschnitt der letzten Sprints.
- Tickets, die laut Tracker schon in einem künftigen Sprint liegen (`in_sprint`), sind Fixpunkte
  und verbrauchen Budget, werden aber nicht verteilt. Gleiches gilt für Hand-Vormerkungen aus
  `preplan.yaml`.

### 5.2 Reihenfolge und Einsortieren

1. **Projekte** nach Zieldatum, dann Priorität; Tickets innerhalb eines Projekts nach Rank.
2. **Topologisch** nach `depends_on`; ein Zyklus ist ein Fehler, der angezeigt wird.
3. Jedes Ticket kommt in den **frühesten Sprint** ab (spätester Sprint seiner Abhängigkeiten
   + `dependency_gap`), dessen Restbudget für sein Produkt reicht. `dependency_gap` ist je Team
   einstellbar: `1` (Standard, Sprint danach) oder `0` (derselbe Sprint ist erlaubt).
4. Ein Ticket, das **größer als ein ganzes Sprint-Budget** ist, wird nicht verteilt und als „zu
   groß, zerlegen“ gemeldet. Ungeschätzte Tickets ebenso („ungeschätzt“).
5. Ergebnis: Sprint je Ticket, Füllstand je Sprint und Produkt, Liste „nicht verteilbar“.

### 5.3 Projekt-Ampel

Je Projekt wird der Sprint seines letzten Tickets mit dem Zielsprint verglichen:

| Ampel | Bedingung |
|---|---|
| **hält** | letzter Sprint liegt mindestens einen Sprint vor dem Zielsprint |
| **knapp** | letzter Sprint ist der Zielsprint |
| **verfehlt** | letzter Sprint liegt nach dem Zielsprint, oder ein Ticket ist nicht verteilbar |

### 5.4 Refinement-Liste

Je künftigem Sprint die Tickets, deren Schätzung `rough` oder `manual` ist, mit Frist = Planning
des Sprints. Das ist die Antwort auf „was muss bis wann refined sein“. Tickets mit unklarem
Refined-Status (Abschnitt 6.3) stehen gesondert darüber.

### 5.5 Unsicherheit (Schritt 4)

Die Verteilung wird dreimal gerechnet: mit der niedrigsten, der mittleren und der höchsten
normierten Velocity aus `analysis.band` (konservativ, mittel, optimistisch). In der konservativen
Variante werden Grobschätzungen mit `rough_factor` (Team-Einstellung, Standard 1,5)
multipliziert. Angezeigt wird die mittlere Variante; Ampel und Zeitstrahl zeigen die Spanne.

## 6. Eingabedaten und Konfiguration

### 6.1 `team.yaml`, Abschnitt `tracker:`

```yaml
features:
  tickets: true

tracker:
  kind: jira                     # jira | csv   (später: github, gitlab)
  base_url: https://jira.example.org
  query: 'project = ABC AND resolution = Unresolved ORDER BY Rank'
  fields:                        # Anzeigenamen der Instanz, Auflösung über /rest/api/2/field
    estimate: Ursprüngliche Story-Punkte
    remaining: Story-Punkte
    epic: Epos-Verknüpfung       # alternativ: Übergeordnet
  planning_uses: remaining       # remaining | estimate
  refined_label: Refined
  refined_also_if:               # gilt als refined, auch wenn das Label fehlt
    any:
      - in_sprint: true
      - status_not: [To Do]
  project_match_order: [epic, component, label]
  dependency_gap: 1              # 0 = Abhängigkeit darf im selben Sprint liegen
  budget_basis: roadmap_share    # roadmap_share | plan; je Produkt/Projekt überschreibbar
  rough_factor: 1.5
  write_labels: false            # Schritt 5: planned_for_<sprint_id> nach Jira schreiben
```

Alle Werte sind Beispiele; der Code enthält keine davon als Vorgabe. Die Einrichtung schlägt
Felder und Statuswerte aus der Instanz vor und speichert die Auswahl.

### 6.2 Woher Schätzung und Rest kommen

`fields.estimate` und `fields.remaining` nennen die Felder nach ihrem **Anzeigenamen**; das Tool
löst sie beim Verbinden in die Feld-ID (`customfield_…`) auf und meldet, wenn ein Name mehrdeutig
oder unbekannt ist. Fehlt `remaining` in der Instanz, darf es weggelassen werden; dann rechnet das
Tool nur mit der Schätzung. Für den CSV-Import heißen die Spalten wie im Jira-Export
(„Custom field (Ursprüngliche Story-Punkte)“ bzw. „Benutzerdefiniertes Feld (…)“).

### 6.3 Refined oder nicht

Ein Ticket gilt als refined, wenn es das `refined_label` trägt **oder** eine Bedingung aus
`refined_also_if` erfüllt (das Label wird in der Praxis manchmal vergessen). Die Import-Vorschau
zeigt eine Liste „Refined-Status unklar“: Tickets, die nur über die Zusatzbedingung als refined
gelten, oder die das Label tragen, aber keine Schätzung haben. Bis zur Klärung gilt die Schätzung
als `rough`.

### 6.4 Projektzuordnung und Zuordnungsregeln

Jedes Projekt trägt in `projects.yaml` seine Kriterien unter `match:`. Ein Ticket gehört zu dem
Projekt, dessen Regel es erfüllt. Treffen zwei Projekte, entscheidet `project_match_order` nach
der **Quelle** des Treffers (Standard: Epic vor Komponente vor Label); treffen zwei Projekte über
dieselbe Quelle, ist das ein Widerspruch, der in der Vorschau steht und bis zur Klärung „ohne
Projekt“ bleibt.

```yaml
# projects.yaml
schema: 1
projects:
  - id: zahlung-v2
    name: Zahlungsabwicklung v2
    product: shop
    target: 2027-03-31
    priority: 1
    budget_basis: plan             # optional, überschreibt den Team-Standard
    match:                         # Kurzform: Listen sind ODER-verknüpft
      epic: [ABC-100, ABC-101]
      label: [zahlung]

  - id: migration
    name: Datenbank-Migration
    product: plattform
    target: 2027-01-15
    priority: 2
    match:                         # Lange Form: any (ODER), all (UND), none (Ausschluss)
      all:
        - component: [Datenbank]
        - none:
            - label: [wartung, hotfix]
        - any:
            - epic: [ABC-200]
            - status: [Ready]
```

Regelsprache:

- **Blatt** = eine Quelle (`epic`, `component`, `label`, `status`, `issue_type`, `in_sprint`)
  mit Werteliste; die Werte eines Blatts sind ODER-verknüpft.
- **Kurzform:** mehrere Blätter direkt unter `match:` sind ODER-verknüpft (irgendein Treffer
  genügt).
- **Lange Form:** `any` (mindestens eines), `all` (alle), `none` (keines); beliebig schachtelbar.
- Dieselbe Sprache gilt für `refined_also_if` und für die Produktzuordnung ohne Projekt.
- Die Validierung lehnt leere Listen, unbekannte Quellen und Kurz- und Langform im selben
  `match:` ab.

### 6.5 Abgleich beim Import

| Zustand im Tracker | Reaktion |
|---|---|
| Ticket in aktuellem oder künftigem echten Sprint | gilt als eingeplant; zählt auf das Budget dieses Sprints; eine abweichende Vormerkung wird verworfen und die Abweichung angezeigt |
| Ticket erledigt | Vormerkung entfällt, Hinweis |
| Ticket nicht mehr in der Abfrage | Vormerkung bleibt, Warnung |
| Ticket gelöscht oder nicht lesbar | Warnung „nicht prüfbar“, Vormerkung bleibt sichtbar |
| Schätzung oder Rest geändert | neue Zahl, Verteilung rechnet neu |
| Ticket ohne Projekt oder mit zwei Projekten | Liste „zuzuordnen“ in der Vorschau |
| Unbekanntes Epic | Liste „unbekanntes Epic“ (Kandidat für ein neues Projekt) |

Der Import ist zweistufig wie der Excel-Import: Vorschau (neu, geändert, erledigt, zuzuordnen,
Refined unklar) und dann Übernahme nach `tickets.yaml`.

### 6.6 Rückschreiben eines Labels (Schritt 5)

Ist `write_labels: true`, setzt das Tool beim Vormerken das Label `planned_for_<sprint_id>` am
Ticket und entfernt ein vorhandenes `planned_for_*`-Label; geschrieben wird nur bei Änderung und
nach einer Vorschau. Beim Import werden solche Labels als Vormerkung gelesen.

Rangfolge bei Widerspruch: **Jira-Sprint-Feld > Vormerkung im Tool > Label.** Liegt ein Ticket in
Jira in einem echten Sprint, übernimmt das Tool diesen Sprint, verwirft die abweichende
Vormerkung, zeigt die Abweichung und räumt das Label beim nächsten Schreiben auf.

## 7. Anbindung

### 7.1 Jira Data Center

- **Personal Access Token** je Person, Header `Authorization: Bearer`. Das Token liegt in einer
  Umgebungsvariable oder im Betriebssystem-Schlüsselbund; nie in YAML, im Daten-Repo, in Logs
  oder Fehlermeldungen. Eingabe maskiert, „Verbindung testen“ über `/rest/api/2/myself`.
- Tickets über `/rest/api/2/search` mit `fields=` (nur benötigte Felder) und Paging
  (`startAt`/`maxResults`); Sprints über die Agile-API; Feldnamen über `/rest/api/2/field`.
  Abhängigkeiten aus Issue-Links (Typ einstellbar, Standard „Blocks“).
- Alle Aufrufe gehen durch eine Funktion, die nur GET zulässt, plus genau das eine PUT für das
  Label in Schritt 5; ein Test erzwingt das.
- Sichtbarkeit richtet sich nach den Rechten der Person; Tokens laufen ab. Verständliche Meldungen
  bei 401, 403 und TLS; „kein Ergebnis“ gilt nie als „keine Arbeit“. Die App bleibt ohne Jira
  voll benutzbar.
- Cache nur im Prozess, zeitbegrenzt, getrennt nach Instanz und Konto.
- Jira-Add-ons sind nicht möglich und werden nicht vorausgesetzt.

### 7.2 CSV-Import

Hauptweg in Schritt 1 und Rückfall, wenn kein Netzzugang besteht: Export aus der erweiterten
Jira-Suche („alle Felder“, ohne Bearbeiter und Reporter). Spaltennamen folgen dem
Jira-Standardexport („Custom field (…)“, „Benutzerdefiniertes Feld (…)“, Issue-Links als
„Inward issue link (Blocks)“). Die Zuordnung der Spalten nutzt dieselben Feldnamen wie
`tracker.fields`.

### 7.3 Hand-Pflege

Ohne Tracker können Tickets und Projekte direkt in `tickets.yaml` und `projects.yaml` gepflegt
werden (`kind: csv` ohne Datei, oder reine Hand-Pflege auf der Seite). Alles Weitere funktioniert
gleich.

### 7.4 Andere Tracker (später)

Die Schnittstelle `TicketSource` liefert ein neutrales `Ticket`. Für GitHub und GitLab bilden
sich die Begriffe so ab:

| Begriff | Jira | GitHub | GitLab |
|---|---|---|---|
| Schätzung | Feld (einstellbar) | Label `estimate:<n>` oder Projektfeld | Weight |
| Sprint | Sprint-Feld | Milestone | Iteration oder Milestone |
| Projekt-Zuordnung | Epic, Komponente, Label | Label, Milestone, Projektfeld | Epic, Label |
| Abhängigkeit | Issue-Link | „blocked by“-Verweis | Blocking Link |
| Refined | Label | Label | Label |

Diese Adapter werden erst gebaut, wenn eine zweite Anbindung konkret ansteht; die Schnittstelle
wächst dann, nicht vorher.

## 8. Darstellung

Eine Seite **„Tickets“** (nur mit `features.tickets`), oben ein **Filter** über Produkte und
Projekte, einzeln abwählbar; er gilt für alle Teile der Seite. Darunter:

1. **Projekt-Ampel:** je Projekt Zieldatum, Zielsprint, Sprint des letzten Tickets, Ampel, Zahl
   der Tickets, offene Punkte (ungeschätzt, zu groß, ohne Projekt).
2. **Zeitstrahl:** alle gewählten Projekte in einer Abbildung, Sprints als Spalten, je Projekt
   ein Balken vom ersten bis zum letzten Sprint seiner Tickets, Zieldatum als Marke; Farbe nach
   Ampel; in Schritt 4 die Spanne der drei Varianten als hellerer Bereich.
3. **Sprint-Spalten:** je künftigem Sprint eine Spalte mit Füllstand (Budget, belegt, frei) und
   Karten je Ticket (Schlüssel, Kurztitel, Schätzung, Herkunft, Projekt). Vormerken und Freigeben
   per Auswahlfeld; Fixpunkte (echter Jira-Sprint) sind gekennzeichnet und nicht verschiebbar.
4. **Refinement-Liste:** je Sprint die zu refinenden Tickets mit Frist.
5. **Nicht verteilbar:** ungeschätzt, zu groß, Zyklus, ohne Projekt.
6. **Import und Pflege:** Import mit Vorschau, Projekte anlegen und ändern, Hand-Schätzungen.
7. **Berichtsabschnitt** und Vorschlag im Planning-Assistenten (Summen je Produkt, Schritt 4).

Skizze Zeitstrahl (ein Balken je Projekt, Zieldatum als `|`):

```
             S43      S44      S45      S46      S47      S48
Zahlung v2   ████████████████████████▌         |                 hält
Migration    ████████████████████████████████████████▌|          knapp
Reporting             ████████████████████████████████████████▌  verfehlt (Ziel S46)
```

Skizze Sprint-Spalten (Füllstand und Karten):

```
S44  Budget 21 · belegt 18 · frei 3     S45  Budget 21 · belegt 20 · frei 1
┌─────────────────────────────┐          ┌─────────────────────────────┐
│ ABC-123  Checkout-API    5 R│ Zahlung  │ ABC-130  Rückerstattung  8 G│ Zahlung
│ ABC-125  Schema v2       8 R│ Migration│ ABC-131  Alt-Daten       5 R│ Migration
│ ABC-127  Export          5 M│ Reporting│ ABC-140  Dashboard       7 G│ Reporting
└─────────────────────────────┘          └─────────────────────────────┘
R = refined, G = grob, M = eigene Schätzung      fett = fester Jira-Sprint
```

Streamlit genügt für Filter, Tabellen, Auswahlfelder und die beiden Diagramme; eine interaktive
Planungsfläche (Drag-and-drop) ist nicht Ziel.

## 9. Architektur

```
sprintforecast/
  Kern: capacity, forecast, analysis, calendar   (kennt weder Quellen noch Vorplanung)
  model.py      + Ticket, Project
  storage.py    + projects.yaml, tickets.yaml, preplan.yaml
  preplan.py    Budgets, Reihenfolge, Einsortieren, Projekt-Ampel, Refinement-Liste, Varianten
  sources/      neutrales Ticketmodell, Schnittstelle TicketSource, csv.py, jira.py
                (jira als optionales Extra: sprintforecast[jira])
  web/seiten/tickets.py, report, cli tickets
```

- Der Kern importiert nie aus `sources/` oder `preplan.py` (per Test erzwungen).
- Mit `features.tickets: false` wird nichts davon geladen.
- Der Jira-Adapter ist ein optionales Extra im selben Repo, kein Plugin: der Code enthält nichts
  Instanzspezifisches, ein eigenes Registrierungsverfahren ist nicht nötig.
- Begriff: Der Forecast-Kern nennt den Anteil für Vorplanung heute „Roadmap-Anteil“
  (`roadmap_share`). PR #106 benennt die Anzeige in „Verplanbarer Anteil“ um; der Schlüssel
  bleibt. Dieses Dokument nutzt „verplanbarer Anteil“.

## 10. Umsetzungsschritte

Erst nach dem Merge der offenen PR-Welle #96 bis #106, dann von frischem `main`. Je Schritt ein
kleiner Pull Request (oder ein Stapel), deutsch, mit Tests und `locale_en.py`-Einträgen.

| Schritt | Inhalt | Berührte Module |
|---|---|---|
| **1 Modell und Verteilung** | `Ticket`, `Project` in `model.py`; `projects.yaml`, `tickets.yaml`, `preplan.yaml` in `storage.py`; `features.tickets`; Validierung (Regelsprache, Zyklen, Zieldaten); `preplan.py`; CLI `tickets` mit CSV-Import (Vorschau, Übernahme) und Ausgabe von Verteilung, Ampel und Refinement-Liste | model, storage, validate, cli, settings, locale_en, docs |
| **2 Jira-Import** | `sources/jira.py` als Extra: JQL lesen, Feldnamen auflösen, Refined-Regel, Zuordnungsregeln, Vorschau, Schreiben nach `tickets.yaml`; Token aus Umgebung oder Schlüsselbund; nur GET | sources/, settings, cli |
| **3 Seite** | Seite „Tickets“ (Abschnitt 8) ohne Varianten; Berichtsabschnitt | web/ui, web/seiten, report, i18n |
| **4 Varianten und Übernahme** | drei Varianten mit `rough_factor`; Spanne im Zeitstrahl; Übernahme der Summen je Produkt als `preplanned` in die PO-Vorplanung | preplan, analysis, web/ui |
| **5 Label nach Jira** | `planned_for_<sprint_id>` setzen und altes entfernen, nur bei Änderung, mit Vorschau; Labels beim Import lesen; Rangfolge aus 6.6 | sources/jira, preplan, web/ui |

Schritt 3 beginnt nur, wenn an `web/ui.py` nichts Großes offen ist. Spätere Kandidaten: GitHub-
und GitLab-Adapter, Epic-Roadmap aus den Projekten, Export der Verteilung (CSV), Drag-and-drop.

## 11. Tests

- Verteilung: Beispiele mit erwartetem Ergebnis (Reihenfolge, Abhängigkeiten mit `gap` 0 und 1,
  Budgetgrenze, zu großes Ticket, ungeschätztes Ticket, Zyklus, Fixpunkte aus `in_sprint` und
  `preplan.yaml`); Eigenschaftstest: kein Sprint über Budget, jedes Ticket höchstens einmal,
  Abhängigkeiten nie nach ihrem Nachfolger.
- Projekt-Ampel und Refinement-Liste je Fall; drei Varianten mit Faktor.
- Regelsprache: Kurzform, `any`/`all`/`none`, Schachtelung, `project_match_order`, Widersprüche,
  ungültige Regeln.
- Refined-Erkennung mit Label, Zusatzbedingung und „unklar“.
- Import: ein Test je Abgleichfall aus 6.5; CSV mit deutschen und englischen Spaltennamen.
- Jira: keine echten Netzaufrufe in der CI (`httpx.MockTransport` mit aufgezeichneten
  Antworten); Feldnamen-Auflösung; nur GET (und ab Schritt 5 genau das Label-PUT); Token und
  Ticketdaten nie in Logs oder Fehlermeldungen; ein manuell auslösbarer Test gegen eine echte
  Instanz.
- `features.tickets: false`: keine Seite, kein Menüeintrag, kein geladenes Modul; der Kern
  importiert nichts aus `sources/` oder `preplan.py`.
- AppTest für die Seite „Tickets“ (Filter, Vormerken, Freigeben, Import-Vorschau).

## 12. Offene Punkte

- Standard-Rangfolge der Projektzuordnung „Epic vor Komponente vor Label“ ist eine Annahme und
  vom Owner zu bestätigen.
- Ein CSV-Export aus der echten Instanz als Testgrundlage für Schritt 1; bis dahin wird gegen die
  Spaltennamen des Jira-Standardexports gebaut.
