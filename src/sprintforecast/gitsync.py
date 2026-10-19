# SPDX-License-Identifier: EUPL-1.2
"""Stand und „Speichern und teilen“ für gemeinsam genutzte Daten-Repositories.

Das Modell ist bewusst einfach: ein Branch, immer synchron halten. Die Funktionen rufen das
Programm ``git`` auf (siehe :mod:`sprintforecast.git`) und liefern Fehler als
:class:`~sprintforecast.git.GitError` mit Art und nächstem Schritt. Eigene Änderungen werden vor
jedem Abgleich committet, damit sie nie verloren gehen können; scheitert das Zusammenführen,
wird es abgebrochen und der Stand bleibt wie zuvor.
"""

from __future__ import annotations

import difflib
import hashlib
import io
import os
import re
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from sprintforecast import git as gitmod
from sprintforecast.git import (
    GitError,
    _git,
    hint_for,
    pending_changes,
    require_root,
    split_record,
)
from sprintforecast.i18n import t
from sprintforecast.yamlmerge import (
    MISSING,
    OURS,
    KeyConflict,
    header_of,
    merge3,
)

# Wie die eigenen Änderungen auf den Server kommen: direkt auf den Branch oder (Server mit
# geschütztem Hauptbranch, z. B. GitLab) über einen Merge Request. Die Wahl gilt je
# Daten-Repository und steht in dessen lokaler Git-Konfiguration.
SHARE_KEY = "sprintforecast.share"
AUTO_MERGE_KEY = "sprintforecast.mrautomerge"  # "false" schaltet das Automerge ab (Standard: an)
SHARE_DIRECT, SHARE_MERGE_REQUEST = "direct", "merge_request"
_PR_URL = re.compile(
    r"https?://\S+/(?:pulls?/(?:\d+|new/\S+)|merge_requests/(?:\d+|new\b\S*)|compare/\S+)"
)
# Auf welchem Server liegt das Daten-Repository? Das bestimmt, wie ein Merge/Pull Request
# entsteht. ``HOST_KEY`` überschreibt die Erkennung aus der Adresse (Standard: automatisch).
HOST_KEY = "sprintforecast.host"
HOST_GITLAB, HOST_GITHUB, HOST_FORGEJO, HOST_GENERIC = "gitlab", "github", "forgejo", "generic"
HOSTS = (HOST_GITLAB, HOST_GITHUB, HOST_FORGEJO, HOST_GENERIC)

# Wie oft ein Push nach "inzwischen hat jemand anderes hochgeladen" neu versucht wird.
MAX_ATTEMPTS = 3

_SEP = "\x1f"


@dataclass(frozen=True)
class Commit:
    rev: str
    author: str
    day: str
    subject: str


@dataclass(frozen=True)
class SyncState:
    """Stand des Datenordners gegenüber dem Server (ohne Netzwerkzugriff ermittelt; ``behind``
    gilt für den Stand beim letzten Abgleich, siehe :func:`fetch`)."""

    root: Path
    branch: str | None  # None = detached HEAD
    upstream: str | None  # z. B. "origin/main"
    remote: str | None  # Name des Servers, None = keiner eingerichtet
    # Roh, kann Zugangsdaten enthalten (Altbestand): nie anzeigen, auch nicht über ``repr``.
    url: str = field(default="", repr=False)
    ahead: int = 0
    behind: int = 0
    unfinished: str | None = None  # "merge" oder "rebase"
    conflicts: tuple[str, ...] = ()
    fetch_error: GitError | None = None  # Ergebnis des letzten Abgleichs, None = ok/unbekannt
    fetched_at: float | None = None
    unborn: bool = False  # noch kein Commit (frisch angelegtes Repository)

    @property
    def detached(self) -> bool:
        return self.branch is None

    @property
    def offline(self) -> bool:
        return self.fetch_error is not None and self.fetch_error.kind == "offline"

    @property
    def can_share(self) -> bool:
        return self.remote is not None and not self.detached and self.unfinished is None


@dataclass(frozen=True)
class ConflictFile:
    """Eine Datei, die beim Zusammenführen nicht von selbst zusammenpasst."""

    file: str  # relativ zur Repository-Wurzel
    keys: tuple[KeyConflict, ...] = ()  # echte Wertkonflikte (nur bei Zusammenführen je Schlüssel)
    whole: bool = False  # nur als Ganzes entscheidbar (kein YAML, gelöscht auf einer Seite)
    ours_deleted: bool = False
    theirs_deleted: bool = False

    @property
    def open(self) -> bool:
        """Braucht eine Entscheidung (sonst wird die Datei automatisch zusammengeführt)."""
        return self.whole or bool(self.keys)


@dataclass
class SyncResult:
    """Ergebnis von :func:`sync`: was getan wurde, was von anderen kam und woran es ggf. hakt."""

    committed: str | None = None  # Kurz-Hash des eigenen Commits
    pulled: list[Commit] = field(default_factory=list)  # neu von anderen
    pulled_files: list[tuple[str, str]] = field(default_factory=list)
    pushed: bool = False
    merge_request_url: str | None = None  # Teilen über Merge Request: Adresse, falls gemeldet
    merge_request_branch: str | None = None  # Branch, der hochgeladen wurde
    pull_only: bool = False  # „Vom Server holen“: nichts hochladen, auch nicht beim Fortsetzen
    merged: bool = False  # fremde Änderungen wurden zusammengeführt
    conflicts: list[ConflictFile] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)  # neue Fehler nach dem Zusammenführen
    notes: list[str] = field(default_factory=list)  # Hinweise, obwohl alles gelang
    error: GitError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# Zuletzt bekannter Abgleich je Repository: (Zeit, Fehler oder None).
_FETCHED: dict[Path, tuple[float, GitError | None]] = {}
_STATE_CACHE: dict[Path, tuple[float, SyncState]] = {}
_STATE_TTL = 5.0
gitmod.on_invalidate(_STATE_CACHE.clear)


def git_available() -> bool:
    return gitmod.find_git() is not None


def _root(path: Path) -> Path:
    if not git_available():
        raise gitmod.classify("", missing=True, broken=gitmod.broken_git())
    return require_root(path)


def _git_dir(root: Path) -> Path:
    inner = root / ".git"
    if inner.is_dir():
        return inner
    return Path(_git(root, "rev-parse", "--absolute-git-dir"))


def state(path: Path) -> SyncState:
    """Stand des Datenordners (lokal ermittelt, ohne Netzwerk)."""
    root = _root(path)
    out = _git(
        root, "status", "--porcelain=v2", "-z", "--branch", "--untracked-files=no", strip=False
    )
    branch: str | None = None
    upstream: str | None = None
    unborn = False
    ahead = behind = 0
    conflicts: list[str] = []
    entries = out.split("\0")
    skip = 0
    for line in entries:
        if skip:  # bisheriger Pfad einer Umbenennung
            skip -= 1
            continue
        if line.startswith("2 "):
            skip = 1
        elif line.startswith("# branch.oid "):
            unborn = line.split(" ", 2)[2] == "(initial)"  # noch kein Commit
        elif line.startswith("# branch.head "):
            head = line.split(" ", 2)[2]
            branch = None if head == "(detached)" else head
        elif line.startswith("# branch.upstream "):
            upstream = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            plus, minus = line.split(" ")[2:4]
            ahead, behind = int(plus.lstrip("+")), abs(int(minus))
        elif line.startswith("u "):  # nicht zusammengeführte Datei
            conflicts.append(line.split(" ", 10)[-1])
    remote = upstream.split("/", 1)[0] if upstream else None
    if remote is None:
        remotes = _git(root, "remote", check=False).split()
        remote = "origin" if "origin" in remotes else (remotes[0] if remotes else None)
    url = _git(root, "config", "--get", f"remote.{remote}.url", check=False) if remote else ""
    gdir = _git_dir(root)
    unfinished = None
    if (gdir / "MERGE_HEAD").exists():
        unfinished = "merge"
    elif (gdir / "rebase-merge").exists() or (gdir / "rebase-apply").exists():
        unfinished = "rebase"
    fetched = _FETCHED.get(root)
    return SyncState(
        root=root,
        branch=branch,
        upstream=upstream,
        remote=remote,
        url=url,
        ahead=ahead,
        behind=behind,
        unfinished=unfinished,
        conflicts=tuple(conflicts),
        fetch_error=fetched[1] if fetched else None,
        fetched_at=fetched[0] if fetched else None,
        unborn=unborn,
    )


