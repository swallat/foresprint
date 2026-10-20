# SPDX-License-Identifier: EUPL-1.2
"""User settings outside the team data (e.g. the remembered data folder).

Stored next to the plugin selection of the install scripts:
Windows %APPDATA%\\sprintforecast, otherwise ~/.config/sprintforecast.
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
    """The settings cannot be saved (e.g. folder not writable). The message is meant for
    users."""


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
    """Back up an unreadable settings file before it is overwritten."""
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
    while target.exists():  # an older backup is kept
        n += 1
        target = path.with_name(f"{path.name}.defekt-{stamp}" + (f"-{n}" if n > 1 else ""))
    shutil.copy2(path, target)


def update(**changes: Any) -> None:
    """Save settings atomically (via a temporary file, never half-written); a corrupted file is
    backed up first as ``settings.json.defekt`` (an older backup is kept, the new one gets a
    timestamp). If that fails, a :class:`SettingsError` with an understandable message is raised."""
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
