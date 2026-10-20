# SPDX-License-Identifier: EUPL-1.2
import shutil
from pathlib import Path

import pytest
from gitrepos import alice, bob, clean_caches, no_login_prompt, remote  # noqa: F401  (Fixtures)
from webfixtures import repo, second_folder, shared  # noqa: F401  (Fixtures)

from sprintforecast import i18n

EXAMPLES = Path(__file__).parent.parent / "examples" / "teams"


@pytest.fixture(autouse=True)
def german_by_default(monkeypatch: pytest.MonkeyPatch):
    """The UI is English by default; the test suite still expects German texts, so every test
    defaults to "de" (tests using the ``english`` fixture or SPRINTFORECAST_LANG=en are
    unaffected)."""
    monkeypatch.setattr(i18n, "DEFAULT", "de")


@pytest.fixture(autouse=True)
def no_background_fetch(monkeypatch: pytest.MonkeyPatch):
    """No background fetch of the server state: a thread that changes the Git state in the middle
    of a test would make runs flaky (tests for it reset the variable)."""
    monkeypatch.setenv("SPRINTFORECAST_NO_BACKGROUND_FETCH", "1")


@pytest.fixture
def english(monkeypatch: pytest.MonkeyPatch):
    """The UI and messages are English (also in AppTest runs)."""
    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, "en")
    yield
    i18n.set_language(None)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Copy of the demo data that tests may modify."""
    target = tmp_path / "teams"
    shutil.copytree(EXAMPLES, target)
    return target


@pytest.fixture(autouse=True)
def no_git_outside_path(monkeypatch: pytest.MonkeyPatch):
    """Look for Git only in PATH, not in the fallback locations of this machine (Homebrew, Scoop
    ...): tests that "remove" Git (empty PATH) behave the same on every machine."""
    from sprintforecast import git

    git.reset_git_cache()
    monkeypatch.setattr(git, "git_locations", lambda: [])
    yield
    git.reset_git_cache()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Do not use real user settings (remembered data folder, update state)."""
    config = tmp_path_factory.mktemp("config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("APPDATA", str(config))