def cached_state(path: Path) -> SyncState:
    """Wie :func:`state`, aber kurz zwischengespeichert (für die Oberfläche); wird mit
    :func:`sprintforecast.git.invalidate_status` ungültig."""
    key = path.resolve()
    cached = _STATE_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATE_TTL:
        return cached[1]
    current = state(path)
    _STATE_CACHE[key] = (time.monotonic(), current)
    return current


# Im Hintergrund: kurzes Zeitlimit (der ganze Prozessbaum wird beendet) und nie ein Anmeldefenster
# oder eine Rückfrage (Credential Manager, GIT_ASKPASS/SSH_ASKPASS, SSH-Passphrase). Fehlt die
# Anmeldung oder ist der Server nicht erreichbar, bleibt der Stand unverändert; der Knopf „Stand
# prüfen“ erklärt dann den nächsten Schritt.
BACKGROUND_FETCH_SECONDS = 30 * 60
BACKGROUND_TIMEOUT = 20.0
BACKGROUND_OFF_ENV = "SPRINTFORECAST_NO_BACKGROUND_FETCH"  # gesetzt: kein Abruf im Hintergrund
_QUIET_ENV = {
    "GCM_INTERACTIVE": "never",
    "SSH_ASKPASS_REQUIRE": "never",
    "GIT_ASKPASS": "",  # leer (nicht fehlend): Git fragt weder core.askPass noch SSH_ASKPASS
}
_BACKGROUND_LOCK = threading.Lock()
_BACKGROUND_ACTIVE: set[Path] = set()
_BACKGROUND_LAST: dict[Path, float] = {}  # letzter Versuch je Datenordner (ohne Git-Aufruf)
_SYNC_LOCKS: dict[Path, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    """Eine Sperre je Datenordner: Abgleich und Abruf laufen nie gleichzeitig (Git sperrt sonst
    ``packed-refs`` und Index, und „Speichern und teilen“ scheiterte an einem Abruf im
    Hintergrund). Wiedereintrittsfähig, denn der Abgleich ruft :func:`fetch` selbst auf."""
    key = path.resolve()
    with _BACKGROUND_LOCK:
        return _SYNC_LOCKS.setdefault(key, threading.RLock())


def _quiet_env(root: Path) -> dict[str, str]:
    """Umgebung für den Abruf im Hintergrund; SSH läuft ohne Rückfrage (``BatchMode``), wenn
    niemand einen eigenen SSH-Befehl festgelegt hat (Umgebung oder ``core.sshCommand``)."""
    env = dict(_QUIET_ENV)
    if not (
        os.environ.get("GIT_SSH_COMMAND")
        or os.environ.get("GIT_SSH")
        or _git(root, "config", "--get", "core.sshCommand", check=False)
    ):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
    return env


def _fetch_in_background(root: Path, current: SyncState) -> None:
    """Ein ``git fetch --prune`` mit Zeitlimit; gespeichert wird nur ein Erfolg (ein Misserfolg
    ohne Rückfrage sagt nichts über den Server und soll den letzten guten Stand nicht
    überschreiben). Ist der Server inzwischen ein anderer, gilt das Ergebnis nicht."""
    run = gitmod._probe_run(
        root,
        ("fetch", "--prune", "--no-tags", current.remote or "origin"),
        BACKGROUND_TIMEOUT,
        _quiet_env(root),
    )
    if run.code != 0:
        return
    if gitmod.remote_url(root, current.remote or "origin") != current.url:
        return
    _FETCHED[root] = (time.time(), None)
    gitmod.invalidate_status()


def fetch(path: Path) -> SyncState:
    """Holt den Stand vom Server (nur herunterladen, nichts ändern) und merkt sich, ob der
    Server erreichbar war. Fehler werden nicht ausgelöst, sondern im Stand vermerkt."""
    with _lock_for(path):
        root = _root(path)
        current = state(path)
        error: GitError | None = None
        if current.remote is None:
            error = GitError(t("Kein Server eingerichtet."), "no_remote", hint_for("no_remote"))
        else:
            try:
                _git(root, "fetch", "--prune", current.remote, network=True, url=current.url)
            except GitError as e:
                error = e
        _FETCHED[root] = (time.time(), error)
        gitmod.invalidate_status()
        return state(path)


def background_fetch_due(path: Path, now: float | None = None) -> bool:
    """Ist der letzte Abruf (Versuch im Hintergrund oder Abruf von Hand) länger als 30 Minuten
    her oder gab es noch keinen in diesem Programmlauf, und hat der Datenordner einen Server?
    Die Prüfung der Zeit kommt zuerst und braucht keinen Git-Aufruf: Die Seitenleiste fragt bei
    jedem Neuzeichnen."""
    now = now or time.time()
    key = path.resolve()
    # Etwas Spielraum: Die Oberfläche ruft genau alle 30 Minuten, der letzte Abruf endete aber
    # einige Sekunden nach seinem Beginn.
    due_after = BACKGROUND_FETCH_SECONDS - 60
    last = _BACKGROUND_LAST.get(key)
    if last is not None and now - last < due_after:
        return False
    if cached_state(path).remote is None:
        _BACKGROUND_LAST[key] = now  # ohne Server nicht bei jedem Neuzeichnen neu fragen
        return False
    fetched = _FETCHED.get(_root(path))
    return fetched is None or now - fetched[0] >= due_after


def start_background_fetch(path: Path) -> bool:
    """Startet bei Bedarf einen Abruf des Serverstands im Hintergrund (``git fetch --prune``)
    und liefert, ob einer gestartet wurde. Es läuft nie mehr als einer je Datenordner, nie
    gleichzeitig mit einem Abgleich, und keine Dauerschleife: Aufgerufen wird nur aus einer
    verbundenen Sitzung (beim Start und alle 30 Minuten), der Faden ist ein Nebenfaden und hält
    ``idle.py`` nicht auf."""
    if os.environ.get(BACKGROUND_OFF_ENV):
        return False
    key = path.resolve()
    try:
        if not background_fetch_due(path):
            return False
        root = _root(path)
        current = state(path)
    except GitError:
        return False
    lock = _lock_for(path)
    with _BACKGROUND_LOCK:
        if key in _BACKGROUND_ACTIVE:
            return False
        _BACKGROUND_ACTIVE.add(key)
        _BACKGROUND_LAST[key] = time.time()

    def run() -> None:
        try:
            if lock.acquire(blocking=False):  # ein Abgleich läuft: beim nächsten Mal wieder
                try:
                    _fetch_in_background(root, current)
                finally:
                    lock.release()
        except Exception:  # ein Hintergrundabruf darf nie etwas beenden
            pass
        finally:
            with _BACKGROUND_LOCK:
                _BACKGROUND_ACTIVE.discard(key)

    threading.Thread(target=run, name="sprintforecast-fetch", daemon=True).start()
    return True


def incoming(path: Path, limit: int = 50) -> tuple[list[Commit], list[tuple[str, str]]]:
    """Was andere seit dem eigenen Stand geändert haben (nach dem letzten Abgleich): Commits
    und geänderte Dateien (Status, Pfad) unterhalb von ``path``."""
    root = _root(path)
    current = state(path)
    if not current.upstream or current.behind == 0:
        return [], []
    target = str(path.resolve())
    log = _git(
        root,
        "log",
        f"-{limit}",
        f"--format=%h{_SEP}%an{_SEP}%as{_SEP}%s",
        f"HEAD..{current.upstream}",
        "--",
        target,
        check=False,
    )
    commits = [Commit(*split_record(line, 4, _SEP)) for line in log.split("\n") if _SEP in line]
    related = bool(_git(root, "merge-base", "HEAD", current.upstream, check=False))
    span = f"HEAD...{current.upstream}" if related else f"HEAD..{current.upstream}"
    diff = _git(
        root, "diff", "--name-status", "-z", span, "--", target,
        check=False, strip=False,
    )  # fmt: skip
    files = []
    entries = diff.split("\0")
    i = 0
    while i < len(entries) and entries[i]:
        status = entries[i]
        i += 1
        names = 2 if status[:1] in {"R", "C"} else 1  # bei Umbenennungen: alt, neu
        if i + names > len(entries):
            break
        files.append((status[:1], entries[i + names - 1]))
        i += names
    return commits, files


def _parse(text: str) -> Any:
    from sprintforecast.storage import _YAML_LOADER

    content = yaml.load(text, Loader=_YAML_LOADER)
    return {} if content is None else content


def _stages(root: Path) -> dict[str, set[int]]:
    """Nicht zusammengeführte Dateien mit den vorhandenen Ständen (1 = Basis, 2 = meine,
    3 = andere)."""
    out = _git(root, "ls-files", "-u", "-z", strip=False, check=False)
    stages: dict[str, set[int]] = {}
    for entry in filter(None, out.split("\0")):
        info, _, name = entry.partition("\t")
        stages.setdefault(name, set()).add(int(info.split()[2]))
    return stages


def _stage_text(root: Path, stage: int, file: str) -> str:
    return _git(root, "show", f":{stage}:{file}", strip=False)


# Obergrenzen der Textansicht (Zeilen und Zeichen je Zeile), damit eine große Datei die Seite
# nicht sprengt.
MAX_DIFF_LINES = 300
MAX_DIFF_COLUMNS = 400


def unified_diff(old: str, new: str, old_name: str, new_name: str) -> str:
    """Zeilenweiser Unterschied (``diff -u``) zweier Texte, gekürzt; leer, wenn gleich."""
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), old_name, new_name, lineterm="", n=2
    )
    kept = [line[:MAX_DIFF_COLUMNS] for line in lines]
    if len(kept) > MAX_DIFF_LINES:
        kept = [*kept[:MAX_DIFF_LINES], f"… (+{len(kept) - MAX_DIFF_LINES})"]
    return "\n".join(kept)


