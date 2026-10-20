# SPDX-License-Identifier: EUPL-1.2
"""Small Git helpers for commits and sprint tags."""

from __future__ import annotations

import contextlib
import errno
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, NamedTuple, NoReturn

from sprintforecast import proctree
from sprintforecast.i18n import t

_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*)://")
_NAME_START = re.compile(r"[A-Za-z0-9._~-]+")
_SCP_PASSWORD = re.compile(r"([^@/\\\s:]+):[^@/\\\s]*@")  # user:password@host:path
# The lookbehind instead of ``\b`` is important: an attempt only starts at the beginning of a word
# of scheme characters, not after every dot or hyphen. Otherwise the match runs to the end and back
# from every position on long lines such as "a.a.a.a. …" (quadratic running time).
_URL_IN_TEXT = re.compile(r"(?i)(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://[^\s'\"<>]+")


def public_url(url: str) -> str:
    """Address without credentials and without anything after ``?`` or ``#`` (for display only).
    Never raises and is idempotent. For ssh the user name is kept and the password dropped; local
    paths and every address accepted by :func:`parse_remote_url` stay unchanged."""
    if scheme := _SCHEME.match(url):
        rest = url[scheme.end() :]
        if (at := rest.rfind("@")) >= 0:  # drop everything up to the last “@” (even in the path)
            removed, rest = rest[:at], rest[at + 1 :]
            if scheme.group(1).lower() == "ssh" and (user := _NAME_START.match(removed)):
                rest = f"{user.group(0)}@{rest}"
        cut = [i for i in (rest.find("?"), rest.find("#")) if i >= 0]
        return url[: scheme.end()] + (rest[: min(cut)] if cut else rest)
    if password := _SCP_PASSWORD.match(url):  # user:password@host:path
        return f"{password.group(1)}@{url[password.end() :]}"
    return url


def has_credentials(text: str) -> bool:
    """Does the address contain anything that :func:`public_url` would remove?"""
    return public_url(text.strip()) != text.strip()


def scrub(text: str) -> str:
    """Replaces every address (``scheme://…``) in the text with its display form."""
    return _URL_IN_TEXT.sub(lambda m: public_url(m.group(0)), text)


# Characters that md_code replaces with a space: control characters (Cc), line and paragraph
# separators (Zl, Zp) and the writing-direction control characters. They make text appear
# different from how it is written (reordering, line break). The remaining format characters (Cf)
# stay: the zero-width joiner (U+200D) holds emoji sequences together, the zero-width non-joiner
# (U+200C) is part of the spelling of, for example, Persian and Indian names.
_BIDI_CONTROLS = frozenset(
    "\u061c\u200e\u200f"  # Arabic Letter Mark, Left-to-Right Mark, Right-to-Left Mark
    "\u202a\u202b\u202c\u202d\u202e"  # Embedding, Pop, Override
    "\u2066\u2067\u2068\u2069"  # Isolate
)
_BLANKED_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})


def blank_controls(text: str) -> str:
    """Control characters, line breaks and writing-direction characters become spaces
    (external text for output without Markdown, e.g. the command line)."""
    return "".join(
        " " if c in _BIDI_CONTROLS or unicodedata.category(c) in _BLANKED_CATEGORIES else c
        for c in text
    )


def md_plain(text: str) -> str:
    """Plain text that never acts as Markdown: every ASCII punctuation character gets a
    backslash (as CommonMark requires), so that neither emphasis, links, images nor web
    addresses such as ``www.example.com`` or ``http://…`` have any effect. Control characters
    and line breaks become spaces, as with :func:`md_code`. For messages that contain names
    from files and cannot have each name set as code individually."""
    return re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", blank_controls(text))


def md_code(text: str) -> str:
    """Text as a code span for Markdown. Names and addresses that come from outside (server,
    configuration) never belong in the interface as plain text: emphasis would take effect there
    and web addresses such as ``www.example.com/x`` would become links. Backticks in the text do
    not end the span; control characters, line breaks and writing-direction characters become
    spaces. The remaining invisible characters (emoji sequences, Persian names) stay."""
    text = blank_controls(text)
    if not text:
        return ""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text[0] in "` " or text[-1] in "` " else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def md_code_lines(text: str) -> str:
    """Like :func:`md_code`, but line by line (hard line breaks in Markdown): the multi-line
    output of Git stays readable. Empty lines are dropped, as is whitespace at the end of a
    line (the server pads its ``remote:`` lines with it)."""
    return "  \n".join(md_code(line.rstrip()) for line in text.splitlines() if line.strip())


class GitError(Exception):
    """Error from a Git call. ``kind`` names the type (see :func:`classify`), ``hint`` is the
    next step in everyday language; ``str(error)`` stays the short message. Message and hint
    never contain credentials from an address (:func:`scrub`). ``raw`` means: the message is
    the output of Git and the server (:func:`classify`), not a text of our own. It contains
    names and lines that others determine (``remote:``, hooks, tags, branches)."""

    def __init__(
        self,
        message: str,
        kind: str = "error",
        hint: str = "",
        raw: bool = False,
        hint_md: str = "",
    ) -> None:
        super().__init__(scrub(message))
        self.kind = kind
        self._hint = scrub(hint)
        self.raw = raw
        # The hint for Markdown if it contains names from outside (otherwise ``hint`` itself).
        self._hint_md = scrub(hint_md)

    @property
    def hint(self) -> str:
        return self._hint

    @hint.setter
    def hint(self, value: str) -> None:
        self._hint = value
        self._hint_md = ""  # a hint set later also applies to Markdown

    @property
    def hint_md(self) -> str:
        return self._hint_md or self._hint

    def render(self, quote: Callable[[str], str] = str) -> str:
        """The message for the interface: the output of Git (``raw``) goes through ``quote``
        (e.g. :func:`md_code_lines` for Markdown), our own texts stay as they are."""
        return quote(str(self)) if self.raw else str(self)

    def full(self, quote: Callable[[str], str] = str) -> str:
        """Message including the next step – for places without a heading (``title_for``). For a
        login error the cause comes first: the hint (:func:`auth_help`) starts right with the
        next step, because the heading would otherwise name it. As with :meth:`render`, ``quote``
        applies only to the message, never to cause and hint."""
        cause = f"{title_for(self.kind)}." if self.kind == "auth" and self.hint else ""
        return " ".join(part for part in (cause, self.render(quote), self.hint) if part).strip()


# Spreadsheets must never be committed (they may contain real team data).
FORBIDDEN = re.compile(r"\.xls[xm]?$", re.IGNORECASE)
# Data files that are never committed with conflict markers.
DATA_FILES = re.compile(r"\.ya?ml$", re.IGNORECASE)


# Windows: no console windows for helper processes (otherwise one flashes up on every call).
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

_ROOT_CACHE: dict[Path, tuple[float, Path | None, GitError | None]] = {}
_ROOT_TTL = 30.0


# --- Finding Git -----------------------------------------------------------------------
# Without administrator rights, people often install Git only for their own user account; right
# afterwards it is not yet in the PATH of the running app (or of the launcher). That is why the
# app searches the usual places and then calls Git with its full path. The PATH of the
# subprocesses stays unchanged: Git finds its helper programs (credential manager, ssh)
# through its own program folder.

_FOUND: str | None = None  # most recently found path outside the PATH
_BROKEN: dict[str, float] = {}  # paths that could not be started (since when, monotonic)


def git_locations() -> list[Path]:
    """Places where Git is searched for besides the PATH (in this order)."""
    home = Path.home()
    if sys.platform == "win32":
        places: list[Path] = []
        if local := os.environ.get("LOCALAPPDATA"):
            places.append(Path(local) / "Programs" / "Git" / "cmd" / "git.exe")
        places += [
            home / "scoop" / "shims" / "git.exe",
            home / "scoop" / "apps" / "git" / "current" / "cmd" / "git.exe",
        ]
        for name in ("ProgramFiles", "ProgramFiles(x86)"):
            if base := os.environ.get(name):
                places.append(Path(base) / "Git" / "cmd" / "git.exe")
        return places
    return [
        Path("/opt/homebrew/bin/git"),
        Path("/usr/local/bin/git"),
        Path("/usr/local/git/bin/git"),
        Path("/home/linuxbrew/.linuxbrew/bin/git"),
        home / ".local" / "bin" / "git",
        home / ".nix-profile" / "bin" / "git",
    ]


def find_git() -> str | None:
    """Path to Git: first in the PATH, otherwise in the places from :func:`git_locations`;
    ``None`` if Git is nowhere to be found. A find outside the PATH is remembered (as long as the
    file exists); a failure is not, so that a fresh installation is found immediately."""
    global _FOUND
    broken = _active_broken()
    # An empty or "." entry in the PATH yields a relative hit (the working folder).
    if (found := shutil.which("git")) and os.path.abspath(found) not in broken:
        return os.path.abspath(found)
    if found:  # the first hit is unusable: check further PATH entries
        for folder in os.get_exec_path():
            hit = shutil.which("git", path=folder) if folder else None
            if hit and os.path.abspath(hit) not in broken:
                return os.path.abspath(hit)
    cached = _FOUND  # read in one step: another thread may reset it
    if cached and cached not in broken and os.path.isfile(cached):
        return cached
    _FOUND = None
    for candidate in git_locations():
        path = os.path.abspath(candidate)
        if path in broken:
            continue
        if candidate.is_file() and os.access(candidate, os.X_OK):
            _FOUND = path
            return path
    return None


