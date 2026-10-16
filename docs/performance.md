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
  geladen werden. Die Forecast-Seite (Startseite) braucht beide; der Kaltstart bis zur ersten Seite
  sinkt dadurch um rund 0,3 s, ein Teil verschiebt sich auf den ersten Seitenaufbau.
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
  wird (Messung mit größeren Teams siehe offene Punkte).

Referenz des Eigentümers (Windows, vorher): Team laden ca. 18 ms (PyYAML `safe_load` ca. 46 ms
im Planning-Rerun), `build_forecast` 0,25 bis 1,3 ms, Seitenwechsel im AppTest 35 bis 45 ms,
`import pandas` 0,4 bis 1,0 s, `import streamlit` ca. 0,5 s, `git status` Median ca. 61 ms.

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