def conflict_text_diffs(path: Path, file: str) -> tuple[str, str]:
    """Wie sich die Datei bei einem offenen Zusammenführen auf beiden Seiten gegenüber dem
    gemeinsamen Stand geändert hat, als Text (``diff -u``): (meine Seite, andere Seite). Leer,
    wenn es den Stand nicht gibt, die Datei zu groß ist oder kein Text."""
    root = _root(path)
    stages = _stages(root).get(file, set())

    def text(stage: int) -> str | None:
        if stage not in stages:
            return None
        size = _git(root, "cat-file", "-s", f":{stage}:{file}", check=False)
        if not size.isdigit() or int(size) > 1_000_000:
            raise ValueError(file)
        return gitmod._git_bytes(root, "show", f":{stage}:{file}").decode("utf-8")

    try:
        base, mine, theirs = text(1), text(2), text(3)
    except ValueError, GitError:
        return "", ""
    shown = base or ""

    def one(side: str | None, label: str) -> str:
        return unified_diff(
            shown, side or "", f"{file} ({t('gemeinsamer Stand')})", f"{file} ({label})"
        )

    return one(mine, t("meine Änderung")), one(theirs, t("andere Änderung"))


def _analyse(
    root: Path, file: str, stages: set[int], choices: dict[tuple[str, ...], str]
) -> tuple[ConflictFile, str | None]:
    """Prüft eine Datei: lässt sie sich auf Schlüsselebene zusammenführen? Liefert die offenen
    Wertkonflikte und – wenn keine bleiben – den zusammengeführten Text."""
    whole = ConflictFile(
        file, whole=True, ours_deleted=2 not in stages, theirs_deleted=3 not in stages
    )
    if not file.endswith((".yaml", ".yml")) or not {2, 3} <= stages:
        return whole, None
    try:
        ours_text, theirs_text = _stage_text(root, 2, file), _stage_text(root, 3, file)
        base = _parse(_stage_text(root, 1, file)) if 1 in stages else MISSING
        ours, theirs = _parse(ours_text), _parse(theirs_text)
        if not isinstance(ours, dict) or not isinstance(theirs, dict):
            return whole, None
        merged, conflicts = merge3(base, ours, theirs, choices)
    except yaml.YAMLError, GitError, ValueError:
        return whole, None
    if conflicts:
        return ConflictFile(file, keys=tuple(conflicts)), None
    from sprintforecast.storage import dump_yaml

    return ConflictFile(file), header_of(ours_text or theirs_text) + dump_yaml(merged)


def pending_conflicts(path: Path) -> list[ConflictFile]:
    """Dateien eines unvollständigen Zusammenführens: mit ihren echten Wertkonflikten (leer =
    lässt sich automatisch zusammenführen) bzw. als Ganzes zu entscheiden."""
    root = _root(path)
    return [_analyse(root, f, st, {})[0] for f, st in sorted(_stages(root).items())]


def resolve_conflicts(
    path: Path, choices: dict[str, dict[tuple[str, ...], str]] | None = None
) -> list[ConflictFile]:
    """Löst alles, was sich lösen lässt: Dateien ohne Wertkonflikt automatisch, die übrigen
    nach ``choices`` (Datei → Pfad → "ours"/"theirs"; Pfad ``()`` = ganze Datei). Liefert die
    verbleibenden Konflikte. Das Zusammenführen wird erst von :func:`sync` abgeschlossen."""
    root = _root(path)
    for file, stages in sorted(_stages(root).items()):
        wanted = (choices or {}).get(file, {})
        info, merged = _analyse(root, file, stages, wanted)
        if info.whole:
            choice = wanted.get(())
            if choice is None:
                continue
            keep = 2 if choice == OURS else 3
            if keep in stages:
                _git(root, "checkout", "--ours" if choice == OURS else "--theirs", "--", file)
                _git(root, "add", "--", file)
            else:  # auf dieser Seite gelöscht
                _git(root, "rm", "-q", "--", file)
        elif merged is not None:
            try:
                (root / file).write_text(merged, encoding="utf-8", newline="\n")
            except OSError as e:  # gesperrt oder schreibgeschützt: das Zusammenführen bleibt offen
                # Die Art bleibt ``locked`` („Eine Datei ist gesperrt“): Windows meldet eine von
                # einem anderen Programm gehaltene Datei als „Permission denied“, wie eine
                # schreibgeschützte, und die Fehlernummer trennt beide nicht verlässlich.
                # Anders als bei Gits ``index.lock`` passt hier aber nur der Hinweis zur Datei.
                raise GitError(
                    t(
                        "{file} konnte nicht geschrieben werden ({reason}).",
                        file=file,
                        reason=e.strerror or str(e),
                    ),
                    "locked",
                    gitmod.unwritable_file_hint(),
                ) from e
            _git(root, "add", "--", file)
    gitmod.invalidate_status()
    return pending_conflicts(path)


def _unrelated(root: Path, remote: str | None, upstream: str) -> bool:
    """Haben der eigene Stand und ``upstream`` keinen gemeinsamen Ursprung? Unterscheidet
    „kein gemeinsamer Vorfahr“ (Rückgabecode 1) von echten Fehlern (werden ausgelöst) und
    von einem flachen Klon, dessen abgeschnittene Historie nur so aussieht: Dort wird erst
    die volle Historie geholt. Ohne eigenen Commit gibt es nichts, was sich vermischen ließe."""
    if not _ref_exists(root, "HEAD"):
        return False
    for attempt in range(2):
        proc = gitmod._git_result(root, "merge-base", "HEAD", upstream)
        if proc.returncode == 0 and proc.stdout.strip():
            return False
        if proc.returncode not in {0, 1}:
            raise gitmod.classify(proc.stderr.strip() or proc.stdout.strip())
        shallow = _git(root, "rev-parse", "--is-shallow-repository", check=False) == "true"
        if attempt == 0 and shallow and remote:
            _git(
                root,
                "fetch",
                "--unshallow",
                "--prune",
                remote,
                network=True,
                url=gitmod.remote_url(root, remote),
            )
            continue
        break
    return True


