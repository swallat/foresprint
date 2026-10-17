# SPDX-License-Identifier: EUPL-1.2
import shutil
from pathlib import Path

import pytest
from gitrepos import alice, bob, clean_caches, remote  # noqa: F401  (Fixtures)
from webfixtures import repo, second_folder, shared  # noqa: F401  (Fixtures)

EXAMPLES = Path(__file__).parent.parent / "examples" / "teams"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Kopie der Demo-Daten, die Tests verändern dürfen."""
    target = tmp_path / "teams"
    shutil.copytree(EXAMPLES, target)
    return target


@pytest.fixture(autouse=True)
def isolated_config(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Keine echten Benutzereinstellungen (gemerkter Datenordner, Update-Stand) verwenden."""
    config = tmp_path_factory.mktemp("config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("APPDATA", str(config))
