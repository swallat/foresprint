# sprintforecast

Velocity- und Kapazitäts-Forecast für Scrum-Teams. Beantwortet vor allem eine Frage: **Wie viel kann das Team im nächsten
Sprint einplanen?** – auch mitten im laufenden Sprint, für die Planung der POs.

- **Git ist die Datenbank:** YAML-Dateien, ein Sprint pro Datei, gut diff- und mergebar.
- **Geführte Eingabe:** Assistenten für Planning, Review und Fehltage, mit Erklärung zu
  jedem Feld und Plausibilitätsprüfung.
- **Kapazität aus einer Personenliste:** Personen mit Zugehörigkeitszeitraum und FTE,
  planbare Fehltage je Sprint, Feiertage je Bundesland.
- **Nachvollziehbare Rechenlogik:** normierte Velocity, gleitender Durchschnitt und Trend,
  konfigurierbar je Team.
- **Erweiterbar:** Plugins können Befehle und Seiten ergänzen, z. B. Importe.
- **SP/PT-neutral:** Die Schätzeinheit ist eine Team-Einstellung.

## Installation

Als Werkzeug mit [uv](https://docs.astral.sh/uv/) – uv besorgt dabei auch Python 3.15:

```bash
uv tool install "sprintforecast[web] @ git+https://github.com/swallat/sprint-forecast"
sprintforecast --version
```

Aktualisieren mit `uv tool upgrade sprintforecast`, entfernen mit
`uv tool uninstall sprintforecast`. `[web]` bringt die Weboberfläche mit;
ohne Extra wird nur die Kommandozeile installiert.

## Schnellstart

```bash
cd sprint-daten                    # Datenverzeichnis: je Team ein Unterordner
sprintforecast web                 # Weboberfläche
sprintforecast hilfe               # Was ist wann zu tun?
sprintforecast forecast team-a     # Prognose auf der Kommandozeile
```

**Datenverzeichnis:** `--daten PFAD`, sonst die Umgebungsvariable `SPRINTFORECAST_DATEN`,
sonst das **aktuelle Verzeichnis**. Teams sind Unterordner mit einer `team.yaml`.

**Windows PowerShell:**

```powershell
uv tool install "sprintforecast[web] @ git+https://github.com/swallat/sprint-forecast"
cd "$HOME\sprint-daten"
sprintforecast web
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
| | Planning / Review | Formulare mit Erklärungen zu jedem Feld |
| Team | Personen | eine Tabelle (Zeile je Zeitraum, FTE); IDs automatisch; Ehemalige ausblendbar |
| | Einstellungen | alle Team-Einstellungen; Änderungen werden vor dem Speichern angezeigt |
| | Neues Team | Team anlegen |
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
| Urlaub o. Ä. wird bekannt | `sprintforecast fehltage team-a [SPRINT]` | Fehltage je Person erfassen (Standard: nächster Sprint). Zeigt Kapazität und Prognose. |
| Team ändert sich | `sprintforecast personen team-a` | Person hinzufügen, FTE ändern, Austritt eintragen. |
| Einstellungen ändern | `sprintforecast einstellungen team-a` | Bundesland, Referenzkapazität, Trend-Modus usw. geführt ändern; zeigt die Änderungen vor dem Speichern. |
| Sprint Planning | `sprintforecast planning team-a` | Zeigt Forecast PLAN; erfasst Forecast IST, Überkipper, Backlog, Korrekturen; zeigt das Delta. |
| Sprint Review | `sprintforecast review team-a --commit` | Erfasst Velocity und Scope Creep, friert die Kapazität ein, committet und setzt Tag `team-a/<sprint>`. |
| PO-Planung | `sprintforecast forecast team-a` | Prognose für laufenden + nächste Sprints. |
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
capacity:
  overhead_share: 0.0       # pauschaler Abzug für Scrum-Termine
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

**`sprints/<id>.yaml`** – leere Felder sind `null` (= keine Angabe):

```yaml
id: '2026.21'               # in Anführungszeichen!
start: 2026-10-14
end: 2026-10-28             # Arbeitstage zählen von start bis einschließlich end − 1
absences: {ben: 3, cem: 5}  # planbare Fehltage (Arbeitstage), ohne Feiertage
capacity: null              # wird beim Review eingefroren; manuell nur ohne Personenliste
forecast_ist: 10
velocity: null
scope_creep: null           # Anteil, 0.3 = 30 %
planning: {carryover: 0.25, backlog: 9.48, corrections: [1.5]}
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

**Kapazität eines Sprints** – in dieser Reihenfolge:
1. `capacity` in der Sprintdatei (eingefroren oder manuell) → *erfasst*
2. Sprintdatei existiert, Personenliste vorhanden → Σ Personen
   (Arbeitstage − Feiertage − Fehltage) × FTE − Overhead → *Personenliste*
3. Keine Sprintdatei → Kapazitäts-Trend → *Trend* (im Bericht mit ⚠️ markiert)

**Trend-Modi** (`forecast.trend_mode`):
- `klassisch` (Standard): 1. Zukunftssprint linear `Ø + (Ø − Ø_vorher)`,
  2. multiplikativ `Ø_vorletzt / Ø_vorvorletzt × Trend_vorher`, danach linear.
- `linear`: durchgehend linear.
- `flat`: letzter Ø bleibt konstant (robust bei langen Horizonten).

## Erweiterungen (Plugins)

Plugins sind eigene Python-Pakete, die sich über den Entry-Point
`sprintforecast.plugins` einklinken (siehe `src/sprintforecast/plugins.py`). Sie können
Befehle für die Kommandozeile und Seiten für die Weboberfläche ergänzen – etwa einen Import
der Historie aus einem bisherigen Werkzeug. Installiert werden sie neben dem Tool:

```bash
uv tool install "sprintforecast[web] @ git+https://github.com/swallat/sprint-forecast" \
  --with "mein-plugin @ git+https://…"
```

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
