# SPDX-License-Identifier: EUPL-1.2
"""Module erst beim ersten Zugriff importieren.

``pandas`` und ``altair`` kosten beim Kaltstart zusammen rund eine halbe bis eine Sekunde und
werden nur von Seiten mit Tabellen und Diagrammen gebraucht."""

from __future__ import annotations

import importlib
from types import ModuleType


class LazyModule:
    def __init__(self, name: str) -> None:
        self._name = name
        self._module: ModuleType | None = None

    def __getattr__(self, attr: str) -> object:
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return getattr(self._module, attr)