def _unrelated_error(current: SyncState, target: str) -> GitError:
    return gitmod.UnrelatedHistoriesError(
        gitmod.public_url(current.url) or current.remote or "?", target.split("/", 1)[-1]
    )


def _merge(
    root: Path, upstream: str, path: Path, allow_unrelated: bool = False
) -> list[ConflictFile]:
    """Führt den Server-Stand ein. Bei Konflikten bleibt das Zusammenführen offen, alles
    automatisch Lösbare ist erledigt; zurück kommen die Konflikte für den Menschen (leer =
    fertig). Die eigenen Änderungen sind bereits committet. Unverwandte Historien werden nur
    mit ``allow_unrelated`` zusammengeführt (der Aufrufer hat sie vorher geprüft)."""
    args = ["merge", "--no-edit"]
    if allow_unrelated:
        args.append("--allow-unrelated-histories")
    try:
        _git(root, *args, upstream)
        return []
    except GitError as e:
        if e.kind not in {"conflict", "error"} or not (_git_dir(root) / "MERGE_HEAD").exists():
            raise
    remaining = resolve_conflicts(path)
    if not remaining:
        gitmod.refuse_staged_conflict_markers(root)
        _git(root, "commit", "--no-edit")
    return remaining


def _conflict_error() -> GitError:
    return GitError(
        t("Zusammenführen: Konflikte warten auf deine Entscheidung."),
        "conflict",
        hint_for("conflict"),
    )


def _error_set(repo_dir: Path, today: date) -> set[tuple[str, str, str]]:
    from sprintforecast.storage import Repository
    from sprintforecast.validate import Level, check_all

    # Ohne den Ordner im Text: Der Vergleich Arbeitsstand gegen Commit läuft in verschiedenen
    # Ordnern, und Ladefehler nennen den Dateipfad.
    prefix = str(repo_dir)

    def relative(text: str) -> str:
        return text.replace(prefix + os.sep, "").replace(prefix, "")

    return {
        (key, relative(i.where), relative(i.message))
        for key, issues in check_all(Repository(repo_dir), today).items()
        for i in issues
        if i.level is Level.ERROR
    }


def _errors_at(root: Path, path: Path, rev: str, today: date) -> set[tuple[str, str, str]]:
    """Fehler der Gesamtvalidierung für den Stand eines Commits (ohne ihn auszuchecken)."""
    rel = path.resolve().relative_to(root).as_posix()
    tree = rev if rel == "." else f"{rev}:{rel}"
    try:
        data = gitmod._git_bytes(root, "archive", "--format=tar", tree)
    except GitError:
        return set()
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(tmp, filter="data")
        return _error_set(Path(tmp), today)


def new_errors(path: Path, baseline: str, today: date | None = None) -> list[str]:
    """Fehler der Gesamtvalidierung im Arbeitsstand, die im Stand ``baseline`` (Commit) noch
    nicht vorhanden waren – als lesbare Zeilen."""
    root = _root(path)
    today = today or date.today()
    found = _error_set(path, today) - _errors_at(root, path, baseline, today)
    return [f"{key}: {where}: {message}" for key, where, message in sorted(found)]


def _ref_exists(root: Path, ref: str) -> bool:
    return bool(_git(root, "rev-parse", "--verify", "--quiet", ref, check=False))


def _unpushed_merges(root: Path, current: SyncState) -> bool:
    # Ohne Gegenstelle (noch nie hochgeladen oder vom Server entfernt) gibt es nichts zu
    # vergleichen.
    if not current.upstream or not _ref_exists(root, f"refs/remotes/{current.upstream}"):
        return False
    count = _git(root, "rev-list", "--merges", "--count", f"{current.upstream}..HEAD")
    return count.isdigit() and int(count) > 0


def _sync(
    path: Path,
    message: str,
    tags: list[str] | None = None,
    today: date | None = None,
    allow_invalid: bool = False,
    allow_unrelated: bool = False,
    push: bool = True,
) -> SyncResult:
    """„Speichern und teilen“: eigene Änderungen committen, die der anderen holen und
    zusammenführen, prüfen, hochladen. Erwartbare Fehler (offline, abgelehnt, Anmeldung,
    Konflikt …) stehen in ``result.error``; was bis dahin gelang (z. B. der eigene Commit),
    bleibt erhalten. Bei Konflikten bleibt das Zusammenführen offen (``result.conflicts``);
    nach der Entscheidung (:func:`resolve_conflicts`) setzt ein erneuter Aufruf fort. Nach
    einem Zusammenführen läuft die Gesamtvalidierung: Neue Fehler verhindern das Hochladen,
    außer mit ``allow_invalid``. Hat der Server eine fremde Historie ohne gemeinsamen Ursprung
    (meist das falsche Repository), bricht die Funktion vor dem Zusammenführen mit der
    Fehlerart ``unrelated_histories`` ab; nur mit ``allow_unrelated`` (ausdrückliche
    Bestätigung) wird trotzdem zusammengeführt, danach gilt die übliche Konfliktbehandlung.
    Tags (``tags``) werden vor dem Commit geprüft: Ist ein Name ungültig oder lokal schon
    vergeben, bricht die Funktion ab, ohne zu committen; fehlende Tags werden auch ohne neuen
    Commit nachgeholt. Hat der Datenordner nach dem Sichern noch keinen Commit (frisch angelegt,
    keine Dateien), gibt es nichts zu teilen: Fehlerart ``nothing_to_share``. Mit
    ``push=False`` („Vom Server holen“) endet der Ablauf nach dem Zusammenführen: Eigenes wird
    gesichert und der Server-Stand übernommen, aber nichts hochgeladen und nicht geprüft."""
    result = SyncResult(pull_only=not push)
    try:
        root = _root(path)
        current = state(path)
        if current.unfinished == "rebase":
            raise GitError(
                t("Ein früherer Vorgang ist noch nicht abgeschlossen."),
                "merge_in_progress",
                hint_for("merge_in_progress"),
            )
        if current.detached:
            raise GitError(t("Kein Branch ausgewählt."), "detached", hint_for("detached"))
        # 0. Wiederaufnahme: ein offenes Zusammenführen zuerst abschließen.
        if current.unfinished == "merge":
            result.conflicts = resolve_conflicts(path)
            if result.conflicts:
                raise _conflict_error()
            gitmod.refuse_staged_conflict_markers(root)
            _git(root, "commit", "--no-edit")
            result.merged = True
        elif current.conflicts:
            raise GitError(
                t("Ein früherer Vorgang ist noch nicht abgeschlossen."),
                "merge_in_progress",
                hint_for("merge_in_progress"),
            )
        # 1. Eigenes sichern: erst als Commit, dann ist nichts mehr in Gefahr.
        if pending_changes(path):
            result.committed = gitmod.commit_directory(path, message, tags)
        elif tags:
            _, elsewhere = gitmod.ensure_tags(root, tags, message)
            result.notes += [
                t(
                    "Der Tag {tag} zeigt auf einen anderen Commit als den aktuellen Stand und "
                    "wurde nicht verschoben.",
                    tag=tag,
                )
                for tag in elsewhere
            ]
        current = state(path)
        if current.remote is None:
            raise GitError(t("Kein Server eingerichtet."), "no_remote", hint_for("no_remote"))
        if not _ref_exists(root, "HEAD"):
            # Frisches Repository ohne eigene Daten: Es gibt nichts hochzuladen, und ein Branch
            # ohne Commit lässt sich weder mit dem Server verbinden noch pushen (Git meldete
            # sonst „failed to push some refs“, was wie ein Wettlauf aussieht).
            raise gitmod.nothing_to_share_error()
        # 2. Server-Stand holen, 3. zusammenführen, 4. prüfen, 5. hochladen (bei Wettlauf neu).
        for attempt in range(MAX_ATTEMPTS):
            current = fetch(path)
            if current.fetch_error is not None:
                raise current.fetch_error
            unrelated = False
            if target := _server_branch(root, current):
                unrelated = _unrelated(root, current.remote, target)
                if unrelated and not allow_unrelated:
                    raise _unrelated_error(current, target)
            if not current.upstream and current.branch:
                current = _adopt_remote_branch(root, current)
            commits, files = incoming(path)
            result.pulled += [c for c in commits if c not in result.pulled]
            result.pulled_files += [f for f in files if f not in result.pulled_files]
            if current.upstream and current.behind:
                result.conflicts = _merge(root, current.upstream, path, unrelated)
                if result.conflicts:
                    raise _conflict_error()
                result.merged = True
                current = state(path)
            if not push:
                if share_mode(root) == SHARE_MERGE_REQUEST:
                    result.notes += _open_merge_request_note(root, path, current)
                break
            if not allow_invalid and _unpushed_merges(root, current):
                found = new_errors(path, current.upstream or "HEAD", today)
                if found:
                    result.validation = found
                    raise GitError(
                        t("Die zusammengeführten Daten sind nicht gültig."),
                        "invalid",
                        hint_for("invalid"),
                    )
            via_mr = share_mode(root) == SHARE_MERGE_REQUEST
            if via_mr and current.upstream and current.ahead:
                current = _drop_merged_commits(root, current)  # z. B. nach „Squash“ im Merge
            if via_mr and tags:
                result.notes.append(
                    t(
                        "Tags werden bei Merge Requests nicht hochgeladen; sie lassen sich nach "
                        "dem Merge im Bereich „Tags“ teilen."
                    )
                )
            if via_mr and current.upstream and not current.ahead:
                break  # nichts Eigenes, das einen Merge Request bräuchte
            try:
                if via_mr:
                    result.merge_request_branch, result.merge_request_url = _push_merge_request(
                        root, current, message
                    )
                else:
                    _push(root, current)
            except GitError as e:
                if e.kind == "rejected" and not via_mr and attempt + 1 < MAX_ATTEMPTS:
                    continue
                raise
            result.pushed = True
            result.notes += _tag_notes(root, current, tags or [])
            break
    except GitError as e:
        result.error = e
    finally:
        gitmod.invalidate_status()
    return result


