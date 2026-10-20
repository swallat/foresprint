# SPDX-License-Identifier: EUPL-1.2
"""uninstall.sh against a fake home folder and a fake `uv`."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "uninstall.sh"
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None, reason="needs a POSIX shell"
)

FAKE_UV = """#!/bin/sh
log="$HOME/.uv-log"
if [ "$1 $2" = "tool list" ]; then
  for t in $FAKE_TOOLS; do
    grep -qx "$t" "$log" 2>/dev/null || printf '%s v1\\n- %s\\n' "$t" "$t"
  done
elif [ "$1 $2" = "tool uninstall" ]; then
  [ -z "$FAKE_UV_FAIL" ] || exit 3
  echo "$3" >>"$log"
fi
"""


def entry(name: str) -> str:
    return f'[Desktop Entry]\nExec="/uv/bin/{name}-app"\n'


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    apps = home / ".local/share/applications"
    apps.mkdir(parents=True)
    (home / "Desktop").mkdir()
    for name in ("sprintforecast", "foresprint"):
        (home / ".config" / name).mkdir(parents=True)
        (home / ".config" / name / "settings.json").write_text('{"data_dir": "/x"}')
        (home / ".cache" / name / "browser-profil").mkdir(parents=True)
        (apps / f"{name}.desktop").write_text(entry(name))
        (home / "Desktop" / f"{name}.desktop").write_text(entry(name))
    for app, script in (("Sprint-Forecast", "sprintforecast"), ("Foresprint", "foresprint")):
        starter = home / "Applications" / f"{app}.app/Contents/MacOS"
        starter.mkdir(parents=True)
        (starter / app).write_text(f'#!/bin/sh\nexec "/uv/bin/{script}-app"\n')
    (home / "sprint-daten").mkdir()
    (home / "sprint-daten/teams.yaml").write_text("x")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(FAKE_UV)
    (bin_dir / "uv").chmod(0o755)
    return home


def run(
    home: Path, *args: str, tools: str = "foresprint sprintforecast", **env: str
) -> subprocess.CompletedProcess[str]:
    environ = {
        "HOME": str(home),
        "PATH": f"{home.parent / 'bin'}:/usr/bin:/bin",
        "FAKE_TOOLS": tools,
        **env,
    }
    return subprocess.run(
        ["sh", str(SCRIPT), *args],
        env=environ,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def test_dry_run_changes_nothing(home: Path):
    result = run(home, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "uv tool        foresprint" in result.stdout
    assert "uv tool        sprintforecast" in result.stdout
    assert "Dry run" in result.stdout
    assert (home / ".cache/sprintforecast").exists()
    assert (home / "Desktop/foresprint.desktop").exists()
    assert not (home / ".uv-log").exists()


def test_removes_both_names_and_keeps_user_data(home: Path):
    result = run(home, "--yes")
    assert result.returncode == 0, result.stderr
    assert set((home / ".uv-log").read_text().split()) == {"foresprint", "sprintforecast"}
    for name in ("sprintforecast", "foresprint"):
        assert not (home / ".cache" / name).exists()
        assert not (home / "Desktop" / f"{name}.desktop").exists()
        assert not (home / ".local/share/applications" / f"{name}.desktop").exists()
        assert (home / ".config" / name / "settings.json").exists()
    assert not (home / "Applications/Sprint-Forecast.app").exists()
    assert not (home / "Applications/Foresprint.app").exists()
    assert (home / "sprint-daten/teams.yaml").exists()


def test_only_installed_tool_is_uninstalled(home: Path):
    run(home, "--yes", tools="sprintforecast")
    assert (home / ".uv-log").read_text().split() == ["sprintforecast"]


def test_remove_config_on_request(home: Path):
    run(home, "--yes", "--remove-config")
    assert not (home / ".config/sprintforecast").exists()
    assert not (home / ".config/foresprint").exists()
    assert (home / "sprint-daten/teams.yaml").exists()


def test_idempotent_and_foreign_files_kept(home: Path):
    foreign = home / "Desktop/foresprint.desktop"
    foreign.write_text("[Desktop Entry]\nExec=/usr/bin/other\n")
    run(home, "--yes")
    assert foreign.exists()
    second = run(home, "--yes", tools="")
    assert second.returncode == 0
    assert "Nothing to remove" in second.stdout


def test_dangling_alias_removed(home: Path):
    alias = home / "Desktop/Foresprint.app"
    alias.symlink_to(home / "nowhere")
    run(home, "--yes")
    assert not alias.is_symlink()


def test_nothing_found(tmp_path: Path):
    (tmp_path / "bin").mkdir()
    result = run(tmp_path / "empty-home", "--yes", tools="")
    assert result.returncode == 0
    assert "Nothing to remove" in result.stdout


def test_help_and_failing_uv(home: Path):
    assert "Usage" in run(home, "--help").stdout
    result = run(home, "--yes", FAKE_UV_FAIL="1")
    assert result.returncode == 1
    assert "failed" in result.stderr


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
