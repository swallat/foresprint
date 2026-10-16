# SPDX-License-Identifier: EUPL-1.2
"""Starter zum Doppelklicken: Verknüpfung auf `sprintforecast-app` (= `web --app`).

- Windows: Desktop und Startmenü (.lnk über PowerShell/WScript.Shell)
- macOS: ~/Applications/Sprint-Forecast.app plus Alias auf dem Schreibtisch
- Linux: ~/.local/share/applications/sprintforecast.desktop plus Kopie auf dem Desktop
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from sprintforecast.i18n import t
from sprintforecast.icon import write_icon
from sprintforecast.launcher import profile_dir

APP_NAME = "Sprint-Forecast"
APP_SCRIPT = "sprintforecast-app"


def app_program() -> str | None:
    """Pfad von `sprintforecast-app` (liegt neben `sprintforecast` im bin-Ordner von uv)."""
    exe = f"{APP_SCRIPT}.exe" if sys.platform == "win32" else APP_SCRIPT
    if found := shutil.which(APP_SCRIPT):
        return found
    for folder in (Path(sys.argv[0]).resolve().parent, Path(sys.executable).parent):
        if (folder / exe).is_file():
            return str(folder / exe)
    return None


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def icon_dir() -> Path:
    """Ordner für das Logo (neben dem Browserprofil der App)."""
    return profile_dir().parent


def windows_script(program: str, workdir: str, icon: str | None = None) -> str:
    """PowerShell: Verknüpfungen auf dem Desktop und im Startmenü anlegen; gibt die Pfade aus."""
    lines = ["$shell = New-Object -ComObject WScript.Shell"]
    for folder in ("Desktop", "Programs"):
        lines += [
            f"$path = Join-Path ([Environment]::GetFolderPath('{folder}')) '{APP_NAME}.lnk'",
            "$link = $shell.CreateShortcut($path)",
            f"$link.TargetPath = {_ps_quote(program)}",
            f"$link.WorkingDirectory = {_ps_quote(workdir)}",
            "$link.Description = 'Sprint-Forecast'",
            *([f"$link.IconLocation = {_ps_quote(icon)}"] if icon else []),
            "$link.Save()",
            "Write-Output $path",
        ]
    return "\n".join(lines)


def desktop_entry(program: str, icon: str = "office-calendar") -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Comment={t('Velocity- und Kapazitäts-Forecast')}\n"
        f'Exec="{program}"\n'
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Office;ProjectManagement;\n"
    )


def mac_bundle(app_dir: Path, program: str, icon: Path | None = None) -> Path:
    """Minimales App-Bundle, das `sprintforecast-app` startet."""
    contents = app_dir / f"{APP_NAME}.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f"<key>CFBundleName</key><string>{APP_NAME}</string>\n"
        f"<key>CFBundleExecutable</key><string>{APP_NAME}</string>\n"
        "<key>CFBundleIdentifier</key><string>de.sprintforecast.app</string>\n"
        "<key>CFBundlePackageType</key><string>APPL</string>\n"
        + (f"<key>CFBundleIconFile</key><string>{icon.stem}</string>\n" if icon else "")
        + "</dict></plist>\n",
        encoding="utf-8",
    )
    if icon:
        (contents / "Resources").mkdir(exist_ok=True)
        shutil.copyfile(icon, contents / "Resources" / icon.name)
    starter = contents / "MacOS" / APP_NAME
    # GUI-Apps erben keinen Shell-PATH – daher absoluter Pfad; Ausgabe ins Protokoll.
    starter.write_text(f'#!/bin/sh\ncd "$HOME"\nexec "{program}"\n', encoding="utf-8")
    starter.chmod(0o755)
    return contents.parent


def create(home: Path | None = None, platform: str = sys.platform) -> list[Path]:
    """Legt die Verknüpfungen an und liefert ihre Pfade. Wirft RuntimeError mit Hinweis."""
    program = app_program()
    if program is None:
        raise RuntimeError(
            t(
                "{program} nicht gefunden – bitte sprintforecast mit dem Installationsskript "
                "installieren bzw. aktualisieren.",
                program=APP_SCRIPT,
            )
        )
    home = home or Path.home()
    if platform == "win32":
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                windows_script(program, str(home), str(write_icon(icon_dir(), "ico"))),
            ],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or t("Verknüpfung nicht angelegt"))
        return [Path(line) for line in proc.stdout.splitlines() if line.strip()]
    if platform == "darwin":
        bundle = mac_bundle(home / "Applications", program, write_icon(icon_dir(), "icns"))
        paths = [bundle]
        desktop = home / "Desktop"
        if desktop.is_dir():
            alias = desktop / bundle.name
            if alias.is_symlink() or alias.exists():
                alias.unlink()
            alias.symlink_to(bundle)
            paths.append(alias)
        return paths
    entry = desktop_entry(program, str(write_icon(icon_dir(), "png")))
    data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    targets = [data_home / "applications" / "sprintforecast.desktop"]
    if (home / "Desktop").is_dir():
        targets.append(home / "Desktop" / "sprintforecast.desktop")
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry, encoding="utf-8")
        target.chmod(0o755)
    return targets
