# SPDX-License-Identifier: EUPL-1.2
"""Start der Weboberfläche als „App“: Browserfenster im App-Modus mit Rückfallkette.

1. Chromium-Browser (Edge, Chrome, Comet, Chromium, Brave, Vivaldi) mit ``--app``: eigenes
   Fenster ohne Adressleiste; wird es geschlossen, endet auch der Server.
2. Firefox (kein App-Modus mehr) in einem neuen Fenster.
3. Standardbrowser des Systems.
4. Nichts gefunden: nur die Adresse ausgeben.

Gesucht wird im PATH (dort liegen auch die Shims von Scoop und Chocolatey) sowie in den
üblichen Installationsorten, unter Windows inklusive Scoop- und Chocolatey-Verzeichnissen.
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

BROWSER_ENV = "SPRINTFORECAST_BROWSER"


class Kind(StrEnum):
    APP = "app"  # Chromium mit --app
    WINDOW = "window"  # Firefox o. Ä. mit neuem Fenster
    DEFAULT = "default"  # Standardbrowser über das webbrowser-Modul
    NONE = "none"


@dataclass(frozen=True)
class Browser:
    kind: Kind
    name: str
    path: str | None = None


# Programmnamen im PATH (Linux, teils macOS/Windows)
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
    # Scoop: <scoop>/apps/<app>/current/…, benutzerweit und global
    scoop_apps = [
        Path(env.get("SCOOP") or home / "scoop") / "apps",
        Path(env.get("SCOOP_GLOBAL") or Path(env.get("ProgramData", "C:/ProgramData")) / "scoop")
        / "apps",
    ]
    # Chocolatey: Programme meist in Program Files, portable Pakete als Shim in <choco>/bin
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
    """Sucht den besten verfügbaren Browser gemäß der Rückfallkette."""
    explicit = explicit or os.environ.get(BROWSER_ENV)
    if explicit:
        path = shutil.which(explicit) or (explicit if Path(explicit).is_file() else None)
        if path is None:
            raise FileNotFoundError(f"Browser nicht gefunden: {explicit}")
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
        return Browser(Kind.NONE, "kein Browser")
    return Browser(Kind.DEFAULT, "Standardbrowser")


def profile_dir() -> Path:
    """Eigenes Browserprofil: Nur so blockiert der Browserprozess, bis das Fenster zu ist
    (sonst übergibt er an eine laufende Instanz und endet sofort)."""
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
    """``preferred``, falls frei – sonst ein freier Port des Systems."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise OSError("Kein freier Port gefunden")


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