def sync(path: Path, *args: Any, **kwargs: Any) -> SyncResult:
    """„Speichern und teilen“ (siehe :func:`_sync`); läuft nie gleichzeitig mit einem Abruf."""
    with _lock_for(path):
        return _sync(path, *args, **kwargs)


def _server_branch(root: Path, current: SyncState) -> str | None:
    """Der Stand des Servers zum aktuellen Branch (z. B. ``origin/main``), soweit es ihn gibt:
    der verbundene Upstream oder, vor der ersten Verbindung, der gleichnamige Branch."""
    candidate = current.upstream or (
        f"{current.remote}/{current.branch}" if current.remote and current.branch else None
    )
    if candidate and _ref_exists(root, f"refs/remotes/{candidate}"):
        return candidate
    return None


def _adopt_remote_branch(root: Path, current: SyncState) -> SyncState:
    """Hat der Server den Branch schon, dieser Rechner ihn aber noch nicht mit dem Server
    verbunden (z. B. ein getrennt begonnenes Repository), wird er jetzt verbunden. Danach
    wird der Server-Stand ganz normal zusammengeführt."""
    candidate = f"{current.remote}/{current.branch}"
    if current.remote and _ref_exists(root, f"refs/remotes/{candidate}"):
        _git(root, "branch", f"--set-upstream-to={candidate}")
        return state(root)
    return current


def _git_ok(root: Path, *args: str) -> bool:
    return gitmod._git_result(root, *args).returncode == 0


def _tag_notes(root: Path, current: SyncState, tags: list[str]) -> list[str]:
    """Hinweise zu Tags, die ``push --follow-tags`` nicht veröffentlicht hat: Der Name ist auf
    dem Server schon für einen anderen Stand vergeben (zwei Personen haben denselben Sprint
    getaggt) – der Tag bleibt dort unverändert, lokal zeigt er auf den eigenen Stand."""
    notes: list[str] = []
    if not tags or not current.remote:
        return notes
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
    for tag in tags:
        local = gitmod.tag_commit(root, tag)
        if not local:
            continue
        if local != head and not _git_ok(root, "merge-base", "--is-ancestor", local, "HEAD"):
            notes.append(
                t(
                    "Der Tag {tag} zeigt auf einen anderen Commit, der nicht zum aktuellen "
                    "Stand gehört; er wurde nicht verschoben.",
                    tag=tag,
                )
            )
            continue
        try:
            out = _git(root, "ls-remote", "--tags", current.remote, f"refs/tags/{tag}",
                       f"refs/tags/{tag}^{{}}", network=True, url=current.url)  # fmt: skip
        except GitError:
            continue  # ohne Antwort des Servers lässt sich nichts sagen
        refs = {}
        for line in out.splitlines():
            sha, _, ref = line.partition("\t")
            refs[ref] = sha
        remote = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
        if remote and remote != local:
            notes.append(
                t(
                    "Der Tag {tag} ist auf dem Server bereits für einen anderen Stand vergeben "
                    "und wurde nicht überschrieben. Auf diesem Rechner zeigt er auf den "
                    "eigenen Stand.",
                    tag=tag,
                )
            )
        elif not remote:
            notes.append(t("Der Tag {tag} konnte nicht auf den Server übertragen werden.", tag=tag))
    return notes


def _drop_merged_commits(root: Path, current: SyncState) -> SyncState:
    """Hat der eigene Stand denselben Inhalt wie der Server (der Merge Request ist gemergt, etwa
    als „Squash“ mit neuem Commit), setzt dies den Branch auf den Server-Stand: Sonst bliebe er
    für immer „voraus“ und jedes Teilen legte einen leeren Merge Request an. ``--keep`` bricht ab,
    wo etwas verloren ginge."""
    if _git_ok(root, "diff", "--quiet", current.upstream or "HEAD", "HEAD", "--") and _git_ok(
        root, "diff", "--quiet", "--cached"
    ):
        _git(root, "reset", "--keep", current.upstream or "HEAD", check=False)
        return state(root)
    return current


def share_mode(path: Path) -> str:
    """``"direct"`` (Standard) oder ``"merge_request"``: wohin „Speichern und teilen“ hochlädt."""
    root = _root(path)
    value = _git(root, "config", "--local", "--get", SHARE_KEY, check=False)
    return value if value == SHARE_MERGE_REQUEST else SHARE_DIRECT


def _open_merge_request_note(root: Path, path: Path, current: SyncState) -> list[str]:
    """Hinweis für „Vom Server holen“ im Merge-Request-Modus: Stehen eigene Änderungen noch nicht
    im Hauptbranch, sagt er, ob sie in einem offenen Merge Request liegen (der eigene Branch ist
    auf dem Server und enthält den Stand) oder noch gar nicht geteilt wurden. Inhalt, der schon
    im Hauptbranch steht (gemergt, etwa als „Squash“), zählt nicht."""
    if current.upstream and current.ahead:
        current = _drop_merged_commits(root, current)
    if not (current.upstream and current.ahead):
        return []
    branch = (current.upstream).partition("/")[2] or "main"
    mr_ref = f"refs/remotes/{current.remote or 'origin'}/{merge_request_branch(root)}"
    if _ref_exists(root, mr_ref) and _git_ok(root, "merge-base", "--is-ancestor", "HEAD", mr_ref):
        return [
            t(
                "Dein Merge Request ist noch offen: Deine Änderungen stehen auf dem Server noch "
                "nicht in {branch}. Hole sie nach dem Merge erneut.",
                branch=branch,
            )
        ]
    if host_kind(root) == HOST_FORGEJO:
        # Der Pull Request liegt nicht auf einem eigenen Branch, den man hier sehen könnte.
        return [
            t(
                "Deine Änderungen stehen auf dem Server noch nicht in {branch}. Liegen sie in "
                "einem offenen Pull Request, hole sie nach dem Merge erneut.",
                branch=branch,
            )
        ]
    return [
        t(
            "Deine Änderungen sind noch nicht geteilt (nicht in {branch}, kein Merge Request "
            "auf dem Server). „Speichern und teilen“ legt ihn an.",
            branch=branch,
        )
    ]


