# SPDX-License-Identifier: EUPL-1.2
"""Git finden, auch wenn es nicht im PATH liegt (Installation ohne Administratorrechte)."""

import errno
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from sprintforecast import git as gitmod
from sprintforecast import gitsync
from sprintforecast.git import GitError, find_git, git_command, git_locations, reset_git_cache

# Die echte Funktion; die Testumgebung (conftest) ersetzt gitmod.git_locations durch eine leere.
REAL_LOCATIONS = git_locations
REAL_GIT = shutil.which("git")  # vor jeder PATH-Änderung der Tests

posix = pytest.mark.skipif(sys.platform == "win32", reason="Shell-Skript als Fake-Git")


def fake_git(folder: Path, name: str = "git", version: str = "9.9.9-fake") -> Path:
    """Ein ausführbares „git“, das ``--version`` selbst beantwortet und sonst an das echte
    Git weiterreicht."""
    real = REAL_GIT
    assert real
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "git version {version}"; exit 0; fi\n'
        f'exec "{real}" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def no_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git ist nicht im PATH."""
    leer = tmp_path / "leerer-path"
    leer.mkdir()
    monkeypatch.setenv("PATH", str(leer))


@posix
def test_git_outside_path_is_found_and_used(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    fake = fake_git(tmp_path / "benutzer" / "cmd")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [tmp_path / "gibt-es-nicht", fake])
    assert shutil.which("git") is None
    assert find_git() == str(fake)
    assert gitsync.git_available()
    assert gitmod._git(tmp_path, "--version") == "git version 9.9.9-fake"
    assert gitmod._git_bytes(tmp_path, "--version").strip() == b"git version 9.9.9-fake"
    assert gitmod._probe_run(tmp_path, ("--version",), 10).out.strip() == "git version 9.9.9-fake"
    assert git_command("status")[:2] == [str(fake), "status"]


@posix
def test_path_wins_over_fallback_locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    im_path = fake_git(tmp_path / "im-path", version="1.1.1-path")
    fallback = fake_git(tmp_path / "ersatz", version="2.2.2-fallback")
    monkeypatch.setenv("PATH", str(im_path.parent))
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fallback])
    assert find_git() == str(im_path)
    assert gitmod._git(tmp_path, "--version") == "git version 1.1.1-path"


@posix
def test_first_existing_location_wins(tmp_path: Path, no_path: None, monkeypatch):
    first = fake_git(tmp_path / "a")
    second = fake_git(tmp_path / "b")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [first, second])
    assert find_git() == str(first)


