# sprintforecast

Velocity- und Kapazitäts-Forecast für Scrum-Teams. Beantwortet vor allem eine Frage: **Wie viel kann das Team im nächsten
Sprint einplanen?** – auch mitten im laufenden Sprint, für die Planung der POs.

- **Git ist die Datenbank:** YAML-Dateien, ein Sprint pro Datei, gut diff- und mergebar.
- **Geführte Eingabe:** Assistenten für Planning, Review und Fehltage, mit Erklärung zu
  jedem Feld und Plausibilitätsprüfung. Das Planning folgt dem Ablauf am Termin:
  Fehltage → Forecast PLAN & Einplanung → Forecast IST.
- **Mehrere Produkte:** Standardverteilung, PO-Vorplanung, Planning und Erledigt je Produkt,
  mit Diagrammen und Saldo; die Produktliste kann sich über die Zeit ändern.
- **Aktualisiert sich selbst:** prüft täglich auf eine neue Version und installiert sie nach
  dem Beenden (abschaltbar).
- **Kapazität aus einer Personenliste:** Personen mit Zugehörigkeitszeitraum und FTE,
  planbare Fehltage je Sprint, Feiertage je Bundesland.
- **Nachvollziehbare Rechenlogik:** normierte Velocity, gleitender Durchschnitt und Trend,
  konfigurierbar je Team.
- **Erweiterbar:** Plugins können Befehle und Seiten ergänzen, z. B. Importe.
- **SP/PT-neutral:** Die Schätzeinheit ist eine Team-Einstellung.

## Installation

