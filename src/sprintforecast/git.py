# SPDX-License-Identifier: EUPL-1.2
"""Kleine Git-Helfer für Commit und Sprint-Tag."""

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
_SCP_PASSWORD = re.compile(r"([^@/\\\s:]+):[^@/\\\s]*@")  # benutzer:kennwort@host:pfad
# Der Rückblick statt ``\b`` ist wichtig: Ein Versuch beginnt nur am Anfang eines Wortes aus
# Schema-Zeichen, nicht hinter jedem Punkt oder Bindestrich. Sonst läuft der Treffer bei langen
# Zeilen wie „a.a.a.a. …“ an jeder Stelle bis zum Ende und zurück (quadratische Laufzeit).
_URL_IN_TEXT = re.compile(r"(?i)(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://[^\s'\"<>]+")


def public_url(url: str) -> str:
    """Adresse ohne Zugangsdaten und ohne Zusätze nach ``?`` oder ``#`` (nur zur Anzeige).
    Wirft nie und ist idempotent. Bei ssh bleibt der Benutzername erhalten, das Kennwort fällt
    weg; lokale Pfade und jede von :func:`parse_remote_url` akzeptierte Adresse bleiben
    unverändert."""
    if scheme := _SCHEME.match(url):
        rest = url[scheme.end() :]
        if (at := rest.rfind("@")) >= 0:  # alles bis zum letzten „@“ (auch im Pfad) fällt weg
            removed, rest = rest[:at], rest[at + 1 :]
            if scheme.group(1).lower() == "ssh" and (user := _NAME_START.match(removed)):
                rest = f"{user.group(0)}@{rest}"
        cut = [i for i in (rest.find("?"), rest.find("#")) if i >= 0]
        return url[: scheme.end()] + (rest[: min(cut)] if cut else rest)
    if password := _SCP_PASSWORD.match(url):  # benutzer:kennwort@host:pfad
        return f"{password.group(1)}@{url[password.end() :]}"
    return url


def has_credentials(text: str) -> bool:
    """Steckt in der Adresse etwas, das :func:`public_url` entfernen würde?"""
    return public_url(text.strip()) != text.strip()


def scrub(text: str) -> str:
    """Ersetzt jede Adresse (``schema://…``) im Text durch ihre Anzeigefassung."""
    return _URL_IN_TEXT.sub(lambda m: public_url(m.group(0)), text)


# Zeichen, die md_code durch ein Leerzeichen ersetzt: Steuerzeichen (Cc), Zeilen- und
# Absatztrenner (Zl, Zp) und die Steuerzeichen der Schreibrichtung. Sie lassen Text anders
# erscheinen, als er geschrieben ist (Umordnen, Zeilenumbruch). Die übrigen Formatzeichen (Cf)
# bleiben: Der Zero-Width-Joiner (U+200D) hält Emoji-Folgen zusammen, der Zero-Width-Non-Joiner
# (U+200C) gehört zur Schreibweise etwa persischer und indischer Namen.
_BIDI_CONTROLS = frozenset(
    "\u061c\u200e\u200f"  # Arabic Letter Mark, Left-to-Right Mark, Right-to-Left Mark
    "\u202a\u202b\u202c\u202d\u202e"  # Embedding, Pop, Override
    "\u2066\u2067\u2068\u2069"  # Isolate
)
_BLANKED_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})


def blank_controls(text: str) -> str:
    """Steuerzeichen, Zeilenumbrüche und Zeichen der Schreibrichtung werden zu Leerzeichen
    (Text von außen für Ausgaben ohne Markdown, z. B. die Kommandozeile)."""
    return "".join(
        " " if c in _BIDI_CONTROLS or unicodedata.category(c) in _BLANKED_CATEGORIES else c
        for c in text
    )


def md_plain(text: str) -> str:
    """Fließtext, der in Markdown nie als Markdown wirkt: Jedes ASCII-Satzzeichen erhält einen
    Backslash (so verlangt es CommonMark), damit weder Auszeichnung, Links, Bilder noch
    Webadressen wie ``www.beispiel.de`` oder ``http://…`` etwas bewirken. Steuerzeichen und
    Zeilenumbrüche werden wie bei :func:`md_code` zu Leerzeichen. Für Meldungen, die Namen aus
    Dateien enthalten und sich im Text nicht einzeln als Code setzen lassen."""
    return re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", blank_controls(text))


def md_code(text: str) -> str:
    """Text als Code-Span für Markdown. Namen und Adressen, die von außen kommen (Server,
    Konfiguration), gehören nie als Fließtext in die Oberfläche: Dort würden Auszeichnungen
    wirken und Webadressen wie ``www.beispiel.de/x`` zu Links. Backticks im Text lassen den
    Span nicht enden; Steuerzeichen, Zeilenumbrüche und Zeichen der Schreibrichtung werden zu
    Leerzeichen. Die übrigen unsichtbaren Zeichen (Emoji-Folgen, persische Namen) bleiben."""
    text = blank_controls(text)
    if not text:
        return ""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text[0] in "` " or text[-1] in "` " else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def md_code_lines(text: str) -> str:
    """Wie :func:`md_code`, aber Zeile für Zeile (harte Zeilenumbrüche in Markdown): Die
    mehrzeilige Ausgabe von Git bleibt lesbar. Leere Zeilen entfallen, ebenso Leerzeichen am
    Zeilenende (der Server füllt seine ``remote:``-Zeilen damit auf)."""
    return "  \n".join(md_code(line.rstrip()) for line in text.splitlines() if line.strip())


class GitError(Exception):
    """Fehler eines Git-Aufrufs. ``kind`` benennt die Art (siehe :func:`classify`), ``hint`` ist
    der nächste Schritt in Alltagssprache; ``str(error)`` bleibt die kurze Meldung. Meldung und
    Hinweis enthalten nie Zugangsdaten aus einer Adresse (:func:`scrub`). ``raw`` heißt: Die
    Meldung ist die Ausgabe von Git und vom Server (:func:`classify`), nicht ein eigener Text.
    Darin stehen Namen und Zeilen, die andere bestimmen (``remote:``, Hooks, Tags, Branches)."""

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
        # Der Hinweis für Markdown, wenn er Namen von außen enthält (sonst ``hint`` selbst).
        self._hint_md = scrub(hint_md)

    @property
    def hint(self) -> str:
        return self._hint

    @hint.setter
    def hint(self, value: str) -> None:
        self._hint = value
        self._hint_md = ""  # ein später gesetzter Hinweis gilt auch für Markdown

    @property
    def hint_md(self) -> str:
        return self._hint_md or self._hint

    def render(self, quote: Callable[[str], str] = str) -> str:
        """Die Meldung für die Oberfläche: Die Ausgabe von Git (``raw``) geht durch ``quote``
        (z. B. :func:`md_code_lines` für Markdown), eigene Texte bleiben, wie sie sind."""
        return quote(str(self)) if self.raw else str(self)

    def full(self, quote: Callable[[str], str] = str) -> str:
        """Meldung samt nächstem Schritt – für Stellen ohne Überschrift (``title_for``). Bei
        einem Anmeldefehler steht die Ursache voran: Der Hinweis (:func:`auth_help`) beginnt
        gleich mit dem nächsten Schritt, weil die Überschrift sie sonst nennt. ``quote`` wirkt
        wie bei :meth:`render` nur auf die Meldung, nie auf Ursache und Hinweis."""
        cause = f"{title_for(self.kind)}." if self.kind == "auth" and self.hint else ""
        return " ".join(part for part in (cause, self.render(quote), self.hint) if part).strip()


