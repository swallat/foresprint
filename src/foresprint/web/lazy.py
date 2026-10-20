# SPDX-License-Identifier: EUPL-1.2
"""Import modules only on first access.

``pandas`` and ``altair`` together cost roughly half a second to a second on a cold start and
are only needed by pages with tables and charts."""

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
