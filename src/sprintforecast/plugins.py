# SPDX-License-Identifier: EUPL-1.2
"""Extensions via Python entry points (group ``sprintforecast.plugins``).

A plugin is a separately installed package that, e.g., in its ``pyproject.toml`` declares

    [project.entry-points."sprintforecast.plugins"]
    mein_import = "mein_paket.plugin:plugin"

as an entry point. ``plugin`` is a :class:`Plugin`; it can contribute commands for the command
line and pages for the web UI. It is installed next to the tool, e.g.

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
    key: str  # URL path, e.g. "mein_import"
    title: str
    icon: str  # e.g. ":material/upload_file:"
    render: Callable[[Repository], None]
    group: str = "Data & help"


@dataclass(frozen=True)
class Plugin:
    name: str
    # Receives the Typer app and registers its own commands.
    register_cli: Callable[[Any], None] | None = None
    web_pages: list[WebPage] = field(default_factory=list)


@cache
def load_plugins() -> tuple[Plugin, ...]:
    """Installed plugins; faulty ones are skipped with a warning."""
    plugins = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            plugin = ep.load()
        except Exception as e:  # a broken plugin must not block the tool
            print(f"Plugin {ep.name!r} konnte nicht geladen werden: {e}", file=sys.stderr)
            continue
        if isinstance(plugin, Plugin):
            plugins.append(plugin)
        else:
            print(f"Plugin {ep.name!r} ist kein sprintforecast.plugins.Plugin", file=sys.stderr)
    return tuple(plugins)


def web_pages() -> list[WebPage]:
    return [page for plugin in load_plugins() for page in plugin.web_pages]