# Tabellenkalkulationen dürfen nie committet werden (können echte Team-Daten enthalten).
FORBIDDEN = re.compile(r"\.xls[xm]?$", re.IGNORECASE)
# Datendateien, die nie mit Konfliktmarkierungen committet werden.
DATA_FILES = re.compile(r"\.ya?ml$", re.IGNORECASE)


# Windows: keine Konsolenfenster für Hilfsprozesse (sonst blitzt bei jedem Aufruf eines auf).
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

_ROOT_CACHE: dict[Path, tuple[float, Path | None, GitError | None]] = {}
_ROOT_TTL = 30.0


# --- Git finden -----------------------------------------------------------------------
# Wer keine Administratorrechte hat, installiert Git oft nur für das eigene Benutzerkonto; das
# steht unmittelbar danach noch nicht im PATH der laufenden App (oder des Starters). Darum
# sucht die App an den üblichen Orten nach und ruft Git dann mit vollem Pfad auf. Der PATH der
# Unterprozesse bleibt unverändert: Git findet seine Hilfsprogramme (Anmeldeverwaltung, ssh)
# über den eigenen Programmordner.

_FOUND: str | None = None  # zuletzt gefundener Pfad außerhalb des PATH
_BROKEN: dict[str, float] = {}  # Pfade, die sich nicht starten ließen (seit wann, monotonic)


def git_locations() -> list[Path]:
    """Orte, an denen außer im PATH nach Git gesucht wird (in dieser Reihenfolge)."""
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
    """Pfad zu Git: zuerst im PATH, sonst an den Orten aus :func:`git_locations`; ``None``, wenn
    es Git nirgends gibt. Ein Fund außerhalb des PATH wird gemerkt (solange die Datei besteht);
    ein Misserfolg nicht, damit eine frische Installation sofort gefunden wird."""
    global _FOUND
    broken = _active_broken()
    # Ein leerer oder „.“-Eintrag im PATH liefert einen relativen Treffer (Arbeitsordner).
    if (found := shutil.which("git")) and os.path.abspath(found) not in broken:
        return os.path.abspath(found)
    if found:  # der erste Treffer ist unbrauchbar: weitere Einträge des PATH prüfen
        for folder in os.get_exec_path():
            hit = shutil.which("git", path=folder) if folder else None
            if hit and os.path.abspath(hit) not in broken:
                return os.path.abspath(hit)
    cached = _FOUND  # in einem Schritt gelesen: ein anderer Thread darf zurücksetzen
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
    """Vergisst den gemerkten Git-Pfad und die als unbrauchbar erkannten (für Tests und nach
    einer Neuinstallation)."""
    global _FOUND
    _FOUND = None
    _BROKEN.clear()


def broken_git() -> str:
    """Pfad des zuletzt als unbrauchbar erkannten Git (leer, wenn es keines gibt)."""
    return next(reversed(_active_broken()), "")


def _now() -> float:
    return time.monotonic()


def _active_broken() -> dict[str, float]:
    """Die Pfade, die noch als unbrauchbar gelten (Kopie in Einfügereihenfolge): Eine Sperre
    verfällt nach ``_BROKEN_TTL`` Sekunden, dann wird der Pfad erneut versucht."""
    now = _now()
    return {path: since for path, since in list(_BROKEN.items()) if now - since < _BROKEN_TTL}


def _mark_broken(executable: str) -> None:
    global _FOUND
    _FOUND = None
    if executable != "git":
        path = os.path.abspath(executable)
        _BROKEN.pop(path, None)  # ans Ende der Reihenfolge, mit neuer Frist
        _BROKEN[path] = _now()


def _started(executable: str) -> None:
    """Git ließ sich starten: eine frühere Sperre dieses Pfads entfällt."""
    if _BROKEN:
        _BROKEN.pop(os.path.abspath(executable), None)


def _not_startable(executable: str) -> GitError:
    """Fehler für einen Git-Aufruf, der sich nicht starten ließ (fehlt, defekt, kein Zugriff,
    falsches Format, Windows-Store-Alias). Der Pfad gilt vorübergehend als unbrauchbar: Die Suche
    wählt dann den nächsten Kandidaten (weiterer PATH-Eintrag, Ersatzort)."""
    _mark_broken(executable)
    return classify("", missing=True, broken="" if executable == "git" else executable)


# Fehler beim Start, die das Programm dauerhaft unbrauchbar machen: nicht gefunden, kein Zugriff,
# kein gültiges Programm. Andere (E2BIG: zu lange Argumente, ETXTBSY: Datei gerade geschrieben,
# EMFILE, ENOMEM, EAGAIN …) sind vorübergehend oder betreffen nicht das Programm.
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
# Windows: nicht gefunden (2), Zugriff verweigert (5), kein gültiges Programm (193), Erhöhung
# nötig (740), Anwendung nicht ausführbar (1260).
_PROGRAM_WINERRORS = frozenset({2, 5, 193, 740, 1260})
_BROKEN_TTL = 60.0
# Ein Aufruf versucht es nach einem Startfehler am Programm höchstens einmal mit dem nächsten
# Kandidaten (kein Endlosversuch).
_START_ATTEMPTS = 2


def _program_failed(error: OSError, executable: str) -> bool:
    """Macht der Fehler beim Start das Programm selbst dauerhaft unbrauchbar? Auf POSIX trägt
    jeder ``execve``-Fehler den Programmpfad als Dateinamen; entscheidend ist daher die Art."""
    name = None if error.filename is None else os.fspath(error.filename)
    winerror = getattr(error, "winerror", None)
    if winerror in _PROGRAM_WINERRORS and name in (None, executable):
        return True
    return name == executable and error.errno in _PROGRAM_ERRNOS


def _retry_with_next(error: OSError, executable: str) -> bool:
    """Sperrt den Pfad, wenn der Fehler das Programm betrifft, und sagt, ob ein anderer
    Kandidat zur Verfügung steht, mit dem der Aufruf noch einmal versucht werden kann."""
    if not _program_failed(error, executable):
        return False
    _mark_broken(executable)
    other = find_git()
    return other is not None and other != os.path.abspath(executable)


