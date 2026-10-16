# SPDX-License-Identifier: EUPL-1.2
"""Kleine Git-Helfer für Commit und Sprint-Tag."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from sprintforecast.i18n import t


class GitError(Exception):
    pass


# Tabellenkalkulationen dürfen nie committet werden (können echte Team-Daten enthalten).
FORBIDDEN = re.compile(r"\.xls[xm]?$", re.IGNORECASE)


# Windows: keine Konsolenfenster für Hilfsprozesse (sonst blitzt bei jedem Aufruf eines auf).
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

_ROOT_CACHE: dict[Path, tuple[float, Path | None]] = {}
_ROOT_TTL = 30.0


def _git(cwd: Path, *args: str, strip: bool = True) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, **NO_WINDOW)
    except FileNotFoundError as e:
        raise GitError(t("git ist nicht installiert oder nicht im PATH")) from e
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip() if strip else proc.stdout


def repo_root(path: Path) -> Path | None:
    """Wurzel des Git-Repositorys, in dem ``path`` liegt – oder None."""
    path = path.resolve()
    cached = _ROOT_CACHE.get(path)
    if cached and time.monotonic() - cached[0] < _ROOT_TTL:
        return cached[1]
    start = path
    while not start.exists():
        start = start.parent
    try:
        root = Path(_git(start if start.is_dir() else start.parent, "rev-parse", "--show-toplevel"))
    except GitError:
        root = None
    _ROOT_CACHE[path] = (time.monotonic(), root)
    return root


def pending_changes(path: Path) -> list[tuple[str, str]]:
    """Nicht committete Änderungen unterhalb von ``path`` als (Status, Pfad relativ zur Wurzel)."""
    root = repo_root(path)
    if root is None:
        raise GitError(t("{path} liegt in keinem Git-Repository", path=path))
    # Nicht strippen: Die Statusspalte beginnt ggf. mit einem Leerzeichen (" M datei").
    out = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        str(path.resolve()),
        strip=False,
    )
    changes = []
    for line in out.splitlines():
        status, file = line[:2].strip(), line[3:]
        if " -> " in file:  # Umbenennung
            file = file.split(" -> ", 1)[1]
        changes.append((status, file.strip('"')))
    return changes


def commit_directory(path: Path, message: str, tags: list[str] | None = None) -> str:
    """Committet alle Änderungen unterhalb von ``path`` (nur dort) und setzt optional Tags."""
    root = repo_root(path)
    if root is None:
        raise GitError(t("{path} liegt in keinem Git-Repository", path=path))
    changes = pending_changes(path)
    if not changes:
        raise GitError(t("Keine Änderungen zum Committen"))
    if blocked := [f for _, f in changes if FORBIDDEN.search(f)]:
        raise GitError(
            t(
                "Tabellenkalkulationen werden nicht committet – bitte entfernen oder in "
                ".gitignore aufnehmen: {files}",
                files=", ".join(blocked),
            )
        )
    target = str(path.resolve())
    _git(root, "add", "--all", "--", target)
    _git(root, "commit", "-m", message, "--", target)
    for tag in tags or []:
        _git(root, "tag", "-a", tag, "-m", message)
    return _git(root, "rev-parse", "--short", "HEAD")


def commit(paths: list[Path], message: str, tag: str | None = None) -> str:
    """Committet ``paths`` und setzt optional einen Tag. Gibt den Commit-Hash zurück."""
    cwd = paths[0].resolve().parent
    root = Path(_git(cwd, "rev-parse", "--show-toplevel"))
    _git(root, "add", "--", *(str(p.resolve()) for p in paths))
    _git(root, "commit", "-m", message, "--", *(str(p.resolve()) for p in paths))
    if tag:
        _git(root, "tag", "-a", tag, "-m", message)
    return _git(root, "rev-parse", "--short", "HEAD")


GITIGNORE = """\
# Tabellenkalkulationen nie committen – sie können echte Team-Daten enthalten.
*.xlsx
*.xlsm
*.xls
"""


def init_data_repository(path: Path, teams_folder: bool = True) -> Path:
    """Legt ein Daten-Repository an (git init, .gitignore, optional Ordner ``teams``) und
    liefert den Ordner für die Teams."""
    path.mkdir(parents=True, exist_ok=True)
    if repo_root(path) is None:
        _git(path, "init", "-q")
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE, encoding="utf-8")
    if not teams_folder:
        return path
    teams = path / "teams"
    teams.mkdir(exist_ok=True)
    return teams


def clone_repository(url: str, path: Path, timeout: float = 300) -> None:
    """Klont ein bestehendes Daten-Repository nach ``path``."""
    if path.exists() and any(path.iterdir()):
        raise GitError(t("{path} ist nicht leer", path=path))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["git", "clone", url, str(path)], capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as e:
        raise GitError(t("git ist nicht installiert oder nicht im PATH")) from e
    except subprocess.TimeoutExpired as e:
        raise GitError(t("Klonen dauert zu lange – Adresse und Anmeldung prüfen")) from e
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip())
