# SPDX-License-Identifier: EUPL-1.2
import socket
import sys
import webbrowser
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sprintforecast import launcher
from sprintforecast.launcher import Browser, Kind, browser_command, find_browser, free_port


@pytest.fixture
def no_browsers(monkeypatch: pytest.MonkeyPatch):
    """Simuliert ein System ohne bekannte Browser; einzelne Tests fügen welche hinzu."""
    available: dict[str, str] = {}
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd: available.get(cmd))
    monkeypatch.setattr(launcher, "_known_paths", lambda: {})
    monkeypatch.delenv(launcher.BROWSER_ENV, raising=False)
    monkeypatch.setattr(launcher.webbrowser, "get", lambda: object())
    return available


def test_prefers_chromium_app_mode(no_browsers: dict):
    no_browsers.update({"firefox": "/usr/bin/firefox", "chromium": "/usr/bin/chromium"})
    assert find_browser() == Browser(Kind.APP, "Chromium", "/usr/bin/chromium")
    no_browsers["msedge"] = "C:/Edge/msedge.exe"
    assert find_browser().name == "Microsoft Edge"


def test_falls_back_to_firefox_then_default_then_none(
    no_browsers: dict, monkeypatch: pytest.MonkeyPatch
):
    no_browsers["firefox"] = "/usr/bin/firefox"
    assert find_browser().kind is Kind.WINDOW
    del no_browsers["firefox"]
    assert find_browser().kind is Kind.DEFAULT

    def no_default():
        raise webbrowser.Error("keiner")

    monkeypatch.setattr(launcher.webbrowser, "get", no_default)
    assert find_browser().kind is Kind.NONE


