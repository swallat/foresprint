# Performance (Phase P)

Dieses Dokument hält die Maßnahmen aus [konzept-kern.md](konzept-kern.md), Abschnitt E, und
ihre Messung fest.

## Messen

```bash
uv run python scripts/measure.py --md          # Demo-Team aus examples/teams
uv run python scripts/measure.py --daten PFAD --team NAME --runs 30
```

Das Skript gibt Mediane in Millisekunden aus: Importzeiten (je in einem frischen Prozess),
Team laden (ohne und mit Zwischenspeicher), `build_forecast`, Git-Status und den Aufbau von
Seiten mit dem Streamlit-AppTest (ohne Browser). Gemessen wird nur, was im Python-Prozess
passiert. **Nicht gemessen** sind Browserstart, Frontend-Rendering und die Wege zwischen Browser
und Server.

## Messprotokoll Cloud-Umgebung (Linux, x86_64, 4 Kerne, Python 3.14.6, Demo-Team mit 22 Sprints)

Vorher = `main` (78010e5 plus Messskript), nachher = dieser Stand. Einzelne Zeilen
schwanken von Lauf zu Lauf um etwa 10 bis 20 %.

| Messung | vorher (ms) | nachher (ms) |
|---|---:|---:|
| import yaml | 14.9 | 14.0 |
| import pandas | 308.9 | 356.8 |
| import altair | 256.3 | 255.2 |
| import streamlit | 258.3 | 246.8 |
| import rich.console | 39.4 | 33.5 |
| import typer | 48.2 | 45.9 |
| import sprintforecast.storage | 32.4 | 36.2 |
| import sprintforecast.forecast | 79.9 | 80.2 |
| import sprintforecast.web.ui | 982.8 | 387.1 |
| import sprintforecast.cli | 258.0 | 232.7 |
| Team laden (ohne Cache) | 19.5 | 4.7 |
| Team laden (Cache-Treffer) | – | 0.7 |
| build_forecast | 0.3 | 0.3 |
| git status (pending_changes) | 2.5 | 3.0 |
| AppTest Start (kalt, erster Lauf) | 1083.4 | 792.1 |
| AppTest erneuter Lauf (gleiche Seite) | 71.2 | 32.8 |
| AppTest Seite forecast | 63.4 | 32.0 |
| AppTest Seite fehltage | 52.8 | 23.6 |
| AppTest Seite planning | 48.3 | 20.5 |
| AppTest Seite analyse | 42.8 | 19.1 |
| AppTest Seite produkte | 118.8 | 74.6 |
| AppTest Seite personen | 63.4 | 18.1 |
| AppTest Seite hilfe | 33.5 | 29.3 |

Lesehilfe:

- `import sprintforecast.web.ui` (alles, was der Start der Oberfläche vor der ersten Seite
  importiert) sinkt, weil `pandas` und `altair` erst bei der ersten Seite mit Tabelle oder Diagramm
  geladen werden. Die Seiten der Auswertung (z. B. Forecast) brauchen beide, die Startseite „Start“
  nicht. Gemessen wurde das, als der Forecast noch die Startseite war: Der Kaltstart bis zur ersten
  Seite sank um rund 0,3 s, ein Teil verschiebt sich auf den ersten Seitenaufbau.
- Team laden: Der C-Lader von libyaml (`CSafeLoader`) senkt das Laden eines Teams ohne
  Zwischenspeicher deutlich; bei unveränderten Dateien liefert der Zwischenspeicher das Team in
  unter einer Millisekunde (Dateiversion prüfen plus Kopie).
- Seitenwechsel und erneute Läufe im AppTest sinken auf etwa die Hälfte (Team-Cache, C-Lader,
  kein Warten auf die Update-Anzeige).
- Git-Status ist in der Cloud mit ca. 3 ms schnell (kleiner Klon, Linux). Unter Windows
  gemessen waren es im Median etwa 61 ms; dort bringt der Zwischenspeicher am meisten.
- `build_forecast` braucht 0,3 ms. Er wird **nicht** zwischengespeichert: Eine Kopie des
  Ergebnisses (das Ergebnis muss unabhängig bleiben, weil Seiten Vorschauen daraus rechnen) wäre
  langsamer als die Berechnung. Ein Zwischenspeicher lohnt erst, wenn die Berechnung spürbar
  wird; gemessen wurde nur mit dem Demo-Team (22 Sprints), größere Teams sind nicht gemessen.

Referenz des Eigentümers (Windows, vorher): Team laden ca. 18 ms (PyYAML `safe_load` ca. 46 ms
im Planning-Rerun), `build_forecast` 0,25 bis 1,3 ms, Seitenwechsel im AppTest 35 bis 45 ms,
`import pandas` 0,4 bis 1,0 s, `import streamlit` ca. 0,5 s, `git status` Median ca. 61 ms.

## Messprotokoll Windows (Eigentümer, Python 3.14.8, Demo-Team)

Gemessen am 17.10.2026 mit `scripts\measure.py --md` auf dem Arbeitsrechner. Vorher = Commit
`78010e5` (vor PR 1), nachher = `main` nach dem Merge von PR 1. Mediane in ms.

