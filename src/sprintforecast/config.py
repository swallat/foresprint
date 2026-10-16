# SPDX-License-Identifier: EUPL-1.2
"""Benutzereinstellungen außerhalb der Team-Daten (z. B. gemerkter Datenordner).

Ablage neben der Plugin-Auswahl der Installationsskripte:
Windows %APPDATA%\\sprintforecast, sonst ~/.config/sprintforecast.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PACKAGE = "sprintforecast"


def config_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / PACKAGE
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / PACKAGE


def _settings_file() -> Path:
    return config_dir() / "settings.json"


def load() -> dict[str, Any]:
    try:
        content = json.loads(_settings_file().read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return content if isinstance(content, dict) else {}


def update(**changes: Any) -> None:
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(load() | changes, indent=2, sort_keys=True), encoding="utf-8")
