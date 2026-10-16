# SPDX-License-Identifier: EUPL-1.2
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sprintforecast import updater

RECEIPT = """\
[tool]
requirements = [{{ name = "sprintforecast", url = "{url}", extras = ["web"] }}]
"""
MAIN = "https://github.com/swallat/sprint-forecast/archive/refs/heads/main.zip"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolierte Konfiguration und eine uv-Tool-Installation von main."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.delenv(updater.MODE_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    prefix = tmp_path / "venv"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(RECEIPT.format(url=MAIN))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(updater, "installed_version", lambda: "0.2.0")
    return prefix


def remote(monkeypatch: pytest.MonkeyPatch, version: str) -> list[str]:
    calls: list[str] = []

    def fetch(url: str, timeout: float) -> str:
        calls.append(url)
        return f'[project]\nname = "sprintforecast"\nversion = "{version}"\n'

    monkeypatch.setattr(updater, "_fetch", fetch)
    return calls


def test_versions():
    assert updater.parse_version("v1.10.2rc1") == (1, 10, 2)
    assert updater.is_newer("0.10.0", "0.9.9")
    assert not updater.is_newer("0.2.0", "0.2.0")
    assert not updater.is_newer(None, "0.1")


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        (f'url = "{MAIN}"', ("swallat/sprint-forecast", "main", False)),
        (
            'url = "https://github.com/me/fork/archive/refs/tags/v1.0.zip"',
            ("me/fork", "v1.0", True),
        ),
        ('git = "https://github.com/me/fork", branch = "dev"', ("me/fork", "dev", False)),
        ("", ("swallat/sprint-forecast", "main", False)),  # Quelle aus einem Plugin
    ],
)
def test_installation_from_receipt(env: Path, requirement: str, expected):
    sep = ", " if requirement else ""
    (env / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "sprintforecast"{sep}{requirement} }}]\n'
    )
    inst = updater.installation()
    assert (inst.repo, inst.ref, inst.pinned) == expected


def test_not_installed_with_uv_tool(env: Path):
    (env / "uv-receipt.toml").unlink()
    assert updater.installation() is None
    assert updater.check().error


def test_check_caches_for_a_day(env: Path, monkeypatch: pytest.MonkeyPatch):
    calls = remote(monkeypatch, "0.3.0")
    now = datetime(2026, 10, 16, tzinfo=UTC)
    assert updater.check(now=now).available
    assert calls == [
        "https://raw.githubusercontent.com/swallat/sprint-forecast/main/pyproject.toml"
    ]
    assert updater.check(now=now + timedelta(hours=1)).latest == "0.3.0"
    assert len(calls) == 1
    updater.check(now=now + timedelta(hours=25))
    assert len(calls) == 2


def test_auto_update_schedules_once(env: Path, monkeypatch: pytest.MonkeyPatch):
    remote(monkeypatch, "0.3.0")
    monkeypatch.setattr(updater, "find_uv", lambda: "/bin/uv")
    started: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: started.append(args) or None)
    said: list[str] = []
    updater.AutoUpdate().start().finish(said.append)
    assert started and started[0][-5:] == [
        "/bin/uv",
        "tool",
        "upgrade",
        "--reinstall",
        "sprintforecast",
    ]
    assert "0.3.0 wird im Hintergrund installiert" in said[0]
    assert updater.load_state()["attempted"] == "0.3.0"
    # Zweiter Start: nicht erneut anstoßen
    updater.AutoUpdate().start().finish(said.append)
    assert len(started) == 1
    assert "wird nach dem Beenden installiert" in updater.status_line()


def test_notice_mode_only_reports(env: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(updater.MODE_ENV, "hinweis")
    remote(monkeypatch, "0.3.0")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("kein Start"))
    said: list[str] = []
    updater.AutoUpdate().start().finish(said.append)
    assert "sprintforecast aktualisieren" in said[0]


def test_off_mode_and_ci_skip(env: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(updater, "_fetch", lambda *a: pytest.fail("keine Prüfung"))
    updater.update_state(mode="aus")
    updater.AutoUpdate().start().finish(lambda _: None)
    updater.update_state(mode="an")
    monkeypatch.setenv("CI", "true")
    updater.AutoUpdate().start().finish(lambda _: None)


def test_startup_notices(env: Path):
    updater.update_state(seen_version="0.1.0")
    assert updater.startup_notices() == ["sprintforecast wurde auf Version 0.2.0 aktualisiert."]
    assert updater.startup_notices() == []
    past = datetime.now(UTC) - timedelta(hours=1)
    updater.update_state(attempted="0.3.0", attempted_at=past.isoformat())
    [message] = updater.startup_notices()
    assert "nicht geklappt" in message
    assert updater.startup_notices() == []  # nur einmal


def test_powershell_script_waits_and_quotes(tmp_path: Path):
    script = updater._powershell_script(
        [11, 22], ["C:\\uv's\\uv.exe", "tool"], tmp_path / "log", visible=False
    )
    assert "Wait-Process -Id 11,22" in script
    assert "& 'C:\\uv''s\\uv.exe' 'tool'" in script


def test_version_matches_pyproject():
    import tomllib

    from sprintforecast import __version__

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    assert tomllib.loads(pyproject.read_text())["project"]["version"] == __version__