@posix
def test_found_path_is_remembered_and_cache_can_be_reset(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    assert find_git() == str(fake)
    monkeypatch.setattr(gitmod, "git_locations", lambda: [])  # Orte sind nicht mehr bekannt …
    assert find_git() == str(fake)  # … der gemerkte Pfad gilt, solange die Datei besteht
    reset_git_cache()
    assert find_git() is None
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    assert find_git() == str(fake)
    fake.unlink()  # deinstalliert: der gemerkte Pfad verfällt von selbst
    assert find_git() is None


@posix
def test_fresh_installation_is_found_without_restart(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    """Ein Misserfolg wird nicht gemerkt: Git, das erst nach dem ersten Suchen installiert
    wird, findet die App beim nächsten Aufruf."""
    later = tmp_path / "spaeter" / "git"
    monkeypatch.setattr(gitmod, "git_locations", lambda: [later])
    assert find_git() is None and not gitsync.git_available()
    fake_git(later.parent)
    assert find_git() == str(later) and gitsync.git_available()


@posix
def test_a_directory_or_non_executable_file_is_no_git(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    folder = tmp_path / "ordner"
    folder.mkdir()
    plain = tmp_path / "text"
    plain.write_text("kein Programm", encoding="utf-8")
    plain.chmod(0o644)
    monkeypatch.setattr(gitmod, "git_locations", lambda: [folder, plain])
    assert find_git() is None


def test_missing_git_message_names_the_searched_places(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    places = [tmp_path / "eins" / "git", tmp_path / "zwei" / "git"]
    monkeypatch.setattr(gitmod, "git_locations", lambda: places)
    with pytest.raises(GitError) as raised:
        gitmod._git(tmp_path, "--version")
    error = raised.value
    assert error.kind == "git_missing"
    assert str(error) == "git ist nicht installiert oder nicht im PATH"
    assert "PATH" in error.hint
    assert all(str(place) in error.hint for place in places)
    assert "neu öffnen" in error.hint and "Sprint-Forecast" in error.hint
    assert "ohne Administratorrechte" in error.hint
    assert "IT " not in error.hint and "Betreuung" not in error.hint
    assert "winget" not in error.hint


def test_default_locations_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert REAL_LOCATIONS() == [
        tmp_path / "lokal" / "Programs" / "Git" / "cmd" / "git.exe",
        tmp_path / "home" / "scoop" / "shims" / "git.exe",
        tmp_path / "home" / "scoop" / "apps" / "git" / "current" / "cmd" / "git.exe",
        tmp_path / "pf" / "Git" / "cmd" / "git.exe",
        tmp_path / "pf86" / "Git" / "cmd" / "git.exe",
    ]


def test_default_locations_on_windows_without_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sys, "platform", "win32")
    for name in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert REAL_LOCATIONS() == [
        tmp_path / "scoop" / "shims" / "git.exe",
        tmp_path / "scoop" / "apps" / "git" / "current" / "cmd" / "git.exe",
    ]


def test_default_locations_on_unix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert REAL_LOCATIONS() == [
        Path("/opt/homebrew/bin/git"),
        Path("/usr/local/bin/git"),
        Path("/usr/local/git/bin/git"),
        Path("/home/linuxbrew/.linuxbrew/bin/git"),
        tmp_path / ".local" / "bin" / "git",
        tmp_path / ".nix-profile" / "bin" / "git",
    ]


@posix
def test_relative_path_hit_is_made_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ein leerer oder „.“-Eintrag im PATH liefert einen relativen Treffer (Arbeitsordner)."""
    fake_git(tmp_path / "hier")
    monkeypatch.chdir(tmp_path / "hier")
    monkeypatch.setattr(shutil, "which", lambda name: "git")
    assert find_git() == str(tmp_path / "hier" / "git")
    assert git_command("status")[0] == str(tmp_path / "hier" / "git")


@posix
def test_cache_read_survives_a_reset_by_another_thread(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    assert find_git() == str(fake)
    real_isfile = gitmod.os.path.isfile

    def isfile_after_reset(path):
        reset_git_cache()  # ein anderer Thread setzt zurück, mitten in der Prüfung
        return real_isfile(path)

    monkeypatch.setattr(gitmod.os.path, "isfile", isfile_after_reset)
    assert find_git() == str(fake)


def broken_git(folder: Path) -> Path:
    """Ausführbar, aber kein Programm (kein gültiges Format, keine Shebang-Zeile)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "git"
    path.write_bytes(b"\x00\x01\x02 kein Programm")
    path.chmod(0o755)
    return path


@posix
@pytest.mark.parametrize(
    "call",
    [
        lambda cwd: gitmod._git(cwd, "--version"),
        lambda cwd: gitmod._git_bytes(cwd, "--version"),
        lambda cwd: gitmod._probe_run(cwd, ("--version",), 10),
    ],
    ids=["_git", "_git_bytes", "_probe_run"],
)
def test_unusable_git_is_reported_as_missing_and_forgotten(
    call, tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    broken = broken_git(tmp_path / "defekt")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [broken])
    assert find_git() == str(broken) and str(broken) == gitmod._FOUND
    with pytest.raises(GitError) as raised:
        call(tmp_path)
    assert raised.value.kind == "git_missing"
    assert str(broken) in raised.value.hint and "nicht starten" in raised.value.hint
    assert gitmod._FOUND is None  # der gemerkte Fund ist vergessen


@posix
def test_permission_error_is_reported_as_missing(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])

    def denied(*args, **kwargs):
        raise PermissionError(13, "Zugriff verweigert", str(fake))

    monkeypatch.setattr(gitmod.subprocess, "run", denied)
    monkeypatch.setattr(gitmod.subprocess, "Popen", denied)
    with pytest.raises(GitError) as raised:
        gitmod._git(tmp_path, "--version")
    assert raised.value.kind == "git_missing" and str(fake) in raised.value.hint


def test_missing_git_hint_is_a_short_paragraph_and_a_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sys, "platform", "win32")
    places = [tmp_path / "eins" / "git.exe", tmp_path / "zwei" / "git.exe"]
    monkeypatch.setattr(gitmod, "git_locations", lambda: places)
    first, listing, advice = gitmod.missing_hint().split("\n\n")
    assert "\n" not in first and "ab- und wieder anmelden" in first
    assert listing.splitlines()[1:] == [f"- `{place}`" for place in places]
    assert "PATH des eigenen Benutzers" in advice and "Umgebungsvariablen" in advice
    assert "winget" not in first + listing + advice


def test_missing_git_hint_on_macos_and_linux_has_no_windows_advice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [tmp_path / "git"])
    advice = gitmod.missing_hint().split("\n\n")[-1]
    assert "~/.profile" in advice and "Homebrew" in advice
    assert "Umgebungsvariablen" not in advice and "git.exe" not in advice


