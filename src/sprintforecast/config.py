# SPDX-License-Identifier: EUPL-1.2
"""Benutzereinstellungen außerhalb der Team-Daten (z. B. gemerkter Datenordner).

Ablage neben der Plugin-Auswahl der Installationsskripte:
Windows %APPDATA%\\sprintforecast, sonst ~/.config/sprintforecast.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from sprintforecast.i18n import t

PACKAGE = "sprintforecast"


class SettingsError(OSError):
    """Die Einstellungen lassen sich nicht speichern (z. B. Ordner nicht beschreibbar). Die
    Meldung ist für Anwender gedacht."""


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


def _keep_damaged(path: Path) -> None:
    """Sichert eine unlesbare Einstellungsdatei, bevor sie überschrieben wird."""
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except OSError, ValueError:
        pass
    else:
        if isinstance(content, dict):
            return
    target = path.with_name(path.name + ".defekt")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    n = 0
    while target.exists():  # eine ältere Sicherung bleibt erhalten
        n += 1
        target = path.with_name(f"{path.name}.defekt-{stamp}" + (f"-{n}" if n > 1 else ""))
    shutil.copy2(path, target)


def update(**changes: Any) -> None:
    """Speichert Einstellungen: atomar (über eine Zwischendatei, nie halb geschrieben); eine
    beschädigte Datei wird vorher als ``settings.json.defekt`` gesichert (eine ältere
    Sicherung bleibt erhalten, die neue bekommt einen Zeitstempel). Schlägt das fehl, kommt
    eine :class:`SettingsError` mit verständlicher Meldung."""
    path = _settings_file()
    tmp: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _keep_damaged(path)
        text = json.dumps(load() | changes, indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            tmp = handle.name
            handle.write(text)
        os.replace(tmp, path)
        tmp = None
    except OSError as e:
        raise SettingsError(
            t(
                "The settings could not be saved ({path}): {error}",
                path=path,
                error=e.strerror or e,
            )
        ) from e
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
