# SPDX-License-Identifier: EUPL-1.2
"""Self-update, similar to Claude Code.

- When a command starts, a background check runs at most once a day to see whether a newer
  version exists (``version`` in ``pyproject.toml`` of the installed branch).
- Mode ``on`` (default): after the command ends, a separate process updates with
  ``uv tool upgrade --reinstall sprintforecast``; the next start uses the new version.
  ``uv`` keeps the source, plugins (``--with``) and Python version of the installation.
- Mode ``notice``: only a notice. Mode ``off``: no check.
- Manually: ``sprintforecast update``.

Active only for an installation with ``uv tool install`` (recognizable by ``uv-receipt.toml``),
so not in development (``uv run``) and not in CI. The update waits for the end of the own
process, because Windows locks running programs and loaded libraries.
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
import time
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
from sprintforecast.git import find_git
from sprintforecast.i18n import t

PACKAGE = "sprintforecast"
DEFAULT_REPO = "swallat/sprint-forecast"
DEFAULT_REF = "main"
MODE_ENV = "SPRINTFORECAST_AUTOUPDATE"
CHECK_INTERVAL = timedelta(hours=24)
# Only after this time does an update that had no effect count as failed.
FAILURE_GRACE = timedelta(minutes=15)


class Mode(StrEnum):
    ON = "on"
    NOTICE = "notice"
    OFF = "off"


# --- Storage --------------------------------------------------------------------------


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


def save_state(state: dict[str, Any], strict: bool = False) -> bool:
    """Writes the state; ``True`` if that worked. Without ``strict`` an error stays silent
    (the update is a convenience and never disturbs the actual command), with ``strict`` the
    ``OSError`` is passed on."""
    try:
        path = state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        if strict:
            raise
        return False
    return True


def update_state(strict: bool = False, **changes: Any) -> dict[str, Any]:
    state = load_state() | changes
    save_state(state, strict=strict)
    return state


def mode() -> Mode:
    """Environment variable before stored setting; default: on."""
    for raw in (os.environ.get(MODE_ENV), load_state().get("mode")):
        if raw:
            value = str(raw).strip().lower()
            aliases = {
                "1": "on",
                "true": "on",
                "on": "on",
                "notice": "notice",
                "0": "off",
                "false": "off",
                "off": "off",
                # Values written by older versions.
                "an": "on",
                "hinweis": "notice",
                "aus": "off",
            }
            try:
                return Mode(aliases.get(value, value))
            except ValueError:
                continue
    return Mode.ON


# --- Versions -------------------------------------------------------------------------


def installed_version() -> str:
    try:
        return metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        from sprintforecast import __version__

        return __version__


def parse_version(text: str) -> tuple[int, ...]:
    """Parses "0.10.2" to (0, 10, 2); suffixes like "rc1" are ignored."""
    parts = []
    for piece in text.strip().lstrip("v").split("."):
        match = re.match(r"\d+", piece)
        if not match:
            break
        parts.append(int(match.group()))
    return tuple(parts)


def is_newer(candidate: Any, current: Any) -> bool:
    """Only strings are versions; anything else in the state file (edited by hand, corrupted)
    counts as "not newer" instead of disturbing the start."""
    if not isinstance(candidate, str) or not isinstance(current, str):
        return False
    return parse_version(candidate) > parse_version(current)


# --- Installation ---------------------------------------------------------------------


@dataclass(frozen=True)
class Installation:
    """Where the running installation comes from (from the uv receipt)."""

    repo: str
    ref: str
    # Pinned to a tag: not updated automatically.
    pinned: bool
    # Core without its own address, the source comes from a plugin.
    via_plugin: bool = False


_ARCHIVE = re.compile(r"github\.com/([^/]+/[^/]+)/archive/refs/(heads|tags)/(.+?)\.(zip|tar\.gz)$")
_GIT = re.compile(r"github\.com/([^/@#?]+/[^/@#?]+?)(?:\.git)?(?:[@#?].*)?$")


def receipt_path() -> Path:
    return Path(sys.prefix) / "uv-receipt.toml"


def installation() -> Installation | None:
    """None if not installed with ``uv tool install`` (e.g. development, CI)."""
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


def remote_version(inst: Installation, timeout: float = 5.0, fresh: bool = False) -> str:
    """Version in ``pyproject.toml`` of the installed branch; raises OSError/ValueError.

    raw.githubusercontent.com caches responses for a few minutes; with ``fresh`` (manual
    check) the cache is bypassed by a changing parameter."""
    url = f"https://raw.githubusercontent.com/{inst.repo}/{inst.ref}/pyproject.toml"
    request_url = f"{url}?nocache={int(time.time())}" if fresh else url
    project = tomllib.loads(_fetch(request_url, timeout)).get("project", {})
    version = project.get("version")
    if not isinstance(version, str):
        raise ValueError(t("No version in {url}", url=url))
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
    """Checks for a new version; without ``force`` at most once per CHECK_INTERVAL."""
    now = now or datetime.now(UTC)
    current = installed_version()
    inst = installation()
    if inst is None:
        return Check(current, None, None, t("not installed with uv tool install"))
    state = load_state()
    last = _parse_time(state.get("last_check"))
    if not force and last is not None and now - last < CHECK_INTERVAL:
        return Check(current, state.get("latest"), inst)
    try:
        latest = remote_version(inst, timeout, fresh=force)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        update_state(last_check=now.isoformat())  # do not wait again on every start
        return Check(current, state.get("latest"), inst, str(e))
    update_state(last_check=now.isoformat(), latest=latest)
    return Check(current, latest, inst)


def _parse_time(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


# --- Updating -------------------------------------------------------------------------


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
    # --reinstall reloads the source (same address, new content) and keeps --with plugins.
    return [uv, "tool", "upgrade", "--reinstall", PACKAGE]


def _path_key(env: dict[str, str] | os._Environ[str]) -> str:
    # Windows: variable names are case-insensitive ("Path" instead of "PATH").
    if sys.platform == "win32":
        return next((name for name in env if name.upper() == "PATH"), "PATH")
    return "PATH"


def _same_file(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def upgrade_path() -> str | None:
    """PATH for the uv call. For plugins from Git addresses, uv itself starts ``git`` via the
    PATH. If Git is only outside the PATH (see ``git.find_git``), its folder goes at the END
    of the PATH: at the front it would shadow programs of the same name (python, uv, …) in
    the same folder, e.g. for ``~/.local/bin`` or ``scoop\\shims``. If the PATH is not set,
    the system's default search (``os.defpath``) is kept. ``None``: nothing to change (Git
    is on the PATH or not found). What counts is the result of ``find_git``: if the PATH only
    holds an unusable ``git`` (e.g. the Windows Store alias, now blocked) and the usable one
    is at a fallback location, that folder is appended."""
    found = find_git()
    if not found:
        return None
    if (in_path := shutil.which("git")) and _same_file(in_path, found):
        return None
    folder = os.path.normcase(os.path.dirname(found))
    if any(folder == os.path.normcase(os.path.abspath(f)) for f in os.get_exec_path() if f):
        return None  # a later PATH entry: appending would change nothing
    current = os.environ.get(_path_key(os.environ)) or os.defpath
    return os.pathsep.join([current, os.path.dirname(found)])


def upgrade_environment() -> dict[str, str] | None:
    """Environment for the uv call (copy with adjusted PATH, see :func:`upgrade_path`);
    ``None``: uv inherits the environment unchanged."""
    path = upgrade_path()
    if path is None:
        return None
    env = dict(os.environ)
    env[_path_key(env)] = path
    return env


def run_upgrade(uv: str) -> int:
    """Updates immediately in the foreground (not on Windows, where files are locked)."""
    return subprocess.run(upgrade_command(uv), env=upgrade_environment()).returncode


def _powershell_script(
    pids: list[int],
    command: list[str],
    log: Path,
    visible: bool,
    then: list[str] | None = None,
    cwd: str | None = None,
    path: str | None = None,
) -> str:
    def quote(text: str) -> str:
        return "'" + text.replace("'", "''") + "'"

    call = "& " + " ".join(quote(c) for c in command)
    lines = [
        "$ErrorActionPreference = 'Continue'",
        f"Wait-Process -Id {','.join(map(str, pids))} -ErrorAction SilentlyContinue",
        "Start-Sleep -Seconds 1",
    ]
    if path is not None:
        # Only for the uv call; ``then`` (the restart) runs with the original PATH.
        lines += ["$sfPath = $env:PATH", f"$env:PATH = {quote(path)}"]
    if visible:
        lines += [
            f"Write-Host {quote(t('Updating sprintforecast …'))}",
            f"{call} 2>&1 | Tee-Object -FilePath {quote(str(log))}",
        ]
    else:
        lines.append(f"{call} *> {quote(str(log))}")
    if path is not None:
        lines.append("$env:PATH = $sfPath")
    if then:
        # A single command line quoted by Windows rules: Start-Process joins array elements
        # with spaces only, so paths containing spaces would otherwise fall apart.
        args = f" -ArgumentList {quote(subprocess.list2cmdline(then[1:]))}" if then[1:] else ""
        location = f" -WorkingDirectory {quote(cwd)}" if cwd else ""
        lines.append(f"Start-Process -FilePath {quote(then[0])}{args}{location}")
    elif visible:
        lines += [
            "Write-Host ''",
            f"Write-Host {quote(t('Done. This window closes in 15 seconds.'))}",
            "Start-Sleep -Seconds 15",
        ]
    return "\n".join(lines)


def _posix_script(
    pids: list[int],
    command: list[str],
    then: list[str] | None,
    cwd: str | None,
    path: str | None = None,
) -> str:
    waits = "; ".join(f"while kill -0 {p} 2>/dev/null; do sleep 1; done" for p in pids)
    # The PATH applies only to the uv call (assignment before the command), not to ``then``.
    prefix = f"PATH={shlex.quote(path)} " if path is not None else ""
    script = f"{waits}; {prefix}{shlex.join(command)}"
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
    """Starts a standalone process that updates after this process (or the processes
    ``pids``) has ended and then optionally starts ``then`` (restart)."""
    log = log_file()
    log.parent.mkdir(parents=True, exist_ok=True)
    command = upgrade_command(uv)
    path = upgrade_path()
    pids = list(pids or [os.getpid()])
    if sys.platform == "win32":
        # The uv launcher (sprintforecast.exe) is the parent process and is locked as well.
        if os.getppid() not in pids:
            pids.append(os.getppid())
        script = _powershell_script(pids, command, log, visible, then, cwd, path)
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
            ["/bin/sh", "-c", _posix_script(pids, command, then, cwd, path)],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


# --- Web UI ---------------------------------------------------------------------------

# Passed from `sprintforecast web` to the web UI: processes whose end the update has to wait
# for, and the command for the restart (JSON list).
PIDS_ENV = "SPRINTFORECAST_PARENT_PIDS"
RESTART_ENV = "SPRINTFORECAST_RESTART"
# Set by sprintforecast-app: original launcher including arguments (JSON list).
LAUNCHER_ENV = "SPRINTFORECAST_LAUNCHER"


def web_environment(argv: list[str]) -> dict[str, str]:
    """Environment for the web UI server (called by `sprintforecast web`)."""
    pids = [os.getpid()]
    if sys.platform == "win32":
        pids.append(os.getppid())
    if launcher := os.environ.get(LAUNCHER_ENV):
        # Started by double-click: call the same launcher (without console window) again.
        cmd = json.loads(launcher)
    else:
        cmd = [shutil.which(PACKAGE) or argv[0], *argv[1:]]
    return {
        PIDS_ENV: ",".join(map(str, pids)),
        RESTART_ENV: json.dumps({"cmd": cmd, "cwd": os.getcwd()}),
    }


def restart_with_update() -> str | None:
    """Schedules the update and restart for after the web UI has ended.
    Returns an error message or None. The caller then shuts down the server."""
    uv = find_uv()
    if uv is None:
        return t("uv not found – please run the install script again.")
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
        return t("Update cannot be started: {error}", error=e)
    latest = load_state().get("latest")
    update_state(
        attempted=latest, attempted_at=datetime.now(UTC).isoformat(), failure_reported=False
    )
    return None


# --- Command line integration ---------------------------------------------------------


def startup_notices(now: datetime | None = None) -> list[str]:
    """Notices at startup: automatic update that succeeded or failed."""
    if installation() is None:
        return []
    now = now or datetime.now(UTC)
    current = installed_version()
    state = load_state()
    messages = []
    seen = state.get("seen_version")
    if seen and is_newer(current, seen):
        messages.append(t("sprintforecast was updated to version {version}.", version=current))
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
            t(
                (
                    "The automatic update to {version} did not work – log: {log}. Manually: "
                    "sprintforecast update"
                ),
                version=attempted,
                log=log_file(),
            )
        )
        changes["failure_reported"] = True
    update_state(**changes)
    return messages


class AutoUpdate:
    """Checks in the background and schedules the update for the end of the program."""

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
        """Result of the check; waits at most ``wait`` seconds for it."""
        if self._thread is not None and wait:
            self._thread.join(timeout=wait)
        return self._result

    def _run(self) -> None:
        try:
            self._result = check(timeout=3.0)
        except Exception:  # convenience feature: never disturb the command
            self._result = None

    def finish(self, say: Callable[[str], None]) -> None:
        """At program end: wait (briefly) for the result and start the update if needed."""
        if self._thread is None:
            return
        self._thread.join(timeout=2.0)
        result = self._result
        if result is None or not result.available:
            return
        latest = result.latest
        if mode() is Mode.NOTICE:
            say(
                t(
                    (
                        "New version {latest} available (installed: {current}) – update with: "
                        "sprintforecast update"
                    ),
                    latest=latest,
                    current=result.current,
                )
            )
            return
        state = load_state()
        if state.get("attempted") == latest:
            return  # already tried; startup_notices reports a failure
        uv = find_uv()
        if uv is None:
            say(
                t(
                    "New version {latest} available – uv not found, please reinstall.",
                    latest=latest,
                )
            )
            return
        try:
            schedule_after_exit(uv)
        except OSError as e:
            say(
                t(
                    "New version {latest} available – update cannot be started: {error}",
                    latest=latest,
                    error=e,
                )
            )
            return
        update_state(
            attempted=latest,
            attempted_at=datetime.now(UTC).isoformat(),
            failure_reported=False,
        )
        say(
            t(
                (
                    "New version {latest} is being installed in the background (effective from "
                    "the next start)."
                ),
                latest=latest,
            )
        )


def status_line() -> str:
    """Short status for the web UI, without network access."""
    current = installed_version()
    inst = installation()
    text = f"Version {current}"
    if inst is None:
        return text
    if inst.pinned:
        return t("{text} (pinned: {ref})", text=text, ref=inst.ref)
    latest = load_state().get("latest")
    if not is_newer(latest, current):
        return text
    if mode() is Mode.ON:
        return t("{text} · version {latest} will be installed on exit", text=text, latest=latest)
    return t(
        "{text} · version {latest} available (`sprintforecast update`)",
        text=text,
        latest=latest,
    )