def test_missing_git_hint_in_english(tmp_path: Path, english, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "win32")
    place = tmp_path / "eins" / "git.exe"
    monkeypatch.setattr(gitmod, "git_locations", lambda: [place])
    hint = gitmod.missing_hint(broken=str(tmp_path / "defekt"))
    assert "so that they can find Git" in hint
    assert f"Searched in PATH and in these places:\n- `{place}`" in hint
    assert "could not be started" in hint and "your own user’s PATH" in hint
    assert "Gesucht" not in hint and "Liegt Git" not in hint
    monkeypatch.setattr(sys, "platform", "linux")
    assert "~/.profile" in gitmod.missing_hint() and "Liegt Git" not in gitmod.missing_hint()


@posix
def test_broken_git_in_path_gives_way_to_a_fallback_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Veraltetes oder defektes ``git`` im PATH (Store-Alias): Schon der erste Aufruf wiederholt
    den Start mit dem Ersatzort; danach ist das defekte gesperrt."""
    in_path = broken_git(tmp_path / "pfad")
    fallback = fake_git(tmp_path / "ersatz", version="2.2.2-fallback")
    monkeypatch.setenv("PATH", str(in_path.parent))
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fallback])
    assert find_git() == str(in_path)  # PATH hat Vorrang, solange der Treffer taugt
    assert gitmod._git(tmp_path, "--version") == "git version 2.2.2-fallback"
    assert find_git() == str(fallback)
    assert gitsync.git_available()
    reset_git_cache()  # nach dem Zurücksetzen gilt der PATH-Treffer wieder zuerst
    assert find_git() == str(in_path)


@posix
def test_broken_git_in_path_gives_way_to_a_later_path_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first = broken_git(tmp_path / "eins")
    second = fake_git(tmp_path / "zwei", version="3.3.3-later")
    monkeypatch.setenv("PATH", f"{first.parent}{os.pathsep}{second.parent}")
    assert gitmod._git(tmp_path, "--version") == "git version 3.3.3-later"
    assert find_git() == str(second)


@posix
def test_everything_unusable_stays_git_missing_and_names_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    in_path = broken_git(tmp_path / "pfad")
    fallback = broken_git(tmp_path / "ersatz")
    monkeypatch.setenv("PATH", str(in_path.parent))
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fallback])
    for _ in range(3):  # jeder Versuch scheitert gleich, es gibt keine Endlosschleife
        with pytest.raises(GitError) as raised:
            gitmod._git(tmp_path, "--version")
        assert raised.value.kind == "git_missing"
        assert "nicht starten" in raised.value.hint
        assert str(fallback) in raised.value.hint or str(in_path) in raised.value.hint
    assert find_git() is None and not gitsync.git_available()
    with pytest.raises(GitError) as raised:
        gitsync._root(tmp_path)
    assert "nicht starten" in raised.value.hint


CALLS = [
    lambda cwd: gitmod._git(cwd, "--version"),
    lambda cwd: gitmod._git_bytes(cwd, "--version"),
    lambda cwd: gitmod._probe_run(cwd, ("--version",), 10),
]
CALL_IDS = ["_git", "_git_bytes", "_probe_run"]


@posix
@pytest.mark.parametrize("call", CALLS, ids=CALL_IDS)
def test_missing_working_folder_does_not_block_git(
    call, tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    """Ein gelöschter oder getrennter Datenordner betrifft nicht das Programm: Git bleibt
    verfügbar; gemeldet wird es wie bisher als „Git fehlt“."""
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    with pytest.raises(GitError) as raised:
        call(tmp_path / "gibt-es-nicht")
    assert raised.value.kind == "git_missing"
    assert not gitmod._BROKEN and gitmod.broken_git() == ""
    assert find_git() == str(fake)
    assert call(tmp_path) is not None  # und es läuft weiter


@posix
@pytest.mark.parametrize("call", CALLS, ids=CALL_IDS)
@pytest.mark.parametrize("code", [errno.EMFILE, errno.ENOMEM, errno.E2BIG])
def test_resource_errors_do_not_block_git_and_are_passed_on(
    call, code: int, tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])

    def failing(*args, **kwargs):
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(gitmod.subprocess, "run", failing)
    monkeypatch.setattr(gitmod.subprocess, "Popen", failing)
    with pytest.raises(OSError) as raised:
        call(tmp_path)
    assert not isinstance(raised.value, GitError) and raised.value.errno == code
    assert not gitmod._BROKEN
    assert find_git() == str(fake)


@posix
@pytest.mark.parametrize("call", CALLS, ids=CALL_IDS)
def test_too_long_arguments_do_not_block_git(
    call, tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    """Auf POSIX trägt jeder execve-Fehler den Programmpfad als Dateinamen, auch E2BIG (sehr
    lange Commit-Nachricht): Das Programm ist deshalb nicht unbrauchbar."""
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    long_text = "x" * 300_000
    calls = {
        "_git": lambda: gitmod._git(tmp_path, "--version", long_text),
        "_git_bytes": lambda: gitmod._git_bytes(tmp_path, "--version", long_text),
        "_probe_run": lambda: gitmod._probe_run(tmp_path, ("--version", long_text), 10),
    }
    with pytest.raises(OSError) as raised:
        calls[CALL_IDS[CALLS.index(call)]]()
    assert not isinstance(raised.value, GitError) and raised.value.errno == errno.E2BIG
    assert not gitmod._BROKEN and find_git() == str(fake) and gitsync.git_available()


@posix
@pytest.mark.parametrize("call", CALLS, ids=CALL_IDS)
def test_text_file_busy_does_not_block_git(
    call, tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    """ETXTBSY (Datei wird gerade geschrieben, etwa bei einem Update) geht vorüber."""
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])

    def busy(*args, **kwargs):
        raise OSError(errno.ETXTBSY, os.strerror(errno.ETXTBSY), str(fake))

    monkeypatch.setattr(gitmod.subprocess, "run", busy)
    monkeypatch.setattr(gitmod.subprocess, "Popen", busy)
    with pytest.raises(OSError) as raised:
        call(tmp_path)
    assert raised.value.errno == errno.ETXTBSY
    assert not gitmod._BROKEN and find_git() == str(fake)


@posix
def test_block_expires_after_the_time_limit(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    clock = [1000.0]
    monkeypatch.setattr(gitmod, "_now", lambda: clock[0])
    gitmod._mark_broken(str(fake))
    assert find_git() is None and gitmod.broken_git() == str(fake)
    clock[0] += gitmod._BROKEN_TTL - 1
    assert find_git() is None
    clock[0] += 2  # die Frist ist um: der Pfad wird erneut versucht
    assert find_git() == str(fake) and gitmod.broken_git() == ""


@posix
@pytest.mark.parametrize("call", CALLS, ids=CALL_IDS)
def test_block_is_lifted_by_a_successful_start(
    call, tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    gitmod._mark_broken(str(fake))
    assert find_git() is None
    call(tmp_path)  # letzter Versuch mit dem gesperrten Pfad gelingt
    assert not gitmod._BROKEN and find_git() == str(fake)


@posix
@pytest.mark.parametrize("call", CALLS, ids=CALL_IDS)
def test_first_call_already_uses_the_fallback_when_path_git_is_broken(
    call, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    in_path = broken_git(tmp_path / "pfad")
    fallback = fake_git(tmp_path / "ersatz")
    monkeypatch.setenv("PATH", str(in_path.parent))
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fallback])
    assert find_git() == str(in_path) and gitsync.git_available()
    call(tmp_path)  # kein git_missing beim ersten Aufruf
    assert find_git() == str(fallback)


@posix
def test_retry_is_limited_to_one_more_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first = broken_git(tmp_path / "eins")
    second = broken_git(tmp_path / "zwei")
    third = fake_git(tmp_path / "drei")
    monkeypatch.setenv("PATH", f"{first.parent}{os.pathsep}{second.parent}")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [third])
    with pytest.raises(GitError) as raised:
        gitmod._git(tmp_path, "--version")
    assert raised.value.kind == "git_missing" and str(second) in raised.value.hint
    assert gitmod._git(tmp_path, "--version") == "git version 9.9.9-fake"  # nächster Aufruf


@posix
def test_blocked_cached_location_is_not_used(
    tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch
):
    fake = fake_git(tmp_path / "a")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    assert find_git() == str(fake)  # gemerkt
    monkeypatch.setattr(gitmod, "git_locations", lambda: [])
    gitmod._BROKEN[str(fake)] = gitmod._now()
    assert find_git() is None


@posix
def test_relative_location_is_made_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_git(tmp_path / "hier")
    monkeypatch.chdir(tmp_path / "hier")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(gitmod, "git_locations", lambda: [Path("git")])
    assert find_git() == str(tmp_path / "hier" / "git")


@pytest.mark.parametrize("winerror", [2, 5, 193, 740, 1260])
@pytest.mark.parametrize("filename", [None, "C:\\Programme\\Git\\cmd\\git.exe"])
def test_windows_program_errors_block_the_path(winerror: int, filename: str | None):
    error = OSError(errno.EINVAL, "Fehler", filename)  # unter Windows ohne passenden errno
    error.winerror = winerror
    with pytest.raises(GitError) as raised:
        gitmod._start_failed(error, "C:\\Programme\\Git\\cmd\\git.exe")
    assert raised.value.kind == "git_missing"
    assert os.path.abspath("C:\\Programme\\Git\\cmd\\git.exe") in gitmod._BROKEN


@pytest.mark.parametrize("winerror", [87, 206, 267])
def test_other_windows_errors_do_not_block_the_path(winerror: int):
    error = OSError(errno.EINVAL, "Fehler", None)
    error.winerror = winerror
    with pytest.raises(OSError) as raised:
        gitmod._start_failed(error, "C:\\Git\\git.exe")
    assert raised.value is error and not gitmod._BROKEN


def test_windows_error_about_another_file_does_not_block_the_path(tmp_path: Path):
    """Ein Fehler mit gesetztem Dateinamen (etwa der Arbeitsordner) sperrt nicht über den
    Windows-Fehlercode."""
    error = OSError(errno.EINVAL, "Fehler", str(tmp_path / "ordner"))
    error.winerror = 193
    with pytest.raises(OSError) as raised:
        gitmod._start_failed(error, "C:\\Git\\git.exe")
    assert raised.value is error and not gitmod._BROKEN