def auto_merge(path: Path) -> bool:
    """Soll der Merge Request automatisch mergen, sobald die Pipeline grün ist? Standard: ja."""
    root = _root(path)
    return _git(root, "config", "--local", "--get", AUTO_MERGE_KEY, check=False) != "false"


def set_auto_merge(path: Path, enabled: bool) -> None:
    root = _root(path)
    if enabled:
        _git(root, "config", "--local", "--unset-all", AUTO_MERGE_KEY, check=False)
    else:
        _git(root, "config", "--local", AUTO_MERGE_KEY, "false")


def set_share_mode(path: Path, mode: str) -> None:
    root = _root(path)
    if mode == SHARE_MERGE_REQUEST:
        _git(root, "config", "--local", SHARE_KEY, mode)
    else:
        _git(root, "config", "--local", "--unset-all", SHARE_KEY, check=False)


def detect_host(url: str) -> str:
    """Welche Art Server hinter der Adresse steckt, soweit der Name es verrät (GitHub, GitLab,
    Forgejo/Gitea/Codeberg); alles andere ist ``generic``."""
    name = (_web_location(url) or ("", ""))[0].lower()
    if name == "github.com" or name.startswith("github."):
        return HOST_GITHUB
    if "gitlab" in name:
        return HOST_GITLAB
    if name == "codeberg.org" or any(word in name for word in ("forgejo", "gitea")):
        return HOST_FORGEJO
    return HOST_GENERIC


def _web_location(url: str) -> tuple[str, str] | None:
    """Rechnername und Pfad ohne ``.git`` aus einer Server-Adresse (https, ssh oder scp-Form);
    ``None`` bei einem Ordnerpfad."""
    found = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url)
    if not found:
        found = re.match(r"^(?:[^@/\s]+@)?([^/:\s]+):(?!//)(.+?)(?:\.git)?/?$", url)
    return (found.group(1), found.group(2)) if found else None


def host_setting(path: Path) -> str | None:
    """Die ausdrücklich gewählte Server-Art (``None``: automatisch aus der Adresse erkennen)."""
    value = _git(_root(path), "config", "--local", "--get", HOST_KEY, check=False)
    return value if value in HOSTS else None


def set_host(path: Path, host: str | None) -> None:
    root = _root(path)
    if host in HOSTS:
        _git(root, "config", "--local", HOST_KEY, host)
    else:
        _git(root, "config", "--local", "--unset-all", HOST_KEY, check=False)


def host_kind(path: Path) -> str:
    """Die Art des Servers: die gewählte oder, solange nichts gewählt ist, die erkannte."""
    return host_setting(path) or detected_host(path)


def detected_host(path: Path) -> str:
    """Die aus der Adresse des Servers erkannte Art, unabhängig von einer Wahl."""
    root = _root(path)
    return detect_host(gitmod.remote_url(root, state(root).remote or "origin"))


def compare_url(url: str, target: str, branch: str) -> str | None:
    """Die Webadresse, unter der man bei GitHub aus dem Branch einen Pull Request öffnet."""
    where = _web_location(url)
    if not where or len(where[0]) == 1:  # Laufwerksbuchstabe wie ``C:\\x``, kein Rechner
        return None
    host, repo = where
    return f"https://{host}/{repo}/compare/{target}...{branch}?expand=1"


def merge_request_branch(root: Path) -> str:
    """Der Branch, auf den diese Person für Merge Requests hochlädt: je Person ein fester Name
    (``sprintforecast/<name>-<Kürzel der Adresse>``), damit ein weiteres Teilen denselben Merge
    Request fortschreibt und zwei Personen mit gleichem Namensanfang nicht kollidieren."""
    email = _git(root, "config", "--get", "user.email", check=False).strip().lower()
    who = email.partition("@")[0] or _git(root, "config", "--get", "user.name", check=False)
    slug = re.sub(r"[^a-z0-9_-]+", "-", who.lower()).strip("-_") or "user"
    tag = hashlib.sha1((email or who).encode("utf-8")).hexdigest()[:6]
    return f"sprintforecast/{slug}-{tag}"


def _push_merge_request(root: Path, current: SyncState, title: str) -> tuple[str, str | None]:
    """Lädt den Stand für eine Prüfung durch andere hoch, je nach Server:

    - GitLab (und unbekannte Server): auf den eigenen Branch, mit Push-Optionen, damit der Server
      den Merge Request anlegt oder fortschreibt (und auf Wunsch von selbst mergt).
    - Forgejo/Gitea/Codeberg: AGit-Ablauf (``refs/for/<Ziel>``), der Pull Request entsteht beim
      Push; klappt das nicht, bleibt der Branch.
    - GitHub: der eigene Branch; die App hat kein Zugriffstoken, sie nennt die Adresse, unter der
      man den Pull Request öffnet.

    Der Branch gehört dieser Person: Ist er nach einem Rebase im Merge Request oder einem
    gemergten Stand anders weitergelaufen, wird er mit ``--force-with-lease`` überschrieben.
    Tags gehen nicht mit (sie zeigen sonst auf Commits, die nie in den Hauptbranch kommen).
    Liefert Branch und, falls bekannt, die Adresse des Merge/Pull Requests."""
    branch = merge_request_branch(root)
    host = host_kind(root)
    ref = f"refs/heads/{branch}"
    remote = current.remote or "origin"
    target = (current.upstream or "").partition("/")[2] or current.branch or "main"
    subject = (title.strip().splitlines() or ["Änderungen"])[0]
    if host == HOST_FORGEJO:
        proc = gitmod._git_result(
            root,
            "push",
            "-o", f"topic={branch}",
            "-o", f"title={subject}",
            "-o", "force-push=true",
            remote,
            f"HEAD:refs/for/{target}",
            network=True,
        )  # fmt: skip
        if proc.returncode == 0:
            found = _PR_URL.search(proc.stderr + proc.stdout)
            return branch, found.group(0).rstrip(".,)") if found else None
    listed = _git(root, "ls-remote", remote, ref, network=True, url=current.url, check=False)
    lease = (
        f"--force-with-lease={ref}:{listed.split()[0]}" if listed else f"--force-with-lease={ref}:"
    )
    options: list[str] = []
    if host in (HOST_GITLAB, HOST_GENERIC):
        options = [
            "-o", "merge_request.create",
            "-o", f"merge_request.target={target}",
            "-o", f"merge_request.title={subject}",
            "-o", "merge_request.remove_source_branch",
            # Neuere GitLab-Versionen kennen auch ``merge_request.auto_merge`` (gleiche Wirkung).
            *(["-o", "merge_request.merge_when_pipeline_succeeds"] if auto_merge(root) else []),
        ]  # fmt: skip
    proc = gitmod._git_result(root, "push", lease, *options, remote, f"HEAD:{ref}", network=True)
    message = proc.stderr.strip() or proc.stdout.strip()
    if proc.returncode != 0 and options and "does not support push options" in message:
        if host == HOST_GITLAB:
            raise GitError(
                t(
                    "Der Server unterstützt keine Push-Optionen, daher kein Teilen über Merge "
                    "Request. Bitte die Einstellung auf der Seite „Datenordner“ ausschalten."
                )
            )
        # Kein GitLab: nur den Branch hochladen, den Pull Request öffnet man auf dem Server.
        proc = gitmod._git_result(root, "push", lease, remote, f"HEAD:{ref}", network=True)
        message = proc.stderr.strip() or proc.stdout.strip()
    if proc.returncode != 0:
        raise gitmod.classify(message, url=current.url)
    found = _PR_URL.search(proc.stderr + proc.stdout)
    if found:
        return branch, found.group(0).rstrip(".,)")
    if host == HOST_GITHUB:
        return branch, compare_url(current.url, target, branch)
    return branch, None


