# SPDX-License-Identifier: EUPL-1.2
"""Start the web UI as an "app": browser window in app mode with a fallback chain.

1. Chromium browser (Edge, Chrome, Comet, Chromium, Brave, Vivaldi) with ``--app``: own
   window without an address bar; when it is closed, the server ends too.
2. Firefox (no app mode anymore) in a new window.
3. The system's default browser.
4. Nothing found: just print the address.

The search covers the PATH (which also holds the Scoop and Chocolatey shims) and the
usual install locations, on Windows including the Scoop and Chocolatey directories.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sprintforecast.i18n import t

BROWSER_ENV = "SPRINTFORECAST_BROWSER"


class Kind(StrEnum):
    APP = "app"  # Chromium with --app
    WINDOW = "window"  # Firefox or similar with a new window
    DEFAULT = "default"  # default browser via the webbrowser module
    NONE = "none"


@dataclass(frozen=True)
class Browser:
    kind: Kind
    name: str
    path: str | None = None


# Program names on the PATH (Linux, partly macOS/Windows)
_CHROMIUM_COMMANDS = [
    ("Microsoft Edge", ["msedge", "microsoft-edge", "microsoft-edge-stable"]),
    ("Google Chrome", ["chrome", "google-chrome", "google-chrome-stable"]),
    ("Comet", ["comet"]),
    ("Chromium", ["chromium", "chromium-browser"]),
    ("Brave", ["brave", "brave-browser"]),
    ("Vivaldi", ["vivaldi", "vivaldi-stable"]),
]
_FIREFOX_COMMANDS = ["firefox"]


def _windows_paths() -> dict[str, list[Path]]:
    env = os.environ
    home = Path.home()
    roots = [
        Path(p)
        for p in (env.get("ProgramFiles(x86)"), env.get("ProgramFiles"), env.get("LOCALAPPDATA"))
        if p
    ]
    # Scoop: <scoop>/apps/<app>/current/…, per user and global
    scoop_apps = [
        Path(env.get("SCOOP") or home / "scoop") / "apps",
        Path(env.get("SCOOP_GLOBAL") or Path(env.get("ProgramData", "C:/ProgramData")) / "scoop")
        / "apps",
    ]
    # Chocolatey: programs mostly in Program Files, portable packages as a shim in <choco>/bin
    choco_bin = Path(env.get("ChocolateyInstall") or "C:/ProgramData/chocolatey") / "bin"

    def scoop(app: str, *exes: str) -> list[Path]:
        return [base / app / "current" / exe for base in scoop_apps for exe in exes]

    return {
        "Microsoft Edge": [r / "Microsoft/Edge/Application/msedge.exe" for r in roots],
        "Google Chrome": [
            *(r / "Google/Chrome/Application/chrome.exe" for r in roots),
            *scoop("googlechrome", "chrome.exe"),
            choco_bin / "chrome.exe",
        ],
        "Comet": [r / "Perplexity/Comet/Application/comet.exe" for r in roots],
        "Chromium": [
            *(r / "Chromium/Application/chrome.exe" for r in roots),
            *scoop("chromium", "chrome.exe"),
            choco_bin / "chromium.exe",
        ],
        "Brave": [
            *(r / "BraveSoftware/Brave-Browser/Application/brave.exe" for r in roots),
            *scoop("brave", "brave.exe"),
            choco_bin / "brave.exe",
        ],
        "Vivaldi": [
            *(r / "Vivaldi/Application/vivaldi.exe" for r in roots),
            *scoop("vivaldi", "vivaldi.exe", "Application/vivaldi.exe"),
            choco_bin / "vivaldi.exe",
        ],
        "Firefox": [
            *(r / "Mozilla Firefox/firefox.exe" for r in roots),
            *scoop("firefox", "firefox.exe"),
            choco_bin / "firefox.exe",
        ],
    }


def _mac_paths() -> dict[str, list[Path]]:
    apps = [Path("/Applications"), Path.home() / "Applications"]
    bundles = {
        "Microsoft Edge": "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "Google Chrome": "Google Chrome.app/Contents/MacOS/Google Chrome",
        "Comet": "Comet.app/Contents/MacOS/Comet",
        "Chromium": "Chromium.app/Contents/MacOS/Chromium",
        "Brave": "Brave Browser.app/Contents/MacOS/Brave Browser",
        "Vivaldi": "Vivaldi.app/Contents/MacOS/Vivaldi",
        "Firefox": "Firefox.app/Contents/MacOS/firefox",
    }
    return {name: [a / rel for a in apps] for name, rel in bundles.items()}


def _known_paths() -> dict[str, list[Path]]:
    if sys.platform == "win32":
        return _windows_paths()
    if sys.platform == "darwin":
        return _mac_paths()
    return {}


def _first_existing(paths: list[Path]) -> str | None:
    return next((str(p) for p in paths if p.is_file()), None)


def find_browser(explicit: str | None = None) -> Browser:
    """Find the best available browser according to the fallback chain."""
    explicit = explicit or os.environ.get(BROWSER_ENV)
    if explicit:
        path = shutil.which(explicit) or (explicit if Path(explicit).is_file() else None)
        if path is None:
            raise FileNotFoundError(t("Browser not found: {browser}", browser=explicit))
        kind = Kind.WINDOW if "firefox" in Path(path).name.lower() else Kind.APP
        return Browser(kind, Path(path).stem, path)

    known = _known_paths()
    for name, commands in _CHROMIUM_COMMANDS:
        path = next((p for c in commands if (p := shutil.which(c))), None)
        path = path or _first_existing(known.get(name, []))
        if path:
            return Browser(Kind.APP, name, path)
    path = next((p for c in _FIREFOX_COMMANDS if (p := shutil.which(c))), None)
    path = path or _first_existing(known.get("Firefox", []))
    if path:
        return Browser(Kind.WINDOW, "Firefox", path)
    try:
        webbrowser.get()
    except webbrowser.Error:
        return Browser(Kind.NONE, t("no browser"))
    return Browser(Kind.DEFAULT, t("default browser"))


def profile_dir() -> Path:
    """Dedicated browser profile: only then does the browser process block until the window is
    closed (otherwise it hands over to a running instance and exits immediately)."""
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "sprintforecast" / "browser-profil"


def browser_command(browser: Browser, url: str) -> list[str]:
    assert browser.path is not None
    if browser.kind is Kind.APP:
        return [
            browser.path,
            f"--app={url}",
            f"--user-data-dir={profile_dir()}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1400,950",
        ]
    return [browser.path, "--new-window", url]


def free_port(preferred: int) -> int:
    """``preferred`` if free, otherwise a free port chosen by the system."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise OSError(t("No free port found"))


def wait_until_ready(url: str, server: subprocess.Popen, timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.3)
    return False