Ein Befehl – installiert bei Bedarf [uv](https://docs.astral.sh/uv/), lädt Python 3.15 und
installiert sprintforecast mit Weboberfläche. Git wird nur für Plugins benötigt.

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.ps1 | iex"
```

**Linux / macOS:**

```bash
curl -LsSf https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.sh | sh
```

Danach ein neues Terminal öffnen.

**Aktualisieren** – automatisch, ähnlich wie bei Claude Code: Beim Start eines Befehls prüft
sprintforecast höchstens einmal am Tag im Hintergrund, ob es eine neuere Version gibt (Feld
`version` in `pyproject.toml` des installierten Branches). Ist eine da, wird sie **nach dem
Beenden** des Befehls mit `uv tool upgrade --reinstall sprintforecast` installiert und gilt ab
dem nächsten Start; Plugins und Python-Version bleiben erhalten. Unter Windows wartet die
Aktualisierung, bis das Programm geschlossen ist (laufende Programme sind dort gesperrt).

| Befehl / Variable | Wirkung |
|---|---|
| `sprintforecast aktualisieren` | sofort prüfen und aktualisieren (`--pruefen`: nur prüfen, `--erzwingen`: neu installieren) |
| `sprintforecast aktualisieren --auto hinweis` | nur auf neue Versionen hinweisen; `--auto aus` schaltet ab, `--auto an` wieder ein |
| `SPRINTFORECAST_AUTOUPDATE=an\|hinweis\|aus` | wie `--auto`, hat Vorrang (z. B. für verwaltete Rechner) |

**In der Weboberfläche:** Beim Start wird im Hintergrund geprüft; ist eine neue Version da,
erscheint sie in der Seitenleiste. Sie wird beim Schließen installiert – oder sofort mit
**Jetzt aktualisieren und neu starten**: Die App beendet sich, aktualisiert und öffnet sich
neu (gleiches Datenverzeichnis, gleiche Optionen).

Protokoll und Stand liegen neben der Plugin-Auswahl (`update.log`, `update.json`). Auf einen
Tag festgelegte Installationen (`SPRINTFORECAST_REF=v…`) werden nicht automatisch
aktualisiert. Das Installationsskript erneut auszuführen geht weiterhin.

> Für Maintainer: Eine neue Version wird nur erkannt, wenn `version` in `pyproject.toml`
> (und `__version__`) erhöht wird.

**Plugins:** Das Skript fragt, ob Plugins mitinstalliert werden sollen – mehrere mit `;`
getrennt, als Kurzform `besitzer/repo` (wird zu `git+https://github.com/besitzer/repo`) oder
vollständig `name @ git+https://…`. Die Auswahl wird gemerkt (Windows:
`%APPDATA%\sprintforecast\plugins.txt`, sonst `~/.config/sprintforecast/plugins`); beim
Aktualisieren genügt Enter, `-` entfernt alle Plugins. Plugins aus Git-Repositories brauchen Git,
private zusätzlich eine Anmeldung. Ein Plugin muss die Quelle des Kerns in `[tool.uv.sources]`
festlegen.

Ohne Rückfrage (Umgebungsvariablen vor dem Aufruf setzen):

| Variable | Wirkung |
|---|---|
| `SPRINTFORECAST_WITH="besitzer/repo; …"` | diese Plugins installieren (leer = keine) |
| `SPRINTFORECAST_REF=v1.0` | bestimmten Tag oder Branch statt `main` installieren |

Entfernen: `uv tool uninstall sprintforecast`.

Manuell ohne Skript:

```bash
uv tool install "sprintforecast[web] @ https://github.com/swallat/sprint-forecast/archive/refs/heads/main.zip"
```

## Schnellstart

```bash
cd sprint-daten                    # Datenverzeichnis: je Team ein Unterordner
sprintforecast web                 # Weboberfläche
sprintforecast hilfe               # Was ist wann zu tun?
sprintforecast forecast team-a     # Prognose auf der Kommandozeile
```

**Datenverzeichnis:** `--daten PFAD`, sonst die Umgebungsvariable `SPRINTFORECAST_DATEN`,
sonst das **aktuelle Verzeichnis**, falls es Teams enthält, sonst der **gemerkte
Datenordner** (Weboberfläche: Seite *Datenordner*, Kommandozeile: `sprintforecast
datenordner PFAD`). Teams sind Unterordner mit einer `team.yaml`; enthält ein Verzeichnis
keine, aber einen Unterordner `teams` mit Teams, wird dieser genommen.

Findet die Weboberfläche keinen Datenordner (keine Teams, kein Git-Repository), führt sie
durch die Einrichtung: vorhandenen Ordner wählen (muss in einem Git-Repository liegen), neues
Daten-Repository anlegen (`git init`, `.gitignore`, Ordner `teams`) oder das gemeinsame
Daten-Repository des Teams klonen.

**Windows PowerShell:**

```powershell
cd "$HOME\sprint-daten"
sprintforecast web --app
```

Demo ausprobieren (im Ordner dieses Repositorys):

```bash
sprintforecast --daten examples/teams --stichtag 2026-10-15 forecast demo
```

## Weboberfläche

```bash
sprintforecast web                         # im Datenverzeichnis
sprintforecast --daten ../daten-repo web   # oder mit Pfad
```

**Als App:** `sprintforecast web --app` öffnet die Oberfläche in einem eigenen Fenster ohne
Adressleiste; Schließen des Fensters beendet auch den Server. Gesucht wird in dieser
Reihenfolge – im PATH (inkl. Scoop-/Chocolatey-Shims) und in den üblichen
Installationsorten (Windows inkl. Scoop- und Chocolatey-Verzeichnissen):

1. App-Modus: Edge, Chrome, Comet, Chromium, Brave, Vivaldi
2. Firefox (kein App-Modus mehr) in einem neuen Fenster
3. Standardbrowser des Systems
4. nichts gefunden → Adresse wird angezeigt, der Server läuft weiter

Einen bestimmten Browser erzwingt `--browser PFAD` bzw. die Umgebungsvariable
`SPRINTFORECAST_BROWSER`. Ist Port 8501 belegt, wird automatisch ein freier gewählt.

Startet eine lokale Weboberfläche unter <http://localhost:8501>. Sie ist nur auf dem
eigenen Rechner erreichbar und braucht kein Hosting; die Daten bleiben im lokalen
Git-Klon. Die Oberfläche liest und schreibt **dieselben YAML-Dateien** wie die
Kommandozeile und prüft vor jedem Speichern:

| Bereich | Seite | Inhalt |
|---|---|---|
| Sprint | Forecast | Prognose für laufenden + kommende Sprints, Verlauf, Diagramm, Bericht schreiben |
| | Fehltage | Tabelle Person × Sprint mit Live-Vorschau von Kapazität und Forecast |
| | Sprintkalender | kommende Sprints mit Start, letztem Tag und Arbeitstagen; anlegen, Länge anpassen |
| | Planning | geführter Ablauf: 1. Fehltage, 2. Forecast PLAN & Einplanung je Produkt, 3. Forecast IST |
| | Review | Velocity, Scope Creep, Erledigt je Produkt; Kapazität wird eingefroren |
| | Produktverteilung | Standard, PO-Vorplanung, Planning, Erledigt je Produkt; Diagramme, Verlauf, Saldo |
| | Analyse | ergänzend: Bandbreite, Fokusfaktor, Puffer-Empfehlung, „Wann ist es fertig?“ |
| Team | Personen | eine Tabelle (Zeile je Zeitraum, FTE); IDs automatisch; Ehemalige ausblendbar |
| | Produkte | Produktliste mit PO und Zeitraum (ab/bis); Ehemalige ausblendbar |
| | Einstellungen | alle Team-Einstellungen; Änderungen werden vor dem Speichern angezeigt |
| | Neues Team | Team anlegen |
| Daten & Hilfe | Datenordner | Datenordner wählen, neu anlegen oder klonen (Git-Repository) |
| | Prüfung | Befunde aller Teams |
| | Hilfe | Ablauf, Begriffe, Eingabefelder, Einstellungen, Befehle |

**Speichern und Committen:** Jede Seite speichert in die YAML-Dateien. Die Seitenleiste zeigt
unter **Git** die offenen Änderungen im Datenverzeichnis; **Änderungen committen** übernimmt
sie mit frei wählbarer Nachricht (nach einem Review optional mit Tag `TEAM/SPRINT`).
Committet wird nur das Datenverzeichnis, Tabellenkalkulationen (`*.xlsx` …) werden abgelehnt. Gepusht wird
weiterhin von dir.

## Ablauf im Sprint

| Wann | Befehl | Was passiert |
|---|---|---|
| Sprints vorab anlegen | `sprintforecast sprints team-a --anlegen` | Kommende Sprints (Start, letzter Tag, Arbeitstage) anzeigen und Dateien anlegen; `--ende 2026.25=2027-01-12` verlängert einen Sprint, die folgenden verschieben sich. |
| Urlaub o. Ä. wird bekannt | `sprintforecast fehltage team-a [SPRINT]` | Fehltage je Person erfassen (Standard: nächster Sprint). Zeigt Kapazität und Prognose. |
| Team ändert sich | `sprintforecast personen team-a` | Person hinzufügen, FTE ändern, Austritt eintragen. |
| Einstellungen ändern | `sprintforecast einstellungen team-a` | Bundesland, Referenzkapazität, Trend-Modus usw. geführt ändern; zeigt die Änderungen vor dem Speichern. |
| Produkte ändern sich | `sprintforecast produktliste team-a` | Produkt anlegen, PO ändern, Produkt abgeben (mit Enddatum). |
| PO-Vorplanung | `sprintforecast produkte team-a --vorplanung` | POs tragen je Produkt ein, was sie vorsehen; Vergleich mit dem Standard. |
| Sprint Planning | `sprintforecast planning team-a` | Geführt: 1. Fehltage, 2. Forecast PLAN und Planning je Produkt, 3. Forecast IST (+ optional Kontrollrechnung). Friert den Forecast PLAN ein. Standard: nächster noch nicht geplanter Sprint. |
| Sprint Review | `sprintforecast review team-a --commit` | Erfasst Velocity, Scope Creep und Erledigt je Produkt, friert die Kapazität ein, committet und setzt Tag `team-a/<sprint>`. |
| PO-Planung | `sprintforecast forecast team-a` | Prognose für laufenden + nächste Sprints. |
| Produktauswertung | `sprintforecast produkte team-a [SPRINT]` | Verteilung je Produkt und Saldo der letzten Sprints. |
| Bericht | `sprintforecast bericht [team-a]` | Schreibt `teams/team-a/FORECAST.md` (Tabelle + Mermaid-Diagramm). |
| Vor dem Commit / CI | `sprintforecast pruefen` | Fehler und Plausibilität aller Teams prüfen. |

Alle Assistenten erklären jedes Feld (was, woher, Beispiel). Nachschlagen:
`sprintforecast hilfe begriffe`, `… hilfe sprint`, `… hilfe team`.

## Code- und Daten-Repository trennen

Dieses Repository enthält **nur Code und Demo-Daten**. Echte Team-Daten liegen in einem
eigenen Daten-Repository innerhalb der Unternehmensdomäne (`*.xlsx` und `/teams/` sind
hier per `.gitignore` ausgeschlossen). Vorlage: [`templates/daten-repo/`](templates/daten-repo):

```
daten-repo/
├─ mise.toml                      # Tool-Versionen + Task `mise run sf -- …`
├─ .github/workflows/forecast.yml # prüft Änderungen, aktualisiert FORECAST.md (auf GitLab analog)
└─ teams/
   ├─ team-a/
   │  ├─ team.yaml
   │  ├─ people.yaml
   │  ├─ products.yaml            # optional
   │  ├─ FORECAST.md              # erzeugt
   │  └─ sprints/2026.20.yaml …
   └─ team-b/ …
```

Parallele Pflege durch POs und Scrum Master funktioniert, weil jeder Sprint eine eigene
Datei ist. Abgeschlossene Sprints werden per Tag `TEAM/SPRINT` markiert.

## Dateiformate

**`team.yaml`** – Einstellungen (alle optional außer `name`; geführt änderbar mit `einstellungen`):

```yaml
name: Team A
unit: PT                    # PT oder SP (Kapazität ist immer PT)
sprint:
  length_days: 14
  numbering: yearly         # 2026.1, 2026.2 … | sequential: 1, 2, 3 …
  first: {id: '2026.20', start: 2026-10-14}   # nur nötig, solange keine Sprintdatei existiert
forecast:
  reference_capacity: 67    # Bezug der normierten Velocity
  window: 5                 # gleitender Durchschnitt
  roadmap_share: 0.8
  rounding: 1               # Forecast PLAN wird abgerundet
  trend_mode: klassisch     # klassisch | linear | flat
  horizon: 3                # künftige Sprints in der Prognose
  product_basis: plan       # Standard je Produkt aus: plan (Forecast PLAN) | roadmap
capacity:
  overhead_share: 0.0       # pauschaler Abzug für Scrum-Termine
  overhead_days: 1          # optional: zusätzlich fester Abzug in PT je Person und Sprint (× FTE)
  region: NW                # Bundesland für Feiertage
```

**`people.yaml`** – Personen werden nie gelöscht, nur Zugehörigkeiten beendet:

```yaml
people:
- id: ben
  name: Ben
  region: BY                # optional, sonst Team-Region
  memberships:
  - {from: 2025-01-01, to: 2026-05-31, fte: 1}
  - {from: 2026-06-01, to: null, fte: 0.5}
```

**`products.yaml`** (optional) – Produkte nie löschen, sondern mit `to:` beenden:

```yaml
products:
- {id: webshop, name: Webshop, po: Alex, from: null, to: null}
- {id: portal, name: Kundenportal, po: Bea, from: 2026-09-02, to: null}
- {id: altsystem, name: Altsystem, po: Bea, from: null, to: 2026-09-15}
```

**`sprints/<id>.yaml`** – leere Felder sind `null` (= keine Angabe):

```yaml
id: '2026.21'               # in Anführungszeichen!
start: 2026-10-14
end: 2026-10-28             # = Start des nächsten Sprints (exklusiv); letzter Tag 27.10.
absences: {ben: 3, cem: 5}  # planbare Fehltage (Arbeitstage), ohne Feiertage
capacity: null              # wird beim Review eingefroren; manuell nur ohne Personenliste
forecast_ist: 10
velocity: null
scope_creep: null           # Anteil, 0.3 = 30 %
planning: {carryover: 0.25, backlog: 9.48, corrections: [1.5]}
forecast_plan: 10.1         # Forecast PLAN beim Planning (eingefroren), optional
products:                   # optional, je Produkt-ID
  webshop: {preplanned: 4, planned: 4.5, done: 4}
```

## Rechenlogik

| Kennzahl | Formel |
|---|---|
| Normierte Velocity | Velocity / Kapazität × Referenzkapazität |
| Ø | Mittel der letzten `window` Sprints, nur wenn der Sprint selbst einen Wert hat |
| Trend | Fortschreibung des Ø in die Zukunft |
| Forecast PLAN | n. Velocity-Trend / Referenz × Kapazität, auf 1 Stelle abgerundet; Vergangenheit: Forecast IST |
| Roadmap / Kleinkram | Forecast PLAN × 0,8 / Rest |
| Fulfillment | Velocity / Forecast IST |
| Planning-Delta | Forecast PLAN − (Überkipper + Backlog − Korrekturen) |
| Standard je Produkt | verfügbar / Anzahl im Sprint betreuter Produkte; verfügbar = Forecast PLAN (beim Planning eingefroren, sonst aktuell) bzw. dessen Roadmap-Anteil |
| Saldo je Produkt | Σ Erledigt − Σ Standard über die Sprints mit erfasstem Erledigt |

**Kapazität eines Sprints** – in dieser Reihenfolge:
1. `capacity` in der Sprintdatei (eingefroren oder manuell) → *erfasst*
2. Sprintdatei existiert, Personenliste vorhanden → Σ Personen
   (Arbeitstage − Feiertage − Fehltage) × FTE − Abzug Scrum-Termine → *Personenliste*;
   Abzug = Summe × Anteil (%) + Σ min(Kapazität der Person, PT je Person × FTE)
3. Keine Sprintdatei → Kapazitäts-Trend → *Trend* (im Bericht mit ⚠️ markiert)

**Trend-Modi** (`forecast.trend_mode`):
- `klassisch` (Standard): 1. Zukunftssprint linear `Ø + (Ø − Ø_vorher)`,
  2. multiplikativ `Ø_vorletzt / Ø_vorvorletzt × Trend_vorher`, danach linear.
- `linear`: durchgehend linear.
- `flat`: letzter Ø bleibt konstant (robust bei langen Horizonten).

**Rechenweg:** Jede Kennzahl lässt sich mit eingesetzten Zahlen nachvollziehen – in der
Weboberfläche per Tooltip (ⓘ an Kennzahlen und Spaltenköpfen) und im ausklappbaren
**Rechenweg** auf Forecast- und Planning-Seite, auf der Kommandozeile mit
`sprintforecast forecast TEAM --rechenweg SPRINT`.

## Ergänzende Analysen

`sprintforecast analyse TEAM [--rest MENGE] [--gesamt]` bzw. Seite **Analyse** – zusätzlich
zum Forecast, die bisherigen Werte bleiben unverändert:

- **Bandbreite:** Forecast mit der niedrigsten, mittleren und höchsten normierten Velocity
  der letzten Sprints (konservativ / mittel / optimistisch).
- **Fokusfaktor:** Velocity / Kapazität – unabhängig von der Referenzkapazität, daher
  zwischen Teams vergleichbar.
- **Puffer:** Ø Scope Creep der letzten Sprints im Vergleich zum Kleinkram-Anteil.
- **Wann ist es fertig?** Monte-Carlo-Simulation ab dem nächsten Sprint: in welchem Sprint
  eine Restmenge wahrscheinlich (50 %) bzw. mit 85 % Sicherheit erledigt ist – mit dem
  Roadmap-Anteil oder (`--gesamt`) dem ganzen Forecast, optional nur mit einem
  **Projektanteil** davon (`--anteil 50` = die Hälfte). Sprints ohne erfasste Fehltage
  rechnen mit der Ø Kapazität.

Der Bericht `FORECAST.md` enthält am Ende einen Abschnitt „Ergänzend: Bandbreite“.

## Erweiterungen (Plugins)

Plugins sind eigene Python-Pakete, die sich über den Entry-Point
`sprintforecast.plugins` einklinken (siehe `src/sprintforecast/plugins.py`). Sie können
Befehle für die Kommandozeile und Seiten für die Weboberfläche ergänzen – etwa einen Import
der Historie aus einem bisherigen Werkzeug. Installiert werden sie neben dem Tool:

```bash
uv tool install "sprintforecast[web] @ git+https://github.com/swallat/sprint-forecast" \
  --with "mein-plugin @ git+https://…"
```

Legt das Plugin die Quelle des Kerns selbst fest (`[tool.uv.sources]`), den Kern ohne
Adresse angeben – sonst meldet uv „conflicting URLs“:
`uv tool install "sprintforecast[web]" --with "mein-plugin @ git+https://…"`.

Formatneutrale Hilfsfunktion für Importe: `sprintforecast.storage.import_sprints`.

## Entwicklung

Voraussetzung: [mise](https://mise.jdx.dev) – Python und uv sind in `mise.toml` festgelegt.

```bash
mise install
uv sync --all-extras
uv run sprintforecast --daten examples/teams web   # aus dem Quellcode starten
uv run pytest
uv run ruff check && uv run ruff format --check
```

## Lizenz

[EUPL-1.2](LICENSE) (European Union Public Licence). Kurz: Nutzung, auch kommerziell und
firmenintern, ist frei. Wer eine veränderte Fassung weitergibt oder öffentlich als Dienst
anbietet, muss die Änderungen unter der EUPL offenlegen.

Alle von der EU-Kommission genehmigten Sprachfassungen sind gleichwertig (Art. 13 EUPL).
`LICENSE` enthält die englische Fassung; die amtliche deutsche Fassung steht im
[Durchführungsbeschluss (EU) 2017/863](https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32017D0863).
