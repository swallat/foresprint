# SPDX-License-Identifier: EUPL-1.2
"""Velocity- und Kapazitäts-Forecast für Scrum-Teams mit Git als Datenablage."""

__version__ = "0.3.1"


def main() -> None:
    from sprintforecast.cli import app

    app()


# Protokolldatei, wenn ohne Konsole gestartet (Doppelklick); `web` leitet den Server dorthin.
LOG_ENV = "SPRINTFORECAST_LOG"


def app_main() -> None:
    """Doppelklick-Start: Weboberfläche als App-Fenster (`sprintforecast web --app`)."""
    import os
    import sys

    from sprintforecast.config import config_dir

    log = config_dir() / "app.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 – lebt bis zum Ende
    # Ohne Konsole (pythonw) gibt es kein stdout/stderr; ausgaben ins Protokoll.
    sys.stdout = out if sys.stdout is None else sys.stdout
    sys.stderr = out if sys.stderr is None else sys.stderr
    os.environ[LOG_ENV] = str(log)
    import json

    from sprintforecast.updater import LAUNCHER_ENV

    # Für „Aktualisieren und neu starten“: diesen Starter erneut aufrufen, nicht die CLI.
    os.environ[LAUNCHER_ENV] = json.dumps([sys.argv[0], *sys.argv[1:]])
    from sprintforecast.cli import app

    app(args=["web", "--app", *sys.argv[1:]], prog_name="sprintforecast")