def _start_failed(error: OSError, executable: str) -> NoReturn:
    """Deutet einen ``OSError`` beim Start von Git. Betrifft er das Programm
    (:func:`_program_failed`), gilt es als unbrauchbar (:func:`_not_startable`). Sonstige
    Fehler – Arbeitsordner fehlt oder ist kein Ordner, zu lange Argumente, zu viele offene
    Dateien, kein Speicher – sperren Git nicht: Ein fehlender Ordner gilt wie bisher als „Git
    fehlt“, alles andere wird unverändert weitergereicht."""
    if _program_failed(error, executable):
        raise _not_startable(executable) from error
    if isinstance(error, FileNotFoundError):
        raise classify("", missing=True) from error
    raise error


def git_command(*args: str) -> list[str]:
    """Befehlszeile für einen Git-Aufruf. Fehlt Git ganz, bleibt es bei ``git``: Der Aufruf
    scheitert dann mit ``FileNotFoundError``; jeder ``OSError`` beim Start gilt den Aufrufern
    als „Git fehlt oder ist unbrauchbar“ (:func:`_not_startable`). Ist nur Unbrauchbares da,
    wird dessen Pfad noch einmal versucht: So nennt die Meldung ihn."""
    return [find_git() or broken_git() or "git", *args]


# Netzwerkaufrufe (fetch, push, clone) dürfen nie ewig hängen oder im Hintergrund nach einem
# Kennwort fragen: Es gibt kein Terminal, in dem man antworten könnte.
NETWORK_TIMEOUT = 90.0


def _env(network: bool, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Umgebung für Git: englische Meldungen (damit sie sich erkennen lassen) und bei
    Netzwerkaufrufen keine Rückfrage im Terminal. Anmeldehelfer (Credential Manager) laufen
    weiter. Ablaufprotokolle (``GIT_TRACE*``, ``GIT_CURL_VERBOSE``) werden entfernt: Sie würden
    Anmelde-Kopfzeilen in die Fehlerausgabe schreiben. ``extra`` kommt zuletzt dazu."""
    # Pfade sind nie Suchmuster: Dateinamen mit *, ? oder [ bleiben wörtlich gemeint.
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(("GIT_TRACE", "GIT_CURL_VERBOSE"))
    }
    env |= {"LC_ALL": "C", "LANGUAGE": "C", "GIT_LITERAL_PATHSPECS": "1"}
    if network:
        env["GIT_TERMINAL_PROMPT"] = "0"
    return env | (extra or {})


# Laufende Git-Aufrufe je Ordner, damit ein hängender Abgleich von außen beendet werden kann
# (:func:`abort_running`). Der Schlüssel ist der aufgelöste Arbeitsordner des Aufrufs.
_ACTIVE_LOCK = threading.Lock()
_ACTIVE: dict[Path, dict[subprocess.Popen, int]] = {}  # Prozess → Faden, der ihn gestartet hat
# Ordner → Fäden, deren Git-Aufruf abgebrochen wurde. Nur sie bekommen den Abbruch zu spüren; er
# endet mit dem Abgleich (:func:`end_sync`), andere Fäden (Anzeige) lesen weiter.
_ABORTED: dict[Path, set[int]] = {}
_HOLDERS: dict[Path, int] = {}  # Ordner → Faden, der gerade dessen Abgleich ausführt


def _key(cwd: Path) -> Path:
    return Path(cwd).resolve()


def _aborted_here(cwd: Path) -> bool:
    with _ACTIVE_LOCK:
        return threading.get_ident() in _ABORTED.get(_key(cwd), ())


def _raise_if_aborted(cwd: Path) -> None:
    if _aborted_here(cwd):
        raise GitError(t("The sync was aborted."), "aborted", hint_for("aborted"))


def begin_sync(cwd: Path) -> None:
    """Der aufrufende Faden führt jetzt den Abgleich dieses Ordners aus: Nur seine Git-Aufrufe
    kann :func:`abort_running` beenden."""
    with _ACTIVE_LOCK:
        _HOLDERS[_key(cwd)] = threading.get_ident()
        _ABORTED.pop(_key(cwd), None)


def end_sync(cwd: Path) -> None:
    """Der Abgleich ist zu Ende: Halter und Abbruchmarke verfallen (Fadennummern werden
    wiederverwendet und dürfen nichts erben)."""
    with _ACTIVE_LOCK:
        _HOLDERS.pop(_key(cwd), None)
        _ABORTED.pop(_key(cwd), None)


def abort_running(cwd: Path) -> bool:
    """Beendet die laufenden Git-Aufrufe des Abgleichs dieses Ordners (samt Kindprozessen). Sein
    Faden startet bis :func:`end_sync` keinen neuen Aufruf. ``True``, wenn ein Aufruf lief. Dateien
    wie ``index.lock`` werden nie entfernt; ein abgebrochenes Git meldet sie als ``locked``."""
    key = _key(cwd)
    with _ACTIVE_LOCK:
        holder = _HOLDERS.get(key)  # Leser anderer Fäden (status, log, diff) bleiben unberührt
        running = [
            p for p, ident in _ACTIVE.get(key, {}).items() if ident == holder and p.poll() is None
        ]
        if running:
            _ABORTED.setdefault(key, set()).add(holder)
    for process in running:
        proctree.terminate_tree(process, timeout=5)
    return bool(running)


def _run_tracked(
    command: list[str], cwd: Path, *, timeout: float, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Wie ``subprocess.run`` mit Zeitlimit, aber der Prozess ist für :func:`abort_running`
    auffindbar und läuft in eigener Prozessgruppe, damit sich der ganze Baum beenden lässt."""
    key = _key(cwd)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        env=env,
        **{**proctree.popen_options(), **NO_WINDOW},
    )
    ident = threading.get_ident()
    with _ACTIVE_LOCK:
        _ACTIVE.setdefault(key, {})[process] = ident
        late = ident in _ABORTED.get(key, ())  # Abbruch, während der Prozess startete
    try:
        if late:
            proctree.terminate_tree(process, timeout=5)
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proctree.terminate_tree(process)
            # Pipes können von Enkeln (ssh) offen gehalten werden: nicht ewig warten
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
) -> subprocess.CompletedProcess[str]:
    """Führt ``git`` aus und liefert das Ergebnis samt Rückgabecode (ohne Fehlerprüfung); nur
    „git fehlt“ und Zeitüberschreitung kommen als :class:`GitError`."""
    _raise_if_aborted(cwd)
    for attempt in range(_START_ATTEMPTS):
        command = git_command(*args)
        try:
            result = _run_tracked(
                command,
                cwd,
                timeout=timeout or (NETWORK_TIMEOUT if network else 120),
                env=_env(network, env_extra),
            )
        except subprocess.TimeoutExpired as e:
            raise classify("", timeout=True) from e
        except OSError as e:
            if attempt + 1 < _START_ATTEMPTS and _retry_with_next(e, command[0]):
                continue
            _start_failed(e, command[0])
        _started(command[0])
        _raise_if_aborted(cwd)  # ein beendetes Git meldet nichts Brauchbares (Code -15)
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
    """Führt ``git`` aus. Bei Fehlern :class:`GitError` mit erkannter Art und nächstem Schritt;
    mit ``check=False`` wird bei Fehlern statt einer Ausnahme ein leerer Text geliefert. ``url``
    ist bei Netzwerkaufrufen die Adresse des Servers: Sie bestimmt die Anmelde-Hilfe (SSH oder
    https, siehe :func:`classify`)."""
    proc = _git_result(cwd, *args, network=network, timeout=timeout, env_extra=env_extra)
    if proc.returncode != 0:
        if not check:
            return ""
        raise classify(proc.stderr.strip() or proc.stdout.strip(), url=url)
    return proc.stdout.strip() if strip else proc.stdout


