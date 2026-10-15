# SPDX-License-Identifier: EUPL-1.2
"""Velocity- und Kapazitäts-Forecast für Scrum-Teams mit Git als Datenablage."""

__version__ = "0.1.0"


def main() -> None:
    from sprintforecast.cli import app

    app()