def test_explicit_browser(no_browsers: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    firefox = tmp_path / "firefox.exe"
    firefox.write_text("")
    assert find_browser(str(firefox)).kind is Kind.WINDOW
    monkeypatch.setenv(launcher.BROWSER_ENV, str(tmp_path / "gibt-es-nicht"))
    with pytest.raises(FileNotFoundError):
        find_browser()


def test_windows_paths_scoop_and_choco(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Keine Browser des Rechners: sonst fände der Test ein echtes Chrome in Program Files.
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(variable, str(tmp_path / "leer"))
    monkeypatch.setenv("SCOOP", str(tmp_path / "scoop"))
    monkeypatch.setenv("SCOOP_GLOBAL", str(tmp_path / "scoop-global"))  # sonst ProgramData
    monkeypatch.setenv("ChocolateyInstall", str(tmp_path / "choco"))
    chrome = tmp_path / "scoop/apps/googlechrome/current/chrome.exe"
    firefox = tmp_path / "choco/bin/firefox.exe"
    for f in (chrome, firefox):
        f.parent.mkdir(parents=True)
        f.write_text("")
    paths = launcher._windows_paths()
    assert launcher._first_existing(paths["Google Chrome"]) == str(chrome)
    assert launcher._first_existing(paths["Firefox"]) == str(firefox)


def test_comet_is_app_capable(no_browsers: dict):
    no_browsers["comet"] = "/opt/comet/comet"
    assert find_browser() == Browser(Kind.APP, "Comet", "/opt/comet/comet")


def test_windows_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    edge = tmp_path / "Microsoft/Edge/Application/msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_text("")
    paths = launcher._windows_paths()
    assert launcher._first_existing(paths["Microsoft Edge"]) == str(edge)
    assert launcher._first_existing(paths["Google Chrome"]) is None


def test_browser_command():
    cmd = browser_command(Browser(Kind.APP, "Edge", "/edge"), "http://localhost:8501")
    assert cmd[:2] == ["/edge", "--app=http://localhost:8501"]
    assert any(a.startswith("--user-data-dir=") for a in cmd)
    assert browser_command(Browser(Kind.WINDOW, "Firefox", "/ff"), "u") == [
        "/ff",
        "--new-window",
        "u",
    ]


def test_free_port_skips_busy_port():
    with socket.socket() as busy:
        busy.bind(("localhost", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert free_port(taken) != taken


def test_handoff_keeps_server_running(monkeypatch: pytest.MonkeyPatch):
    """Endet der Browserprozess sofort (laufende Instanz), darf der Server nicht stoppen."""
    from sprintforecast import cli

    monkeypatch.setattr(cli, "wait_until_ready", lambda url, server: True)
    monkeypatch.setattr(cli, "find_browser", lambda explicit: Browser(Kind.APP, "Edge", "/e"))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: FakeProcess(done=True))
    cli._open_app_window("http://localhost:1", server=FakeProcess(), explicit=None)  # kein Abbruch


class FakeProcess:
    def __init__(self, done: bool = False) -> None:
        self.done = done
        self.terminated = False

    def poll(self) -> int | None:
        return 0 if self.done else None

    def terminate(self) -> None:
        self.terminated = True


def test_window_closes_when_server_ends(monkeypatch: pytest.MonkeyPatch):
    """Beendet sich der Server (Neustart für eine Aktualisierung), schließt das Fenster."""
    from sprintforecast import cli

    window = FakeProcess()
    monkeypatch.setattr(cli, "wait_until_ready", lambda url, server: True)
    monkeypatch.setattr(cli, "find_browser", lambda explicit: Browser(Kind.APP, "Edge", "/e"))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: window)
    cli._open_app_window("http://localhost:1", server=FakeProcess(done=True), explicit=None)
    assert window.terminated


@pytest.mark.skipif(sys.platform == "win32", reason="Fake-Browser als Shell-Skript")
def test_app_window_closes_server(data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("streamlit")
    from sprintforecast.cli import app

    log = tmp_path / "browser-args.txt"
    fake = tmp_path / "fake-browser"
    fake.write_text(f'#!/bin/sh\necho "$@" > {log}\nsleep 6\n')
    fake.chmod(0o755)
    monkeypatch.setattr("sprintforecast.cli._HANDOFF_SECONDS", 5.0)
    result = CliRunner().invoke(
        app, ["--data", str(data_dir), "web", "--app", "--browser", str(fake), "--port", "8590"]
    )
    assert result.exit_code == 0, result.output
    assert "App-Fenster geschlossen" in result.output
    args = log.read_text()
    assert "--app=http://localhost:" in args
    port = int(args.split("--app=http://localhost:")[1].split()[0])
    with socket.socket() as s, pytest.raises(ConnectionRefusedError):
        s.connect(("localhost", port))  # Server ist beendet


class _FakeServer:
    """Stellt den Streamlit-Prozess dar, den `web` startet; endet sofort."""

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int:
        return 0


@pytest.fixture
def web_run(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Ruft `sprintforecast web` ohne echten Server und Browser auf und meldet, was geschah."""
    pytest.importorskip("streamlit")
    from sprintforecast import cli
    from sprintforecast.idle import IDLE_ENV

    monkeypatch.delenv(IDLE_ENV, raising=False)  # sonst gälte der Wert des Aufrufers

    def run(*options: str) -> dict:
        seen: dict = {"window": None, "env": None, "cmd": None}

        def popen(cmd, env=None, **_):
            seen["cmd"], seen["env"] = cmd, env
            return _FakeServer()

        monkeypatch.setattr(cli.subprocess, "Popen", popen)
        monkeypatch.setattr(cli, "adopt", lambda process: None)
        monkeypatch.setattr(cli, "terminate_tree", lambda process: None)
        monkeypatch.setattr(
            cli, "_open_app_window", lambda url, server, explicit: seen.update(window=url)
        )
        result = CliRunner().invoke(cli.app, ["--data", str(data_dir), "web", *options])
        assert result.exit_code == 0, result.output
        return seen

    return run


def _headless(cmd: list[str]) -> str:
    return cmd[cmd.index("--server.headless") + 1]


@pytest.mark.parametrize("options", [[], ["--app"]])
def test_web_opens_app_window_by_default(web_run, options: list[str]):
    from sprintforecast.idle import IDLE_ENV

    seen = web_run(*options)
    assert seen["window"].startswith("http://localhost:")
    assert IDLE_ENV in seen["env"]  # Server beendet sich selbst, wenn das Fenster zu ist
    assert _headless(seen["cmd"]) == "true"  # Streamlit öffnet keinen zweiten Tab


def test_web_no_app_leaves_the_browser_tab_to_streamlit(web_run):
    from sprintforecast.idle import IDLE_ENV

    seen = web_run("--no-app")
    assert seen["window"] is None
    assert IDLE_ENV not in seen["env"]
    assert _headless(seen["cmd"]) == "false"


@pytest.mark.parametrize("options", [["--no-browser"], ["--app", "--no-browser"]])
def test_web_no_browser_opens_nothing_and_never_stops_itself(web_run, options: list[str]):
    from sprintforecast.idle import IDLE_ENV

    seen = web_run(*options)
    assert seen["window"] is None
    assert IDLE_ENV not in seen["env"]
    assert _headless(seen["cmd"]) == "true"


def test_invalid_browser_variable_falls_back_to_automatic_search(
    no_browsers: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Zeigt SPRINTFORECAST_BROWSER auf einen nicht vorhandenen Pfad, sucht `web` selbst weiter
    (kein Traceback), obwohl der App-Modus jetzt der Standard ist."""
    from sprintforecast import cli

    missing = str(tmp_path / "gibt-es-nicht")
    monkeypatch.setenv(launcher.BROWSER_ENV, missing)
    opened: list[str] = []
    monkeypatch.setattr(cli, "wait_until_ready", lambda url, server: True)
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    cli._open_app_window("http://localhost:1", server=FakeProcess(), explicit=missing)
    assert opened == ["http://localhost:1"]  # kein App-fähiger Browser: der Standardbrowser


def test_terminate_tree_stops_children():
    import subprocess
    import sys
    import time

    from sprintforecast.proctree import adopt, popen_options, terminate_tree

    # Elternprozess startet ein Kind und wartet – beides muss enden.
    code = (
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(c.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, **popen_options()
    )
    adopt(parent)
    child_pid = int(parent.stdout.readline())
    terminate_tree(parent, timeout=5)
    assert parent.poll() is not None
    deadline = time.monotonic() + 5
    alive = True
    while alive and time.monotonic() < deadline:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {child_pid}"], capture_output=True, text=True
            ).stdout
            alive = str(child_pid) in out
        else:
            import os

            try:
                os.kill(child_pid, 0)
            except OSError:
                alive = False
        if alive:
            time.sleep(0.2)
    assert not alive


def test_unwritable_log_does_not_stop_the_start(web_run, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SPRINTFORECAST_LOG", str(tmp_path / "nothing" / "app.log"))
    seen = web_run("--no-browser")
    assert seen["cmd"] is not None  # the server was started anyway


def test_app_starter_survives_an_unwritable_config_dir(tmp_path: Path, monkeypatch, capsys):
    import os

    import sprintforecast
    from sprintforecast import cli
    from sprintforecast.updater import LAUNCHER_ENV

    monkeypatch.setenv(LAUNCHER_ENV, "")  # app_main() sets it; the monkeypatch restores it
    blocked = tmp_path / "config"
    blocked.write_text("a file, not a folder")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(blocked))
    monkeypatch.setenv("APPDATA", str(blocked))
    monkeypatch.delenv(sprintforecast.LOG_ENV, raising=False)
    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "app", lambda args, prog_name: seen.append(args))
    monkeypatch.setattr("sys.argv", ["sprintforecast-app"])
    sprintforecast.app_main()
    assert seen == [["web", "--app"]]
    assert sprintforecast.LOG_ENV not in os.environ
