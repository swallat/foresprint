# SPDX-License-Identifier: EUPL-1.2
"""Messskript für Phase P (Performance): Importzeiten, Teamladen, build_forecast, Git-Status
und der Aufbau mehrerer Seiten per Streamlit AppTest.

    uv run python scripts/measure.py [--daten examples/teams] [--team demo] [--runs 15] [--md]

Alle Werte sind Mediane in Millisekunden (Importe: Median aus frischen Prozessen). Das Skript
misst nur auf dem Rechner, auf dem es läuft – Browserstart, Frontend-Rendering und Roundtrip
fehlen bewusst (siehe docs/performance.md).
"""

from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "src" / "sprintforecast" / "web" / "app.py"
PAGES = ["forecast", "fehltage", "planning", "analyse", "produkte", "personen", "hilfe"]
IMPORTS = [
    "yaml",
    "pandas",
    "altair",
    "streamlit",
    "rich.console",
    "typer",
    "sprintforecast.storage",
    "sprintforecast.forecast",
    "sprintforecast.web.ui",
    "sprintforecast.cli",
]


def median_ms(fn, runs: int) -> float:
    """Median der Laufzeit von ``fn`` in Millisekunden (ein Aufwärmlauf zählt nicht)."""
    fn()
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def import_ms(module: str, runs: int) -> float:
    """Importzeit in einem frischen Prozess (Median); fehlt das Modul, ``nan``."""
    code = (
        "import time; t = time.perf_counter(); "
        f"import {module}; print((time.perf_counter() - t) * 1000)"
    )
    times = []
    for _ in range(runs):
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        if out.returncode != 0:
            return float("nan")
        times.append(float(out.stdout.strip()))
    return statistics.median(times)


def measure(data: Path, team: str, runs: int, today: date) -> dict[str, float]:
    from sprintforecast.forecast import build_forecast
    from sprintforecast.git import pending_changes
    from sprintforecast.storage import Repository

    result: dict[str, float] = {}
    for module in IMPORTS:
        result[f"import {module}"] = import_ms(module, max(3, runs // 3))
    repo = Repository(data)
    result["Team laden (ohne Cache)"] = median_ms(lambda: repo.load(team), runs)
    loaded = repo.load(team)
    result["build_forecast"] = median_ms(lambda: build_forecast(loaded, today), runs)
    try:
        result["git status (pending_changes)"] = median_ms(lambda: pending_changes(data), runs)
    except Exception:
        result["git status (pending_changes)"] = float("nan")
    result.update(apptest(data, today, max(3, runs // 3)))
    return result


def apptest(data: Path, today: date, runs: int) -> dict[str, float]:
    """Startlauf (kalt) und Seitenaufbau je Seite per AppTest (ohne Browser)."""
    from streamlit.testing.v1 import AppTest

    os.environ["SPRINTFORECAST_DATEN"] = str(data)
    os.environ["SPRINTFORECAST_STICHTAG"] = today.isoformat()
    start = time.perf_counter()
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    out = {"AppTest Start (kalt, erster Lauf)": (time.perf_counter() - start) * 1000}
    out["AppTest erneuter Lauf (gleiche Seite)"] = median_ms(lambda: at.run(), runs)
    for page in PAGES:

        def switch(page=page) -> None:
            at.switch_page(f"seiten/{page}.py").run()

        out[f"AppTest Seite {page}"] = median_ms(switch, runs)
    at.switch_page("seiten/forecast.py").run()
    assert not at.exception, at.exception
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--daten", type=Path, default=ROOT / "examples" / "teams")
    parser.add_argument("--team", default="demo")
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--stichtag", default="2026-10-15")
    parser.add_argument("--md", action="store_true", help="als Markdown-Tabelle ausgeben")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as config:  # keine echten Benutzereinstellungen
        os.environ["XDG_CONFIG_HOME"] = config
        os.environ["APPDATA"] = config
        values = measure(args.daten, args.team, args.runs, date.fromisoformat(args.stichtag))
    print(f"Python {sys.version.split()[0]}, {sys.platform}, Läufe: {args.runs}")
    if args.md:
        print("\n| Messung | ms |\n|---|---:|")
    for name, ms in values.items():
        print(f"| {name} | {ms:.1f} |" if args.md else f"{name:<45} {ms:9.1f} ms")


if __name__ == "__main__":
    main()
