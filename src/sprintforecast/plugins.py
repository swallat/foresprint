# SPDX-License-Identifier: EUPL-1.2
"""Erweiterungen über Python-Entry-Points (Gruppe ``sprintforecast.plugins``).

Ein Plugin ist ein separat installiertes Paket, das in seiner ``pyproject.toml`` z. B.

    [project.entry-points."sprintforecast.plugins"]
    mein_import = "mein_paket.plugin:plugin"

einträgt. ``plugin`` ist ein :class:`Plugin`; es kann Befehle für die Kommandozeile und
Seiten für die Weboberfläche beisteuern. Installiert wird es neben dem Tool, z. B.

    uv tool install "sprintforecast[web] @ git+…" --with "mein-paket @ git+…"
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sprintforecast.storage import Repository

ENTRY_POINT_GROUP = "sprintforecast.plugins"


@dataclass(frozen=True)
class WebPage:
    key: str  # URL-Pfad, z. B. "mein_import"
    title: str
    icon: str  # z. B. ":material/upload_file:"
    render: Callable[[Repository], None]
    group: str = "Daten & Hilfe"


@dataclass(frozen=True)
class Plugin:
    name: str
    # Erhält die Typer-App und registriert eigene Befehle.
    register_cli: Callable[[Any], None] | None = None
    web_pages: list[WebPage] = field(default_factory=list)


@cache
def load_plugins() -> tuple[Plugin, ...]:
    """Installierte Plugins; fehlerhafte werden mit Hinweis übersprungen."""
    plugins = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            plugin = ep.load()
        except Exception as e:  # ein defektes Plugin darf das Tool nicht blockieren
            print(f"Plugin {ep.name!r} konnte nicht geladen werden: {e}", file=sys.stderr)
            continue
        if isinstance(plugin, Plugin):
            plugins.append(plugin)
        else:
            print(f"Plugin {ep.name!r} ist kein sprintforecast.plugins.Plugin", file=sys.stderr)
    return tuple(plugins)


def web_pages() -> list[WebPage]:
    return [page for plugin in load_plugins() for page in plugin.web_pages]