def split_record(line: str, count: int, sep: str = "\x1f") -> list[str]:
    """Zerlegt eine Zeile mit ``sep`` getrennter Felder in genau ``count`` Felder. ``_git``
    schneidet Leerraum am Ende der Ausgabe ab, und dazu zählt auch das Trennzeichen \\x1f: Ist
    das letzte Feld der letzten Zeile leer (etwa der Betreff eines Commits ohne Text), fehlt es
    in der Zeile. Fehlende Felder am Ende gelten als leer."""
    fields = line.split(sep, count - 1)
    return fields + [""] * (count - len(fields))


def split_z(out: str) -> list[str]:
    """Zerlegt NUL-getrennte Git-Ausgabe (``-z``) in ihre Einträge. Nur so bleiben Pfade mit
    Umlauten, Anführungszeichen oder Tabulatoren unverändert (ohne ``-z`` setzt Git sie in
    Anführungszeichen und maskiert Sonderzeichen)."""
    return [item for item in out.split("\0") if item]


def check_name(name: str) -> str:
    """Prüft einen Tag-Namen, der an Git übergeben wird: er darf nicht mit ``-`` beginnen (Git
    läse ihn sonst als Option), nicht ``HEAD`` oder ``@`` heißen (für Git mehrdeutig) und keine
    Leerzeichen am Anfang oder Ende haben (sie werden nicht still entfernt, sonst entstünde ein
    anderer Name als der eingegebene). Gibt den Namen unverändert zurück."""
    if not name.strip() or name != name.strip() or name.startswith("-") or name in {"HEAD", "@"}:
        raise GitError(t("Invalid tag name: {name}", name=name))
    return name


def valid_tag_name(root: Path, name: str) -> str:
    """Wie :func:`check_name`, prüft aber zusätzlich mit Git, ob der Referenzname gültig ist."""
    name = check_name(name)
    if _git_result(root, "check-ref-format", f"refs/tags/{name}").returncode != 0:
        raise GitError(t("Invalid tag name: {name}", name=name))
    return name


def tag_commit(root: Path, name: str) -> str:
    """Voller Hash des Commits, auf den der lokale Tag zeigt (leer = es gibt ihn nicht)."""
    return _git(
        root, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{commit}}", check=False
    )


def check_new_tags(root: Path, tags: list[str] | None) -> list[str]:
    """Prüft Tag-Namen VOR einem Commit: gültig und lokal noch nicht vergeben (ein vorhandener
    Tag zeigt nie auf den neuen Commit). Bei einem Konflikt :class:`GitError`; dann ist noch
    nichts verändert. Gibt die Namen ohne Doppelte zurück."""
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
    """Setzt fehlende Tags auf den aktuellen Stand (HEAD), ohne neuen Commit – etwa wenn ein
    früherer Versuch den Commit schrieb, den Tag aber nicht. Liefert (neu gesetzte Tags, Tags,
    die schon auf einem anderen Stand liegen und unverändert bleiben)."""
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
    """Wie :func:`_git`, liefert aber die rohe Ausgabe (z. B. ein Archiv)."""
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


# Der Rechner kennt den SSH-Server noch nicht oder sein Schlüssel hat sich geändert.
_HOST_KEY = re.compile(r"Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED", re.I)
# Der Server antwortet, aber es gibt das Repository unter dieser Adresse nicht (oder er
# verschweigt es mangels Berechtigung): GitHub, GitLab, Bitbucket, Azure DevOps, Gitea, https-404.
_NOT_FOUND = re.compile(
    r"does not appear to be a git repository|repository '[^']*' (not found|does not exist)|"
    r"returned error: 404|Repository not found|Project not found|remote: Not Found|"
    r"project you were looking for could not be found|repository does not exist|"
    r"TF401019|does not exist or you do not have permission",
    re.I,
)
# Das Zertifikat des Servers wird vom Rechner nicht anerkannt (Firmenzertifikat, selbst
# ausgestellt): Der Server antwortet, Internet oder VPN zu prüfen nützt nichts.
_CERTIFICATE = re.compile(
    r"SSL certificate problem|certificate verification failed|SEC_E_UNTRUSTED_ROOT|"
    r"SEC_E_CERT_|CRYPT_E_|no alternative certificate subject name",
    re.I,
)

# Git konnte im eigenen Dateisystem nichts schreiben. Verlangt wird eine ganze Zeile, die mit
# dem Vorgang beginnt und auf den Fehler endet („error: unable to create file x: Permission
# denied“): „Permission denied“ allein steht auch bei „ssh: connect to host … Permission
# denied“ (Verbindung gesperrt), „Load key …: Permission denied“ und „remote: Permission
# denied“ (Hook des Servers) und gehört dort zu offline, auth bzw. denied. Meldungen des Servers
# beginnen mit „remote:“ und passen deshalb nicht.
_NOT_WRITABLE = re.compile(
    r"^(?:error: |fatal: )?"
    r"(?:unable to (?:create|open|write)\b|could not (?:lock|create|write|open)\b|"
    r"cannot (?:lock|create|open|mkdir)\b|open\()"
    r"[^\n]*?:\s*(?:Permission denied|Read-only file system)\.?\s*$",
    re.I | re.M,
)

# Erkennungsmuster in der Reihenfolge der Prüfung (englische Git-Meldungen, siehe _env). Was der
# Server über das Repository sagt (nicht gefunden, Zertifikat), steht vor „offline“: Git hängt
# an solche Meldungen „Could not read from remote repository“ an und beginnt sie mit „unable to
# access“.
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
    # Ein anderes Programm hält die Datei; Windows meldet das oft als „Permission denied“.
    (
        "locked",
        re.compile(r"unable to unlink|Device or resource busy|being used by another process", re.I),
    ),
    # Kein Schreibrecht im eigenen Dateisystem (siehe _NOT_WRITABLE), nicht irgendein
    # „Permission denied“: Das steht auch bei der SSH-Anmeldung, beim Verbindungsaufbau und in
    # Meldungen des Servers.
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
    """Ist die Adresse des Servers ein vollständiger Ordnerpfad (auch Netzfreigabe), dessen
    übergeordneter Ordner auf diesem Rechner fehlt? Dann ist das Laufwerk weg (nicht verbunden,
    VPN aus, Stick abgezogen, Freigabe nicht erreichbar), und Git meldet trotzdem „does not
    appear to be a git repository“: Das ist „nicht erreichbar“, keine falsche Adresse. Ist der
    übergeordnete Ordner da, antwortet der Server und das Repository gibt es dort wirklich nicht
    (nicht gefunden)."""
    if not url or "://" in url:
        return False
    try:
        path = Path(url)
        return path.is_absolute() and not path.parent.exists()
    except OSError, ValueError:
        return True


