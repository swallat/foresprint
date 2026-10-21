# SPDX-License-Identifier: EUPL-1.2
"""Measurement script for phase P (performance): import times, team loading, build_forecast,
Git status and the build of several pages via the Streamlit AppTest.

    uv run python scripts/measure.py [--data examples/teams] [--team demo] [--runs 15] [--md]

All values are medians in milliseconds (imports: median over fresh processes). The script only
measures the machine it runs on; browser start-up, frontend rendering and round trips are
deliberately left out (see docs/performance.md).
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
APP = ROOT / "src" / "foresprint" / "web" / "app.py"
PAGES = ["forecast", "absences", "planning", "analysis", "products", "people", "help"]
IMPORTS = [
    "yaml",
    "pandas",
    "altair",
    "streamlit",
    "rich.console",
    "typer",
    "foresprint.storage",
    "foresprint.forecast",
    "foresprint.web.ui",
    "foresprint.cli",
]


def median_ms(fn, runs: int) -> float:
    """Median run time of ``fn`` in milliseconds (one warm-up run does not count)."""
    fn()
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def import_ms(module: str, runs: int) -> float:
    """Import time in a fresh process (median); ``nan`` if the module is missing."""
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
    from foresprint.forecast import build_forecast
    from foresprint.git import pending_changes
    from foresprint.storage import Repository

    result: dict[str, float] = {}
    for module in IMPORTS:
        result[f"import {module}"] = import_ms(module, max(3, runs // 3))
    repo = Repository(data)
    result["Load team (no cache)"] = median_ms(lambda: repo.load(team), runs)
    cached = getattr(repo, "load_cached", None)  # only present from phase P on
    result["Load team (cache hit)"] = (
        median_ms(lambda: cached(team), runs) if cached else float("nan")
    )
    loaded = repo.load(team)
    result["build_forecast"] = median_ms(lambda: build_forecast(loaded, today), runs)
    try:
        result["git status (pending_changes)"] = median_ms(lambda: pending_changes(data), runs)
    except Exception:
        result["git status (pending_changes)"] = float("nan")
    result.update(apptest(data, today, max(3, runs // 3)))
    return result


def apptest(data: Path, today: date, runs: int) -> dict[str, float]:
    """Cold start and per-page build via AppTest (no browser)."""
    from streamlit.testing.v1 import AppTest

    os.environ["FORESPRINT_DATA"] = str(data)
    os.environ["FORESPRINT_AS_OF"] = today.isoformat()
    start = time.perf_counter()
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    out = {"AppTest start (cold, first run)": (time.perf_counter() - start) * 1000}
    out["AppTest rerun (same page)"] = median_ms(lambda: at.run(), runs)
    for page in PAGES:

        def switch(page=page) -> None:
            at.switch_page(f"page_scripts/{page}.py").run()

        out[f"AppTest page {page}"] = median_ms(switch, runs)
    at.switch_page("page_scripts/forecast.py").run()
    assert not at.exception, at.exception
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=ROOT / "examples" / "teams")
    parser.add_argument("--team", default="demo")
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--as-of", default="2026-10-15")
    parser.add_argument("--md", action="store_true", help="print as a Markdown table")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as config:  # no real user settings
        os.environ["XDG_CONFIG_HOME"] = config
        os.environ["APPDATA"] = config
        values = measure(args.data, args.team, args.runs, date.fromisoformat(args.as_of))
    print(f"Python {sys.version.split()[0]}, {sys.platform}, runs: {args.runs}")
    if args.md:
        print("\n| Measurement | ms |\n|---|---:|")
    for name, ms in values.items():
        shown = "–" if ms != ms else f"{ms:.1f}"  # nan: not available
        print(f"| {name} | {shown} |" if args.md else f"{name:<45} {shown:>9} ms")


if __name__ == "__main__":
    main()