def _push(root: Path, current: SyncState) -> None:
    if current.upstream:
        _git(root, "push", "--follow-tags", network=True, url=current.url)
        return
    # Erster Push: Branch mit dem Server verbinden.
    _git(
        root,
        "push",
        "--follow-tags",
        "-u",
        current.remote or "origin",
        current.branch or "HEAD",
        network=True,
        url=current.url,
    )


def restore_file(path: Path, file: Path) -> None:
    """Stellt eine Datei auf den letzten gespeicherten (committeten) Stand zurück."""
    root = _root(path)
    _git(root, "checkout", "HEAD", "--", str(file.resolve()))
    gitmod.invalidate_status()


def abort_unfinished(path: Path) -> None:
    """Bricht ein unvollständiges Zusammenführen (oder einen Rebase) ab; eigene committete
    Änderungen bleiben unverändert."""
    root = _root(path)
    current = state(path)
    if current.unfinished == "merge" or (current.conflicts and current.unfinished is None):
        _git(root, "merge", "--abort")
    elif current.unfinished == "rebase":
        _git(root, "rebase", "--abort")
    gitmod.invalidate_status()


class Reattached(NamedTuple):
    """Ergebnis von :func:`reattach`: der Branch, auf dem der Datenordner nun steht, und der
    Rettungsbranch, auf dem Gesichertes liegt (``None`` = nichts wurde gesichert). ``commits``:
    Dort liegen die Commits des losen Stands; ``changes``: Dort liegen auch die offenen
    Änderungen im Datenordner (als eigener Commit)."""

    branch: str
    rescue: str | None = None
    commits: bool = False
    changes: bool = False


def _reattach_hint(saved: str | None = None) -> str:
    """Nächster Schritt, wenn der Wechsel zurück auf den Branch an offenen Änderungen scheitert.
    Die im Datenordner sichert :func:`reattach` selbst; es bleiben Änderungen außerhalb davon,
    die die App nicht anfasst. Eine Anleitung zu Einstellungen gibt es nie. ``saved`` ist der
    Rettungsbranch, auf dem die Änderungen im Datenordner schon liegen."""
    text = t(
        "Der Wechsel zurück auf den Branch würde offene Änderungen überschreiben, die "
        "außerhalb des Datenordners liegen. Die App fasst nur den Datenordner an. Der "
        "Ausweg: die Änderungen in Git außerhalb des Datenordners sichern oder verwerfen "
        "(Git-Client oder Terminal; bei Bedarf bei der Betreuung des Rechners nachfragen) "
        "und danach „Zurück auf den Branch“ noch einmal wählen. Die Dateien nennt die "
        "Meldung von Git unter „Technische Meldung“."
    )
    if saved:
        text = _saved_note(saved) + " " + text
    return text


def _saved_note(rescue: str) -> str:
    """Satz, der den Rettungsbranch nennt, auf dem die Änderungen im Datenordner liegen."""
    return t(
        "Die offenen Änderungen im Datenordner sind bereits auf dem Rettungsbranch "
        "{rescue} gesichert.",
        rescue=rescue,
    )


_SAVE_SUBJECT = "Offene Änderungen vor dem Wechsel gesichert"


def _save_open_changes(root: Path, path: Path, rescue: str | None) -> str:
    """Committet die offenen Änderungen im Datenordner auf einem Rettungsbranch und gibt dessen
    Namen zurück. ``rescue`` ist ein vorhandener Rettungsbranch an dieser Stelle (``None`` =
    neu anlegen). Scheitert das Committen (Identität, Tabellenkalkulationen,
    Konfliktmarker …), steht das Repository wieder wie vorher auf dem losen Stand."""
    start = _git(root, "rev-parse", "HEAD")
    index = _git(root, "write-tree")  # die Vormerkung des Benutzers, für den Rückbau
    name = rescue or f"rettung-{time.strftime('%Y%m%d-%H%M%S')}"
    if rescue:
        _git(root, "switch", rescue)
    else:
        _git(root, "switch", "-c", name)
    try:
        gitmod.commit_directory(path, _SAVE_SUBJECT)
    except GitError, OSError:
        try:
            # Den Index exakt wie vorher wiederherstellen (``git add`` hat ihn verändert; der
            # Arbeitsbaum bleibt unberührt) und zurück auf den losen Stand; HEAD bleibt nie auf
            # dem neuen Rettungsbranch stehen.
            _git(root, "read-tree", index, check=False)
            _git(root, "switch", "--detach", start)
            if rescue is None:
                _git(root, "branch", "-D", name)
        finally:
            gitmod.invalidate_status()
        raise
    return name


def _saved_before(root: Path, holders: list[str]) -> bool | None:
    """Steht HEAD auf der Sicherung eines früheren Versuchs von :func:`reattach` (Commit
    „Offene Änderungen vor dem Wechsel gesichert“, nur auf Rettungsbranches)? Dann: Hingen
    davor Commits an keinem Branch (``True``) oder nicht (``False``)? Sonst ``None``."""
    if not holders or not all(b.startswith("rettung-") for b in holders):
        return None
    if _git(root, "log", "-1", "--format=%s", "HEAD", check=False) != _SAVE_SUBJECT:
        return None
    # Über die ganze Kette der Sicherungen zurück (mehrere Versuche): erst der erste andere
    # Commit zeigt, ob der lose Stand eigene Commits hatte.
    depth = 1
    while _git(root, "log", "-1", "--format=%s", f"HEAD~{depth}", check=False) == _SAVE_SUBJECT:
        depth += 1
    parent = _git(
        root, "branch", "--contains", f"HEAD~{depth}", "--format=%(refname:short)", check=False
    )
    return all(b.startswith("rettung-") for b in parent.splitlines() if not b.startswith("("))