def remote_url(root: Path, remote: str) -> str:
    """Gespeicherte Adresse des Servers ``remote`` (leer, wenn es keine gibt): Sie gehört zu den
    Netzwerkaufrufen, damit :func:`classify` Anmeldehilfe und Ordnerpfad-Server unterscheidet."""
    return _git(root, "config", "--get", f"remote.{remote}.url", check=False)


def _without_safe_directory_advice(message: str) -> str:
    """Gits Meldung zu einem fremden Ordner endet mit dem Rat, ihn per ``git config --global
    --add safe.directory …`` als sicher einzutragen. Die App rät nie zu einer solchen Änderung
    (das ist Sache der Betreuung des Rechners), auch nicht in der technischen Meldung oder der
    Kommandozeile, wo jemand den Befehl einfach kopieren würde."""
    kept = re.sub(r"\s*To add an exception for this directory.*", "", message, flags=re.I | re.S)
    lines = [line for line in kept.splitlines() if "safe.directory" not in line]
    return "\n".join(lines).strip()


def missing_hint(broken: str = "") -> str:
    """Nächster Schritt, wenn Git fehlt: wie es sich ohne Administratorrechte installieren
    lässt, dass die App danach neu zu öffnen ist und wo gesucht wurde (Liste). ``broken`` ist
    der Pfad eines gefundenen Git, das sich nicht starten ließ."""
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
) -> GitError:
    """Macht aus einer Git-Fehlermeldung eine :class:`GitError` mit Art und nächstem Schritt.
    ``url`` ist die Adresse des Servers, wenn die Meldung von einem Netzwerkaufruf stammt: Sie
    wählt bei einem Anmeldefehler die passende Hilfe (SSH oder https, siehe :func:`auth_help`).
    Ist ``url`` ein Ordnerpfad, den es gerade nicht gibt (getrenntes Laufwerk), gilt „Repository
    nicht gefunden“ als ``offline``, außer mit ``drive_check=False`` (die Prüfung einer neu
    eingegebenen Adresse: Dort ist ein fehlender Ordner ein Tippfehler)."""
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
                kind = "offline"  # Netzlaufwerk getrennt, Stick abgezogen: nicht die Adresse
            hint = auth_help(url, message) if kind == "auth" else hint_for(kind)
            return GitError(message or kind, kind, hint, raw=bool(message))
    if _BARE_READ.search(message):
        # Git hängt das auch an, wenn der Server das Repository verweigert; allein belegt es keine
        # fehlende Verbindung. Alle anderen Muster haben Vorrang.
        return GitError(message, "error", _refused_hint(), raw=True)
    return GitError(message or t("Unknown Git error"), "error", raw=bool(message))


def title_for(kind: str) -> str:
    """Kurze Überschrift zu einer Fehlerart."""
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
    """Nächster Schritt in Alltagssprache zu einer Fehlerart (leer, wenn es keinen gibt)."""
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
    """Nächster Schritt, wenn die App selbst eine Datei im Datenordner nicht schreiben kann (nicht
    Git, wie bei ``hint_for("locked")``): Dort passt der Absatz zur verwaisten ``index.lock`` nicht.
    Unter Windows sagt Python „Permission denied“ sowohl für eine von einem anderen Programm
    gehaltene als auch für eine schreibgeschützte Datei; beides nennt der Hinweis."""
    return t(
        "The file could not be written. Either another program is using it right now "
        "(editor, spreadsheet program, virus scanner, sync service; on Windows usually the "
        "reason), or it is write-protected or your user account may not change it. Close "
        "other programs, check the write protection and permissions, and choose “Save and "
        "share” again: the interrupted merge is then continued and nothing is lost. If "
        "that does not help, ask whoever looks after the computer."
    )


def auth_help(url: str = "", message: str = "") -> str:
    """Anmelde-Hilfe passend zur Adresse des Servers (https oder SSH). Der Text beginnt gleich
    mit dem nächsten Schritt und wiederholt die Ursache nicht: Wo der Hinweis unter der
    Überschrift (``title_for``) steht („Anmeldung fehlt oder wurde abgelehnt“), nennt sie schon
    diese; wo es keine gibt, stellt :meth:`GitError.full` sie voran. Meldet Git (``message``)
    einen unbekannten oder geänderten Schlüssel des Servers, hilft keine Anmelde-Anleitung,
    sondern nur der Fingerabdruck."""
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
    return f"{steps} {credential_advice()} " + t("Then try again.")


# Anmeldedienste, die Git mitbringt oder die verbreitet sind; alles andere heißt „custom“.
# Nur diese Namen werden ausgewertet, nie der Wortlaut der Einstellung (kann Pfade enthalten).
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
_PLAIN_TEXT_HELPERS = {"store"}  # legt den Token unverschlüsselt in ~/.git-credentials ab


def credential_helpers() -> list[str]:
    """Namen der Anmeldedienste, die Git für diesen Benutzer eingetragen hat (nur lesend:
    ``git config``, keine Änderung). Eine leere Einstellung hebt die davor stehenden auf, wie
    in Git selbst. Namen außerhalb der bekannten Liste erscheinen als ``custom``. Ist Git nicht
    zu starten, ist die Liste leer."""
    try:
        proc = _git_result(
            Path.cwd(), "config", "--get-regexp", r"^credential(\..+)?\.helper$", timeout=10
        )
    except GitError, OSError:
        return []
    names: list[str] = []
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(" ")
        value = value.strip()
        if not value:
            if key == "credential.helper":  # nur der allgemeine Eintrag hebt alle auf
                names.clear()
            continue
        first = "custom" if value.startswith("!") else value.split()[0]
        first = first.removeprefix("git-credential-")
        names.append(first if first in _SAFE_HELPERS | _PLAIN_TEXT_HELPERS else "custom")
    return names


def credential_advice() -> str:
    """Konkreter nächster Schritt für https-Anmeldungen, passend zum Betriebssystem dieses
    Rechners und zum eingetragenen Anmeldedienst. Die App liest nur und ändert keine
    Git-Einstellung; ein Klartext-Speicher (``store``) wird nie empfohlen."""
    helpers = credential_helpers()
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


# --- Server-Adresse prüfen ------------------------------------------------------------------

