# SPDX-License-Identifier: EUPL-1.2
import shutil
from pathlib import Path

import pytest
from gitrepos import alice, bob, clean_caches, no_login_prompt, remote  # noqa: F401  (Fixtures)
from webfixtures import repo, second_folder, shared  # noqa: F401  (Fixtures)

from sprintforecast import i18n

EXAMPLES = Path(__file__).parent.parent / "examples" / "teams"


@pytest.fixture
def english(monkeypatch: pytest.MonkeyPatch):
    """Die Oberfläche und die Meldungen sind englisch (auch in AppTest-Läufen)."""
    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, "en")
    yield
    i18n.set_language(None)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Kopie der Demo-Daten, die Tests verändern dürfen."""
    target = tmp_path / "teams"
    shutil.copytree(EXAMPLES, target)
    return target


@pytest.fixture(autouse=True)
def no_git_outside_path(monkeypatch: pytest.MonkeyPatch):
    """Git wird nur im PATH gesucht, nicht an den Ersatzorten dieses Rechners (Homebrew, Scoop
    …): Tests, die Git „entfernen“ (PATH leeren), bleiben so auf jedem Rechner gleich."""
    from sprintforecast import git

    git.reset_git_cache()
    monkeypatch.setattr(git, "git_locations", lambda: [])
    yield
    git.reset_git_cache()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Keine echten Benutzereinstellungen (gemerkter Datenordner, Update-Stand) verwenden."""
    config = tmp_path_factory.mktemp("config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("APPDATA", str(config))
