# SPDX-License-Identifier: EUPL-1.2
"""Alltagsvorgänge ohne Terminal: Änderungen verwerfen, Verlauf, früheren Stand
wiederherstellen und Tags verwalten.

Alles läuft über das Programm ``git`` (siehe :mod:`sprintforecast.git`). Verwerfen sichert die
betroffenen Dateien vorher in einen Papierkorb unter ``.git``; Wiederherstellen ist selbst ein
Commit und lässt sich mit :func:`revert_commit` zurücknehmen. Pfade lesen wir immer aus
NUL-getrennter Ausgabe (``-z``): Nur so bleiben Namen mit Umlauten oder Anführungszeichen heil.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sprintforecast import git as gitmod
from sprintforecast.git import (
    Change,
    GitError,
    _git,
    changes_in,
    split_record,
    split_z,
)
from sprintforecast.gitsync import _git_dir, _root, state
from sprintforecast.i18n import t

_SEP = "\x1f"
_REC = "\x1e"

# Höchstens so viele Zeichen Pfade je Git-Aufruf (Windows erlaubt rund 32 000 für eine Zeile).
_CHUNK_CHARS = 16000


@dataclass(frozen=True)
class Lost:
    """Was beim Verwerfen verloren geht."""

    status: str  # M geändert, D gelöscht, A/?? neu, R umbenannt
    file: str  # relativ zur Repository-Wurzel
    added: int = 0
    removed: int = 0
    orig: str = ""  # bei Umbenennungen der bisherige Pfad


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
    """Ein Tag. ``local``: auf diesem Rechner vorhanden; ``on_server``: auf dem Server
    vorhanden (None = unbekannt, weil nicht abgefragt oder Server nicht erreichbar);
    ``differs``: lokal und auf dem Server zeigt der Tag auf verschiedene Stände."""

    name: str
    target: str  # Kurz-Hash des getaggten Commits
    day: str
    subject: str
    local: bool = True
    on_server: bool | None = None
    differs: bool = False


def _no_unfinished(path: Path) -> None:
    current = state(path)
    if current.unfinished or current.conflicts:
        raise GitError(
            t("Ein Zusammenführen ist noch nicht abgeschlossen."),
            "merge_in_progress",
            gitmod.hint_for("merge_in_progress"),
        )


def _chunks(paths: list[str]) -> Iterator[list[str]]:
    """Teilt eine lange Pfadliste so, dass jede Zeile für Git kurz genug bleibt."""
    chunk: list[str] = []
    size = 0
    for p in paths:
        if chunk and size + len(p) + 1 > _CHUNK_CHARS:
            yield chunk
            chunk, size = [], 0
        chunk.append(p)
        size += len(p) + 1
    if chunk:
        yield chunk


def _inside(file: str, rel: str) -> bool:
    """Liegt ``file`` (Pfad relativ zur Wurzel) in ``rel``? ``.`` ist die Wurzel selbst."""
    if rel in {"", "."}:
        return True
    return file == rel or file.startswith(rel.rstrip("/") + "/")


# --- Änderungen verwerfen -------------------------------------------------------------------


def _selected(path: Path, files: list[str] | None) -> list[Change]:
    return [c for c in changes_in(path) if files is None or c.file in files]


def _numstat(root: Path, path: Path) -> dict[str, tuple[int, int]]:
    """Hinzugefügte/entfernte Zeilen je Datei (Schlüssel: neuer Pfad)."""
    out = _git(
        root, "diff", "HEAD", "-M", "--numstat", "-z", "--", str(path.resolve()),
        check=False, strip=False,
    )  # fmt: skip
    stats: dict[str, tuple[int, int]] = {}
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        parts = entries[i].split("\t", 2)
        i += 1
        if len(parts) != 3:
            continue
        added, removed, name = parts
        if not name:  # Umbenennung: bisheriger und neuer Pfad folgen
            if i + 1 >= len(entries):
                break
            name = entries[i + 1]
            i += 2
        if added.isdigit() and removed.isdigit():
            stats[name] = (int(added), int(removed))
    return stats


def discard_preview(path: Path, files: list[str] | None = None) -> list[Lost]:
    """Zeigt, was ein Verwerfen kostet (``files`` relativ zur Wurzel; None = alles im
    Datenordner): Status und Zahl hinzugefügter/entfernter Zeilen."""
    root = _root(path)
    changes = _selected(path, files)
    stats = _numstat(root, path)
    lost = []
    for change in changes:
        added, removed = stats.get(change.file, (0, 0))
        if change.status in {"??", "A"} and not added:
            with contextlib.suppress(OSError):
                added = len(
                    (root / change.file).read_text(encoding="utf-8", errors="replace").splitlines()
                )
        lost.append(Lost(change.status, change.file, added, removed, change.orig))
    return lost


def _new_trash(root: Path) -> Path:
    """Ein neuer, noch nicht vorhandener Papierkorb-Ordner (auch bei mehreren Vorgängen in
    derselben Sekunde)."""
    base = _git_dir(root) / "sprintforecast-verworfen"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    n = 0
    while True:
        trash = base / (stamp if n == 0 else f"{stamp}-{n}")
        try:
            trash.mkdir(parents=True)
        except FileExistsError:
            n += 1
            continue
        return trash


def _paths_of(changes: list[Change]) -> list[str]:
    """Alle von den Änderungen berührten Pfade (neuer und bisheriger Name), ohne Doppelte."""
    return list(dict.fromkeys(p for c in changes for p in (c.file, c.orig) if p))


def _backup(root: Path, trash: Path, changes: list[Change]) -> None:
    for name in _paths_of(changes):
        source = root / name
        if source.is_file():
            (trash / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, trash / name)


@dataclass(frozen=True)
class _Snapshot:
    """Zustand vor dem Verwerfen, damit sich nach einem Teilfehler alles zurücklegen lässt:
    welche Dateien es gab (Inhalt liegt im Papierkorb), welche nicht (z. B. gelöscht oder
    vor einer Umbenennung) und die Vormerkung (Index)."""

    present: tuple[str, ...]
    absent: tuple[str, ...]
    index: bytes | None


def _snapshot(root: Path, changes: list[Change]) -> _Snapshot:
    paths = _paths_of(changes)
    try:
        index = (_git_dir(root) / "index").read_bytes()
    except OSError:
        index = None
    return _Snapshot(
        tuple(p for p in paths if (root / p).is_file()),
        tuple(p for p in paths if not (root / p).exists()),
        index,
    )


def _write_index(root: Path, data: bytes) -> None:
    index = _git_dir(root) / "index"
    tmp = index.with_name("index.sprintforecast-rollback")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, index)
    finally:
        tmp.unlink(missing_ok=True)


def _put_back(root: Path, trash: Path, snap: _Snapshot) -> list[str]:
    """Stellt den Zustand vor dem Verwerfen her (nach einem Teilfehler): gesicherte Dateien
    zurückkopieren, wieder angelegte (vorher gelöschte) Dateien entfernen, Vormerkung
    zurückschreiben. Liefert, was sich nicht wiederherstellen ließ (leer = alles)."""
    failed: list[str] = []
    for name in snap.present:
        try:
            saved = trash / name
            if not saved.is_file():
                raise OSError(name)
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, root / name)
        except OSError:
            failed.append(name)
    for name in snap.absent:
        try:
            (root / name).unlink(missing_ok=True)
        except OSError:
            failed.append(name)
    if snap.index is not None:
        try:
            _write_index(root, snap.index)
        except OSError:
            failed.append(t("die Vormerkung (Index)"))
    return failed


def _rollback_hint(failed: list[str], trash: Path, quote: Callable[[str], str] = str) -> str:
    if not failed:
        return t(
            "Der ursprüngliche Zustand (Dateien und Vormerkung) wurde wiederhergestellt. "
            "Sicherung der Änderungen: {trash}",
            trash=quote(str(trash)),
        )
    return t(
        "Der ursprüngliche Zustand konnte nicht vollständig wiederhergestellt werden. "
        "Nicht wiederhergestellt: {files}. Die Sicherung der Änderungen liegt in {trash}; "
        "bitte die Dateien von dort zurückkopieren.",
        files=quote(", ".join(failed)),
        trash=quote(str(trash)),
    )


def discard(path: Path, files: list[str] | None = None) -> Path | None:
    """Verwirft offene Änderungen (einzelne Dateien oder alles im Datenordner). Die Dateien
    werden vorher in einen Papierkorb unter ``.git`` kopiert; dessen Ordner wird zurückgegeben.
    Scheitert etwas, wird der Zustand davor aus der Sicherung wiederhergestellt (Dateien,
    gelöschte Dateien, Vormerkung); die Fehlermeldung nennt, was sich nicht wiederherstellen
    ließ und wo die Sicherung liegt."""
    root = _root(path)
    _no_unfinished(path)
    changes = _selected(path, files)
    if not changes:
        raise GitError(t("Keine Änderungen zum Verwerfen"))
    trash = _new_trash(root)
    try:
        _backup(root, trash, changes)
        snap = _snapshot(root, changes)
    except OSError as e:
        shutil.rmtree(trash, ignore_errors=True)
        raise GitError(
            t("Die Sicherung der Änderungen ist nicht möglich: {error}", error=e),
            "error",
            t("Es wurde nichts verworfen."),
        ) from e
    try:
        _apply_discard(root, changes)
    except (GitError, OSError) as e:
        failed = _put_back(root, trash, snap)
        gitmod.invalidate_status()
        raise GitError(
            t("Das Verwerfen ist nicht vollständig gelungen: {error}", error=e),
            getattr(e, "kind", "error"),
            _rollback_hint(failed, trash),
            hint_md=_rollback_hint(failed, trash, gitmod.md_plain),
        ) from e
    gitmod.invalidate_status()
    if not any(trash.iterdir()):
        trash.rmdir()
        return None
    return trash


def _apply_discard(root: Path, changes: list[Change]) -> None:
    """Setzt die Pfade auf den Stand von HEAD zurück: bekannte Dateien werden wiederhergestellt
    (auch der bisherige Name einer Umbenennung), Dateien, die es in HEAD nicht gibt (neu,
    Ziel einer Umbenennung), aus der Vormerkung genommen und gelöscht."""
    paths = list(dict.fromkeys(p for c in changes for p in (c.file, c.orig) if p))
    in_head: set[str] = set()
    for chunk in _chunks(paths):
        out = _git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", *chunk,
                   check=False, strip=False)  # fmt: skip
        in_head.update(split_z(out))
    restore = [p for p in paths if p in in_head]
    remove = [p for p in paths if p not in in_head]
    for chunk in _chunks(remove):
        _git(root, "rm", "-q", "-f", "--cached", "--ignore-unmatch", "--", *chunk)
    for chunk in _chunks(restore):
        _git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", *chunk)
    for p in remove:
        (root / p).unlink(missing_ok=True)


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
        "-z",
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
        head, _, names = record.partition("\0")
        rev, short, author, day, parents, subject = head.split(_SEP, 5)
        files = tuple(split_z(names.removeprefix("\n")))
        entries.append(Entry(rev, short, author, day, subject, files, len(parents.split()) > 1))
    return entries


def _check_rev(rev: str) -> str:
    rev = rev.strip()
    if not rev or rev.startswith("-"):
        raise GitError(t("Ungültiger Stand: {rev}", rev=rev))
    return rev


def _rollback_restore(
    root: Path, rel: str, added: set[str], saved: dict[str, Path] | None = None
) -> list[str]:
    """Macht ein halb ausgeführtes Wiederherstellen rückgängig (vorher gab es in diesem
    Bereich keine offenen Änderungen, HEAD ist also der richtige Stand). ``saved``: vorher
    gesicherte ignorierte Dateien (Pfad → Sicherung), die wieder an ihren Platz kommen.
    Liefert, was sich nicht zurücksetzen ließ (leer = alles)."""
    saved = saved or {}
    failed: list[str] = []
    for args in (("reset", "-q", "HEAD", "--", rel), ("checkout", "HEAD", "--", rel)):
        try:
            _git(root, *args)
        except GitError:
            failed.append(rel)
    for file in sorted(added - saved.keys()):
        try:
            (root / file).unlink(missing_ok=True)
        except OSError:
            failed.append(file)
    for file, backup in sorted(saved.items()):
        try:
            shutil.copy2(backup, root / file)
        except OSError:
            failed.append(file)
    left = _git(
        root, "status", "--porcelain", "-z", "--untracked-files=no", "--", rel,
        check=False, strip=False,
    )  # fmt: skip
    if left and rel not in failed:
        failed.append(rel)
    return list(dict.fromkeys(failed))


def _save_ignored(root: Path, trash: Path, files: list[str]) -> dict[str, Path]:
    """Sichert ignorierte, nicht verfolgte Dateien, die ein Wiederherstellen überschreiben
    würde (Pfad → Sicherung im Papierkorb)."""
    saved: dict[str, Path] = {}
    for file in files:
        (trash / file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / file, trash / file)
        saved[file] = trash / file
    return saved


def restore_version(path: Path, scope: Path, rev: str, message: str | None = None) -> str:
    """Stellt ``scope`` (Datei oder Ordner) auf den Stand von ``rev`` zurück – als neuer Commit,
    der sich mit :func:`revert_commit` zurücknehmen lässt. Gibt den Kurz-Hash zurück. Mit
    offenen Änderungen im Bereich wird abgelehnt (sie würden sonst überschrieben). Ignorierte,
    nicht verfolgte Dateien (z. B. ``*.tmp``), die der alte Stand überschreiben würde, werden
    vorher in den Papierkorb unter ``.git/sprintforecast-verworfen`` gesichert."""
    root = _root(path)
    _no_unfinished(path)
    rev = _check_rev(rev)
    target = scope.resolve()
    rel = target.relative_to(root).as_posix()  # "." = die Wurzel selbst
    if any(_inside(c.file, rel) or (c.orig and _inside(c.orig, rel)) for c in changes_in(path)):
        raise GitError(
            t("Es gibt offene Änderungen in diesem Bereich."),
            "dirty",
            t("Bitte zuerst speichern (committen) oder verwerfen, dann wiederherstellen."),
        )
    where = [] if rel == "." else ["--", rel]
    then = set(split_z(_git(root, "ls-tree", "-r", "-z", "--name-only", rev, *where, strip=False)))
    now = set(split_z(_git(root, "ls-files", "-z", *where, strip=False)))
    gone = sorted(now - then)
    listing = _git(
        root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", *where,
        check=False, strip=False,
    )  # fmt: skip
    ignored = split_z(listing)
    clash = sorted(set(ignored) & then)
    saved: dict[str, Path] = {}
    trash: Path | None = None
    if clash:
        trash = _new_trash(root)
        try:
            saved = _save_ignored(root, trash, clash)
        except OSError as e:
            shutil.rmtree(trash, ignore_errors=True)
            raise GitError(
                t("Die Sicherung ignorierter Dateien ist nicht möglich: {error}", error=e),
                "error",
                t("Es wurde nichts verändert."),
            ) from e
    try:
        for chunk in _chunks(sorted(then)):
            _git(root, "checkout", rev, "--", *chunk)
        for chunk in _chunks(gone):
            _git(root, "rm", "-q", "--", *chunk)
        if not _git(root, "status", "--porcelain", "-z", "--", rel, strip=False):
            raise GitError(t("Dieser Bereich hat bereits genau diesen Stand."))
        short = _git(root, "rev-parse", "--short", rev)
        text = message or t("Stand von {rev} wiederhergestellt ({scope})", rev=short, scope=rel)
        _git(root, "add", "--all", "--", rel)
        gitmod.refuse_staged_conflict_markers(root)  # ein früher geteilter Fehlerstand
        _git(root, "commit", "-m", text, "--", rel)
    except GitError as e:
        failed = _rollback_restore(root, rel, then - now, saved)
        gitmod.invalidate_status()
        if failed:
            where_saved = trash if trash else _git_dir(root) / "sprintforecast-verworfen"
            raise GitError(
                str(e),
                e.kind,
                t(
                    "Der ursprüngliche Stand konnte nicht vollständig wiederhergestellt werden "
                    "(betroffen: {files}). Gesicherte ignorierte Dateien liegen in {trash}.",
                    files=", ".join(failed),
                    trash=where_saved,
                ),
            ) from e
        raise
    gitmod.invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


def revert_commit(path: Path, rev: str) -> str:
    """Nimmt einen Commit mit einem neuen Commit zurück (macht z. B. eine Wiederherstellung
    rückgängig). Zusammenführungen lassen sich so nicht zurücknehmen."""
    root = _root(path)
    _no_unfinished(path)
    rev = _check_rev(rev)
    parents = _git(root, "rev-list", "--parents", "-n", "1", rev).split()
    if len(parents) > 2:
        raise GitError(t("Eine Zusammenführung lässt sich nicht zurücknehmen."))
    if changes_in(root):  # das ganze Repository, nicht nur der Datenordner
        raise GitError(
            t("Es gibt offene Änderungen."),
            "dirty",
            t("Bitte zuerst speichern (committen) oder verwerfen, dann zurücknehmen."),
        )
    try:
        _git(root, "revert", "--no-edit", rev)
    except GitError as e:
        _git(root, "revert", "--abort", check=False)
        if e.kind == "conflict":
            raise GitError(
                t("Zurücknehmen ist nicht ohne Konflikt möglich: {error}", error=e),
                "conflict",
                t("Spätere Änderungen betreffen dieselben Stellen. Es wurde nichts verändert."),
            ) from e
        if "now empty" in str(e) or "nothing to commit" in str(e):
            raise GitError(
                t("Dieser Commit ändert nichts (mehr); es gibt nichts zurückzunehmen."),
                "error",
                t("Es wurde nichts verändert."),
            ) from e
        raise
    changed = gitmod.split_z(
        _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD", strip=False)
    )
    try:  # kein Stand mit Konfliktmarkierungen (z. B. das Zurücknehmen einer Reparatur)
        gitmod.refuse_conflict_markers(root, (root / name for name in changed))
    except GitError:
        _git(root, "reset", "--hard", "HEAD~1")  # eigener Commit von eben, vorher war alles sauber
        gitmod.invalidate_status()
        raise
    gitmod.invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


# --- Tags -----------------------------------------------------------------------------------


def _remote(root: Path) -> str | None:
    remotes = _git(root, "remote", check=False).split()
    return "origin" if "origin" in remotes else (remotes[0] if remotes else None)


def _server_tags(root: Path, remote: str) -> dict[str, str]:
    """Tags auf dem Server: Name → Commit, auf den sie zeigen (fragt den Server ab)."""
    out = _git(
        root, "ls-remote", "--tags", remote, network=True, url=gitmod.remote_url(root, remote)
    )
    objects: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if not ref.startswith("refs/tags/"):
            continue
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name.removesuffix("^{}")] = sha
        else:
            objects[name] = sha
    return {name: peeled.get(name, sha) for name, sha in objects.items()}


def server_reachable(path: Path) -> bool:
    """Ob der Server der Tags abgefragt werden kann (Netzwerk). False auch ohne Server."""
    root = _root(path)
    remote = _remote(root)
    if not remote:
        return False
    try:
        _server_tags(root, remote)
    except GitError:
        return False
    return True


def list_tags(path: Path, check_server: bool = False) -> list[Tag]:
    """Die Tags dieses Repositorys, neueste zuerst. Mit ``check_server`` wird der Server
    abgefragt (Netzwerk): Dann zeigen ``on_server`` und ``differs`` Unterschiede, und Tags, die
    es nur auf dem Server gibt, stehen mit ``local=False`` am Ende. Ist der Server nicht
    erreichbar, bleibt ``on_server`` None."""
    root = _root(path)
    fmt = _SEP.join(
        [
            "%(refname:strip=2)",
            "%(*objectname)",
            "%(objectname)",
            "%(*objectname:short)",
            "%(objectname:short)",
            "%(creatordate:short)",
            "%(contents:subject)",
        ]
    )
    out = _git(
        root, "for-each-ref", "--sort=-creatordate", f"--format={fmt}", "refs/tags", check=False
    )
    local: list[tuple[Tag, str]] = []
    # nicht splitlines: U+2028, \x0c … trennten den Betreff in mehrere Einträge
    for line in filter(None, out.split("\n")):
        name, deref_full, obj_full, deref, obj, day, subject = split_record(line, 7, _SEP)
        local.append((Tag(name, deref or obj, day, subject), deref_full or obj_full))
    server: dict[str, str] | None = None
    remote = _remote(root) if check_server else None
    if remote:
        try:
            server = _server_tags(root, remote)
        except GitError:
            server = None
    if server is None:
        return [tag for tag, _ in local]
    tags = [
        Tag(
            tag.name,
            tag.target,
            tag.day,
            tag.subject,
            True,
            tag.name in server,
            tag.name in server and server[tag.name] != full,
        )
        for tag, full in local
    ]
    known = {tag.name for tag in tags}
    tags += [
        Tag(name, sha[:7], "", "", local=False, on_server=True)
        for name, sha in sorted(server.items())
        if name not in known
    ]
    return tags


def _valid_name(root: Path, name: str) -> str:
    """Prüft einen Tag-Namen (siehe :func:`sprintforecast.git.valid_tag_name`)."""
    return gitmod.valid_tag_name(root, name)


def _commit_of(root: Path, ref: str) -> str:
    return _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)


def _tag_exists(root: Path, name: str) -> bool:
    return bool(_git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}", check=False))


def set_tag(
    path: Path, name: str, rev: str = "HEAD", message: str | None = None
) -> GitError | None:
    """Setzt (auch nachträglich) einen Tag und lädt ihn hoch. Gibt eine Warnung zurück, wenn
    das Hochladen scheiterte (der Tag bleibt dann lokal; ein erneuter Aufruf lädt ihn hoch).
    Gibt es den Tag lokal schon auf demselben Stand, wird nur hochgeladen; auf einem anderen
    Stand lehnt die Funktion ab. Ist der Server erreichbar und hat den Namen schon für einen
    anderen Stand, wird der Tag nicht angelegt (Fehler ``tag_exists``); hat er ihn für
    denselben Stand, wird er übernommen."""
    root = _root(path)
    name = _valid_name(root, name)
    rev = _check_rev(rev)
    existing = _commit_of(root, f"refs/tags/{name}")
    target = _commit_of(root, rev)
    if existing and existing != target:
        raise GitError(t("Der Tag {name} existiert bereits.", name=name))
    if not existing:
        if _adopt_server_tag(root, name, target):
            return None
        _git(root, "tag", "-a", "-m", message or name, "--", name, rev)
        gitmod.invalidate_status()
    return _push_tag(root, name)


def _adopt_server_tag(root: Path, name: str, target: str) -> bool:
    """Fragt (wenn erreichbar) den Server: Ist der Name dort für einen anderen Stand vergeben,
    Fehler. Zeigt er auf denselben Stand, wird dieser Tag geholt (True), statt einen zweiten
    anzulegen, den der Server als abweichend ablehnen würde."""
    if not (remote := _remote(root)):
        return False
    try:
        on_server = _server_tags(root, remote).get(name)
    except GitError:
        return False  # ohne Antwort des Servers lässt sich nichts sagen
    if not on_server or not target:
        return False
    if on_server != target:
        raise GitError(
            t(
                "Der Tag {name} ist auf dem Server bereits für einen anderen Stand vergeben "
                "({rev}). Er wurde nicht angelegt.",
                name=name,
                rev=on_server[:7],
            ),
            "tag_exists",
            t("Einen anderen Namen wählen oder den Tag auf dem Server zuerst löschen."),
        )
    try:
        _git(
            root,
            "fetch",
            remote,
            f"refs/tags/{name}:refs/tags/{name}",
            network=True,
            url=gitmod.remote_url(root, remote),
        )
    except GitError:
        return False
    gitmod.invalidate_status()
    return True


def _push_tag(root: Path, name: str) -> GitError | None:
    if not (remote := _remote(root)):
        return None
    try:
        _git(
            root,
            "push",
            remote,
            f"refs/tags/{name}",
            network=True,
            url=gitmod.remote_url(root, remote),
        )
    except GitError as e:
        return e
    return None


def upload_tag(path: Path, name: str) -> None:
    """Lädt einen vorhandenen lokalen Tag auf den Server (z. B. nachdem das Hochladen beim
    Setzen scheiterte). Fehler (kein lokaler Tag, kein Server, Server erreichbar nicht, Tag
    mit anderem Stand schon dort) kommen als :class:`GitError`."""
    root = _root(path)
    name = _valid_name(root, name)
    if not _tag_exists(root, name):
        raise GitError(t("Den Tag {name} gibt es auf diesem Rechner nicht.", name=name))
    if _remote(root) is None:
        raise GitError(t("Kein Server eingerichtet."), "no_remote", gitmod.hint_for("no_remote"))
    if error := _push_tag(root, name):
        raise error


def delete_tag(path: Path, name: str) -> GitError | None:
    """Löscht einen Tag lokal und auf dem Server (auch einen, den es nur auf einer der beiden
    Seiten gibt; mehrfaches Aufrufen schadet nicht). Warnung, wenn der Server nicht erreichbar
    war (der Tag bleibt dort bestehen; ein erneuter Aufruf löscht ihn dort)."""
    root = _root(path)
    name = _valid_name(root, name)
    if _tag_exists(root, name):
        _git(root, "tag", "-d", "--", name)
        gitmod.invalidate_status()
    if remote := _remote(root):
        try:
            _git(
                root,
                "push",
                remote,
                f":refs/tags/{name}",
                network=True,
                url=gitmod.remote_url(root, remote),
            )
        except GitError as e:
            if "remote ref does not exist" in str(e):
                return None
            return e
    return None
