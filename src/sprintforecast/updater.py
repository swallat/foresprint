# SPDX-License-Identifier: EUPL-1.2
"""Selbstaktualisierung – ähnlich wie bei Claude Code.

- Beim Start eines Befehls wird höchstens einmal am Tag im Hintergrund geprüft, ob es eine
  neuere Version gibt (``version`` in ``pyproject.toml`` des installierten Branches).
- Modus ``an`` (Standard): Nach dem Ende des Befehls aktualisiert ein eigener Prozess mit
  ``uv tool upgrade --reinstall sprintforecast``; der nächste Start nutzt die neue Version.
  ``uv`` übernimmt dabei Quelle, Plugins (``--with``) und Python-Version der Installation.
- Modus ``hinweis``: nur ein Hinweis. Modus ``aus``: keine Prüfung.
- Manuell: ``sprintforecast aktualisieren``.

Aktiv nur bei einer Installation mit ``uv tool install`` (erkennbar an ``uv-receipt.toml``),
also nicht in der Entwicklung (``uv run``) und nicht in CI. Gewartet wird auf das Ende des
eigenen Prozesses, weil Windows laufende Programme und geladene Bibliotheken sperrt.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from importlib import metadata
from pathlib import Path
from typing import Any

from sprintforecast.config import config_dir

PACKAGE = "sprintforecast"
DEFAULT_REPO = "swallat/sprint-forecast"
DEFAULT_REF = "main"
MODE_ENV = "SPRINTFORECAST_AUTOUPDATE"
CHECK_INTERVAL = timedelta(hours=24)
# Erst nach dieser Zeit gilt eine nicht wirksame Aktualisierung als fehlgeschlagen.
FAILURE_GRACE = timedelta(minutes=15)


class Mode(StrEnum):
    ON = "an"
    NOTICE = "hinweis"
    OFF = "aus"


# --- Ablage ---------------------------------------------------------------------------


def state_file() -> Path:
    return config_dir() / "update.json"


def log_file() -> Path:
    return config_dir() / "update.log"


def load_state() -> dict[str, Any]:
    try:
        content = json.loads(state_file().read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return content if isinstance(content, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    try:
        path = state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # Aktualisierung ist Komfort – nie den eigentlichen Befehl stören


def update_state(**changes: Any) -> dict[str, Any]:
    state = load_state() | changes
    save_state(state)
    return state


def mode() -> Mode:
    """Umgebungsvariable vor gespeicherter Einstellung; Standard: an."""
    for raw in (os.environ.get(MODE_ENV), load_state().get("mode")):
        if raw:
            value = str(raw).strip().lower()
            aliases = {
                "1": "an",
                "true": "an",
                "on": "an",
                "0": "aus",
                "false": "aus",
                "off": "aus",
            }
            try:
                return Mode(aliases.get(value, value))
            except ValueError:
                continue
    return Mode.ON


# --- Versionen ------------------------------------------------------------------------


def installed_version() -> str:
    try:
        return metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        from sprintforecast import __version__

        return __version__


def parse_version(text: str) -> tuple[int, ...]:
    """„0.10.2“ → (0, 10, 2); Zusätze wie „rc1“ werden ignoriert."""
    parts = []
    for piece in text.strip().lstrip("v").split("."):
        match = re.match(r"\d+", piece)
        if not match:
            break
        parts.append(int(match.group()))
    return tuple(parts)


def is_newer(candidate: str | None, current: str) -> bool:
    return candidate is not None and parse_version(candidate) > parse_version(current)


# --- Installation ---------------------------------------------------------------------


@dataclass(frozen=True)
class Installation:
    """Woher die laufende Installation stammt (aus der uv-Quittung)."""

    repo: str
    ref: str
    # Auf einen Tag festgelegt – wird nicht automatisch aktualisiert.
    pinned: bool
    # Kern ohne eigene Adresse, die Quelle kommt aus einem Plugin.
    via_plugin: bool = False


_ARCHIVE = re.compile(r"github\.com/([^/]+/[^/]+)/archive/refs/(heads|tags)/(.+?)\.(zip|tar\.gz)$")
_GIT = re.compile(r"github\.com/([^/@#?]+/[^/@#?]+?)(?:\.git)?(?:[@#?].*)?$")


def receipt_path() -> Path:
    return Path(sys.prefix) / "uv-receipt.toml"


def installation() -> Installation | None:
    """None, wenn nicht mit ``uv tool install`` installiert (z. B. Entwicklung, CI)."""
    try:
        receipt = tomllib.loads(receipt_path().read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return None
    requirements = receipt.get("tool", {}).get("requirements", [])
    core = next((r for r in requirements if r.get("name") == PACKAGE), None)
    if core is None:
        return None
    if url := core.get("url"):
        if match := _ARCHIVE.search(url):
            repo, kind, ref, _ = match.groups()
            return Installation(repo=repo, ref=ref, pinned=kind == "tags")
        return Installation(repo=DEFAULT_REPO, ref=DEFAULT_REF, pinned=False)
    if git := core.get("git"):
        match = _GIT.search(git)
        repo = match.group(1) if match else DEFAULT_REPO
        if tag := core.get("tag"):
            return Installation(repo=repo, ref=tag, pinned=True)
        if rev := core.get("rev"):
            return Installation(repo=repo, ref=rev, pinned=True)
        return Installation(repo=repo, ref=core.get("branch") or DEFAULT_REF, pinned=False)
    return Installation(repo=DEFAULT_REPO, ref=DEFAULT_REF, pinned=False, via_plugin=True)


def _fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": f"{PACKAGE}-updater"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def remote_version(inst: Installation, timeout: float = 5.0) -> str:
    """Version im ``pyproject.toml`` des installierten Branches; wirft OSError/ValueError."""
    url = f"https://raw.githubusercontent.com/{inst.repo}/{inst.ref}/pyproject.toml"
    project = tomllib.loads(_fetch(url, timeout)).get("project", {})
    version = project.get("version")
    if not isinstance(version, str):
        raise ValueError(f"Keine Version in {url}")
    return version


@dataclass
class Check:
    current: str
    latest: str | None
    installation: Installation | None
    error: str | None = None

    @property
    def available(self) -> bool:
        return is_newer(self.latest, self.current)


def check(force: bool = False, timeout: float = 5.0, now: datetime | None = None) -> Check:
    """Prüft auf eine neue Version; ohne ``force`` höchstens einmal je CHECK_INTERVAL."""
    now = now or datetime.now(UTC)
    current = installed_version()
    inst = installation()
    if inst is None:
        return Check(current, None, None, "nicht mit uv tool install installiert")
    state = load_state()
    last = _parse_time(state.get("last_check"))
    if not force and last is not None and now - last < CHECK_INTERVAL:
        return Check(current, state.get("latest"), inst)
    try:
        latest = remote_version(inst, timeout)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        update_state(last_check=now.isoformat())  # nicht bei jedem Start erneut warten
        return Check(current, state.get("latest"), inst, str(e))
    update_state(last_check=now.isoformat(), latest=latest)
    return Check(current, latest, inst)


def _parse_time(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


# --- Aktualisieren --------------------------------------------------------------------


def find_uv() -> str | None:
    if found := shutil.which("uv"):
        return found
    home = Path.home()
    exe = "uv.exe" if sys.platform == "win32" else "uv"
    for candidate in (home / ".local" / "bin" / exe, home / ".cargo" / "bin" / exe):
        if candidate.is_file():
            return str(candidate)
    return None


def upgrade_command(uv: str) -> list[str]:
    # --reinstall lädt die Quelle neu (gleiche Adresse, neuer Inhalt) und behält --with-Plugins.
    return [uv, "tool", "upgrade", "--reinstall", PACKAGE]


def run_upgrade(uv: str) -> int:
    """Aktualisiert sofort im Vordergrund (nicht unter Windows – dort sind Dateien gesperrt)."""
    return subprocess.run(upgrade_command(uv)).returncode


def _powershell_script(
    pids: list[int],
    command: list[str],
    log: Path,
    visible: bool,
    then: list[str] | None = None,
    cwd: str | None = None,
) -> str:
    def quote(text: str) -> str:
        return "'" + text.replace("'", "''") + "'"

    call = "& " + " ".join(quote(c) for c in command)
    lines = [
        "$ErrorActionPreference = 'Continue'",
        f"Wait-Process -Id {','.join(map(str, pids))} -ErrorAction SilentlyContinue",
        "Start-Sleep -Seconds 1",
    ]
    if visible:
        lines += [
            "Write-Host 'sprintforecast wird aktualisiert …'",
            f"{call} 2>&1 | Tee-Object -FilePath {quote(str(log))}",
        ]
    else:
        lines.append(f"{call} *> {quote(str(log))}")
    if then:
        args = ", ".join(quote(a) for a in then[1:]) or "''"
        location = f" -WorkingDirectory {quote(cwd)}" if cwd else ""
        lines.append(f"Start-Process -FilePath {quote(then[0])} -ArgumentList @({args}){location}")
    elif visible:
        lines += [
            "Write-Host ''",
            "Write-Host 'Fertig. Dieses Fenster schließt sich in 15 Sekunden.'",
            "Start-Sleep -Seconds 15",
        ]
    return "\n".join(lines)


def _posix_script(
    pids: list[int], command: list[str], then: list[str] | None, cwd: str | None
) -> str:
    waits = "; ".join(f"while kill -0 {p} 2>/dev/null; do sleep 1; done" for p in pids)
    script = f"{waits}; {shlex.join(command)}"
    if then:
        script += f"; cd {shlex.quote(cwd or '.')} && exec {shlex.join(then)} >/dev/null 2>&1"
    return script


def schedule_after_exit(
    uv: str,
    visible: bool = False,
    pids: list[int] | None = None,
    then: list[str] | None = None,
    cwd: str | None = None,
) -> None:
    """Startet einen eigenständigen Prozess, der nach dem Ende dieses Prozesses (bzw. der
    Prozesse ``pids``) aktualisiert und danach optional ``then`` startet (Neustart)."""
    log = log_file()
    log.parent.mkdir(parents=True, exist_ok=True)
    command = upgrade_command(uv)
    pids = list(pids or [os.getpid()])
    if sys.platform == "win32":
        # Der uv-Starter (sprintforecast.exe) ist der Elternprozess und ebenfalls gesperrt.
        if os.getppid() not in pids:
            pids.append(os.getppid())
        script = _powershell_script(pids, command, log, visible, then, cwd)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
        args += ["-EncodedCommand", encoded]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        flags |= subprocess.CREATE_NEW_CONSOLE if visible else subprocess.CREATE_NO_WINDOW
        try:
            subprocess.Popen(args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            subprocess.Popen(args, creationflags=flags)
        return
    with log.open("w", encoding="utf-8") as out:
        subprocess.Popen(
            ["/bin/sh", "-c", _posix_script(pids, command, then, cwd)],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


# --- Weboberfläche --------------------------------------------------------------------

# Von `sprintforecast web` an die Weboberfläche übergeben: Prozesse, auf deren Ende die
# Aktualisierung warten muss, und der Befehl für den Neustart (JSON-Liste).
PIDS_ENV = "SPRINTFORECAST_PARENT_PIDS"
RESTART_ENV = "SPRINTFORECAST_RESTART"


def web_environment(argv: list[str]) -> dict[str, str]:
    """Umgebung für den Server der Weboberfläche (aufgerufen von `sprintforecast web`)."""
    pids = [os.getpid()]
    if sys.platform == "win32":
        pids.append(os.getppid())
    program = shutil.which(PACKAGE) or argv[0]
    return {
        PIDS_ENV: ",".join(map(str, pids)),
        RESTART_ENV: json.dumps({"cmd": [program, *argv[1:]], "cwd": os.getcwd()}),
    }


def restart_with_update() -> str | None:
    """Plant Aktualisierung und Neustart nach dem Ende der Weboberfläche.
    Liefert eine Fehlermeldung oder None. Der Aufrufer beendet danach den Server."""
    uv = find_uv()
    if uv is None:
        return "uv nicht gefunden – bitte das Installationsskript erneut ausführen."
    try:
        restart = json.loads(os.environ.get(RESTART_ENV, "null")) or {}
        extra = [int(p) for p in os.environ.get(PIDS_ENV, "").split(",") if p.strip()]
    except ValueError:
        restart, extra = {}, []
    try:
        schedule_after_exit(
            uv, pids=[os.getpid(), *extra], then=restart.get("cmd"), cwd=restart.get("cwd")
        )
    except OSError as e:
        return f"Aktualisierung nicht startbar: {e}"
    latest = load_state().get("latest")
    update_state(
        attempted=latest, attempted_at=datetime.now(UTC).isoformat(), failure_reported=False
    )
    return None


# --- Einbindung in die Kommandozeile --------------------------------------------------


def startup_notices(now: datetime | None = None) -> list[str]:
    """Hinweise beim Start: erfolgte bzw. fehlgeschlagene automatische Aktualisierung."""
    if installation() is None:
        return []
    now = now or datetime.now(UTC)
    current = installed_version()
    state = load_state()
    messages = []
    seen = state.get("seen_version")
    if seen and is_newer(current, seen):
        messages.append(f"sprintforecast wurde auf Version {current} aktualisiert.")
    changes: dict[str, Any] = {"seen_version": current}
    attempted = state.get("attempted")
    attempted_at = _parse_time(state.get("attempted_at"))
    if (
        is_newer(attempted, current)
        and attempted_at is not None
        and now - attempted_at > FAILURE_GRACE
        and not state.get("failure_reported")
    ):
        messages.append(
            f"Die automatische Aktualisierung auf {attempted} hat nicht geklappt – "
            f"Protokoll: {log_file()}. Manuell: sprintforecast aktualisieren"
        )
        changes["failure_reported"] = True
    update_state(**changes)
    return messages


class AutoUpdate:
    """Prüft im Hintergrund und plant die Aktualisierung für das Programmende ein."""

    def __init__(self) -> None:
        self._result: Check | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> AutoUpdate:
        if os.environ.get("CI") or mode() is Mode.OFF:
            return self
        inst = installation()
        if inst is None or inst.pinned:
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def result(self, wait: float = 0.0) -> Check | None:
        """Ergebnis der Prüfung; wartet höchstens ``wait`` Sekunden darauf."""
        if self._thread is not None and wait:
            self._thread.join(timeout=wait)
        return self._result

    def _run(self) -> None:
        try:
            self._result = check(timeout=3.0)
        except Exception:  # Komfortfunktion – nie den Befehl stören
            self._result = None

    def finish(self, say: Callable[[str], None]) -> None:
        """Am Programmende: Ergebnis abwarten (kurz) und ggf. Aktualisierung starten."""
        if self._thread is None:
            return
        self._thread.join(timeout=2.0)
        result = self._result
        if result is None or not result.available:
            return
        latest = result.latest
        if mode() is Mode.NOTICE:
            say(
                f"Neue Version {latest} verfügbar (installiert: {result.current}) – "
                "aktualisieren mit: sprintforecast aktualisieren"
            )
            return
        state = load_state()
        if state.get("attempted") == latest:
            return  # schon versucht; Fehlschlag meldet startup_notices
        uv = find_uv()
        if uv is None:
            say(f"Neue Version {latest} verfügbar – uv nicht gefunden, bitte neu installieren.")
            return
        try:
            schedule_after_exit(uv)
        except OSError as e:
            say(f"Neue Version {latest} verfügbar – Aktualisierung nicht startbar: {e}")
            return
        update_state(
            attempted=latest,
            attempted_at=datetime.now(UTC).isoformat(),
            failure_reported=False,
        )
        say(f"Neue Version {latest} wird im Hintergrund installiert (gilt ab dem nächsten Start).")


def status_line() -> str:
    """Kurzer Stand für die Weboberfläche – ohne Netzzugriff."""
    current = installed_version()
    inst = installation()
    text = f"Version {current}"
    if inst is None:
        return text
    if inst.pinned:
        return f"{text} (fest: {inst.ref})"
    latest = load_state().get("latest")
    if not is_newer(latest, current):
        return text
    if mode() is Mode.ON:
        return f"{text} · Version {latest} wird nach dem Beenden installiert"
    return f"{text} · Version {latest} verfügbar (`sprintforecast aktualisieren`)"
