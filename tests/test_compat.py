# SPDX-License-Identifier: EUPL-1.2
"""Names from before the rename to Foresprint keep working."""

import subprocess
import sys
from pathlib import Path

import pytest
from gitrepos import make_local

from sprintforecast import compat, config, gitsync
from sprintforecast.sources import jira as jira_module


def test_legacy_environment_variables_are_adopted():
    env = {"SPRINTFORECAST_DATA": "/old", "SPRINTFORECAST_LANG": "de", "FORESPRINT_LANG": "en"}
    compat.adopt_legacy_environment(env)
    assert env["FORESPRINT_DATA"] == "/old"
    assert env["FORESPRINT_LANG"] == "en"  # a new variable wins
    assert env["SPRINTFORECAST_DATA"] == "/old"  # the old one stays for child programs


def test_legacy_variable_reaches_a_fresh_process():
    code = "import os, sprintforecast; print(os.environ.get('FORESPRINT_AS_OF'))"
    out = subprocess.run(
        [sys.executable, "-c", code],
        env={"SPRINTFORECAST_AS_OF": "2026-01-02", "PATH": "", "SYSTEMROOT": "C:\\Windows"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "2026-01-02"


def test_config_folder_is_copied_not_moved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    legacy = tmp_path / "sprintforecast"
    legacy.mkdir()
    (legacy / "settings.json").write_text('{"language": "de"}', encoding="utf-8")
    assert config.load() == {"language": "de"}
    assert (tmp_path / "foresprint" / "settings.json").is_file()
    assert (legacy / "settings.json").is_file()  # the old folder stays as a backup
    config.update(language="en")
    assert config.load() == {"language": "en"}
    assert '"de"' in (legacy / "settings.json").read_text(encoding="utf-8")


def test_config_migration_fills_a_folder_the_installer_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    legacy = tmp_path / "sprintforecast"
    legacy.mkdir()
    (legacy / "settings.json").write_text('{"data_dir": "/x"}', encoding="utf-8")
    (legacy / "plugins").write_text("old", encoding="utf-8")
    (tmp_path / "foresprint").mkdir()
    (tmp_path / "foresprint" / "plugins").write_text("new", encoding="utf-8")  # written first
    assert config.load() == {"data_dir": "/x"}
    assert (tmp_path / "foresprint" / "plugins").read_text(encoding="utf-8") == "new"


def test_legacy_git_settings_are_read_and_replaced(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    for key, value in (
        ("sprintforecast.share", "merge_request"),
        ("sprintforecast.host", "gitlab"),
        ("sprintforecast.mrautomerge", "false"),
    ):
        subprocess.run(["git", "config", "--local", key, value], cwd=root, check=True)
    assert gitsync.share_mode(data) == gitsync.SHARE_MERGE_REQUEST
    assert gitsync.host_setting(data) == "gitlab"
    assert gitsync.auto_merge(data) is False
    gitsync.set_share_mode(data, gitsync.SHARE_DIRECT)  # saving drops the old spelling
    gitsync.set_host(data, "github")
    gitsync.set_auto_merge(data, True)
    listing = subprocess.run(
        ["git", "config", "--local", "--list"], cwd=root, capture_output=True, text=True
    ).stdout
    assert "sprintforecast." not in listing
    assert "foresprint.host=github" in listing
    assert gitsync.share_mode(data) == gitsync.SHARE_DIRECT


def test_token_stored_under_the_old_keychain_service_is_found_and_removed(
    monkeypatch: pytest.MonkeyPatch,
):
    stored = {(jira_module.LEGACY_KEYRING_SERVICE, "jira.example.org"): "secret"}

    class Keyring:
        @staticmethod
        def get_password(service: str, user: str):
            return stored.get((service, user))

        @staticmethod
        def delete_password(service: str, user: str):
            stored.pop((service, user), None)

    monkeypatch.setitem(sys.modules, "keyring", Keyring)
    monkeypatch.delenv(jira_module.TOKEN_ENV, raising=False)
    base = "https://jira.example.org"
    assert jira_module.jira_token(base) == "secret"
    assert jira_module.stored_token_exists(base)
    jira_module.delete_token(base)
    assert not stored


def test_new_git_key_wins_over_the_old_one(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    for key, value in (
        ("sprintforecast.host", "gitlab"),
        ("foresprint.host", "github"),
    ):
        subprocess.run(["git", "config", "--local", key, value], cwd=root, check=True)
    assert gitsync.host_setting(data) == "github"


def test_config_migration_skips_lock_files_and_leaves_no_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    legacy = tmp_path / "sprintforecast"
    (legacy / "sperren").mkdir(parents=True)
    (legacy / "sperren" / "x.lock").write_text("lock", encoding="utf-8")
    (legacy / "settings.json").write_text('{"language": "de"}', encoding="utf-8")
    assert config.load() == {"language": "de"}
    folder = tmp_path / "foresprint"
    assert not (folder / "sperren" / "x.lock").exists()
    assert not list(folder.rglob("*.tmp"))
