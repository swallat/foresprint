# SPDX-License-Identifier: EUPL-1.2
"""The package was renamed to ``foresprint``. This alias keeps ``import sprintforecast`` and
``import sprintforecast.storage`` (plugins written before the rename) working: both names lead
to the very same module objects."""

import importlib
import importlib.abc
import importlib.util
import sys

import foresprint

_OLD, _NEW = "sprintforecast", "foresprint"


class _Alias(importlib.abc.Loader):
    def __init__(self, module):
        self.module = module
        self.spec = module.__spec__

    def create_module(self, spec):
        return self.module

    def exec_module(self, module):
        module.__spec__ = self.spec  # the real module keeps its own identity
        module.__loader__ = self.spec.loader


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(_OLD + "."):
            return None
        real = importlib.import_module(_NEW + fullname[len(_OLD) :])
        spec = importlib.util.spec_from_loader(
            fullname, _Alias(real), is_package=hasattr(real, "__path__")
        )
        return spec


if not any(isinstance(f, _Finder) for f in sys.meta_path):
    sys.meta_path.insert(0, _Finder())
sys.modules[_OLD] = foresprint  # ``import sprintforecast`` yields the real package
