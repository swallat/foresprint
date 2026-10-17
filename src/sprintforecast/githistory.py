# SPDX-License-Identifier: EUPL-1.2
"""Alltagsvorgänge ohne Terminal: Änderungen verwerfen, Verlauf, früheren Stand
wiederherstellen und Tags verwalten.

Alles läuft über das Programm ``git`` (siehe :mod:`sprintforecast.git`). Verwerfen sichert die
betroffenen Dateien vorher in einen Papierkorb unter ``.git``; Wiederherstellen ist selbst ein
Commit und lässt sich mit :func:`revert_commit` zurücknehmen.
"""

from __future__ import annotations

import contextlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from sprintforecast import git as gitmod
from sprintforecast.git import GitError, _git, pending_changes
from sprintforecast.gitsync import _git_dir, _root, state
from sprintforecast.i18n import t

_SEP = "\x1f"
_REC = "\x1e"


@dataclass(frozen=True)
class Lost:
    """Was beim Verwerfen verloren geht."""

    status: str  # M geändert, D gelöscht, A/?? neu
    file: str  # relativ zur Repository-Wurzel
    added: int = 0
    removed: int = 0


@dataclass(frozen=True)
class Entry:
    rev: str
    short: str
    author: str
    day: str
    subject: str
    files: tuple[str, ...] = ()
    merge: bool = False


@dataclass(frozen=True)
class Tag:
    name: str
    target: str  # Kurz-Hash des getaggten Commits
    day: str
    subject: str


def _no_unfinished(path: Path) -> None:
    current = state(path)
    if current.unfinished or current.conflicts:
        raise GitError(
            t("Ein Zusammenführen ist noch nicht abgeschlossen."),
            "merge_in_progress",
            gitmod.hint_for("merge_in_progress"),
        )


# --- Änderungen verwerfen -------------------------------------------------------------------


def discard_preview(path: Path, files: list[str] | None = None) -> list[Lost]:
    """Zeigt, was ein Verwerfen kostet (``files`` relativ zur Wurzel; None = alles im
    Datenordner): Status und Zahl hinzugefügter/entfernter Zeilen."""
    root = _root(path)
    changes = [(s, f) for s, f in pending_changes(path) if files is None or f in files]
    stats: dict[str, tuple[int, int]] = {}
    out = _git(root, "diff", "HEAD", "--numstat", "--", str(path.resolve()), check=False)
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            stats[parts[2]] = (int(parts[0]), int(parts[1]))
    lost = []
    for status, file in changes:
        added, removed = stats.get(file, (0, 0))
        if status in {"??", "A"} and not added:
            with contextlib.suppress(OSError):
                added = len(
                    (root / file).read_text(encoding="utf-8", errors="replace").splitlines()
                )
        lost.append(Lost(status, file, added, removed))
    return lost


def discard(path: Path, files: list[str] | None = None) -> Path | None:
    """Verwirft offene Änderungen (einzelne Dateien oder alles im Datenordner). Die Dateien
    werden vorher in einen Papierkorb unter ``.git`` kopiert; dessen Ordner wird zurückgegeben."""
    root = _root(path)
    _no_unfinished(path)
    changes = [(s, f) for s, f in pending_changes(path) if files is None or f in files]
    if not changes:
        raise GitError(t("Keine Änderungen zum Verwerfen"))
    trash = _git_dir(root) / "sprintforecast-verworfen" / time.strftime("%Y%m%d-%H%M%S")
    for _, file in changes:
        source = root / file
        if source.is_file():
            (trash / file).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, trash / file)
    for status, file in changes:
        if status in {"??", "A", "AM"}:
            if status != "??":
                _git(root, "rm", "-q", "-f", "--cached", "--", file)
            (root / file).unlink(missing_ok=True)
        else:
            _git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", file)
    gitmod.invalidate_status()
    return trash if trash.exists() else None


# --- Verlauf --------------------------------------------------------------------------------


def history(path: Path, scope: Path | None = None, limit: int = 40) -> list[Entry]:
    """Commits, die ``scope`` (Datei oder Ordner; Standard: der Datenordner) betreffen: wer hat
    wann was geändert, neueste zuerst."""
    root = _root(path)
    target = str((scope or path).resolve())
    fmt = f"{_REC}%H{_SEP}%h{_SEP}%an{_SEP}%ad{_SEP}%P{_SEP}%s"
    out = _git(
        root,
        "log",
        f"-{limit}",
        f"--format={fmt}",
        "--date=format:%Y-%m-%d %H:%M",
        "--name-only",
        "--no-renames",
        "--",
        target,
        check=False,
        strip=False,
    )
    entries = []
    for record in filter(None, out.split(_REC)):
        head, _, names = record.partition("\n")
        rev, short, author, day, parents, subject = head.split(_SEP, 5)
        files = tuple(n for n in names.splitlines() if n.strip())
        entries.append(Entry(rev, short, author, day, subject, files, len(parents.split()) > 1))
    return entries


