# SPDX-License-Identifier: EUPL-1.2
"""uninstall-old.sh against a fake home folder and a fake `uv`."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "uninstall-old.sh"
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None, reason="needs a POSIX shell"
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".config/sprintforecast").mkdir(parents=True)
    (home / ".config/sprintforecast/settings.json").write_text('{"data_dir": "/x"}')
    (home / ".local/share/applications").mkdir(parents=True)
    (home / "Desktop").mkdir()
    for target in (
        home / ".local/share/applications/sprintforecast.desktop",
        home / "Desktop/sprintforecast.desktop",
    ):
        target.write_text('[Desktop Entry]\nExec="/uv/bin/sprintforecast-app"\n')
    (home / ".cache/sprintforecast/browser-profil").mkdir(parents=True)
    starter = home / "Applications/Sprint-Forecast.app/Contents/MacOS"
    starter.mkdir(parents=True)
    (starter / "Sprint-Forecast").write_text('#!/bin/sh\nexec "/uv/bin/sprintforecast-app"\n')
    # the new installation and the team data must survive
    (home / ".local/share/applications/foresprint.desktop").write_text("Exec=foresprint-app\n")
    (home / "sprint-daten").mkdir()
    (home / "sprint-daten/teams.yaml").write_text("x")
    # fake uv: lists the old tool until it is uninstalled
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/bin/sh\nstate="$HOME/.uv-state"\n'
        'if [ "$1 $2" = "tool list" ]; then\n'
        '  [ -f "$state" ] || printf "sprintforecast v0.7.0\\n- sprintforecast\\n"\n'
        'elif [ "$1 $2" = "tool uninstall" ]; then touch "$state"; echo "$3" >"$state"\n'
        "fi\n"
    )
    uv.chmod(0o755)
    return home


def run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(home),
        "PATH": f"{home.parent / 'bin'}:/usr/bin:/bin",
    }
    return subprocess.run(
        ["sh", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def test_dry_run_changes_nothing(home: Path):
    result = run(home, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "uv tool        sprintforecast" in result.stdout
    assert "Dry run" in result.stdout
    assert (home / ".cache/sprintforecast").exists()
    assert (home / "Desktop/sprintforecast.desktop").exists()
    assert not (home / ".config/foresprint").exists()
    assert not (home / ".uv-state").exists()


def test_removes_old_artifacts_and_keeps_user_data(home: Path):
    result = run(home, "--yes")
    assert result.returncode == 0, result.stderr
    assert (home / ".uv-state").read_text().strip() == "sprintforecast"
    assert not (home / ".cache/sprintforecast").exists()
    assert not (home / "Desktop/sprintforecast.desktop").exists()
    assert not (home / ".local/share/applications/sprintforecast.desktop").exists()
    assert not (home / "Applications/Sprint-Forecast.app").exists()
    # settings are copied, the old folder stays, the new installation and the data are untouched
    assert (home / ".config/foresprint/settings.json").read_text() == '{"data_dir": "/x"}'
    assert (home / ".config/sprintforecast/settings.json").exists()
    assert (home / ".local/share/applications/foresprint.desktop").exists()
    assert (home / "sprint-daten/teams.yaml").exists()


def test_existing_new_settings_are_not_overwritten(home: Path):
    (home / ".config/foresprint").mkdir()
    (home / ".config/foresprint/settings.json").write_text("new")
    run(home, "--yes", "--remove-old-config")
    assert (home / ".config/foresprint/settings.json").read_text() == "new"
    assert not (home / ".config/sprintforecast").exists()


def test_remove_old_config_copies_first(home: Path):
    run(home, "--yes", "--remove-old-config")
    assert not (home / ".config/sprintforecast").exists()
    assert (home / ".config/foresprint/settings.json").exists()


def test_idempotent_and_foreign_desktop_file_kept(home: Path):
    foreign = home / "Desktop/sprintforecast.desktop"
    foreign.write_text("[Desktop Entry]\nExec=/usr/bin/other\n")
    run(home, "--yes")
    assert foreign.exists()
    second = run(home, "--yes")
    assert second.returncode == 0
    assert "copy settings" not in second.stdout


def test_nothing_found(tmp_path: Path):
    (tmp_path / "bin").mkdir()
    result = run(tmp_path / "empty-home", "--yes")
    assert result.returncode == 0
    assert "Nothing to remove" in result.stdout


def test_needs_confirmation_without_terminal(home: Path):
    result = subprocess.run(
        ["sh", str(SCRIPT)],
        env={"HOME": str(home), "PATH": f"{home.parent / 'bin'}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # no controlling terminal
    )
    assert result.returncode == 1
    assert (home / ".cache/sprintforecast").exists()
    assert os.path.exists(home / "Desktop/sprintforecast.desktop")


def test_help_and_failing_uv(home: Path):
    assert "Usage" in run(home, "--help").stdout
    uv = home.parent / "bin/uv"
    uv.write_text('#!/bin/sh\nif [ "$2" = list ]; then echo "sprintforecast v1"; else exit 3; fi\n')
    result = run(home, "--yes")
    assert result.returncode == 1
    assert "failed" in result.stderr


def test_mac_bundle_checked(home: Path):
    new = home / "Applications/Foresprint.app/Contents"
    new.mkdir(parents=True)
    run(home, "--yes")
    assert new.exists()
    assert not (home / "Applications/Sprint-Forecast.app").exists()