def reset_git_cache() -> None:
    """Forgets the remembered Git path and those recognised as unusable (for tests and after
    a reinstallation)."""
    global _FOUND
    _FOUND = None
    _BROKEN.clear()


def broken_git() -> str:
    """Path of the Git most recently recognised as unusable (empty if there is none)."""
    return next(reversed(_active_broken()), "")


def _now() -> float:
    return time.monotonic()


def _active_broken() -> dict[str, float]:
    """The paths that still count as unusable (copy in insertion order): a block expires
    after ``_BROKEN_TTL`` seconds, then the path is tried again."""
    now = _now()
    return {path: since for path, since in list(_BROKEN.items()) if now - since < _BROKEN_TTL}


def _mark_broken(executable: str) -> None:
    global _FOUND
    _FOUND = None
    if executable != "git":
        path = os.path.abspath(executable)
        _BROKEN.pop(path, None)  # to the end of the order, with a new deadline
        _BROKEN[path] = _now()


def _started(executable: str) -> None:
    """Git could be started: an earlier block on this path is lifted."""
    if _BROKEN:
        _BROKEN.pop(os.path.abspath(executable), None)


def _not_startable(executable: str) -> GitError:
    """Error for a Git call that could not be started (missing, damaged, no access, wrong
    format, Windows Store alias). The path temporarily counts as unusable: the search then
    picks the next candidate (further PATH entry, fallback location)."""
    _mark_broken(executable)
    return classify("", missing=True, broken="" if executable == "git" else executable)


# Errors at startup that make the program permanently unusable: not found, no access, not a
# valid program. Others (E2BIG: arguments too long, ETXTBSY: file currently being written,
# EMFILE, ENOMEM, EAGAIN …) are temporary or do not concern the program.
_PROGRAM_ERRNOS = frozenset(
    code
    for code in (
        errno.ENOENT,
        errno.EACCES,
        errno.ENOEXEC,
        getattr(errno, "ELIBBAD", None),
        getattr(errno, "EBADARCH", None),
    )
    if code is not None
)
# Windows: not found (2), access denied (5), not a valid program (193), elevation required
# (740), application cannot be run (1260).
_PROGRAM_WINERRORS = frozenset({2, 5, 193, 740, 1260})
_BROKEN_TTL = 60.0
# After a startup failure of the program, a call tries the next candidate at most once
# (no endless retrying).
_START_ATTEMPTS = 2


def _program_failed(error: OSError, executable: str) -> bool:
    """Does the startup error make the program itself permanently unusable? On POSIX every
    ``execve`` error carries the program path as its file name; the kind is therefore decisive."""
    name = None if error.filename is None else os.fspath(error.filename)
    winerror = getattr(error, "winerror", None)
    if winerror in _PROGRAM_WINERRORS and name in (None, executable):
        return True
    return name == executable and error.errno in _PROGRAM_ERRNOS


def _retry_with_next(error: OSError, executable: str) -> bool:
    """Blocks the path if the error concerns the program, and says whether another candidate
    is available with which the call can be tried once more."""
    if not _program_failed(error, executable):
        return False
    _mark_broken(executable)
    other = find_git()
    return other is not None and other != os.path.abspath(executable)


def _start_failed(error: OSError, executable: str) -> NoReturn:
    """Interprets an ``OSError`` when starting Git. If it concerns the program
    (:func:`_program_failed`), the program counts as unusable (:func:`_not_startable`). Other
    errors – working folder missing or not a folder, arguments too long, too many open files,
    out of memory – do not block Git: a missing folder counts as “Git is missing”, as before,
    everything else is passed on unchanged."""
    if _program_failed(error, executable):
        raise _not_startable(executable) from error
    if isinstance(error, FileNotFoundError):
        raise classify("", missing=True) from error
    raise error


def git_command(*args: str) -> list[str]:
    """Command line for a Git call. If Git is missing entirely, it stays at ``git``: the call
    then fails with ``FileNotFoundError``; any ``OSError`` at startup counts for the callers
    as “Git is missing or unusable” (:func:`_not_startable`). If only unusable ones exist,
    their path is tried once more: that way the message names it."""
    return [find_git() or broken_git() or "git", *args]


# Network calls (fetch, push, clone) must never hang forever or ask for a password in the
# background: there is no terminal in which anyone could answer.
NETWORK_TIMEOUT = 90.0