def restore_version(path: Path, scope: Path, rev: str, message: str | None = None) -> str:
    """Stellt ``scope`` (Datei oder Ordner) auf den Stand von ``rev`` zurück – als neuer Commit,
    der sich mit :func:`revert_commit` zurücknehmen lässt. Gibt den Kurz-Hash zurück."""
    root = _root(path)
    _no_unfinished(path)
    target = scope.resolve()
    rel = target.relative_to(root).as_posix()
    if any(f == rel or f.startswith(rel.rstrip("/") + "/") for _, f in pending_changes(path)):
        raise GitError(
            t("Es gibt offene Änderungen in diesem Bereich."),
            "dirty",
            t("Bitte zuerst speichern (committen) oder verwerfen, dann wiederherstellen."),
        )
    then = set(_git(root, "ls-tree", "-r", "--name-only", rev, "--", rel).splitlines())
    now = set(_git(root, "ls-files", "--", rel).splitlines())
    if then:
        _git(root, "checkout", rev, "--", *sorted(then))
    if gone := sorted(now - then):
        _git(root, "rm", "-q", "--", *gone)
    if not _git(root, "status", "--porcelain", "--", rel):
        raise GitError(t("Dieser Bereich hat bereits genau diesen Stand."))
    short = _git(root, "rev-parse", "--short", rev)
    text = message or t("Stand von {rev} wiederhergestellt ({scope})", rev=short, scope=rel)
    _git(root, "add", "--all", "--", rel)
    _git(root, "commit", "-m", text, "--", rel)
    gitmod.invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


def revert_commit(path: Path, rev: str) -> str:
    """Nimmt einen Commit mit einem neuen Commit zurück (macht z. B. eine Wiederherstellung
    rückgängig). Zusammenführungen lassen sich so nicht zurücknehmen."""
    root = _root(path)
    _no_unfinished(path)
    parents = _git(root, "rev-list", "--parents", "-n", "1", rev).split()
    if len(parents) > 2:
        raise GitError(t("Eine Zusammenführung lässt sich nicht zurücknehmen."))
    if pending_changes(path):
        raise GitError(
            t("Es gibt offene Änderungen."),
            "dirty",
            t("Bitte zuerst speichern (committen) oder verwerfen, dann zurücknehmen."),
        )
    try:
        _git(root, "revert", "--no-edit", rev)
    except GitError as e:
        _git(root, "revert", "--abort", check=False)
        raise GitError(
            t("Zurücknehmen ist nicht ohne Konflikt möglich: {error}", error=e),
            "conflict",
            t("Spätere Änderungen betreffen dieselben Stellen. Es wurde nichts verändert."),
        ) from e
    gitmod.invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


# --- Tags -----------------------------------------------------------------------------------


def list_tags(path: Path) -> list[Tag]:
    root = _root(path)
    fmt = _SEP.join(
        [
            "%(refname:short)",
            "%(*objectname:short)",
            "%(objectname:short)",
            "%(creatordate:short)",
            "%(contents:subject)",
        ]
    )
    out = _git(
        root, "for-each-ref", "--sort=-creatordate", f"--format={fmt}", "refs/tags", check=False
    )
    tags = []
    for line in out.splitlines():
        name, deref, obj, day, subject = line.split(_SEP, 4)
        tags.append(Tag(name, deref or obj, day, subject))
    return tags


def _remote(root: Path) -> str | None:
    remotes = _git(root, "remote", check=False).split()
    return "origin" if "origin" in remotes else (remotes[0] if remotes else None)


def set_tag(
    path: Path, name: str, rev: str = "HEAD", message: str | None = None
) -> GitError | None:
    """Setzt (auch nachträglich) einen Tag und lädt ihn hoch. Gibt eine Warnung zurück, wenn
    das Hochladen scheiterte (der Tag bleibt dann lokal)."""
    root = _root(path)
    name = name.strip()
    try:
        if not name:
            raise GitError("")
        _git(root, "check-ref-format", f"refs/tags/{name}")
    except GitError as e:
        raise GitError(t("Ungültiger Tag-Name: {name}", name=name)) from e
    if _git(root, "tag", "-l", name):
        raise GitError(t("Der Tag {name} existiert bereits.", name=name))
    _git(root, "tag", "-a", name, rev, "-m", message or name)
    gitmod.invalidate_status()
    if remote := _remote(root):
        try:
            _git(root, "push", remote, f"refs/tags/{name}", network=True)
        except GitError as e:
            return e
    return None


def delete_tag(path: Path, name: str) -> GitError | None:
    """Löscht einen Tag lokal und auf dem Server. Warnung, wenn der Server nicht erreichbar
    war (der Tag bleibt dort bestehen)."""
    root = _root(path)
    _git(root, "tag", "-d", name)
    gitmod.invalidate_status()
    if remote := _remote(root):
        try:
            _git(root, "push", remote, f":refs/tags/{name}", network=True)
        except GitError as e:
            if "remote ref does not exist" in str(e):
                return None
            return e
    return None