| Messung | vorher | nachher |
|---|---:|---:|
| import yaml | 23,8 | 24,2 |
| import pandas | 475,1 | 488,8 |
| import altair | 331,6 | 321,3 |
| import streamlit | 480,2 | 433,3 |
| import rich.console | 53,3 | 49,6 |
| import typer | 74,9 | 74,3 |
| import sprintforecast.storage | 46,5 | 50,1 |
| import sprintforecast.forecast | 124,9 | 124,4 |
| import sprintforecast.web.ui | 1364,8 | 730,9 |
| import sprintforecast.cli | 409,6 | 394,9 |
| Team laden (ohne Cache) | 18,4 | 5,0 |
| Team laden (Cache-Treffer) | – | 1,1 |
| build_forecast | 0,3 | 0,3 |
| git status (pending_changes) | 60,0 | 52,9 |
| AppTest Start (kalt, erster Lauf) | 1165,7 | 1175,4 |
| AppTest erneuter Lauf (gleiche Seite) | 99,4 | 23,6 |
| AppTest Seite forecast | 101,4 | 24,0 |
| AppTest Seite fehltage | 94,1 | 18,5 |
| AppTest Seite planning | 96,5 | 18,8 |
| AppTest Seite analyse | 90,2 | 17,4 |
| AppTest Seite produkte | 122,1 | 46,4 |
| AppTest Seite personen | 91,4 | 16,2 |
| AppTest Seite hilfe | 80,5 | 23,6 |

Ergebnis (nur Python-Prozess, ohne Browser):

- **Seitenaufbau und erneuter Lauf** sinken von 80 bis 120 ms auf 16 bis 46 ms (Seite
  `produkte` 122 → 46 ms, alle anderen unter 25 ms). Normale Eingaben liegen damit im
  Python-Teil weit unter dem Ziel von 200 ms.
- **Team laden** 18 → 5 ms (C-Lader), bei unverändertem Stand 1,1 ms (Cache).
- **Import der Oberfläche** 1365 → 731 ms (ohne `pandas`/`altair`).
- **Kalter Start** im AppTest bleibt bei etwa 1,2 s: Die Startseite (Forecast) braucht
  `pandas` und `altair`, was sich vom Import in den ersten Seitenaufbau verschiebt. Hier bringt
  PR 1 auf diesem Rechner nichts.
- **Git-Status** 60 → 53 ms pro Abfrage; der Zwischenspeicher spart ihn bei Eingaben innerhalb von
  5 Sekunden.
- Einzelne Importzeiten schwanken um 10 bis 20 % (Reihenfolge, Festplattencache).

Die Stoppuhr-Messung im Browser (Start bis zur ersten Seite, Ziel unter 3 s; normale Eingaben,
Ziel unter 200 ms) ist der einzige offene Rest, siehe „Ziele und Abnahme“.

## Umgesetzte Maßnahmen

1. **Update-Anzeige** wartet nicht mehr auf den Hintergrundthread (`result()` ohne `wait`); das
   Ergebnis erscheint im nächsten Durchlauf.
2. **Git-Status** wird höchstens alle 5 Sekunden abgefragt (`git.cached_pending_changes`). Jedes
   Schreiben über `Repository`, jeder Commit und der Wechsel des Datenordners machen ihn
   ungültig. Änderungen außerhalb der App (Editor, Terminal) erscheinen nach höchstens 5 Sekunden.
3. **Team-Zwischenspeicher** (`Repository.load_cached`): Schlüssel ist Datenordner und Team,
   Gültigkeit die Dateiversion (Name, Änderungszeit in ns, Größe von `team.yaml`, `people.yaml`,
   `products.yaml` und allen Sprintdateien – neue und gelöschte Dateien ändern sie).
   Jeder Aufrufer erhält eine eigene Kopie. Dateien, die in den letzten 2 Sekunden geändert
   wurden, werden nicht zwischengespeichert (grobe Zeitauflösung von Dateisystemen). Speichern
   und Ordnerwechsel leeren den Zwischenspeicher zusätzlich.
   Seiten ohne Prognose (Personen, Produkte, Einstellungen) berechnen keinen Forecast.
4. **YAML** mit `CSafeLoader`, falls PyYAML mit libyaml gebaut ist; sonst `SafeLoader`.
5. **Lazy Imports:** `pandas` und `altair` werden beim ersten Zugriff geladen
   (`web/lazy.py`). `rich`, `typer` und die Kommandozeile werden von der Oberfläche nicht
   importiert (durch einen Test abgesichert).
6. **Fragmente:** Der Rechenweg (Auswahl des Sprints) und das Was-wäre-wenn-Panel der
   Forecast-Seite zeichnen bei Eingaben nur sich selbst neu. Weitere Bereiche (Produkt-Editor,
   Fehltage-Matrix, Planning) speisen Ergebnisse in den Rest der Seite und sind daher bewusst
   keine Fragmente; ein Formular würde dort die Live-Vorschau entfernen.

## Ziele und Abnahme

Ziele: Start unter 3 Sekunden, normale Eingaben unter 200 ms. Diese Ziele **prüft der
Eigentümer mit der Stoppuhr auf seinem Rechner** (Browser und Frontend eingeschlossen); die
Cloud-Messung belegt nur den Anteil im Python-Prozess.

Stand: Phase P ist abgeschlossen. Alle sechs Maßnahmen sind umgesetzt, und die Messprotokolle
(Cloud und Windows) liegen vor. Offen ist ausschließlich die Stoppuhr-Abnahme im Browser auf dem
Rechner des Eigentümers (Start unter 3 s, normale Eingaben unter 200 ms); sie wird auf Wunsch
nachgeholt.