def reattach(path: Path) -> Reattached:
    """Geht von „detached HEAD“ zurück auf den Hauptbranch. Hängen Commits an keinem Branch,
    werden sie vorher auf einem Rettungsbranch gesichert, ebenso die offenen Änderungen im
    Datenordner (als eigener Commit dort). Scheitert der Wechsel an Änderungen außerhalb des
    Datenordners, bleibt der Rettungsbranch bestehen und wird beim nächsten Versuch wieder
    genannt."""
    root = _root(path)
    if state(path).branch is not None:
        raise GitError(t("Das Repository steht bereits auf einem Branch."))
    default = _git(root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", check=False)
    candidates = [default.split("/", 1)[-1]] if default else []
    candidates += ["main", "master"]
    local = set(_git(root, "branch", "--format=%(refname:short)").split())
    target = next((c for c in candidates if c in local), None)
    if target is None:
        raise GitError(
            t("Kein Hauptbranch gefunden (main oder master)."),
            "detached",
            t("Bitte einen Git-Client oder ein Terminal verwenden."),
        )
    contains = _git(root, "branch", "--contains", "HEAD", "--format=%(refname:short)", check=False)
    holders = [b for b in contains.splitlines() if not b.startswith("(")]
    rescue = None
    commits = False
    if not holders:
        commits = True
        rescue = f"rettung-{time.strftime('%Y%m%d-%H%M%S')}"
    elif all(b.startswith("rettung-") for b in holders):  # gesichert von einem früheren Versuch
        commits = True
        rescue = holders[0]
    new_changes = bool(gitmod.changes_in(path))
    earlier = _saved_before(root, holders)  # Sicherung aus einem früheren Versuch
    if earlier is not None:
        commits = earlier
    if new_changes:
        # Auf dem Rettungsbranch committen (ein vorhandener an dieser Stelle, sonst ein neuer).
        rescue = _save_open_changes(root, path, rescue if holders else None)
        saved_at = _git(root, "rev-parse", "HEAD")
    elif rescue and not holders:
        _git(root, "branch", rescue)
    changes = new_changes or earlier is not None
    try:
        _git(root, "switch", target)
    except GitError as e:
        if new_changes:  # wieder lose auf der Sicherung: der nächste Versuch findet sie
            _git(root, "switch", "--detach", saved_at)
        gitmod.invalidate_status()
        saved = rescue if changes else None
        if e.kind != "dirty":
            if saved:  # nicht verschweigen, wohin die Änderungen gesichert wurden
                e.hint = _saved_note(saved) + (" " + e.hint if e.hint else "")
            raise
        raise GitError(str(e), "detached", _reattach_hint(saved), e.raw) from e
    gitmod.invalidate_status()
    return Reattached(target, rescue, commits, changes)


def set_identity(name: str, email: str) -> None:
    """Hinterlegt Name und E-Mail-Adresse für Commits (global für den Benutzer)."""
    if not name.strip() or "@" not in email:
        raise GitError(t("Bitte Name und eine gültige E-Mail-Adresse eintragen."))
    _git(Path.home(), "config", "--global", "user.name", name.strip())
    _git(Path.home(), "config", "--global", "user.email", email.strip())


# --- Server (Remote) einrichten ------------------------------------------------------------

# Gültiger Name eines Servers (Remote); nur dann wird er angefasst.
_REMOTE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class RemoteInfo:
    """Der eingerichtete Server eines Datenordners (lokal ermittelt, ohne Netzwerk).

    ``url`` ist die Anzeigefassung (ohne Zugangsdaten), ``has_secret`` sagt, dass in der
    gespeicherten Adresse welche stehen. ``others`` sind weitere Server, die nie verändert
    werden. ``special`` benennt Einstellungen, die die App nicht anfasst: ``multi_url`` (mehrere
    Adressen), ``pushurl`` (eigene Upload-Adresse) oder ``name`` (ungewöhnlicher Name).
    ``branch`` ist der lokale Branch (``None`` = detached HEAD), ``unborn`` sagt, dass es noch
    keinen Commit gibt (ein frisch angelegtes Repository)."""

    root: Path
    name: str | None
    url: str
    has_secret: bool
    others: tuple[str, ...]
    special: str
    branch: str | None
    unborn: bool = False


def remote_info(path: Path) -> RemoteInfo:
    """Server des Datenordners samt Besonderheiten (siehe :class:`RemoteInfo`)."""
    root = _root(path)
    current = state(path)
    name = current.remote
    remotes = _git(root, "remote", check=False).split()
    urls: list[str] = []
    special = ""
    if name is not None:
        if not _REMOTE_NAME.fullmatch(name):
            special = "name"
        else:
            urls = _git(root, "config", "--get-all", f"remote.{name}.url", check=False).splitlines()
            if len(urls) > 1:
                special = "multi_url"
            elif _git(root, "config", "--get-all", f"remote.{name}.pushurl", check=False):
                special = "pushurl"
    return RemoteInfo(
        root=root,
        name=name,
        url=gitmod.public_url(current.url) if name else "",
        has_secret=any(gitmod.has_credentials(u) for u in urls or [current.url]),
        others=tuple(r for r in remotes if r != name),
        special=special,
        branch=current.branch,
        unborn=current.unborn,
    )


_INFO_CACHE: dict[Path, tuple[float, RemoteInfo]] = {}
gitmod.on_invalidate(_INFO_CACHE.clear)


def cached_remote_info(path: Path) -> RemoteInfo:
    """Wie :func:`remote_info`, aber kurz zwischengespeichert (für die Oberfläche, die bei jeder
    Eingabe neu zeichnet); wird mit :func:`sprintforecast.git.invalidate_status` ungültig."""
    key = path.resolve()
    cached = _INFO_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATE_TTL:
        return cached[1]
    info = remote_info(path)
    _INFO_CACHE[key] = (time.monotonic(), info)
    return info


@dataclass(frozen=True)
class RemoteCheck:
    """Ergebnis der Verbindungsprüfung: geprüfte Adresse, Branches des Servers (alle, soweit sie
    ins Limit der Abfrage passen, siehe :func:`~sprintforecast.git.probe_remote`; gekürzt wird
    erst bei der Anzeige) und lokaler Branch (``None`` = detached HEAD). ``unborn``: Der
    Datenordner hat noch keinen Commit."""

    address: gitmod.RemoteAddress
    heads: tuple[str, ...]
    branch: str | None
    unborn: bool = False

    @property
    def empty(self) -> bool:
        """Der Server ist erreichbar, hat aber noch keinen Branch."""
        return not self.heads

    @property
    def branch_missing(self) -> bool:
        """Der Server hat Branches, aber nicht den lokalen: Der erste Upload legt ihn neu an."""
        return bool(self.heads) and self.branch is not None and self.branch not in self.heads


def check_remote(
    path: Path,
    raw: str,
    *,
    allow_insecure: bool = False,
    timeout: float = gitmod.PROBE_TIMEOUT,
) -> RemoteCheck:
    """Prüft eine Server-Adresse (Form und Verbindung, ``git ls-remote``) und schreibt nichts.
    Wirft nur :class:`GitError`."""
    root = _root(path)
    address = gitmod.parse_remote_url(raw, allow_insecure=allow_insecure)
    info = remote_info(root)
    heads = gitmod.probe_remote(root, address, timeout, info.branch)
    return RemoteCheck(address, heads, info.branch, info.unborn)


@dataclass(frozen=True)
class RemoteSaved:
    """Ergebnis von :func:`set_remote`: Name des Servers, Anzeigefassung der Adresse und ob die
    Verbindung geprüft werden konnte (``False`` = ausdrücklich ungeprüft gespeichert)."""

    name: str
    url: str
    verified: bool


def set_remote(
    path: Path,
    raw: str,
    *,
    allow_insecure: bool = False,
    accept_new_branch: bool = False,
    allow_offline: bool = False,
    timeout: float = gitmod.PROBE_TIMEOUT,
) -> RemoteSaved:
    """Setzt die Adresse des Servers (Name wie bisher, sonst ``origin``) – nach erneuter
    Prüfung im Backend, die Oberfläche gilt nicht als vertrauenswürdig. Gespeichert wird nur
    nach bestandener Prüfung; zwei Ausnahmen gelten nur mit ausdrücklicher Bestätigung:
    ``allow_offline`` (Server nicht erreichbar) und ``accept_new_branch`` (der Server hat
    Branches, aber nicht den lokalen). Bei Anmeldung, nicht gefundenem Repository und anderen
    Fehlern wird nie gespeichert. Gesperrt sind ein offenes Zusammenführen, mehrere Adressen,
    eine eigene Upload-Adresse und ein ungewöhnlicher Servername; es wird nichts bereinigt.
    Kein Abruf, keine Anmeldedaten, nichts Globales."""
    root = _root(path)
    address = gitmod.parse_remote_url(raw, allow_insecure=allow_insecure)
    if state(path).unfinished:
        raise GitError(
            t("Solange ein Zusammenführen offen ist, lässt sich der Server nicht ändern."),
            "merge_in_progress",
        )
    info = remote_info(root)
    if info.special:
        raise gitmod.remote_special_error()
    verified = True
    try:
        check = check_remote(root, address.url, allow_insecure=allow_insecure, timeout=timeout)
    except GitError as e:
        if e.kind != "offline" or not allow_offline:
            raise
        verified = False
    else:
        if check.branch_missing and not accept_new_branch:
            raise gitmod.new_branch_error(check.branch or "", check.heads, check.unborn)
    name = info.name or "origin"
    try:
        if info.name is None:
            _git(root, "remote", "add", "--", name, address.url)
        else:
            _git(root, "remote", "set-url", name, "--", address.url)
    finally:
        _FETCHED.pop(root, None)  # der Stand des alten Servers gilt nicht mehr
        gitmod.invalidate_status()
    return RemoteSaved(name, gitmod.public_url(address.url), verified)
