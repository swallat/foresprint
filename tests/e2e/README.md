# Browsertests (Playwright)

Diese Tests starten die Weboberfläche wirklich (`sprintforecast web --no-browser`, eigener Port,
Kopie der Demo-Daten, fester Stichtag 2026-10-15, eigener Einstellungsordner) und bedienen sie in
einem Browser. Sie prüfen, was `AppTest` nicht sieht: gemessene Höhen und Breiten, Text im
Datenraster, echtes Klicken und Tippen, zwei Apps gegen ein gemeinsames Git-Repository.

Die normale Suite (`uv run pytest`) führt sie **nicht** aus (Marker `e2e`, in `pyproject.toml`
ausgeschlossen). Aufruf:

```bash
uv sync --all-extras
uv run playwright install chromium          # einmalig; unter Linux zusätzlich --with-deps
uv run pytest -m e2e                        # alle Browsertests
uv run pytest -m e2e tests/e2e/test_stepbar.py -k 1400
```

Umgebungsvariablen:

| Variable | Wirkung |
|---|---|
| `E2E_CHANNEL` | einen installierten Browser nehmen, z. B. `msedge` oder `chrome` (Windows) |
| `E2E_EXECUTABLE` | Pfad zu einem Chromium (statt des von Playwright geladenen) |
| `E2E_HEADED=1` | sichtbares Fenster, zum Zusehen |
| `E2E_ARTIFACTS` | Ordner für Bilder und Server-Protokolle fehlgeschlagener Tests (Standard `test-results/e2e`) |

## Aufbau

- `harness.py`: App-Instanzen starten/beenden (Prozessbaum wird sauber beendet), Git-Repositories
  vorbereiten, Hilfen zum Auslesen von Streamlit-Seiten (Datenraster über ihre barrierefreie
  Tabelle, Eingabe in das Raster per Tastatur, „Speichern und teilen“).
- `conftest.py`: Browser, Seiten, Apps (`app` und `app_without_products` nur zum Lesen,
  `make_app` und `clones` je Test).
- Tests: `test_smoke` (jede Seite ohne Fehler, auch Team ohne Produkte), `test_start`,
  `test_sprint_choice`, `test_language`, `test_stepbar` (gleiche Höhe bei jeder Breite),
  `test_tables` (keine „None“-Zellen, nichts abgeschnitten), `test_server_mask`,
  `test_two_clones` (Alice und Bob: Änderungen, Wertkonflikt, Neustart im Konflikt, Tags).

## Fehlersuche

Schlägt ein Test fehl, liegen im Ordner `test-results/e2e/` (in der CI als Artefakt `e2e-bilder`)
ein Bild je geöffneter Seite (`<Test>.png`, bei mehreren `<Test>-1.png` …) und das Protokoll
jeder beteiligten App (`<Test>-<App>.log`). Beides wird gesichert, solange Seiten und Server noch
laufen. Eine App, die nicht startet, wird sofort wieder beendet; ihr Protokoll steht in der
Fehlermeldung.

## Nicht flackern

Keine festen Wartezeiten. Gewartet wird auf Zustände: `expect(...)` mit automatischem Warten
(Zeitlimit 20 s, siehe `conftest.py`), die Gesundheitsprüfung des Servers und – nach Eingaben –
das Ergebnis im Seiteninhalt. `settle()` gilt nur nach dem Laden einer Seite; nach einem Klick
sieht es womöglich noch den Zustand *vor* dem Lauf (siehe `rerun_finished`). Streamlit lädt
Datenraster und Diagramme erst nach dem Ende des Skripts nach: darauf wartet
`wait_until_stable`.

Nicht getestet wird bewusst: zwei Tabs oder Nutzer im selben Checkout (kommt in der Praxis nie vor).