MAX_URL_LENGTH = 2048
# Übertragungswege, die Git für Adressen der App benutzen darf (kein ext::, fd:: oder git://).
SAFE_PROTOCOLS = "https:http:ssh:file"
PROBE_TIMEOUT = 30.0
# Bei http(s) bricht Git ab, wenn zehn Sekunden lang kaum etwas ankommt (Server nimmt an,
# antwortet aber nie).
_PROBE_ENV = {
    "GIT_ALLOW_PROTOCOL": SAFE_PROTOCOLS,
    "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
    "GIT_HTTP_LOW_SPEED_TIME": "10",
}
# Höchstens so viel Ausgabe (Zeichen) liest die Verbindungsprüfung je Strom.
_PROBE_OUTPUT_LIMIT = 64 * 1024

_HOST = r"(?:[A-Za-z0-9][A-Za-z0-9._-]*|\[[0-9A-Fa-f:.]+\])"
_SSH_USER = r"[A-Za-z0-9_][A-Za-z0-9._~-]*"
_HOST_PORT = re.compile(rf"({_HOST})(?::([^:]*))?")
_SCP_FORM = re.compile(rf"{_SSH_USER}@{_HOST}:")
_SCP_ADDRESS = re.compile(rf"({_SSH_USER})@({_HOST}):(\S+)")
_SCP_SECRET = re.compile(r"[^@/\\\s]*:[^@/\\\s]*@")  # u:kennwort@host:pfad
_HELPER = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*::")  # ext::, fd:: und andere Remote-Helfer
_URL_SCHEMES = {"https", "http", "ssh"}
# Nur diese Meldungen belegen, dass der Server nicht erreichbar ist. „Could not read from remote
# repository“ allein tut das nicht: Git hängt es auch an, wenn der Server das Repository
# verweigert.
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
    """Eine geprüfte Server-Adresse. ``kind``: ``https``, ``http``, ``ssh`` (auch die Form
    ``benutzer@host:pfad``) oder ``local`` (vollständiger Ordnerpfad)."""

    url: str
    kind: str


def secret_in_url_error() -> GitError:
    """Fehler für eine Adresse mit Zugangsdaten oder Zusätzen nach ``?`` bzw. ``#`` (ohne die
    Eingabe zu wiederholen)."""
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
    """Fehler für einen Server mit mehreren Adressen oder eigener Upload-Adresse."""
    return GitError(
        t(
            "Several addresses or a separate upload address are set for this server. This "
            "cannot be changed here – please clean it up with a Git program."
        ),
        "remote_special",
    )


class NewBranchError(GitError):
    """Der Server hat Branches, aber nicht den lokalen. ``str(error)`` ist Klartext; für die
    Oberfläche liefert :meth:`render` mit :func:`md_code` die Namen als Code, denn sie kommen
    vom Server bzw. aus der Konfiguration (siehe :func:`md_code`)."""

    def __init__(self, branch: str, heads: tuple[str, ...], unborn: bool = False) -> None:
        self.branch, self.heads, self.unborn = branch, heads, unborn
        super().__init__(self.render(), "new_branch")

    def __reduce__(self):  # kopier- und speicherbar trotz anderer Argumente als GitError
        return (NewBranchError, (self.branch, self.heads, self.unborn))

    def render(self, quote: Callable[[str], str] = str) -> str:
        """Meldung (höchstens fünf Servernamen genannt); ``quote`` wird auf jeden Namen
        angewendet."""
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
    """Fehler, wenn der Server den lokalen Branch nicht hat. ``unborn``: Der Datenordner hat
    noch keinen Commit (Beitritt zu einem Team ist dann der häufige Grund)."""
    return NewBranchError(branch, heads, unborn)


class UnrelatedHistoriesError(GitError):
    """Der Server hat eine andere Historie als der Datenordner. ``str(error)`` ist Klartext; für
    die Oberfläche liefert :meth:`render` mit :func:`md_code` Adresse und Branch als Code, denn
    sie kommen vom Server bzw. aus der Konfiguration. ``url`` ist die Anzeigefassung
    (:func:`public_url`)."""

    def __init__(self, url: str, branch: str) -> None:
        self.url, self.branch = url, branch
        super().__init__(self.render(), "unrelated_histories", hint_for("unrelated_histories"))

    def __reduce__(self):  # kopier- und speicherbar trotz anderer Argumente als GitError
        return (UnrelatedHistoriesError, (self.url, self.branch))

    def render(self, quote: Callable[[str], str] = str) -> str:
        """Meldung; ``quote`` wird auf Adresse und Branch angewendet."""
        return t(
            (
                "The server ({url}, branch {branch}) contains a different history than this "
                "data folder."
            ),
            url=quote(self.url),
            branch=quote(self.branch),
        )


def nothing_to_share_error() -> GitError:
    """Fehler, wenn „Speichern und teilen“ gewählt wird, obwohl der Datenordner noch nichts
    Gespeichertes enthält (kein Commit): Es gäbe nichts hochzuladen."""
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
    """Adresse der Form ``schema://…`` (https, http, ssh); ``text`` hat keine Steuerzeichen."""
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
    if "@" in path:  # fängt auch https://u:12/ss@host/x
        raise secret_in_url_error()
    user, at, host_port = authority.rpartition("@")
    if at:
        if scheme != "ssh" or ":" in user:  # bei http(s) immer; bei ssh der Kennwortteil
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
    """Prüft eine Server-Adresse, bevor sie Git übergeben wird. Erlaubt sind ``https://``,
    ``ssh://``, ``benutzer@host:pfad``, vollständige lokale Ordnerpfade und (nur mit
    ``allow_insecure``) ``http://``. Alles andere – ``git://``, ``file://``, relative Pfade,
    Remote-Helfer (``ext::``), Zugangsdaten in der Adresse – wirft :class:`GitError` mit festem
    Text, der die Eingabe nie wiederholt."""
    text = raw.strip()
    if not text:
        raise _bad_url(t("Please enter an address."))
    if len(text) > MAX_URL_LENGTH:
        raise _bad_url(t("It is too long."))
    # Steuerzeichen, Zeilentrenner und unsichtbare Zeichen (Zero-Width, Bidi, BOM).
    if any(
        unicodedata.category(c) in {"Zl", "Zp"} or unicodedata.category(c)[0] == "C" for c in text
    ):
        raise _bad_url(t("It contains line breaks or control characters."))
    if text.startswith("-"):  # Git läse die Adresse sonst als Option
        raise _bad_url(t("It must not start with “-”."))
    if _HELPER.match(text):
        raise _bad_url(t("Special transports (e.g. “ext::”) are not allowed."))
    if scheme := _SCHEME.match(text):
        return _parse_url_form(text, scheme.group(1).lower(), text[scheme.end() :], allow_insecure)
    if Path(text).is_absolute():  # die Plattform entscheidet, was „vollständig“ ist
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
    """Ergebnis von :func:`_probe_run`. ``code``: ``None`` = Zeitüberschreitung (der
    Prozessbaum ist dann beendet). ``truncated``: Die Ausgabe war länger als das Limit."""

    code: int | None
    out: str
    err: str
    truncated: bool = False