def _env(network: bool, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for Git: English messages (so that they can be recognised) and, for
    network calls, no prompt in the terminal. Credential helpers (credential manager) keep
    running. Trace logs (``GIT_TRACE*``, ``GIT_CURL_VERBOSE``) are removed: they would write
    login headers into the error output. ``extra`` is added last."""
    # Paths are never search patterns: file names with *, ? or [ are meant literally.
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(("GIT_TRACE", "GIT_CURL_VERBOSE"))
    }
    env |= {"LC_ALL": "C", "LANGUAGE": "C", "GIT_LITERAL_PATHSPECS": "1"}
    if network:
        env["GIT_TERMINAL_PROMPT"] = "0"
    return env | (extra or {})


# Running Git calls per folder, so that a hanging sync can be ended from outside
# (:func:`abort_running`). The key is the resolved working folder of the call.
_ACTIVE_LOCK = threading.Lock()
_ACTIVE: dict[Path, dict[subprocess.Popen, int]] = {}  # process → thread that started it
# Folder → threads whose Git call was aborted. Only they feel the abort; it ends with the
# sync (:func:`end_sync`), other threads (display) keep reading.
_ABORTED: dict[Path, set[int]] = {}
_HOLDERS: dict[Path, int] = {}  # folder → thread currently running its sync


def _key(cwd: Path) -> Path:
    return Path(cwd).resolve()


def _aborted_here(cwd: Path) -> bool:
    with _ACTIVE_LOCK:
        return threading.get_ident() in _ABORTED.get(_key(cwd), ())


def _raise_if_aborted(cwd: Path) -> None:
    if _aborted_here(cwd):
        raise GitError(t("The sync was aborted."), "aborted", hint_for("aborted"))


def begin_sync(cwd: Path) -> None:
    """The calling thread now runs the sync of this folder: only its Git calls can be ended
    by :func:`abort_running`."""
    with _ACTIVE_LOCK:
        _HOLDERS[_key(cwd)] = threading.get_ident()
        _ABORTED.pop(_key(cwd), None)


def end_sync(cwd: Path) -> None:
    """The sync is over: holder and abort mark expire (thread numbers are reused and must
    not inherit anything)."""
    with _ACTIVE_LOCK:
        _HOLDERS.pop(_key(cwd), None)
        _ABORTED.pop(_key(cwd), None)


def abort_running(cwd: Path) -> bool:
    """Ends the running Git calls of this folder's sync (including child processes). Its
    thread starts no new call until :func:`end_sync`. ``True`` if a call was running. Files
    such as ``index.lock`` are never removed; an aborted Git reports them as ``locked``."""
    key = _key(cwd)
    with _ACTIVE_LOCK:
        holder = _HOLDERS.get(key)  # readers in other threads (status, log, diff) are left alone
        running = [
            p for p, ident in _ACTIVE.get(key, {}).items() if ident == holder and p.poll() is None
        ]
        if running:
            _ABORTED.setdefault(key, set()).add(holder)
    for process in running:
        proctree.terminate_tree(process, timeout=5)
    return bool(running)


def _run_tracked(
    command: list[str],
    cwd: Path,
    *,
    timeout: float,
    env: dict[str, str],
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Like ``subprocess.run`` with a time limit, but the process can be found by
    :func:`abort_running` and runs in its own process group, so that the whole tree can be ended."""
    key = _key(cwd)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL if stdin_text is None else subprocess.PIPE,
        env=env,
        **{**proctree.popen_options(), **NO_WINDOW},
    )
    ident = threading.get_ident()
    with _ACTIVE_LOCK:
        _ACTIVE.setdefault(key, {})[process] = ident
        late = ident in _ABORTED.get(key, ())  # aborted while the process was starting
    try:
        if late:
            proctree.terminate_tree(process, timeout=5)
        try:
            out, err = process.communicate(stdin_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            proctree.terminate_tree(process)
            # Pipes can be kept open by grandchildren (ssh): do not wait forever
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.communicate(timeout=5)
            raise
        return subprocess.CompletedProcess(command, process.returncode, out, err)
    except BaseException:
        if process.poll() is None:
            proctree.terminate_tree(process)
        raise
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.get(key, {}).pop(process, None)
            if not _ACTIVE.get(key):
                _ACTIVE.pop(key, None)


def _git_result(
    cwd: Path,
    *args: str,
    network: bool = False,
    timeout: float | None = None,
    env_extra: dict[str, str] | None = None,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Runs ``git`` and returns the result including the return code (no error check); only
    “git is missing” and timeouts come as :class:`GitError`."""
    _raise_if_aborted(cwd)
    for attempt in range(_START_ATTEMPTS):
        command = git_command(*args)
        try:
            result = _run_tracked(
                command,
                cwd,
                timeout=timeout or (NETWORK_TIMEOUT if network else 120),
                env=_env(network, env_extra),
                stdin_text=stdin_text,
            )
        except subprocess.TimeoutExpired as e:
            raise classify("", timeout=True) from e
        except OSError as e:
            if attempt + 1 < _START_ATTEMPTS and _retry_with_next(e, command[0]):
                continue
            _start_failed(e, command[0])
        _started(command[0])
        _raise_if_aborted(cwd)  # an ended Git reports nothing useful (code -15)
        return result
    raise AssertionError("unreachable")


def _git(
    cwd: Path,
    *args: str,
    strip: bool = True,
    network: bool = False,
    check: bool = True,
    timeout: float | None = None,
    env_extra: dict[str, str] | None = None,
    url: str = "",
) -> str:
    """Runs ``git``. On errors a :class:`GitError` with the recognised kind and next step;
    with ``check=False`` an empty text is returned instead of an exception. For network calls
    ``url`` is the address of the server: it determines the login help (SSH or https, see
    :func:`classify`)."""
    proc = _git_result(cwd, *args, network=network, timeout=timeout, env_extra=env_extra)
    if proc.returncode != 0:
        if not check:
            return ""
        raise classify(proc.stderr.strip() or proc.stdout.strip(), url=url, cwd=cwd)
    return proc.stdout.strip() if strip else proc.stdout


def split_record(line: str, count: int, sep: str = "\x1f") -> list[str]:
    """Splits a line of ``sep``-separated fields into exactly ``count`` fields. ``_git``
    strips whitespace at the end of the output, and that includes the separator \\x1f: if the
    last field of the last line is empty (e.g. the subject of a commit without text), it is
    missing from the line. Missing fields at the end count as empty."""
    fields = line.split(sep, count - 1)
    return fields + [""] * (count - len(fields))


def split_z(out: str) -> list[str]:
    """Splits NUL-separated Git output (``-z``) into its entries. Only this way do paths with
    umlauts, quotation marks or tabs stay unchanged (without ``-z`` Git puts them in
    quotation marks and escapes special characters)."""
    return [item for item in out.split("\0") if item]


def check_name(name: str) -> str:
    """Checks a tag name that is passed to Git: it must not start with ``-`` (Git would
    otherwise read it as an option), must not be called ``HEAD`` or ``@`` (ambiguous for Git)
    and must not have whitespace at the beginning or end (it is not silently removed, otherwise
    a different name than the one entered would result). Returns the name unchanged."""
    if not name.strip() or name != name.strip() or name.startswith("-") or name in {"HEAD", "@"}:
        raise GitError(t("Invalid tag name: {name}", name=name))
    return name


def valid_tag_name(root: Path, name: str) -> str:
    """Like :func:`check_name`, but additionally asks Git whether the ref name is valid."""
    name = check_name(name)
    if _git_result(root, "check-ref-format", f"refs/tags/{name}").returncode != 0:
        raise GitError(t("Invalid tag name: {name}", name=name))
    return name


def tag_commit(root: Path, name: str) -> str:
    """Full hash of the commit the local tag points to (empty = it does not exist)."""
    return _git(
        root, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{commit}}", check=False
    )


def check_new_tags(root: Path, tags: list[str] | None) -> list[str]:
    """Checks tag names BEFORE a commit: valid and not yet taken locally (an existing tag
    never points to the new commit). On a conflict :class:`GitError`; nothing has been changed
    then. Returns the names without duplicates."""
    names = list(dict.fromkeys(valid_tag_name(root, tag) for tag in tags or []))
    for name in names:
        if existing := tag_commit(root, name):
            raise GitError(
                t(
                    (
                        "The tag {name} already exists on this computer (it points to {rev}). "
                        "Nothing was committed."
                    ),
                    name=name,
                    rev=existing[:7],
                ),
                "tag_exists",
                hint_for("tag_exists"),
            )
    return names


def ensure_tags(root: Path, tags: list[str] | None, message: str) -> tuple[list[str], list[str]]:
    """Sets missing tags on the current state (HEAD), without a new commit – e.g. when an
    earlier attempt wrote the commit but not the tag. Returns (newly set tags, tags that
    already sit on a different state and stay unchanged)."""
    names = list(dict.fromkeys(valid_tag_name(root, tag) for tag in tags or []))
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
    created: list[str] = []
    elsewhere: list[str] = []
    if not head:
        return created, elsewhere
    try:
        for name in names:
            existing = tag_commit(root, name)
            if not existing:
                _git(root, "tag", "-a", "-m", message, "--", name)
                created.append(name)
            elif existing != head:
                elsewhere.append(name)
    finally:
        invalidate_status()
    return created, elsewhere


def _git_bytes(cwd: Path, *args: str) -> bytes:
    """Like :func:`_git`, but returns the raw output (e.g. an archive)."""
    for attempt in range(_START_ATTEMPTS):
        command = git_command(*args)
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                env=_env(False),
                timeout=120,
                **NO_WINDOW,
            )
        except subprocess.TimeoutExpired as e:
            raise classify("", timeout=True) from e
        except OSError as e:
            if attempt + 1 < _START_ATTEMPTS and _retry_with_next(e, command[0]):
                continue
            _start_failed(e, command[0])
        _started(command[0])
        break
    if proc.returncode != 0:
        raise classify(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


# The computer does not know the SSH server yet or its key has changed.
_HOST_KEY = re.compile(r"Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED", re.I)
# The server answers, but the repository does not exist at this address (or it conceals it
# for lack of permission): GitHub, GitLab, Bitbucket, Azure DevOps, Gitea, https 404.
_NOT_FOUND = re.compile(
    r"does not appear to be a git repository|repository '[^']*' (not found|does not exist)|"
    r"returned error: 404|Repository not found|Project not found|remote: Not Found|"
    r"project you were looking for could not be found|repository does not exist|"
    r"TF401019|does not exist or you do not have permission",
    re.I,
)
# The computer does not accept the server's certificate (company certificate, self-issued):
# the server answers, so checking the internet or VPN is of no use.
_CERTIFICATE = re.compile(
    r"SSL certificate problem|certificate verification failed|SEC_E_UNTRUSTED_ROOT|"
    r"SEC_E_CERT_|CRYPT_E_|no alternative certificate subject name",
    re.I,
)

# Git could not write anything in its own file system. A whole line is required that starts
# with the operation and ends with the error (“error: unable to create file x: Permission
# denied”): “Permission denied” alone also appears in “ssh: connect to host … Permission
# denied” (connection blocked), “Load key …: Permission denied” and “remote: Permission
# denied” (server hook) and belongs to offline, auth or denied there. Messages from the
# server start with “remote:” and therefore do not match.
_NOT_WRITABLE = re.compile(
    r"^(?:error: |fatal: )?"
    r"(?:unable to (?:create|open|write)\b|could not (?:lock|create|write|open)\b|"
    r"cannot (?:lock|create|open|mkdir)\b|open\()"
    r"[^\n]*?:\s*(?:Permission denied|Read-only file system)\.?\s*$",
    re.I | re.M,
)

# Detection patterns in the order they are checked (English Git messages, see _env). What the
# server says about the repository (not found, certificate) comes before “offline”: Git appends
# “Could not read from remote repository” to such messages and starts them with “unable to
# access”.
_OFFLINE_REST = (
    r"Could not resolve host|Failed to connect|Connection (timed out|refused|reset)|"
    r"Network is unreachable|unable to access|Operation timed out|Temporary failure in "
    r"name resolution|ssh: connect to host|Connection closed by"
)
_OFFLINE = re.compile(_OFFLINE_REST, re.I)
_BARE_READ = re.compile(r"Could not read from remote repository", re.I)


def _refused_hint() -> str:
    return t(
        "The server did not fulfil the request. Please check the address (typo in the "
        "project name?) and the permission. The message from Git is under “Technical "
        "message”."
    )


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "identity",
        re.compile(
            r"tell me who you are|unable to auto-detect email|empty ident|"
            r"auto-detection is disabled",
            re.I,
        ),
    ),
    ("unsafe_directory", re.compile(r"detected dubious ownership", re.I)),
    # Another program holds the file; Windows often reports this as “Permission denied”.
    (
        "locked",
        re.compile(r"unable to unlink|Device or resource busy|being used by another process", re.I),
    ),
    # No write permission in its own file system (see _NOT_WRITABLE), not just any
    # “Permission denied”: that also appears at SSH login, when connecting and in messages
    # from the server.
    ("not_writable", _NOT_WRITABLE),
    (
        "locked",
        re.compile(r"index\.lock|\.lock'?: File exists|Unable to create '.*\.lock'", re.I),
    ),
    (
        "auth",
        re.compile(
            r"Authentication failed|could not read Username|could not read Password|"
            r"terminal prompts disabled|Permission denied \(publickey|"
            r"Invalid username or password|The requested URL returned error: 40[13]|"
            r"HTTP Basic: Access denied|Support for password authentication was removed|"
            + _HOST_KEY.pattern,
            re.I,
        ),
    ),
    ("not_found", _NOT_FOUND),
    ("certificate", _CERTIFICATE),
    ("offline", _OFFLINE),
    (
        "denied",
        re.compile(
            r"remote rejected|hook declined|protected branch|pre-receive hook|"
            r"Permission to .* denied",
            re.I,
        ),
    ),
    (
        "rejected",
        re.compile(
            r"\[rejected\]|non-fast-forward|failed to push some refs|fetch first|"
            r"Updates were rejected",
            re.I,
        ),
    ),
    (
        "merge_in_progress",
        re.compile(
            r"You have not concluded your merge|MERGE_HEAD exists|"
            r"Exiting because of an unresolved conflict|Pulling is not possible because you "
            r"have unmerged",
            re.I,
        ),
    ),
    ("conflict", re.compile(r"CONFLICT|Automatic merge failed|fix conflicts", re.I)),
    (
        "dirty",
        re.compile(
            r"would be overwritten by (merge|checkout|revert)|"
            r"Please commit your changes or stash them",
            re.I,
        ),
    ),
    ("detached", re.compile(r"You are not currently on a branch|detached HEAD", re.I)),
    (
        "no_upstream",
        re.compile(r"no tracking information|has no upstream branch|no upstream configured", re.I),
    ),
    (
        "no_remote",
        re.compile(
            r"No configured push destination|No remote repository specified|No such remote", re.I
        ),
    ),
]


def _missing_folder(url: str) -> bool:
    """Is the server address a complete folder path (including a network share) whose parent
    folder is missing on this computer? Then the drive is gone (not connected, VPN off, stick
    removed, share unreachable), and Git still reports “does not appear to be a git
    repository”: that is “not reachable”, not a wrong address. If the parent folder is there,
    the server answers and the repository really does not exist there (not found)."""
    if not url or "://" in url:
        return False
    try:
        path = Path(url)
        return path.is_absolute() and not path.parent.exists()
    except OSError, ValueError:
        return True


def remote_url(root: Path, remote: str) -> str:
    """Stored address of the server ``remote`` (empty if there is none): it belongs with the
    network calls, so that :func:`classify` can tell login help and folder-path servers apart."""
    return _git(root, "config", "--get", f"remote.{remote}.url", check=False)


def _without_safe_directory_advice(message: str) -> str:
    """Git's message about a foreign folder ends with the advice to register it as safe with
    ``git config --global --add safe.directory …``. The app never advises such a change (that
    is a matter for whoever looks after the computer), not even in the technical message or the
    command line, where someone would simply copy the command."""
    kept = re.sub(r"\s*To add an exception for this directory.*", "", message, flags=re.I | re.S)
    lines = [line for line in kept.splitlines() if "safe.directory" not in line]
    return "\n".join(lines).strip()


def missing_hint(broken: str = "") -> str:
    """Next step when Git is missing: how it can be installed without administrator rights,
    that the app has to be reopened afterwards and where it searched (list). ``broken`` is
    the path of a Git that was found but could not be started."""
    places = "\n".join(f"- {md_code(str(place))}" for place in git_locations())
    if sys.platform == "win32":
        advice = t(
            "If Git is somewhere else, add the folder containing `git.exe` to your own "
            "user’s PATH – possible without administrator rights via “Edit environment "
            "variables for your account”."
        )
    else:
        advice = t(
            "If Git is somewhere else, it is best to use an installation in your own home "
            "folder (such as Homebrew or Nix) or add the folder containing `git` to your "
            "PATH in the file `~/.profile`."
        )
    parts = []
    if broken:
        parts.append(
            t(
                (
                    "Git was found at {path} but could not be started (damaged or incomplete "
                    "installation)."
                ),
                path=md_code(broken),
            )
        )
    parts += [
        t(
            "Install Git (Windows: https://git-scm.com/download/win – possible without "
            "administrator rights, for your own user account only; macOS: `xcode-select "
            "--install`; Linux: package manager). Then close and reopen the app and the "
            "“Sprint-Forecast” launcher, or sign out and back in once, so that they can "
            "find Git."
        ),
        t("Searched in PATH and in these places:\n{places}", places=places),
        advice,
    ]
    return "\n\n".join(parts)


def classify(
    message: str,
    missing: bool = False,
    timeout: bool = False,
    url: str = "",
    drive_check: bool = True,
    broken: str = "",
    cwd: Path | None = None,
) -> GitError:
    """Turns a Git error message into a :class:`GitError` with kind and next step.
    ``url`` is the address of the server if the message comes from a network call: for a login
    error it selects the matching help (SSH or https, see :func:`auth_help`). If ``url`` is a
    folder path that currently does not exist (disconnected drive), “repository not found”
    counts as ``offline``, except with ``drive_check=False`` (checking a newly entered
    address: there a missing folder is a typo)."""
    if missing:
        return GitError(
            t("git is not installed or not in PATH"),
            "git_missing",
            missing_hint(broken),
        )
    if timeout:
        return GitError(
            t("The server does not answer in time."),
            "offline",
            t("Check the internet connection and VPN and try again later."),
        )
    for kind, pattern in _PATTERNS:
        if pattern.search(message):
            if kind == "unsafe_directory":
                message = _without_safe_directory_advice(message)
            if kind == "not_found" and drive_check and _missing_folder(url):
                kind = "offline"  # network drive disconnected, stick removed: not the address
            hint = auth_help(url, message, cwd) if kind == "auth" else hint_for(kind)
            return GitError(message or kind, kind, hint, raw=bool(message))
    if _BARE_READ.search(message):
        # Git appends this even when the server refuses the repository; on its own it does not
        # prove a missing connection. All other patterns take precedence.
        return GitError(message, "error", _refused_hint(), raw=True)
    return GitError(message or t("Unknown Git error"), "error", raw=bool(message))


def title_for(kind: str) -> str:
    """Short heading for an error kind."""
    titles = {
        "git_missing": t("Git is not installed"),
        "identity": t("Name and email address are missing"),
        "locked": t("A file is locked"),
        "not_writable": t("File or folder not writable"),
        "unsafe_directory": t("Git considers the folder unsafe"),
        "auth": t("Login is missing or was rejected"),
        "offline": t("Server not reachable"),
        "denied": t("Server refuses the upload"),
        "rejected": t("Upload rejected because something new arrived in the meantime"),
        "merge_in_progress": t("Merge is incomplete"),
        "conflict": t("Conflict while merging"),
        "invalid": t("Merged data is not valid"),
        "dirty": t("Open changes outside the data folder"),
        "detached": t("No branch selected (detached HEAD)"),
        "no_upstream": t("Branch is not connected to the server"),
        "no_remote": t("No server set up"),
        "not_repo": t("No Git repository"),
        "not_found": t("Repository not found"),
        "unrelated_histories": t("Server has a different history"),
        "tag_exists": t("Tag name is already taken"),
        "bad_url": t("Invalid address"),
        "secret_in_url": t("Credentials do not belong in the address"),
        "insecure_url": t("Unencrypted connection"),
        "new_branch": t("Branch missing on the server"),
        "remote_special": t("Unusual server setting"),
        "certificate": t("Server certificate not accepted"),
        "folder": t("Folder cannot be used"),
        "nothing_to_share": t("Nothing to share yet"),
        "sync_busy": t("Another sync is still running"),
        "aborted": t("Sync aborted"),
    }
    return titles.get(kind, t("Git error"))


def hint_for(kind: str, url: str = "") -> str:
    """Next step in everyday language for an error kind (empty if there is none)."""
    if kind == "auth":
        return auth_help(url)
    hints = {
        "sync_busy": t(
            "A sync of this data folder has been running for a very long time and may be "
            "stuck (e.g. because of a bad network connection). Wait, or abort the running "
            "sync: your files stay saved locally."
        ),
        "aborted": t(
            "The sync was ended by hand. Your files are saved locally; please share again. "
            "If Git then reports a locked file, follow the hint for it."
        ),
        "identity": t(
            "Git does not know your name yet. Please enter name and email address in the sidebar."
        ),
        "locked": t(
            "A file is locked because another program (Git client, editor, virus scanner, "
            "sync service) is using it. Close other programs and try again. If it stays "
            "that way, a lock file (index.lock in the .git folder) may have been left "
            "behind after a crash: please ask whoever looks after the computer or the "
            "repository before it is removed."
        ),
        "not_writable": t(
            "Git may not write here. Please check that your user account has write "
            "permission in the data folder (including the hidden .git folder inside it), "
            "that the folder is not write-protected and – for a network drive or cloud "
            "folder – is connected and writable. If that does not help, ask whoever looks "
            "after the computer."
        ),
        "unsafe_directory": t(
            "Git refuses to work in this folder because it belongs to a different user "
            "account than the one the app runs under (a protection by Git, common with "
            "network drives, copied folders or after an account change). The app changes "
            "no Git settings. Please ask whoever looks after the computer: they can assign "
            "the folder to your own account or deliberately mark it as safe."
        ),
        "certificate": t(
            "The server responds, but this computer does not accept its security "
            "certificate (often a company certificate or a self-issued one). Please ask IT "
            "to install the certificate on the computer. The app changes no Git settings."
        ),
        "offline": t(
            "The server is not reachable. Your changes stay safely stored locally; check "
            "the internet connection or VPN and choose “Save and share” again later."
        ),
        "denied": t(
            "The server refused the upload, for example because of a protected branch or "
            "missing write permission. Your changes are stored locally; please ask whoever "
            "looks after the repository."
        ),
        "rejected": t(
            "Someone else has uploaded changes in the meantime. Choose “Save and share” "
            "once more; they will be taken over first."
        ),
        "merge_in_progress": t(
            "A merge is incomplete. It can be aborted; your own changes are kept."
        ),
        "conflict": t(
            "Two people changed the same place. On the “Resolve conflicts” page choose "
            "“my” or “other” change for each entry, or abort the merge. Nothing is lost."
        ),
        "invalid": t(
            "The merge was technically possible, but the data is now invalid in content "
            "(see list). Nothing was uploaded. Please correct the values and choose “Save "
            "and share” again – or deliberately “Share anyway”."
        ),
        "dirty": t(
            "There are unsaved changes outside the data folder that collide with the new "
            "changes. Please commit or discard them first."
        ),
        "detached": t(
            "The repository is not on a branch (detached HEAD). Choose “Back to the "
            "branch” in the sidebar; open changes are saved on a rescue branch first."
        ),
        "no_upstream": t(
            "The branch is not connected to the server yet. “Save and share” sets that up "
            "the first time."
        ),
        "no_remote": t(
            "This data folder has no server yet. On the “Data folder” page, under “Server "
            "(remote)”, enter the address of the shared data repository; until then all "
            "changes stay on this computer. Anyone joining an existing team chooses “Clone "
            "repository” there."
        ),
        "not_repo": t(
            "The data folder must be inside a Git repository: create a new one with `git "
            "init` or fetch an existing one with `git clone`. An unpacked ZIP archive "
            "(“Download source code” on GitHub or GitLab) is not a repository because it "
            "lacks the hidden `.git` folder. For an existing team repository, choose "
            "“Clone repository” on the “Data folder” page instead."
        ),
        "not_found": t(
            "The repository was not found or you have no access. Check address and "
            "permission; the address can be changed on the “Data folder” page under "
            "“Server (remote)”."
        ),
        "unrelated_histories": t(
            "The server contains a different history than this data folder – probably the "
            "wrong repository is connected (e.g. a code repository). Nothing was merged "
            "and nothing was uploaded; your changes are safe locally. If it is the wrong "
            "repository, the address can be changed on the “Data folder” page under "
            "“Server (remote)”. If the data repository on the server is the right one, "
            "merging must be confirmed explicitly."
        ),
        "tag_exists": t(
            "Choose a different name or remove the existing tag first. The changes are "
            "unchanged and not yet saved."
        ),
    }
    return hints.get(kind, "")


def unwritable_file_hint() -> str:
    """Next step when the app itself cannot write a file in the data folder (not Git, as with
    ``hint_for("locked")``): the paragraph about the orphaned ``index.lock`` does not fit there.
    On Windows Python says “Permission denied” both for a file held by another program and for
    a write-protected file; the hint names both."""
    return t(
        "The file could not be written. Either another program is using it right now "
        "(editor, spreadsheet program, virus scanner, sync service; on Windows usually the "
        "reason), or it is write-protected or your user account may not change it. Close "
        "other programs, check the write protection and permissions, and choose “Save and "
        "share” again: the interrupted merge is then continued and nothing is lost. If "
        "that does not help, ask whoever looks after the computer."
    )


def auth_help(url: str = "", message: str = "", cwd: Path | None = None) -> str:
    """Login help matching the server address (https or SSH). The text starts right with the
    next step and does not repeat the cause: where the hint sits under the heading
    (``title_for``) (“Login is missing or was rejected”), that already names it; where there is
    none, :meth:`GitError.full` puts it first. If Git (``message``) reports an unknown or
    changed key of the server, no login instructions help, only the fingerprint does."""
    if _HOST_KEY.search(message):
        return t(
            "This computer does not know this SSH server yet (or its key has changed). The "
            "app cannot confirm this: please connect to the server once with an SSH or Git "
            "program and confirm the fingerprint, or use the https address of the "
            "repository. Then try again."
        )
    if url.lower().startswith("ssh://") or _SCP_FORM.match(url):
        return t(
            "This address uses login with an SSH key. To set it up, create a key "
            "(`ssh-keygen -t ed25519`), register the public part (`.pub` file) with the "
            "server (GitHub, GitLab …) under “SSH keys” and make the key available in the "
            "ssh-agent without a passphrase prompt. Then try again."
        )
    steps = t(
        "With https the server usually needs an access token instead of the password "
        "(GitHub: Settings › Developer settings › Personal access tokens; GitLab: access "
        "token with the “write_repository” scope). If you use the GitHub CLI, set up the "
        "login with `gh auth setup-git`; otherwise store the token in the computer's "
        "credential service or enter it as the password in the next login window."
    )
    return f"{steps} {credential_advice(cwd)} " + t("Then try again.")


# Credential services that Git ships or that are widespread; everything else is “custom”.
# Only these names are evaluated, never the wording of the setting (may contain paths).
_SAFE_HELPERS = {
    "manager",
    "manager-core",
    "wincred",
    "osxkeychain",
    "libsecret",
    "gnome-keyring",
    "cache",
    "oauth",
}
_STORE_HELPER = re.compile(r"(?:^|[/\\ ])(?:git-credential-)?store(?:\.exe|\.cmd)?(?:\s|$)")
_PLAIN_TEXT_HELPERS = {"store"}  # stores the token unencrypted in ~/.git-credentials


def credential_helpers(cwd: Path | None = None) -> list[str]:
    """Names of the credential services that Git has set up for this user (read only:
    ``git config``, no change). An empty setting cancels the ones before it, as in Git itself.
    Names outside the known list appear as ``custom``. ``cwd`` is the folder in which Git asks
    (the data folder): that way an entry that exists only in its repository counts too. If
    Git cannot be started, the list is empty."""
    try:
        proc = _git_result(
            cwd or Path.cwd(), "config", "--get-regexp", r"^credential(\..+)?\.helper$", timeout=10
        )
    except GitError, OSError:
        return []
    names: list[str] = []
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(" ")
        value = value.strip()
        if not value:
            if key == "credential.helper":  # only the general entry cancels all
                names.clear()
            continue
        if _STORE_HELPER.search(value):  # also with path, extension or options
            names.append("store")
            continue
        first = "custom" if value.startswith("!") else value.split()[0]
        # A helper with a full path (…/git-credential-store.exe) is recognised by its name too.
        first = first.replace("\\", "/").rsplit("/", 1)[-1]
        first = first.removesuffix(".exe").removesuffix(".cmd").removeprefix("git-credential-")
        names.append(first if first in _SAFE_HELPERS | _PLAIN_TEXT_HELPERS else "custom")
    return names


def credential_advice(cwd: Path | None = None) -> str:
    """Concrete next step for https logins, matching this computer's operating system and
    the configured credential service. The app only reads and changes no Git setting; a
    plain-text store (``store``) is never recommended."""
    helpers = credential_helpers(cwd)
    if any(name in _PLAIN_TEXT_HELPERS for name in helpers):
        return t(
            "Attention: Git stores logins here in plain text (`credential.helper store`, "
            "file `.git-credentials` in the user folder). Better use the computer's "
            "credential service; the app does not change this setting."
        )
    if helpers:
        return t(
            "A credential service is set up. If the login still fails, the stored token "
            "has probably expired or been revoked: delete the old entry in the credential "
            "service and enter the new token on the next attempt."
        )
    prefix = t("No credential service is set up in the Git settings yet.")
    if sys.platform == "win32":
        step = t(
            "Git for Windows ships the Git Credential Manager; `git config --global "
            "credential.helper manager` in a terminal turns it on. On the next attempt, "
            "enter the token as the password in the login window."
        )
    elif sys.platform == "darwin":
        step = t(
            "The Keychain is turned on with `git config --global credential.helper "
            "osxkeychain` in a terminal (the helper belongs to Git from Xcode or "
            "Homebrew). On the next attempt, enter the token as the password."
        )
    else:
        step = t(
            "Either enter `git config --global credential.helper libsecret` in a terminal "
            "(desktop keyring; the helper `git-credential-libsecret` comes with the "
            "distribution's Git package) or use the GitHub CLI with `gh auth setup-git`. "
            "Plain-text storage (`store`) is not a good choice."
        )
    note = t("The app does not change any Git setting itself.")
    return f"{prefix} {step} {note}"


# --- Checking the server address ------------------------------------------------------------------

MAX_URL_LENGTH = 2048
# Transports that Git may use for addresses from the app (no ext::, fd:: or git://).
SAFE_PROTOCOLS = "https:http:ssh:file"
PROBE_TIMEOUT = 30.0
# With http(s), Git aborts if hardly anything arrives for ten seconds (server accepts the
# connection but never answers).
_PROBE_ENV = {
    "GIT_ALLOW_PROTOCOL": SAFE_PROTOCOLS,
    "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
    "GIT_HTTP_LOW_SPEED_TIME": "10",
}
# The connection check reads at most this much output (characters) per stream.
_PROBE_OUTPUT_LIMIT = 64 * 1024

_HOST = r"(?:[A-Za-z0-9][A-Za-z0-9._-]*|\[[0-9A-Fa-f:.]+\])"
_SSH_USER = r"[A-Za-z0-9_][A-Za-z0-9._~-]*"
_HOST_PORT = re.compile(rf"({_HOST})(?::([^:]*))?")
_SCP_FORM = re.compile(rf"{_SSH_USER}@{_HOST}:")
_SCP_ADDRESS = re.compile(rf"({_SSH_USER})@({_HOST}):(\S+)")
_SCP_SECRET = re.compile(r"[^@/\\\s]*:[^@/\\\s]*@")  # u:password@host:path
_HELPER = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*::")  # ext::, fd:: and other remote helpers
_URL_SCHEMES = {"https", "http", "ssh"}
# Only these messages prove that the server is not reachable. “Could not read from remote
# repository” alone does not: Git also appends it when the server refuses the repository.
_UNREACHABLE = re.compile(
    r"Could not resolve|Couldn't resolve|Name or service not known|No such host is known|"
    r"Failed to connect|Couldn't connect|Connection (was )?(timed out|refused|reset|closed)|"
    r"Network is (unreachable|down)|No route to host|timed out|Operation too slow|"
    r"Temporary failure in name resolution|ssh: connect to host|Connection closed by|"
    r"Empty reply from server|Recv failure|Send failure|Timeout was reached",
    re.I,
)


@dataclass(frozen=True)
class RemoteAddress:
    """A checked server address. ``kind``: ``https``, ``http``, ``ssh`` (also the form
    ``user@host:path``) or ``local`` (complete folder path)."""

    url: str
    kind: str


def secret_in_url_error() -> GitError:
    """Error for an address with credentials or additions after ``?`` or ``#`` (without
    repeating the input)."""
    return GitError(
        t(
            "The address contains a user name, a password, a token or parameters "
            "(everything from “?” or “#”). Please enter the plain address only, e.g. "
            "https://server/team/data.git; the login service of the computer handles the "
            "login, and if it is missing the app explains the next step (see Help, "
            "“Login”)."
        ),
        "secret_in_url",
    )


def remote_special_error() -> GitError:
    """Error for a server with several addresses or its own upload address."""
    return GitError(
        t(
            "Several addresses or a separate upload address are set for this server. This "
            "cannot be changed here – please clean it up with a Git program."
        ),
        "remote_special",
    )


class NewBranchError(GitError):
    """The server has branches, but not the local one. ``str(error)`` is plain text; for the
    interface :meth:`render` with :func:`md_code` gives the names as code, because they come
    from the server or from the configuration (see :func:`md_code`)."""

    def __init__(self, branch: str, heads: tuple[str, ...], unborn: bool = False) -> None:
        self.branch, self.heads, self.unborn = branch, heads, unborn
        super().__init__(self.render(), "new_branch")

    def __reduce__(self):  # copyable and picklable despite arguments different from GitError
        return (NewBranchError, (self.branch, self.heads, self.unborn))

    def render(self, quote: Callable[[str], str] = str) -> str:
        """Message (at most five server names mentioned); ``quote`` is applied to each name."""
        names = ", ".join(quote(h) for h in self.heads[:5]) + (", …" if len(self.heads) > 5 else "")
        if self.unborn:
            text = t(
                (
                    "This data folder has no saved data yet, but the server does (available: "
                    "{heads}). The first share would create a new branch “{branch}” there "
                    "without the data of the team arriving. Anyone joining an existing team "
                    "should choose “Clone repository” further down on this page instead."
                ),
                branch=quote(self.branch),
                heads=names,
            )
        else:
            text = t(
                (
                    "The server has no branch “{branch}” (available: {heads}). The first share "
                    "would create it there. That is only right if this really is the data "
                    "repository. Anyone joining an existing team should choose “Clone "
                    "repository” further down on this page instead."
                ),
                branch=quote(self.branch),
                heads=names,
            )
        return scrub(text)


def new_branch_error(branch: str, heads: tuple[str, ...], unborn: bool = False) -> NewBranchError:
    """Error when the server does not have the local branch. ``unborn``: the data folder has
    no commit yet (joining a team is then the common reason)."""
    return NewBranchError(branch, heads, unborn)


class UnrelatedHistoriesError(GitError):
    """The server has a different history than the data folder. ``str(error)`` is plain text;
    for the interface :meth:`render` with :func:`md_code` gives address and branch as code,
    because they come from the server or from the configuration. ``url`` is the display form
    (:func:`public_url`)."""

    def __init__(self, url: str, branch: str) -> None:
        self.url, self.branch = url, branch
        super().__init__(self.render(), "unrelated_histories", hint_for("unrelated_histories"))

    def __reduce__(self):  # copyable and picklable despite arguments different from GitError
        return (UnrelatedHistoriesError, (self.url, self.branch))

    def render(self, quote: Callable[[str], str] = str) -> str:
        """Message; ``quote`` is applied to address and branch."""
        return t(
            (
                "The server ({url}, branch {branch}) contains a different history than this "
                "data folder."
            ),
            url=quote(self.url),
            branch=quote(self.branch),
        )


def nothing_to_share_error() -> GitError:
    """Error when “Save and share” is chosen although the data folder contains nothing saved
    yet (no commit): there would be nothing to upload."""
    return GitError(
        t("The data folder holds no saved data yet, so there is nothing to share."),
        "nothing_to_share",
        t(
            "Create data first (e.g. a team) and save it. Anyone joining an existing team "
            "chooses “Clone repository” on the “Data folder” page."
        ),
    )


def _bad_url(message: str) -> GitError:
    return GitError(message, "bad_url")


def _parse_url_form(text: str, scheme: str, rest: str, allow_insecure: bool) -> RemoteAddress:
    """Address of the form ``scheme://…`` (https, http, ssh); ``text`` has no control characters."""
    if scheme not in _URL_SCHEMES:
        raise _bad_url(
            t(
                "This protocol is not supported. Allowed are https://, ssh://, "
                "git@server:path and complete folder paths."
            )
        )
    if "\\" in text or not all("!" <= c <= "~" for c in text):
        raise _bad_url(t("It contains spaces or invalid characters."))
    if "?" in rest or "#" in rest:
        raise secret_in_url_error()
    authority, _, path = rest.partition("/")
    if "@" in path:  # also catches https://u:12/ss@host/x
        raise secret_in_url_error()
    user, at, host_port = authority.rpartition("@")
    if at:
        if scheme != "ssh" or ":" in user:  # always for http(s); for ssh the password part
            raise secret_in_url_error()
        if not re.fullmatch(_SSH_USER, user):
            raise _bad_url(t("It contains spaces or invalid characters."))
    found = _HOST_PORT.fullmatch(host_port)
    if found is None:
        raise _bad_url(t("The server name is invalid."))
    port = found.group(2)
    if port is not None and not (port.isascii() and port.isdigit() and 0 < int(port) < 65536):
        raise _bad_url(t("The port number is invalid."))
    if not path.strip("/"):
        raise _bad_url(t("The path to the repository is missing, e.g. …/team/sprint-data.git."))
    if scheme == "http" and not allow_insecure:
        raise GitError(
            t(
                "The address starts with http:// – data and login would be sent "
                "unencrypted. Better use https:// or explicitly confirm the unencrypted "
                "connection."
            ),
            "insecure_url",
        )
    return RemoteAddress(f"{scheme}://{rest}", scheme)


def parse_remote_url(raw: str, *, allow_insecure: bool = False) -> RemoteAddress:
    """Checks a server address before it is passed to Git. Allowed are ``https://``,
    ``ssh://``, ``user@host:path``, complete local folder paths and (only with
    ``allow_insecure``) ``http://``. Everything else – ``git://``, ``file://``, relative paths,
    remote helpers (``ext::``), credentials in the address – raises :class:`GitError` with a
    fixed text that never repeats the input."""
    text = raw.strip()
    if not text:
        raise _bad_url(t("Please enter an address."))
    if len(text) > MAX_URL_LENGTH:
        raise _bad_url(t("It is too long."))
    # Control characters, line separators and invisible characters (zero-width, bidi, BOM).
    if any(
        unicodedata.category(c) in {"Zl", "Zp"} or unicodedata.category(c)[0] == "C" for c in text
    ):
        raise _bad_url(t("It contains line breaks or control characters."))
    if text.startswith("-"):  # Git would otherwise read the address as an option
        raise _bad_url(t("It must not start with “-”."))
    if _HELPER.match(text):
        raise _bad_url(t("Special transports (e.g. “ext::”) are not allowed."))
    if scheme := _SCHEME.match(text):
        return _parse_url_form(text, scheme.group(1).lower(), text[scheme.end() :], allow_insecure)
    if Path(text).is_absolute():  # the platform decides what “complete” is
        return RemoteAddress(text, "local")
    if _SCP_SECRET.match(text):
        raise secret_in_url_error()
    if found := _SCP_ADDRESS.fullmatch(text):
        if found.group(3).startswith("-"):
            raise _bad_url(t("It contains spaces or invalid characters."))
        return RemoteAddress(text, "ssh")
    raise _bad_url(
        t(
            "The format is not recognised. Examples: https://server/team/data.git, "
            "git@server:team/data.git or a complete folder path."
        )
    )


class _ProbeRun(NamedTuple):
    """Result of :func:`_probe_run`. ``code``: ``None`` = timeout (the process tree has been
    ended then). ``truncated``: the output was longer than the limit."""

    code: int | None
    out: str
    err: str
    truncated: bool = False


def _read_output(file: IO[bytes]) -> tuple[str, bool]:
    """The first 64 KB of the output as text and whether there was more."""
    file.seek(0)
    data = file.read(_PROBE_OUTPUT_LIMIT + 1)
    text = data[:_PROBE_OUTPUT_LIMIT].decode("utf-8", errors="replace")
    return text, len(data) > _PROBE_OUTPUT_LIMIT


def _probe_run(
    root: Path, args: tuple[str, ...], timeout: float, env_extra: dict[str, str] | None = None
) -> _ProbeRun:
    """Runs ``git`` for the connection check: return code, output and error output
    (each at most 64 KB, see :class:`_ProbeRun`).

    Output goes through temporary files instead of pipes: on Windows a helper process of Git
    (``git-remote-http``) keeps the pipes open even long after the call has ended; reading
    to the end would then hang. On a timeout the whole tree is ended."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        for attempt in range(_START_ATTEMPTS):
            command = git_command(*args)
            try:
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    env=_env(True, _PROBE_ENV | (env_extra or {})),
                    **{**proctree.popen_options(), **NO_WINDOW},
                )
            except OSError as e:
                if attempt + 1 < _START_ATTEMPTS and _retry_with_next(e, command[0]):
                    continue
                _start_failed(e, command[0])
            _started(command[0])
            break
        try:
            code: int | None = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proctree.terminate_tree(process)
            code = None
        text, truncated = _read_output(out)
        return _ProbeRun(code, text, _read_output(err)[0], truncated)


def _heads_of(run: _ProbeRun) -> list[str]:
    """Branch names from the output of ``git ls-remote --heads``. If the output is truncated,
    the last (incomplete) line is dropped."""
    lines = run.out.split("\n")
    if run.truncated:
        lines = lines[:-1]
    prefix = "refs/heads/"
    heads = []
    for line in lines:
        _, _, ref = line.partition("\t")
        if ref.startswith(prefix):
            heads.append(ref[len(prefix) :].strip())
    return heads


def probe_remote(
    root: Path,
    address: RemoteAddress,
    timeout: float = PROBE_TIMEOUT,
    branch: str | None = None,
) -> tuple[str, ...]:
    """Asks the server for its branches (``git ls-remote``, changes nothing) and returns
    their names. An empty server is valid (empty list). Errors come as
    :class:`GitError` with an understandable hint (see :func:`_probe_error`).

    The list is not shortened as long as the output fits the limit (64 KB, around 900 branches).
    With more branches a second request asks specifically for ``branch``: the name is in the
    list exactly when the server has it. Shortening for display is a matter for the interface."""
    run = _probe_run(root, ("ls-remote", "--heads", "--", address.url), timeout)
    if run.code != 0:
        raise _probe_failure(run, address, root)
    heads = _heads_of(run)
    if branch and run.truncated and branch not in heads:
        wanted = _probe_run(
            root, ("ls-remote", "--heads", "--", address.url, f"refs/heads/{branch}"), timeout
        )
        if wanted.code != 0:
            raise _probe_failure(wanted, address, root)
        if branch in _heads_of(wanted):  # the pattern also matches …/refs/heads/NAME
            heads.append(branch)
    return tuple(heads)


def _probe_failure(run: _ProbeRun, address: RemoteAddress, root: Path) -> GitError:
    message = (run.err.strip() or run.out.strip())[:4000]
    return _probe_error(message, address, timed_out=run.code is None, cwd=root)


def _probe_error(
    message: str, address: RemoteAddress, timed_out: bool = False, cwd: Path | None = None
) -> GitError:
    """Turns the error output of the connection check into an understandable error. Kind and
    hint for login, fingerprint, repository not found and certificate come from
    :func:`classify`, as with any other network call. What only the check knows is added here:
    only what proves a network error (:data:`_UNREACHABLE`) or the timeout counts as “server
    not reachable” (``offline``), because only then does the interface offer to save the
    address unchecked. “Could not read from remote repository” alone does not prove that
    (Git also appends it when the server refuses the repository). The text from Git stays in
    ``str(error)`` (appears as “Technical message”); there is always a hint."""
    err = classify(message, timeout=timed_out, url=address.url, drive_check=False, cwd=cwd)
    if timed_out:
        err.hint = _unreachable_hint()
    elif err.kind == "certificate":
        err.hint += " " + t("The address is not saved this way.")
    elif err.kind == "offline" and _UNREACHABLE.search(message):
        err.hint = _unreachable_hint()
    elif err.kind == "offline":  # network error without proven unreachability
        err.kind = "error"
        err.hint = _refused_hint()
    elif err.kind == "error" and _BARE_READ.search(message):
        pass  # classify already explained “Could not read from remote repository” without a reason
    elif err.kind not in {"auth", "not_found", "unsafe_directory", "not_writable", "locked"}:
        err.hint = t(
            "The connection to the server failed. Git’s message is under “Technical message”."
        )
    return err


def _unreachable_hint() -> str:
    return t(
        "The server cannot be reached at this address. Please check the address (typo?), "
        "the internet connection and the VPN. A login window of the computer can delay the "
        "process."
    )


def _locate_root(path: Path) -> tuple[Path | None, GitError | None]:
    """Root of the repository that contains ``path`` and – if there is none although there is
    one – the reason: Git rejects the folder as unsafe (``unsafe_directory``). Any other
    error counts as “no repository”."""
    path = path.resolve()
    cached = _ROOT_CACHE.get(path)
    if cached and time.monotonic() - cached[0] < _ROOT_TTL:
        return cached[1], cached[2]
    start = path
    while not start.exists():
        start = start.parent
    root: Path | None = None
    problem: GitError | None = None
    try:
        root = Path(_git(start if start.is_dir() else start.parent, "rev-parse", "--show-toplevel"))
    except GitError as e:
        problem = e if e.kind == "unsafe_directory" else None
    _ROOT_CACHE[path] = (time.monotonic(), root, problem)
    return root, problem


def repo_root(path: Path) -> Path | None:
    """Root of the Git repository that contains ``path`` – or None. None also means that Git
    rejects the folder as unsafe; :func:`root_problem` then names the reason."""
    return _locate_root(path)[0]


def root_problem(path: Path) -> GitError | None:
    """Reason why :func:`repo_root` returns None although ``path`` is inside a repository
    (kind ``unsafe_directory``); otherwise None."""
    return _locate_root(path)[1]


def require_root(path: Path) -> Path:
    """Like :func:`repo_root`, but raises :class:`GitError` if there is no root: with the
    reason from :func:`root_problem` or as “is not inside a Git repository”."""
    root, problem = _locate_root(path)
    if root is not None:
        return root
    if problem is not None:  # created anew: the stored one accumulated traces on every raise
        raise GitError(str(problem), problem.kind, problem.hint, problem.raw)
    raise GitError(t("{path} is not inside a Git repository", path=path))


def forget_roots(path: Path) -> None:
    """Forgets cached roots for ``path``, below it and above it (after ``git init`` or
    ``git clone`` – otherwise “no repository” would still apply for up to 30 seconds)."""
    path = path.resolve()
    for key in [
        k for k in list(_ROOT_CACHE) if k == path or path in k.parents or k in path.parents
    ]:
        _ROOT_CACHE.pop(key, None)


@dataclass(frozen=True)
class Change:
    """An uncommitted change. ``status``: M modified, D deleted, A new (staged),
    R renamed, ?? new (not staged) – also combined (AM, RM, AD …). For renames and copies
    ``orig`` is the previous path."""

    status: str
    file: str  # relative to the repository root
    orig: str = ""


def changes_in(path: Path) -> list[Change]:
    """Uncommitted changes below ``path``, with the previous path for renames."""
    root = require_root(path)
    # Do not strip: the status column may start with a space (" M file").
    out = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        str(path.resolve()),
        strip=False,
    )
    entries = out.split("\0")
    changes = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, file, orig = entry[:2], entry[3:], ""
        if ("R" in xy or "C" in xy) and i < len(entries):  # the previous path follows
            orig = entries[i]
            i += 1
        changes.append(Change(xy.strip(), file, orig))
    return changes


def pending_changes(path: Path) -> list[tuple[str, str]]:
    """Uncommitted changes below ``path`` as (status, path relative to the root); for
    renames the new path (:func:`changes_in` returns the previous one)."""
    return [(c.status, c.file) for c in changes_in(path)]


_STATUS_CACHE: dict[Path, tuple[float, list[tuple[str, str]]]] = {}
_STATUS_TTL = 5.0


def cached_pending_changes(path: Path) -> list[tuple[str, str]]:
    """Like :func:`pending_changes`, but queried anew only every few seconds (for the
    interface, which redraws on every input). Invalidate with :func:`invalidate_status` after
    saving, committing and switching the data folder."""
    key = path.resolve()
    cached = _STATUS_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATUS_TTL:
        return list(cached[1])
    changes = pending_changes(path)
    _STATUS_CACHE[key] = (time.monotonic(), changes)
    return list(changes)


_INVALIDATE_HOOKS: list[Callable[[], object]] = []


def on_invalidate(hook: Callable[[], object]) -> None:
    """Registers a further cache that is cleared by :func:`invalidate_status`."""
    _INVALIDATE_HOOKS.append(hook)


def invalidate_status() -> None:
    """Discards cached Git states (after saving, commit, sync)."""
    _STATUS_CACHE.clear()
    for key in [k for k, (_, root, _) in list(_ROOT_CACHE.items()) if root is None]:
        _ROOT_CACHE.pop(key, None)  # “no repository” is not permanent
    for hook in _INVALIDATE_HOOKS:
        hook()


def refuse_conflict_markers(root: Path, files: Iterable[Path]) -> None:
    """Refuses to commit data files that still contain conflict markers of an incomplete
    merge: they would be shared and then block editing for everyone else. ``files`` are
    absolute paths; the message names them relative to ``root`` (sprint files and team.yaml are
    called the same in every team)."""
    from sprintforecast.storage import has_conflict_markers  # storage imports this module

    marked: list[str] = []
    for file in files:
        if not DATA_FILES.search(file.name):
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:  # deleted or unreadable: nothing to check
            continue
        if has_conflict_markers(text):
            try:
                name = file.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                name = file.as_posix()
            if name not in marked:
                marked.append(name)
    if marked:
        names = ", ".join(marked)
        raise GitError(
            t(
                (
                    "These files still contain conflict markers (<<<<<<<, =======, >>>>>>>); "
                    "they are not taken over: {files}"
                ),
                files=names,
            ),
            "conflict",
            t(
                (
                    "Affected: {files}. The markers come from an incomplete merge: remove them "
                    "in an editor or, if the page “Resolve conflicts” appears, restore the "
                    "last saved state there."
                ),
                files=names,
            ),
            hint_md=t(
                (
                    "Affected: {files}. The markers come from an incomplete merge: remove them "
                    "in an editor or, if the page “Resolve conflicts” appears, restore the "
                    "last saved state there."
                ),
                files=md_plain(names),
            ),
        )


def refuse_staged_conflict_markers(root: Path) -> None:
    """Like :func:`refuse_conflict_markers` for everything that is currently staged (before a
    commit that does not go through :func:`commit_directory`: completing a merge,
    restoring, reverting)."""
    staged = split_z(_git(root, "diff", "--cached", "--name-only", "-z", strip=False))
    refuse_conflict_markers(root, (root / name for name in staged))


def commit_directory(path: Path, message: str, tags: list[str] | None = None) -> str:
    """Commits all changes below ``path`` (only there) and optionally sets tags."""
    root = require_root(path)
    changes = pending_changes(path)
    if not changes:
        raise GitError(t("No changes to commit"))
    if blocked := [f for _, f in changes if FORBIDDEN.search(f)]:
        raise GitError(
            t(
                (
                    "Spreadsheets are not committed – please remove them or add them to "
                    ".gitignore: {files}"
                ),
                files=", ".join(blocked),
            )
        )
    refuse_conflict_markers(root, (root / f for status, f in changes if "D" not in status))
    names = check_new_tags(root, tags)  # before the commit: on a conflict everything stays open
    target = str(path.resolve())
    try:
        _git(root, "add", "--all", "--", target)
        _git(root, "commit", "-m", message, "--", target)
        for name in names:
            _git(root, "tag", "-a", "-m", message, "--", name)
    finally:
        invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


_NOT_A_REPOSITORY = re.compile(r"not a git repository", re.I)


def _committable(root: Path, paths: list[Path]) -> list[Path]:
    """Without deleted files that Git never knew (e.g. a sprint file that was never committed
    and has since been renamed): ``git add`` would abort on them with “pathspec did not match”."""
    gone = [p for p in paths if not p.exists()]
    if not gone:
        return paths
    listed = _git(root, "ls-files", "--", *(str(p.resolve()) for p in gone))
    tracked = {(root / line).resolve() for line in listed.splitlines() if line}
    return [p for p in paths if p.exists() or p.resolve() in tracked]


def commit(paths: list[Path], message: str, tag: str | None = None) -> str:
    """Commits ``paths`` and optionally sets a tag. Returns the commit hash."""
    cwd = paths[0].resolve().parent
    try:
        root = Path(_git(cwd, "rev-parse", "--show-toplevel"))
    except GitError as e:
        if e.kind == "error" and _NOT_A_REPOSITORY.search(str(e)):
            raise GitError(
                t("{path} is not inside a Git repository", path=cwd),
                "not_repo",
                hint_for("not_repo"),
            ) from e
        raise
    refuse_conflict_markers(root, paths)
    paths = _committable(root, paths)
    names = check_new_tags(root, [tag] if tag else None)
    try:
        _git(root, "add", "--", *(str(p.resolve()) for p in paths))
        _git(root, "commit", "-m", message, "--", *(str(p.resolve()) for p in paths))
        for name in names:
            _git(root, "tag", "-a", "-m", message, "--", name)
    finally:
        invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


GITIGNORE = """\
# Tabellenkalkulationen nie committen – sie können echte Team-Daten enthalten.
*.xlsx
*.xlsm
*.xls
# Übrig gebliebene Zwischendateien des Speicherns.
*.tmp
"""

GITATTRIBUTES = """\
# Datendateien und Berichte immer mit LF, auch bei core.autocrlf (Windows): Sonst schriebe das
# erste Speichern alle Zeilenenden um und erzeugte Rauschen im Verlauf.
*.yaml text eol=lf
*.yml text eol=lf
*.md text eol=lf
"""


def folder_problem(path: Path, error: Exception) -> GitError:
    """A file system error on the folder ``path`` as a :class:`GitError` of kind ``folder`` with
    plain text (paths appear as code, because the message is shown as Markdown)."""
    shown = md_code(str(path))
    if isinstance(error, PermissionError):
        message = t(
            (
                "No access rights for {path} – please choose another folder or adjust the "
                "permissions."
            ),
            path=shown,
        )
    else:
        reason = getattr(error, "strerror", None) or str(error)
        message = t(
            "{path} cannot be created ({reason}) – please check the path.",
            path=shown,
            reason=reason,
        )
    return GitError(message, "folder")


@contextlib.contextmanager
def _folder_access(path: Path) -> Iterator[None]:
    """The target folder ``path`` of a create or clone: a file at this location and
    file system errors (no permission, unusable path, including those reported by Git) come as
    a :class:`GitError` of kind ``folder`` with plain text instead of a raw exception."""
    try:
        if path.is_file():
            raise GitError(
                t(
                    "{path} is a file, not a folder – please specify a folder.",
                    path=md_code(str(path)),
                ),
                "folder",
            )
        yield
    except (OSError, ValueError) as e:  # ValueError: path with NUL character
        raise folder_problem(path, e) from e
    except GitError as e:
        if e.kind == "not_writable" or (e.kind == "error" and "Permission denied" in str(e)):
            raise folder_problem(path, PermissionError()) from e
        raise


def init_data_repository(path: Path, teams_folder: bool = True) -> Path:
    """Creates a data repository (git init, .gitignore, optionally a ``teams`` folder) and
    returns the folder for the teams. A new repository also gets a ``.gitattributes`` in the
    data folder (YAML and reports with LF): it is committed with the data and thus reaches the
    clones too. Existing files and existing repositories stay unchanged: CRLF files might be
    in the index there, which would suddenly count as modified with the setting. A file as the
    target and file system errors come as :class:`GitError` (kind ``folder``), a folder that
    Git rejects as unsafe as kind ``unsafe_directory`` (without writing anything)."""
    with _folder_access(path):
        if (problem := root_problem(path)) is not None:
            # Git rejects the folder because it belongs to a different account: no “git init”
            # there, write nothing into it, but name the reason.
            raise GitError(str(problem), problem.kind, problem.hint, problem.raw)
        path.mkdir(parents=True, exist_ok=True)
        new = repo_root(path) is None
        if new:
            _git(path, "init", "-q")
            forget_roots(path)
        ignore = path / ".gitignore"
        if not ignore.exists():
            ignore.write_text(GITIGNORE, encoding="utf-8")
        data = path
        if teams_folder:
            data = path / "teams"
            data.mkdir(exist_ok=True)
        attributes = data / ".gitattributes"
        if new and not attributes.exists():
            attributes.write_text(GITATTRIBUTES, encoding="utf-8")
        return data


def clone_repository(url: str, path: Path, timeout: float = 300) -> None:
    """Clones an existing data repository to ``path``. The address is checked as with
    :func:`parse_remote_url` (credentials in the address, relative paths, ``git://`` and
    ``file://`` are rejected). Errors (address, target folder, login, server not
    reachable, timeout) come as :class:`GitError` with the next step."""
    # When cloning, http:// is also enough (many company-network repositories offer nothing else).
    address = parse_remote_url(url, allow_insecure=True)
    path = Path(os.path.abspath(path))  # else a relative target would be relative to path.parent
    try:
        with _folder_access(path):
            if path.exists() and any(path.iterdir()):
                raise GitError(
                    t("{path} is not empty", path=md_code(str(path))),
                    "folder",
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            _git(
                path.parent,
                "clone",
                "--",
                address.url,
                str(path),
                network=True,
                timeout=timeout,
                env_extra={"GIT_ALLOW_PROTOCOL": SAFE_PROTOCOLS},
                url=address.url,
            )
    finally:
        with contextlib.suppress(OSError, ValueError):  # an unusable path has already been reported
            forget_roots(path)