def _read_output(file: IO[bytes]) -> tuple[str, bool]:
    """Die ersten 64 KB der Ausgabe als Text und ob es mehr gab."""
    file.seek(0)
    data = file.read(_PROBE_OUTPUT_LIMIT + 1)
    text = data[:_PROBE_OUTPUT_LIMIT].decode("utf-8", errors="replace")
    return text, len(data) > _PROBE_OUTPUT_LIMIT


def _probe_run(
    root: Path, args: tuple[str, ...], timeout: float, env_extra: dict[str, str] | None = None
) -> _ProbeRun:
    """Führt ``git`` für die Verbindungsprüfung aus: Rückgabecode, Ausgabe und Fehlerausgabe
    (je höchstens 64 KB, siehe :class:`_ProbeRun`).

    Ausgabe über Zwischendateien statt Pipes: Unter Windows hält ein Hilfsprozess von Git
    (``git-remote-http``) die Pipes offen, auch wenn der Aufruf längst beendet ist; ein Lesen
    bis zum Ende hinge dann. Bei Zeitüberschreitung wird der ganze Baum beendet."""
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
    """Branch-Namen aus der Ausgabe von ``git ls-remote --heads``. Ist die Ausgabe abgeschnitten,
    fällt die letzte (unvollständige) Zeile weg."""
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
    """Fragt den Server nach seinen Branches (``git ls-remote``, ändert nichts) und liefert
    deren Namen. Ein leerer Server ist gültig (leere Liste). Fehler kommen als
    :class:`GitError` mit verständlichem Hinweis (siehe :func:`_probe_error`).

    Die Liste ist nicht gekürzt, solange die Ausgabe ins Limit passt (64 KB, rund 900 Branches).
    Bei mehr Branches fragt eine zweite Anfrage gezielt nach ``branch``: Der Name steht in der
    Liste, genau wenn der Server ihn hat. Das Kürzen für die Anzeige ist Sache der Oberfläche."""
    run = _probe_run(root, ("ls-remote", "--heads", "--", address.url), timeout)
    if run.code != 0:
        raise _probe_failure(run, address)
    heads = _heads_of(run)
    if branch and run.truncated and branch not in heads:
        wanted = _probe_run(
            root, ("ls-remote", "--heads", "--", address.url, f"refs/heads/{branch}"), timeout
        )
        if wanted.code != 0:
            raise _probe_failure(wanted, address)
        if branch in _heads_of(wanted):  # das Muster passt auch auf …/refs/heads/NAME
            heads.append(branch)
    return tuple(heads)


def _probe_failure(run: _ProbeRun, address: RemoteAddress) -> GitError:
    message = (run.err.strip() or run.out.strip())[:4000]
    return _probe_error(message, address, timed_out=run.code is None)


def _probe_error(message: str, address: RemoteAddress, timed_out: bool = False) -> GitError:
    """Macht aus der Fehlerausgabe der Verbindungsprüfung einen verständlichen Fehler. Art und
    Hinweis zu Anmeldung, Fingerabdruck, nicht gefundenem Repository und Zertifikat kommen von
    :func:`classify`, wie bei jedem anderen Netzwerkaufruf. Hier kommt hinzu, was nur die Prüfung
    weiß: Als „Server nicht erreichbar“ (``offline``) gilt nur, was einen Netzwerkfehler belegt
    (:data:`_UNREACHABLE`) oder die Zeitüberschreitung, denn nur dann bietet die Oberfläche an,
    die Adresse ungeprüft zu speichern. „Could not read from remote repository“ allein belegt
    das nicht (Git hängt es auch an, wenn der Server das Repository verweigert). Der Text von
    Git bleibt in ``str(error)`` (erscheint als „Technische Meldung“); es gibt immer einen
    Hinweis."""
    err = classify(message, timeout=timed_out, url=address.url, drive_check=False)
    if timed_out:
        err.hint = _unreachable_hint()
    elif err.kind == "certificate":
        err.hint += " " + t("The address is not saved this way.")
    elif err.kind == "offline" and _UNREACHABLE.search(message):
        err.hint = _unreachable_hint()
    elif err.kind == "offline":  # Netzwerkfehler ohne belegte Unerreichbarkeit
        err.kind = "error"
        err.hint = _refused_hint()
    elif err.kind == "error" and _BARE_READ.search(message):
        pass  # classify hat „Could not read from remote repository“ ohne Grund schon erklärt
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
    """Wurzel des Repositorys, in dem ``path`` liegt, und – wenn es keine gibt, obwohl dort eins
    liegt – der Grund: Git lehnt den Ordner als unsicher ab (``unsafe_directory``). Jeder andere
    Fehler gilt als „kein Repository“."""
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
    """Wurzel des Git-Repositorys, in dem ``path`` liegt – oder None. None heißt auch, dass Git
    den Ordner als unsicher ablehnt; den Grund nennt dann :func:`root_problem`."""
    return _locate_root(path)[0]


def root_problem(path: Path) -> GitError | None:
    """Grund, warum :func:`repo_root` None liefert, obwohl ``path`` in einem Repository liegt
    (Art ``unsafe_directory``); sonst None."""
    return _locate_root(path)[1]


def require_root(path: Path) -> Path:
    """Wie :func:`repo_root`, wirft aber :class:`GitError`, wenn es keine Wurzel gibt: mit dem
    Grund aus :func:`root_problem` oder als „liegt in keinem Git-Repository“."""
    root, problem = _locate_root(path)
    if root is not None:
        return root
    if problem is not None:  # neu erzeugt: der gespeicherte sammelte bei jedem Auslösen Spuren an
        raise GitError(str(problem), problem.kind, problem.hint, problem.raw)
    raise GitError(t("{path} is not inside a Git repository", path=path))


def forget_roots(path: Path) -> None:
    """Vergisst zwischengespeicherte Wurzeln für ``path``, darunter und darüber (nach
    ``git init`` oder ``git clone`` – sonst gälte „kein Repository“ noch bis zu 30 Sekunden)."""
    path = path.resolve()
    for key in [
        k for k in list(_ROOT_CACHE) if k == path or path in k.parents or k in path.parents
    ]:
        _ROOT_CACHE.pop(key, None)


@dataclass(frozen=True)
class Change:
    """Eine nicht committete Änderung. ``status``: M geändert, D gelöscht, A neu (vorgemerkt),
    R umbenannt, ?? neu (nicht vorgemerkt) – auch kombiniert (AM, RM, AD …). ``orig`` ist bei
    Umbenennungen und Kopien der bisherige Pfad."""

    status: str
    file: str  # relativ zur Repository-Wurzel
    orig: str = ""


def changes_in(path: Path) -> list[Change]:
    """Nicht committete Änderungen unterhalb von ``path``, bei Umbenennungen mit dem bisherigen
    Pfad."""
    root = require_root(path)
    # Nicht strippen: Die Statusspalte beginnt ggf. mit einem Leerzeichen (" M datei").
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
        if ("R" in xy or "C" in xy) and i < len(entries):  # der bisherige Pfad folgt
            orig = entries[i]
            i += 1
        changes.append(Change(xy.strip(), file, orig))
    return changes


def pending_changes(path: Path) -> list[tuple[str, str]]:
    """Nicht committete Änderungen unterhalb von ``path`` als (Status, Pfad relativ zur Wurzel);
    bei Umbenennungen der neue Pfad (den bisherigen liefert :func:`changes_in`)."""
    return [(c.status, c.file) for c in changes_in(path)]


_STATUS_CACHE: dict[Path, tuple[float, list[tuple[str, str]]]] = {}
_STATUS_TTL = 5.0


def cached_pending_changes(path: Path) -> list[tuple[str, str]]:
    """Wie :func:`pending_changes`, aber höchstens alle paar Sekunden neu abgefragt (für die
    Oberfläche, die bei jeder Eingabe neu zeichnet). Nach Speichern, Commit und Wechsel des
    Datenordners mit :func:`invalidate_status` ungültig machen."""
    key = path.resolve()
    cached = _STATUS_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATUS_TTL:
        return list(cached[1])
    changes = pending_changes(path)
    _STATUS_CACHE[key] = (time.monotonic(), changes)
    return list(changes)


_INVALIDATE_HOOKS: list[Callable[[], object]] = []


def on_invalidate(hook: Callable[[], object]) -> None:
    """Meldet einen weiteren Zwischenspeicher an, der mit :func:`invalidate_status` geleert wird."""
    _INVALIDATE_HOOKS.append(hook)


def invalidate_status() -> None:
    """Verwirft zwischengespeicherte Git-Stände (nach Speichern, Commit, Synchronisation)."""
    _STATUS_CACHE.clear()
    for key in [k for k, (_, root, _) in list(_ROOT_CACHE.items()) if root is None]:
        _ROOT_CACHE.pop(key, None)  # „kein Repository“ ist nicht von Dauer
    for hook in _INVALIDATE_HOOKS:
        hook()


def refuse_conflict_markers(root: Path, files: Iterable[Path]) -> None:
    """Verweigert das Committen von Datendateien, in denen noch Konfliktmarkierungen eines
    unvollständigen Zusammenführens stehen: Sie würden geteilt und sperrten dann die Bearbeitung
    bei allen anderen. ``files`` sind absolute Pfade; die Meldung nennt sie relativ zu ``root``
    (Sprintdateien und team.yaml heißen in jedem Team gleich)."""
    from sprintforecast.storage import has_conflict_markers  # storage importiert dieses Modul

    marked: list[str] = []
    for file in files:
        if not DATA_FILES.search(file.name):
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:  # gelöscht oder nicht lesbar: nichts zu prüfen
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
    """Wie :func:`refuse_conflict_markers` für alles, was gerade vorgemerkt ist (vor einem
    Commit, der nicht über :func:`commit_directory` läuft: Zusammenführen abschließen,
    Wiederherstellen, Zurücknehmen)."""
    staged = split_z(_git(root, "diff", "--cached", "--name-only", "-z", strip=False))
    refuse_conflict_markers(root, (root / name for name in staged))


def commit_directory(path: Path, message: str, tags: list[str] | None = None) -> str:
    """Committet alle Änderungen unterhalb von ``path`` (nur dort) und setzt optional Tags."""
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
    names = check_new_tags(root, tags)  # vor dem Commit: bei einem Konflikt bleibt alles offen
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
    """Ohne gelöschte Dateien, die Git nie kannte (z. B. eine nie committete, inzwischen
    umbenannte Sprintdatei): ``git add`` bräche bei ihnen mit „pathspec did not match“ ab."""
    gone = [p for p in paths if not p.exists()]
    if not gone:
        return paths
    listed = _git(root, "ls-files", "--", *(str(p.resolve()) for p in gone))
    tracked = {(root / line).resolve() for line in listed.splitlines() if line}
    return [p for p in paths if p.exists() or p.resolve() in tracked]


def commit(paths: list[Path], message: str, tag: str | None = None) -> str:
    """Committet ``paths`` und setzt optional einen Tag. Gibt den Commit-Hash zurück."""
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
    """Ein Dateisystemfehler am Ordner ``path`` als :class:`GitError` der Art ``folder`` mit
    Klartext (Pfade stehen als Code, denn die Meldung erscheint als Markdown)."""
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
    """Der Zielordner ``path`` eines Anlegens bzw. Klonens: Eine Datei an dieser Stelle und
    Dateisystemfehler (keine Rechte, Pfad unbrauchbar, auch die von Git gemeldeten) kommen als
    :class:`GitError` der Art ``folder`` mit Klartext statt als rohe Ausnahme."""
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
    except (OSError, ValueError) as e:  # ValueError: Pfad mit NUL-Zeichen
        raise folder_problem(path, e) from e
    except GitError as e:
        if e.kind == "not_writable" or (e.kind == "error" and "Permission denied" in str(e)):
            raise folder_problem(path, PermissionError()) from e
        raise


def init_data_repository(path: Path, teams_folder: bool = True) -> Path:
    """Legt ein Daten-Repository an (git init, .gitignore, optional Ordner ``teams``) und liefert
    den Ordner für die Teams. Ein neues Repository bekommt im Datenordner außerdem eine
    ``.gitattributes`` (YAML und Berichte mit LF): Sie wird mit den Daten committet und erreicht
    so auch die Klone. Vorhandene Dateien und bestehende Repositories bleiben unverändert: Dort
    könnten CRLF-Dateien im Index liegen, die mit der Festlegung plötzlich als geändert gelten.
    Eine Datei als Ziel und Dateisystemfehler kommen als :class:`GitError` (Art ``folder``),
    ein Ordner, den Git als unsicher ablehnt, als Art ``unsafe_directory`` (ohne etwas zu
    schreiben)."""
    with _folder_access(path):
        if (problem := root_problem(path)) is not None:
            # Git lehnt den Ordner ab, weil er einem anderen Konto gehört: nicht „git init“ dort,
            # nichts hineinschreiben, sondern den Grund nennen.
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
    """Klont ein bestehendes Daten-Repository nach ``path``. Die Adresse wird wie bei
    :func:`parse_remote_url` geprüft (Zugangsdaten in der Adresse, relative Pfade, ``git://`` und
    ``file://`` werden abgelehnt). Fehler (Adresse, Zielordner, Anmeldung, Server nicht
    erreichbar, Zeitüberschreitung) kommen als :class:`GitError` mit nächstem Schritt."""
    # Beim Klonen reicht auch http:// (viele Repositories im Firmennetz haben nichts anderes).
    address = parse_remote_url(url, allow_insecure=True)
    path = Path(os.path.abspath(path))  # ein relatives Ziel wäre sonst relativ zu path.parent
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
        with contextlib.suppress(
            OSError, ValueError
        ):  # ein unbrauchbarer Pfad wurde schon gemeldet
            forget_roots(path)
