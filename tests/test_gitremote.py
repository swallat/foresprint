# SPDX-License-Identifier: EUPL-1.2
"""Server-Adresse (Remote) prüfen und speichern: Adressformen, Zugangsdaten, Verbindungsprüfung
und ``set_remote`` mit echten Git-Repositories."""

import contextlib
import copy
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from gitrepos import (
    SECRET,
    Denying,
    NotFound,
    Person,
    add_branches,
    git,
    make_local,
    make_server,
    serve,
)

from sprintforecast import git as gitmod
from sprintforecast import gitsync, proctree
from sprintforecast.git import (
    GitError,
    RemoteAddress,
    clone_repository,
    has_credentials,
    md_code,
    md_code_lines,
    parse_remote_url,
    public_url,
    scrub,
)


def assert_no_secret(error: GitError) -> None:
    for text in (str(error), error.hint, error.full(), repr(error)):
        assert SECRET not in text


def snapshot(root: Path) -> dict[str, bytes]:
    """Konfiguration und Referenzen eines Repositories (zum Vergleich vorher/nachher)."""
    gitdir = root / ".git"
    found = {}
    for file in [gitdir / "config", gitdir / "packed-refs"]:
        if file.exists():
            found[file.name] = file.read_bytes()
    for file in sorted((gitdir / "refs").rglob("*")):
        if file.is_file():
            found[file.relative_to(gitdir).as_posix()] = file.read_bytes()
    return found


class SpyPopen:
    """Merkt sich alle ``git``-Aufrufe (Argumente, Umgebung) und führt sie echt aus."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        real = subprocess.Popen

        def popen(args, *a, **kw):
            if args and args[0] == "git":
                self.calls.append((list(args), dict(kw.get("env") or {})))
            return real(args, *a, **kw)

        monkeypatch.setattr(subprocess, "Popen", popen)

    def with_command(self, name: str) -> list[tuple[list[str], dict[str, str]]]:
        return [c for c in self.calls if name in c[0]]


# --- T1/T2: Adressformen ----------------------------------------------------------------------


def test_accepted_addresses(tmp_path: Path):
    folder = tmp_path / "ein ordner" / "daten.git"
    folder.mkdir(parents=True)
    unchanged = [
        ("https://git.example.com:8443/team/daten.git", "https"),
        ("ssh://git@git.example.com/team/daten.git", "ssh"),
        ("ssh://git@git.example.com:2222/team/daten.git", "ssh"),
        ("ssh://git.example.com/team/daten.git", "ssh"),
        ("git@git.example.com:team/daten.git", "ssh"),
        ("git@[::1]:x.git", "ssh"),
        ("https://[::1]:8443/x.git", "https"),
        (str(folder), "local"),
        (str(tmp_path / "server.git"), "local"),
    ]
    for raw, kind in unchanged:
        assert parse_remote_url(raw) == RemoteAddress(raw, kind), raw
    # Das Schema wird klein geschrieben, Randleerraum entfernt; der Rest bleibt, wie er ist.
    assert parse_remote_url("HTTPS://Git.Example.com/t/d.git") == RemoteAddress(
        "https://Git.Example.com/t/d.git", "https"
    )
    assert parse_remote_url("  https://h.example/x.git \n").url == "https://h.example/x.git"


def test_http_needs_confirmation():
    assert parse_remote_url("http://h.example/x.git", allow_insecure=True) == RemoteAddress(
        "http://h.example/x.git", "http"
    )
    with pytest.raises(GitError) as info:
        parse_remote_url("http://h.example/x.git")
    assert info.value.kind == "insecure_url"


@pytest.mark.skipif(sys.platform != "win32", reason="UNC-Pfade gibt es nur unter Windows")
def test_unc_path_is_accepted():
    assert parse_remote_url(r"\\server\freigabe\daten.git").kind == "local"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-Pfad")
def test_posix_path_is_accepted():
    assert parse_remote_url("/srv/git/daten.git") == RemoteAddress("/srv/git/daten.git", "local")


REJECTED = [
    ("", "bad_url"),
    ("   ", "bad_url"),
    ("https://h/" + "a" * 2049, "bad_url"),
    ("-x", "bad_url"),
    ("--upload-pack=touch boese", "bad_url"),
    ("-oProxyCommand=x", "bad_url"),
    ("ssh://-oProxyCommand=x/y", "bad_url"),
    ("git@-o:x", "bad_url"),
    ("https://-h/x", "bad_url"),
    ("ext::sh -c touch% x", "bad_url"),
    ("fd::3", "bad_url"),
    ("git://h/x", "bad_url"),
    ("file:///tmp/x", "bad_url"),
    ("ftp://h/x", "bad_url"),
    ("../x.git", "bad_url"),
    ("x.git", "bad_url"),
    ("host:pfad", "bad_url"),
    ("https://host", "bad_url"),
    ("https://host/", "bad_url"),
    ("https://", "bad_url"),
    ("https://ho st/x", "bad_url"),
    ("https://host:abc/x", "bad_url"),
    ("https://host:0/x", "bad_url"),
    ("https://host:70000/x", "bad_url"),
    ("https://host/x\ny", "bad_url"),
    ("https://host/x\\y", "bad_url"),
    ("https://h\u200bost/x", "bad_url"),
    ("https://host/\ufeffx", "bad_url"),
    ("https://höst.example/x", "bad_url"),
    ("git@host:-x", "bad_url"),
    ("git@host:my repo", "bad_url"),
    ("http://h/x", "insecure_url"),
    (f"https://user:{SECRET}@h/r.git", "secret_in_url"),
    (f"https://{SECRET}@h/r.git", "secret_in_url"),
    ("https://org@h/r.git", "secret_in_url"),
    ("https://anna@bitbucket.org/team/daten.git", "secret_in_url"),
    (f"https://u:p@{SECRET}@h/r.git", "secret_in_url"),
    (f"https://u:12/{SECRET}@h/r.git", "secret_in_url"),
    (f"http://u:{SECRET}@h/r.git", "secret_in_url"),
    (f"ssh://u:{SECRET}@h/x", "secret_in_url"),
    (f"u:{SECRET}@h:pfad", "secret_in_url"),
    (f"https://h/r.git?token={SECRET}", "secret_in_url"),
    (f"https://h/r.git#{SECRET}", "secret_in_url"),
    (f"ssh://git@h/x?{SECRET}", "secret_in_url"),
]


@pytest.mark.parametrize(("raw", "kind"), REJECTED)
def test_rejected_addresses(raw: str, kind: str):
    with pytest.raises(GitError) as info:
        parse_remote_url(raw, allow_insecure=False)
    assert info.value.kind == kind, (raw, info.value)
    assert_no_secret(info.value)
    assert raw.strip() not in str(info.value) or not raw.strip()  # die Eingabe wird nie wiederholt


@pytest.mark.parametrize(("raw", "kind"), REJECTED)
def test_address_messages_do_not_repeat_the_title(raw: str, kind: str):
    """Die Oberfläche setzt die Überschrift (``title_for``) über die Meldung; steht der Titel
    schon in der Meldung, erscheint er doppelt."""
    with pytest.raises(GitError) as info:
        parse_remote_url(raw)
    title = gitmod.title_for(kind)
    assert title not in str(info.value) and not str(info.value).startswith("Ungültige Adresse")
    assert info.value.hint == ""


@pytest.mark.parametrize("raw", ["git://h/x", "file:///tmp/x", "ext::x", f"https://u:{SECRET}@h/x"])
def test_rejection_does_not_depend_on_insecure_flag(raw: str):
    with pytest.raises(GitError):
        parse_remote_url(raw, allow_insecure=True)


def test_relative_and_foreign_paths_are_not_absolute():
    """Was ein vollständiger Pfad ist, entscheidet die Plattform."""
    foreign = "/srv/git/daten.git" if sys.platform == "win32" else r"C:\git\daten.git"
    with pytest.raises(GitError) as info:
        parse_remote_url(foreign)
    assert info.value.kind == "bad_url"


def test_secret_message_names_what_is_wrong_in_plain_words():
    text = str(gitmod.secret_in_url_error())
    assert "Benutzernamen" in text and "Parameter" in text
    assert "Zusätze" not in text  # kein Fachwort für Leute ohne Terminalwissen


# --- T3: Anzeigefassung und Scrubbing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "shown"),
    [
        ("https://u:p@ss@h/r.git", "https://h/r.git"),
        (f"https://h/r.git?token={SECRET}", "https://h/r.git"),
        (f"https://h/r.git#{SECRET}", "https://h/r.git"),
        (f"https://{SECRET}@h/r.git", "https://h/r.git"),
        ("ssh://git:pw@h/x", "ssh://git@h/x"),
        ("ssh://git@h/x", "ssh://git@h/x"),
        ("git@h:p", "git@h:p"),
        ("a:b@host:pfad", "a@host:pfad"),
        ("https://h/r.git", "https://h/r.git"),
        (r"C:\daten\a@b\repo", r"C:\daten\a@b\repo"),
        ("/srv/git/a@b/repo.git", "/srv/git/a@b/repo.git"),
        ("müll", "müll"),
        ("", ""),
        ("://@?#", "://@?#"),
    ],
)
def test_public_url(given: str, shown: str):
    assert public_url(given) == shown
    assert public_url(shown) == shown  # idempotent


def test_public_url_is_identity_for_every_accepted_address(tmp_path: Path):
    for raw in (
        "https://git.example.com:8443/team/daten.git",
        "ssh://git@git.example.com:2222/team/daten.git",
        "git@git.example.com:team/daten.git",
        "git@h:org/a@b.git",
        str(tmp_path / "a@b" / "daten.git"),
    ):
        address = parse_remote_url(raw)
        assert public_url(address.url) == address.url, raw
        assert not has_credentials(address.url)


def test_has_credentials():
    assert has_credentials(f"https://u:{SECRET}@h/r.git")
    assert has_credentials(f"  https://h/r.git?x={SECRET}")
    assert not has_credentials("  git@h:x.git ")
    assert not has_credentials("")


def test_scrub_typical_git_messages():
    text = f"fatal: unable to access 'https://u:{SECRET}@h/r.git/': Could not resolve host: h"
    assert SECRET not in scrub(text) and "https://h/r.git/" in scrub(text)
    text = f"fatal: repository 'https://h/r.git?private_token={SECRET}' not found"
    assert SECRET not in scrub(text) and "https://h/r.git" in scrub(text)
    assert scrub("kein Link, Hilfe: https://git-scm.com/download/win") == (
        "kein Link, Hilfe: https://git-scm.com/download/win"
    )


@pytest.mark.parametrize(
    "text",
    [
        f"fatal: ('https://u:{SECRET}@h/r.git')",
        f"Adresse:https://u:{SECRET}@h/r.git",
        f"remote: siehe\nhttps://u:{SECRET}@h/r.git\nEnde",
        f"HTTPS://u:{SECRET}@h/r.git",
    ],
)
def test_scrub_finds_an_address_after_any_punctuation(text: str):
    assert SECRET not in scrub(text) and "h/r.git" in scrub(text)


@pytest.mark.parametrize("unit", ["a.", "a-", "a+", "Ab1."])
def test_scrub_stays_linear_for_long_lines_without_an_address(unit: str):
    """Eine lange Zeile aus Schema-Zeichen („remote: a.a.a. …“) darf die Sitzung nicht
    minutenlang stilllegen: Der Treffer begann früher hinter jedem Punkt neu."""
    text = "remote: " + unit * 60_000
    started = time.monotonic()
    assert scrub(text) == text
    assert str(GitError(text)) == text
    assert time.monotonic() - started < 2


def test_git_error_never_carries_credentials():
    error = GitError(
        f"unable to access 'https://u:{SECRET}@h/r.git/'",
        "offline",
        f"Adresse https://u:{SECRET}@h/r.git prüfen",
    )
    assert_no_secret(error)
    assert "https://h/r.git" in str(error) and "https://h/r.git" in error.hint
    assert gitmod.classify(f"fatal: unable to access 'https://x:{SECRET}@h/'").kind == "offline"
    assert_no_secret(gitmod.classify(f"fatal: unable to access 'https://x:{SECRET}@h/'"))


def test_sync_state_repr_hides_the_stored_address(tmp_path: Path):
    root = make_local(tmp_path)
    git(root, "remote", "add", "origin", f"https://u:{SECRET}@h.example/r.git")
    current = gitsync.state(root / "teams")
    assert SECRET in current.url  # roh, damit Git sie benutzen kann
    assert SECRET not in repr(current)


def test_env_drops_trace_variables(monkeypatch: pytest.MonkeyPatch):
    for name in ("GIT_TRACE", "GIT_TRACE_CURL", "GIT_CURL_VERBOSE", "git_trace_setup"):
        monkeypatch.setenv(name, "1")
    for network in (False, True):
        env = gitmod._env(network, {"EXTRA": "x"})
        assert not [n for n in env if n.upper().startswith(("GIT_TRACE", "GIT_CURL_VERBOSE"))]
        assert env["EXTRA"] == "x" and env["LC_ALL"] == "C"
    assert gitmod._env(True)["GIT_TERMINAL_PROMPT"] == "0"


# --- Namen vom Server in Markdown ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("main", "`main`"),
        ("www.evil.example/anmelden", "`www.evil.example/anmelden`"),
        ("[klick](http://evil.example)", "`[klick](http://evil.example)`"),
        ("a`b", "``a`b``"),
        ("`x", "`` `x ``"),
        ("x`", "`` x` ``"),
        ("a``b", "```a``b```"),
        ("a\nb\u202ec", "`a b c`"),
        ("", ""),
        # Steuerzeichen, Zeilen- und Absatztrenner und die Zeichen der Schreibrichtung:
        ("a\x00b\x85c\u2028d\u2029e", "`a b c d e`"),
        ("a\u200eb\u200fc\u061cd", "`a b c d`"),
        ("a\u202ab\u202bc\u202cd\u202de", "`a b c d e`"),
        ("a\u2066b\u2067c\u2068d\u2069e", "`a b c d e`"),
        # Formatzeichen, die zu Zeichenfolgen gehören, bleiben: Joiner in Emoji-Folgen,
        # Non-Joiner in persischen Namen, Variantenauswahl, Flaggen.
        (
            "Familie \U0001f468\u200d\U0001f469\u200d\U0001f467",
            "`Familie \U0001f468\u200d\U0001f469\u200d\U0001f467`",
        ),
        ("\U0001f469\u200d\U0001f4bb fix", "`\U0001f469\u200d\U0001f4bb fix`"),
        ("\U0001f3f3\ufe0f\u200d\U0001f308", "`\U0001f3f3\ufe0f\u200d\U0001f308`"),
        (
            "\u0646\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645",
            "`\u0646\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645`",
        ),
        ("Bj\u00f6rn \u00dcber", "`Bj\u00f6rn \u00dcber`"),
    ],
)
def test_md_code_keeps_foreign_text_inside_a_code_span(text: str, code: str):
    assert md_code(text) == code


def test_md_code_lines_makes_one_code_span_per_line():
    assert md_code_lines("remote: [Klick](http://example.org)\n ! [rejected] a`b\r\n\n") == (
        "`remote: [Klick](http://example.org)`  \n``  ! [rejected] a`b ``"
    )
    assert md_code_lines("") == md_code_lines(" \n \n") == ""


def test_git_error_text_of_git_is_quoted_and_own_text_is_not():
    own = GitError("Eigener Text mit `Code`", "folder")
    raw = gitmod.classify("remote: [Klick](http://example.org)\nfatal: www.evil.example/x")
    assert not own.raw and raw.raw and raw.kind == "error" and not raw.hint
    assert own.render(md_code_lines) == "Eigener Text mit `Code`"
    assert raw.render(md_code_lines) == (
        "`remote: [Klick](http://example.org)`  \n`fatal: www.evil.example/x`"
    )
    assert raw.render() == str(raw)  # ohne ``quote`` bleibt der Text unverändert
    assert copy.copy(raw).raw and not copy.copy(own).raw
    assert not gitmod.classify("", missing=True).raw and not gitmod.classify("", timeout=True).raw
    assert not gitmod.classify("").raw  # ohne Text von Git gibt es nichts zu schützen


def test_git_error_full_quotes_only_the_message_of_git():
    denied = gitmod.classify("! [remote rejected] www.evil.example/x (pre-receive hook declined)")
    assert denied.kind == "denied" and denied.hint
    full = denied.full(md_code_lines)
    assert full.startswith("`! [remote rejected] www.evil.example/x (pre-receive hook declined)` ")
    assert full.endswith(denied.hint)  # der Hinweis ist ein eigener Text
    assert denied.full() == f"{denied} {denied.hint}"


def test_new_branch_error_is_plain_text_and_renders_names_as_code():
    error = gitmod.new_branch_error("main", ("www.evil.example/anmelden", "a`b"))
    assert "„main“" in str(error) and "www.evil.example/anmelden" in str(error)
    assert "`www.evil.example" not in str(error) and "„`main`“" not in str(error)
    shown = error.render(md_code)
    assert "`www.evil.example/anmelden`" in shown and "``a`b``" in shown and "`main`" in shown
    assert copy.copy(error).render(md_code) == shown  # Fehler lassen sich kopieren


def test_unrelated_histories_error_is_plain_text_and_renders_server_and_branch_as_code():
    error = gitmod.UnrelatedHistoriesError("https://h.example/r.git", "www.evil.example/x")
    assert error.kind == "unrelated_histories" and error.hint
    assert str(error) == (
        "Der Server (https://h.example/r.git, Branch www.evil.example/x) enthält eine andere "
        "Historie als dieser Datenordner."
    )
    shown = error.render(md_code)
    assert "(`https://h.example/r.git`, Branch `www.evil.example/x`)" in shown
    clone = copy.copy(error)
    assert clone.render(md_code) == shown and clone.hint == error.hint  # lässt sich kopieren


# --- T4: Zuordnung der Fehler der Verbindungsprüfung -------------------------------------------

HTTPS = RemoteAddress("https://h.example/r.git", "https")
SSH = RemoteAddress("git@h.example:r.git", "ssh")
TAIL = (
    "fatal: Could not read from remote repository.\n\nPlease make sure you have the correct "
    "access rights\nand the repository exists."
)


@pytest.mark.parametrize(
    ("message", "address", "kind", "hint_part"),
    [
        ("fatal: Authentication failed for 'https://h/r.git/'", HTTPS, "auth", "Zugangstoken"),
        ("fatal: Authentication failed for 'https://h/r.git/'", SSH, "auth", "SSH"),
        ("git@h: Permission denied (publickey).", SSH, "auth", "SSH"),
        (
            "fatal: could not read Username for 'https://h': terminal prompts disabled",
            HTTPS,
            "auth",
            "Zugangstoken",
        ),
        (
            "Host key verification failed.\nfatal: Could not read from remote repository.",
            SSH,
            "auth",
            "Fingerabdruck",
        ),
        ("@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @", SSH, "auth", "Fingerabdruck"),
        (
            "fatal: '/x/y' does not appear to be a git repository\n"
            "fatal: Could not read from remote repository.",
            HTTPS,
            "not_found",
            "nicht gefunden",
        ),
        ("fatal: repository 'https://h/r.git/' not found", HTTPS, "not_found", "nicht gefunden"),
        (
            "fatal: unable to access 'https://h/r.git/': The requested URL returned error: 404",
            HTTPS,
            "not_found",
            "nicht gefunden",
        ),
        # Der Server antwortet, das Projekt gibt es nicht (oder er verschweigt es): SSH-Meldungen
        # von GitHub, GitLab, Bitbucket, Azure DevOps und Gitea. Nie „nicht erreichbar“.
        (f"ERROR: Repository not found.\n{TAIL}", SSH, "not_found", "nicht gefunden"),
        (
            "remote: ERROR: The project you were looking for could not be found or you don't "
            f"have permission to view it.\n{TAIL}",
            SSH,
            "not_found",
            "nicht gefunden",
        ),
        (f"conq: repository does not exist.\n{TAIL}", SSH, "not_found", "nicht gefunden"),
        (
            "remote: TF401019: The Git repository with name or identifier x does not exist or "
            f"you do not have permissions for the operation you are attempting.\n{TAIL}",
            SSH,
            "not_found",
            "nicht gefunden",
        ),
        (f"Gitea: Repository does not exist.\n{TAIL}", SSH, "not_found", "nicht gefunden"),
        # Das Zertifikat wird nicht anerkannt: Der Server antwortet, VPN prüfen hilft nicht.
        (
            "fatal: unable to access 'https://h/r.git/': SSL certificate problem: unable to get "
            "local issuer certificate",
            HTTPS,
            "certificate",
            "Zertifikat",
        ),
        (
            "fatal: unable to access 'https://h/r.git/': schannel: SEC_E_UNTRUSTED_ROOT "
            "(0x80090325)",
            HTTPS,
            "certificate",
            "Zertifikat",
        ),
        # Nur belegte Netzwerkfehler gelten als „nicht erreichbar“.
        (
            "fatal: unable to access 'https://h/': Could not resolve host: h",
            HTTPS,
            "offline",
            "Tippfehler",
        ),
        (
            "fatal: unable to access 'http://h/': Operation too slow. Less than 1000 bytes/sec",
            HTTPS,
            "offline",
            "Tippfehler",
        ),
        (
            "ssh: connect to host h.example port 22: Connection refused\n" + TAIL,
            SSH,
            "offline",
            "Tippfehler",
        ),
        (
            "ssh: Could not resolve hostname h.example: Name or service not known\n" + TAIL,
            SSH,
            "offline",
            "Tippfehler",
        ),
        (
            "fatal: unable to access 'https://h/': Recv failure: Connection was reset",
            HTTPS,
            "offline",
            "Tippfehler",
        ),
        # Git sagt nur „Could not read from remote repository“ oder der Server antwortet mit
        # einem Fehler: unklar, aber nie „nicht erreichbar“ und nie zum Speichern angeboten.
        (TAIL, SSH, "error", "nicht erfüllt"),
        (
            "fatal: unable to access 'https://h/r.git/': The requested URL returned error: 503",
            HTTPS,
            "error",
            "nicht erfüllt",
        ),
        ("fatal: etwas ganz Neues", HTTPS, "error", "Technische Meldung"),
        ("", HTTPS, "error", "Technische Meldung"),
    ],
)
def test_probe_error_table(message: str, address: RemoteAddress, kind: str, hint_part: str):
    error = gitmod._probe_error(message, address)
    assert error.kind == kind, error
    assert hint_part in error.hint
    if kind != "offline":
        assert "nicht erreichbar" not in error.hint


def test_probe_timeout_is_offline():
    error = gitmod._probe_error("", HTTPS, timed_out=True)
    assert error.kind == "offline" and "Tippfehler" in error.hint


def test_probe_error_keeps_text_of_git_in_the_message():
    error = gitmod._probe_error("fatal: etwas ganz Neues", HTTPS)
    assert str(error) == "fatal: etwas ganz Neues"


def test_new_error_kinds_have_their_own_titles():
    for kind in ("certificate", "nothing_to_share"):
        assert gitmod.title_for(kind) != gitmod.title_for("unbekannt")


def test_classify_is_unchanged_for_the_old_patterns():
    for message, kind in [
        ("fatal: Could not read from remote repository.", "offline"),
        ("fatal: repository not found, Repository not found", "not_found"),
        ("remote: Not Found", "not_found"),
        ("fatal: unable to access 'x': Could not resolve host", "offline"),
    ]:
        assert gitmod.classify(message).kind == kind


def test_not_found_hint_says_where_to_change_the_address():
    for hint in (gitmod.hint_for("not_found"), gitmod.hint_for("unrelated_histories")):
        assert "Datenordner" in hint and "Server (Remote)" in hint
    assert "Repository klonen" in gitmod.hint_for("no_remote")


# --- T5/T6: check_remote ------------------------------------------------------------------------


def test_check_empty_server(tmp_path: Path):
    root = make_local(tmp_path)
    check = gitsync.check_remote(root / "teams", str(make_server(tmp_path)))
    assert check.heads == () and check.empty and not check.branch_missing
    assert check.address.kind == "local" and check.branch == "main"


def test_check_server_with_the_branch(tmp_path: Path):
    root = make_local(tmp_path)
    check = gitsync.check_remote(root / "teams", str(make_server(tmp_path, branch="main")))
    assert check.heads == ("main",) and not check.empty and not check.branch_missing


def test_check_server_without_the_local_branch(tmp_path: Path):
    root = make_local(tmp_path)
    check = gitsync.check_remote(root / "teams", str(make_server(tmp_path, branch="master")))
    assert check.heads == ("master",) and check.branch_missing and not check.unborn


def test_check_without_commit_against_a_server_with_data(tmp_path: Path):
    """Der Beitritts-Fall: Ordner frisch angelegt (noch kein Commit), der Server hat Daten."""
    root = make_local(tmp_path, commit=False)
    check = gitsync.check_remote(root / "teams", str(make_server(tmp_path, branch="master")))
    assert check.branch == "main" and check.unborn and check.branch_missing


def test_check_without_commit_against_an_empty_or_matching_server(tmp_path: Path):
    root = make_local(tmp_path, commit=False)
    assert not gitsync.check_remote(root / "teams", str(make_server(tmp_path))).branch_missing
    matching = make_server(tmp_path, "gleich.git", branch="main")
    assert not gitsync.check_remote(root / "teams", str(matching)).branch_missing


def test_check_with_a_detached_head_has_no_branch_to_miss(tmp_path: Path):
    root = make_local(tmp_path)
    git(root, "checkout", "-q", "--detach")
    gitmod.invalidate_status()
    check = gitsync.check_remote(root / "teams", str(make_server(tmp_path, branch="master")))
    assert check.branch is None and not check.branch_missing


def test_check_sees_all_branches_not_only_the_first_200(tmp_path: Path, monkeypatch):
    """250 Branches ``feature/…`` und ``main``: Die Ausgabe ist alphabetisch, ``main`` steht
    hinter dem 200. Eintrag und gehört trotzdem zum Server."""
    root = make_local(tmp_path)
    server = make_server(tmp_path, branch="main")
    add_branches(server, [f"feature/{n:03d}" for n in range(250)])
    spy = SpyPopen(monkeypatch)
    check = gitsync.check_remote(root / "teams", str(server))
    assert len(check.heads) == 251 and "main" in check.heads
    assert not check.branch_missing
    assert len(spy.with_command("ls-remote")) == 1  # die Liste passt ins Limit: eine Anfrage
    gitsync.set_remote(root / "teams", str(server))  # ohne Bestätigung des Branches
    assert git(root, "remote", "get-url", "origin") == str(server)


def test_check_asks_for_the_local_branch_when_the_list_is_too_long(tmp_path: Path, monkeypatch):
    """Über 64 KB Ausgabe kürzt die Abfrage die Liste; ob der lokale Branch dabei ist, klärt eine
    zweite, gezielte Anfrage (nicht die gekürzte Liste)."""
    root = make_local(tmp_path)
    server = make_server(tmp_path, branch="main")
    add_branches(server, [f"feature/{'x' * 80}-{n:04d}" for n in range(1000)])
    spy = SpyPopen(monkeypatch)
    check = gitsync.check_remote(root / "teams", str(server))
    first, second = (args for args, _ in spy.with_command("ls-remote"))
    assert first[-1] == str(server) and second[-2:] == [str(server), "refs/heads/main"]
    assert "main" in check.heads and len(check.heads) < 1001  # die Liste ist gekürzt
    assert not check.branch_missing

    git(root, "branch", "-m", "lokal")  # einen Branch, den der Server wirklich nicht hat
    gitmod.invalidate_status()
    check = gitsync.check_remote(root / "teams", str(server))
    assert check.branch == "lokal" and "lokal" not in check.heads and check.branch_missing


def test_probe_remote_without_a_branch_does_not_ask_twice(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    server = make_server(tmp_path, branch="main")
    add_branches(server, [f"feature/{'x' * 80}-{n:04d}" for n in range(1000)])
    spy = SpyPopen(monkeypatch)
    heads = gitmod.probe_remote(root, RemoteAddress(str(server), "local"))
    assert 0 < len(heads) < 1001 and len(spy.with_command("ls-remote")) == 1


def test_check_missing_repository_is_not_found(tmp_path: Path):
    root = make_local(tmp_path)
    plain = tmp_path / "kein-repo"
    plain.mkdir()
    for missing in (tmp_path / "gibt-es-nicht.git", plain):
        with pytest.raises(GitError) as info:
            gitsync.check_remote(root / "teams", str(missing))
        assert info.value.kind == "not_found", info.value
        assert "nicht gefunden" in info.value.hint


def test_check_missing_login_is_explained(tmp_path: Path, no_login_prompt):
    root = make_local(tmp_path)
    with serve(Denying) as port, pytest.raises(GitError) as info:
        gitsync.check_remote(root / "teams", f"http://127.0.0.1:{port}/r.git", allow_insecure=True)
    assert info.value.kind == "auth" and "Zugangstoken" in info.value.hint


def test_check_does_not_connect_with_credentials(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    spy = SpyPopen(monkeypatch)
    with pytest.raises(GitError) as info:
        gitsync.check_remote(root / "teams", f"https://u:{SECRET}@127.0.0.1:1/r.git")
    assert info.value.kind == "secret_in_url"
    assert not spy.with_command("ls-remote")


def test_check_changes_nothing(tmp_path: Path):
    root = make_local(tmp_path)
    git(root, "remote", "add", "origin", str(make_server(tmp_path, "alt.git", branch="main")))
    git(root, "fetch", "-q", "origin")
    before = snapshot(root)
    assert "refs/remotes/origin/main" in before
    for target in (
        make_server(tmp_path, "neu.git", branch="master"),
        make_server(tmp_path, "leer.git"),
        tmp_path / "gibt-es-nicht",
    ):
        with contextlib.suppress(GitError):
            gitsync.check_remote(root / "teams", str(target))
    assert snapshot(root) == before


# --- T7: Prozess und Protokollsperre -----------------------------------------------------------


def test_probe_command_and_environment(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    server = make_server(tmp_path)
    spy = SpyPopen(monkeypatch)
    gitsync.check_remote(root / "teams", str(server))
    [(args, env)] = spy.with_command("ls-remote")
    assert args == ["git", "ls-remote", "--heads", "--", str(server)]
    assert env["GIT_ALLOW_PROTOCOL"] == "https:http:ssh:file"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_HTTP_LOW_SPEED_LIMIT"] == "1000" and env["GIT_HTTP_LOW_SPEED_TIME"] == "10"


@pytest.mark.parametrize("helper", ["fd::3", "ext::sh -c 'touch marker'"])
def test_probe_refuses_remote_helpers_even_without_the_parser(tmp_path: Path, helper: str):
    """Zweite Sperre: Käme eine solche Adresse am Parser vorbei, führt Git sie nicht aus."""
    root = make_local(tmp_path)
    started = time.monotonic()
    run = gitmod._probe_run(root, ("ls-remote", "--heads", "--", helper), 20)
    assert run.code not in (0, None) and "not allowed" in run.err
    assert time.monotonic() - started < 15
    assert not (root / "marker").exists()


def test_probe_returns_when_the_server_never_answers(tmp_path: Path, monkeypatch):
    """Der Server nimmt die Verbindung an und schweigt. Das Zeitlimit der App (3 s) liegt unter
    dem von Git (10 s, ``GIT_HTTP_LOW_SPEED_TIME``): Kommt die App-Meldung nach wenigen Sekunden,
    hat die App selbst abgebrochen und den Prozessbaum beendet."""
    root = make_local(tmp_path)
    ended: list[int | None] = []
    terminate = proctree.terminate_tree

    def spy(process, *args, **kwargs):
        terminate(process, *args, **kwargs)
        ended.append(process.poll())  # nach dem Beenden: Rückgabecode, nicht „läuft noch“

    monkeypatch.setattr(proctree, "terminate_tree", spy)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    held = []

    def accept() -> None:
        while True:
            try:
                held.append(listener.accept()[0])
            except OSError:
                return

    threading.Thread(target=accept, daemon=True).start()
    outcome: dict[str, object] = {}

    def probe() -> None:
        started = time.monotonic()
        try:
            gitsync.check_remote(
                root / "teams",
                f"http://127.0.0.1:{listener.getsockname()[1]}/r.git",
                allow_insecure=True,
                timeout=3,
            )
        except GitError as e:
            outcome["error"] = e
        outcome["seconds"] = time.monotonic() - started

    worker = threading.Thread(target=probe, daemon=True)
    worker.start()
    worker.join(25)
    listener.close()
    assert not worker.is_alive(), "Die Prüfung hängt"
    error = outcome["error"]
    assert isinstance(error, GitError) and error.kind == "offline"
    # Die Meldung der App, nicht die von Git („Operation too slow“ nach 10 s): Das Zeitlimit
    # wurde durchgereicht und hat gegriffen.
    assert str(error) == "Der Server antwortet nicht rechtzeitig."
    assert 3 <= outcome["seconds"] < 8
    assert len(ended) == 1 and ended[0] is not None  # der Prozess war beim Zurückkehren beendet


# --- T8: set_remote ----------------------------------------------------------------------------


def config_of(root: Path) -> bytes:
    return (root / ".git" / "config").read_bytes()


def test_set_remote_without_server_creates_origin(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    assert gitsync.fetch(data).fetch_error.kind == "no_remote"
    assert gitsync.cached_state(data).fetch_error is not None
    server = make_server(tmp_path)
    saved = gitsync.set_remote(data, str(server))
    assert saved == gitsync.RemoteSaved("origin", str(server), True)
    current = gitsync.cached_state(data)  # sofort aktuell, ohne Wartezeit
    assert current.remote == "origin" and current.fetch_error is None
    assert current.fetched_at is None  # Serverstand noch nicht geprüft
    assert git(root, "remote", "get-url", "origin") == str(server)


def test_set_remote_replaces_the_address_and_sync_pushes(alice: Person, tmp_path: Path):
    new = make_server(tmp_path, "neu.git")
    saved = gitsync.set_remote(alice.data, str(new))
    assert saved.name == "origin" and saved.verified
    assert git(alice.root, "remote", "get-url", "origin") == str(new)
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Umzug")
    assert result.ok and result.pushed, result.error
    assert git(new, "log", "-1", "--format=%s", "main") == "Umzug"


def test_set_remote_keeps_the_name_of_the_only_server(tmp_path: Path):
    root = make_local(tmp_path)
    git(root, "remote", "add", "zentral", str(make_server(tmp_path, "alt.git")))
    new = make_server(tmp_path, "neu.git")
    assert gitsync.set_remote(root / "teams", str(new)).name == "zentral"
    assert git(root, "remote") == "zentral"
    assert git(root, "remote", "get-url", "zentral") == str(new)


def test_set_remote_changes_only_the_upstream_server(tmp_path: Path):
    root = make_local(tmp_path)
    first, second = make_server(tmp_path, "eins.git"), make_server(tmp_path, "zwei.git")
    git(root, "remote", "add", "origin", str(first))
    git(root, "remote", "add", "hoch", str(second))
    git(root, "push", "-q", "-u", "hoch", "main")
    new = make_server(tmp_path, "neu.git")
    info = gitsync.remote_info(root / "teams")
    assert info.name == "hoch" and info.others == ("origin",)
    assert gitsync.set_remote(root / "teams", str(new)).name == "hoch"
    assert git(root, "remote", "get-url", "hoch") == str(new)
    assert git(root, "remote", "get-url", "origin") == str(first)


@pytest.mark.parametrize("special", ["pushurl", "multi_url"])
def test_set_remote_refuses_unusual_server_settings(tmp_path: Path, special: str):
    root = make_local(tmp_path)
    git(root, "remote", "add", "origin", str(make_server(tmp_path, "alt.git")))
    if special == "pushurl":
        git(root, "config", "remote.origin.pushurl", str(tmp_path / "anderswo.git"))
    else:
        git(root, "config", "--add", "remote.origin.url", str(tmp_path / "zweite.git"))
    before = config_of(root)
    assert gitsync.remote_info(root / "teams").special == special
    with pytest.raises(GitError) as info:
        gitsync.set_remote(root / "teams", str(make_server(tmp_path, "neu.git")))
    assert info.value.kind == "remote_special"
    assert config_of(root) == before


def test_set_remote_refuses_an_unusual_server_name(tmp_path: Path):
    root = make_local(tmp_path)
    git(root, "remote", "add", "_komisch", str(make_server(tmp_path, "alt.git")))
    info = gitsync.remote_info(root / "teams")
    assert info.special == "name"
    before = config_of(root)
    with pytest.raises(GitError) as raised:
        gitsync.set_remote(root / "teams", str(make_server(tmp_path, "neu.git")))
    assert raised.value.kind == "remote_special" and config_of(root) == before


def test_set_remote_refuses_with_an_open_merge(alice: Person, tmp_path: Path):
    (alice.root / ".git" / "MERGE_HEAD").write_text(git(alice.root, "rev-parse", "HEAD") + "\n")
    gitmod.invalidate_status()
    before = config_of(alice.root)
    with pytest.raises(GitError) as info:
        gitsync.set_remote(alice.data, str(make_server(tmp_path, "neu.git")))
    assert info.value.kind == "merge_in_progress" and not info.value.hint
    assert config_of(alice.root) == before


def test_set_remote_saves_nothing_on_login_missing(tmp_path: Path, no_login_prompt):
    root = make_local(tmp_path)
    before = config_of(root)
    with serve(Denying) as port, pytest.raises(GitError) as info:
        gitsync.set_remote(
            root / "teams",
            f"http://127.0.0.1:{port}/r.git",
            allow_insecure=True,
            allow_offline=True,
            accept_new_branch=True,
        )
    assert info.value.kind == "auth"
    assert config_of(root) == before


def test_set_remote_saves_nothing_for_a_missing_repository(tmp_path: Path):
    root = make_local(tmp_path)
    before = config_of(root)
    with pytest.raises(GitError) as info:
        gitsync.set_remote(
            root / "teams",
            str(tmp_path / "gibt-es-nicht"),
            allow_offline=True,
            accept_new_branch=True,
        )
    assert info.value.kind == "not_found" and config_of(root) == before


@pytest.mark.parametrize(
    ("stderr", "kind"),
    [
        # GitLab über SSH: Server erreichbar, Projekt fehlt (Tippfehler). Früher „offline“ und
        # damit zum ungeprüften Speichern angeboten.
        (
            "remote: ERROR: The project you were looking for could not be found or you don't "
            f"have permission to view it.\n{TAIL}",
            "not_found",
        ),
        (f"ERROR: Repository not found.\n{TAIL}", "not_found"),
        (
            "fatal: unable to access 'https://h/r.git/': SSL certificate problem: self-signed "
            "certificate in certificate chain",
            "certificate",
        ),
        (TAIL, "error"),
        ("fatal: etwas ganz Neues", "error"),
    ],
)
def test_set_remote_never_saves_unchecked_for_errors_other_than_unreachable(
    tmp_path: Path, monkeypatch, stderr: str, kind: str
):
    root = make_local(tmp_path)
    before = config_of(root)
    monkeypatch.setattr(gitmod, "_probe_run", lambda *a: gitmod._ProbeRun(128, "", stderr))
    with pytest.raises(GitError) as info:
        gitsync.set_remote(
            root / "teams", str(tmp_path / "x"), allow_offline=True, accept_new_branch=True
        )
    assert info.value.kind == kind and config_of(root) == before


def test_set_remote_offline_needs_confirmation(tmp_path: Path):
    root = make_local(tmp_path)
    url = "http://127.0.0.1:1/r.git"
    before = config_of(root)
    with pytest.raises(GitError) as info:
        gitsync.set_remote(root / "teams", url, allow_insecure=True, timeout=20)
    assert info.value.kind == "offline" and config_of(root) == before
    saved = gitsync.set_remote(
        root / "teams", url, allow_insecure=True, allow_offline=True, timeout=20
    )
    assert saved == gitsync.RemoteSaved("origin", url, False)
    assert git(root, "remote", "get-url", "origin") == url


def test_set_remote_new_branch_needs_confirmation(tmp_path: Path):
    root = make_local(tmp_path)
    server = make_server(tmp_path, branch="master")
    before = config_of(root)
    with pytest.raises(GitError) as info:
        gitsync.set_remote(root / "teams", str(server))
    assert info.value.kind == "new_branch" and config_of(root) == before
    assert "„main“" in str(info.value) and "master" in str(info.value)
    assert "Repository klonen" in str(info.value)  # der Weg für den Beitritt zu einem Team
    assert not info.value.hint
    saved = gitsync.set_remote(root / "teams", str(server), accept_new_branch=True)
    assert saved.verified and git(root, "remote", "get-url", "origin") == str(server)


def test_set_remote_without_commit_against_a_server_with_data_names_cloning(tmp_path: Path):
    """Frisch angelegter Ordner (noch kein Commit) und die Adresse des Team-Servers: Ohne
    Warnung würde der erste Upload auf dem Team-Server einen fremden Branch anlegen."""
    root = make_local(tmp_path, commit=False)
    server = make_server(tmp_path, branch="master")
    before = config_of(root)
    with pytest.raises(GitError) as info:
        gitsync.set_remote(root / "teams", str(server))
    assert info.value.kind == "new_branch" and config_of(root) == before
    assert "noch keine gespeicherten Daten" in str(info.value)
    assert "Repository klonen" in str(info.value) and "master" in str(info.value)
    assert gitsync.set_remote(root / "teams", str(server), accept_new_branch=True).verified


def test_new_branch_lists_at_most_five_names():
    error = gitmod.new_branch_error("main", tuple(f"b{i}" for i in range(9)))
    assert "b4" in str(error) and "b5" not in str(error) and "…" in str(error)
    error = gitmod.new_branch_error("main", tuple(f"b{i}" for i in range(9)), unborn=True)
    assert "b4" in str(error) and "b5" not in str(error) and "…" in str(error)


@pytest.mark.parametrize(
    "raw",
    [
        f"https://u:{SECRET}@127.0.0.1:1/r.git",
        f"https://127.0.0.1:1/r.git?token={SECRET}",
        "ext::sh -c touch% marker",
        "-x",
        "https://127.0.0.1:1/r.git\nhttps://127.0.0.1:1/zweite",
        "../relativ.git",
        "git://127.0.0.1/r.git",
    ],
)
def test_set_remote_rejects_bad_input_without_touching_the_configuration(tmp_path: Path, raw: str):
    root = make_local(tmp_path)
    before = config_of(root)
    with pytest.raises(GitError) as info:
        gitsync.set_remote(
            root / "teams", raw, allow_insecure=True, allow_offline=True, accept_new_branch=True
        )
    assert info.value.kind in {"bad_url", "secret_in_url"}
    assert_no_secret(info.value)
    assert config_of(root) == before and SECRET.encode() not in config_of(root)
    assert not (root / "marker").exists() and not (root / "teams" / "marker").exists()


def test_set_remote_never_touches_global_or_credential_settings(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    spy = SpyPopen(monkeypatch)
    gitsync.set_remote(root / "teams", str(make_server(tmp_path)))
    assert spy.calls
    for args, _ in spy.calls:
        assert "--global" not in args and "--system" not in args
        assert not any(a.startswith("credential") for a in args), args
        assert "fetch" not in args  # kein automatischer Abruf


def test_write_arguments_work_with_the_installed_git(tmp_path: Path):
    """Die Argumentstellung ``remote add -- NAME URL`` und ``remote set-url NAME -- URL``."""
    root = make_local(tmp_path)
    gitmod._git(root, "remote", "add", "--", "o", "https://a.example/x.git")
    gitmod._git(root, "remote", "set-url", "o", "--", "https://b.example/y.git")
    assert git(root, "remote", "get-url", "o") == "https://b.example/y.git"


# --- T9: remote_info ---------------------------------------------------------------------------


def test_remote_info_hides_stored_credentials(tmp_path: Path):
    root = make_local(tmp_path)
    git(root, "remote", "add", "origin", f"https://u:{SECRET}@h.example/r.git")
    info = gitsync.remote_info(root / "teams")
    assert info.name == "origin" and info.url == "https://h.example/r.git"
    assert info.has_secret and not info.special
    assert SECRET not in repr(info)


def test_cached_remote_info_follows_set_remote(tmp_path: Path):
    root = make_local(tmp_path)
    assert gitsync.cached_remote_info(root / "teams").name is None
    gitsync.set_remote(root / "teams", str(make_server(tmp_path)))
    assert gitsync.cached_remote_info(root / "teams").name == "origin"


def test_remote_info_without_server(tmp_path: Path):
    root = make_local(tmp_path, commit=False)
    info = gitsync.remote_info(root / "teams")
    assert info.name is None and info.url == "" and not info.has_secret
    assert info.others == () and info.special == ""
    assert info.branch == "main" and info.unborn  # frisch angelegt: Branch ohne Commit


def test_remote_info_reports_branch_and_unborn_state(tmp_path: Path):
    root = make_local(tmp_path)
    info = gitsync.remote_info(root / "teams")
    assert info.branch == "main" and not info.unborn
    git(root, "checkout", "-q", "--detach")
    gitmod.invalidate_status()
    info = gitsync.remote_info(root / "teams")
    assert info.branch is None and not info.unborn


def test_state_knows_a_repository_without_commit(tmp_path: Path):
    root = make_local(tmp_path, commit=False)
    assert gitsync.state(root / "teams").unborn
    git(root, "commit", "-q", "--allow-empty", "-m", "Start")
    assert not gitsync.state(root / "teams").unborn


def test_a_stored_address_with_a_token_is_scrubbed_from_sync_errors(
    tmp_path: Path, no_login_prompt
):
    """Der echte Leckpfad: Ein Altbestand mit ``?token=…`` in der Adresse. Git selbst druckt die
    Adresse samt Token („repository '…' not found“); erst ``GitError`` entfernt ihn."""
    root = make_local(tmp_path)
    with serve(NotFound) as port:
        git(root, "remote", "add", "origin", f"http://127.0.0.1:{port}/r.git?token={SECRET}")
        raw = subprocess.run(
            ["git", "fetch", "origin"], cwd=root, capture_output=True, text=True
        ).stderr
        if SECRET not in raw:
            pytest.skip("Diese Git-Version gibt die Adresse nicht aus; es gibt nichts zu entfernen")
        fetched = gitsync.fetch(root / "teams").fetch_error
        shared = gitsync.sync(root / "teams", "Teilen").error
    for error in (fetched, shared):
        assert error is not None and "not found" in str(error) and "/r.git" in str(error)
        assert_no_secret(error)


# --- Frisches Repository ohne Commit und „Speichern und teilen“ -------------------------------


def test_sync_without_any_data_says_there_is_nothing_to_share(tmp_path: Path):
    """Neuer Ordner ohne Dateien, Server mit Team-Daten (Branch ``master``): Es gibt nichts
    hochzuladen. Früher kam „Hochladen abgelehnt, weil inzwischen etwas Neues da ist“."""
    root = make_local(tmp_path, commit=False)
    server = make_server(tmp_path, branch="master")
    gitsync.set_remote(root / "teams", str(server), accept_new_branch=True)
    result = gitsync.sync(root / "teams", "Teilen")
    assert result.error is not None and result.error.kind == "nothing_to_share"
    assert "Repository klonen" in result.error.hint
    assert git(server, "for-each-ref", "--format=%(refname:short)", "refs/heads") == "master"


def test_sync_of_a_fresh_repository_with_files_still_uploads(tmp_path: Path):
    root = make_local(tmp_path, commit=False)
    server = make_server(tmp_path)
    gitsync.set_remote(root / "teams", str(server))
    (root / "teams" / "team.yaml").write_text("name: A\n", encoding="utf-8")
    gitmod.invalidate_status()
    result = gitsync.sync(root / "teams", "Start")
    assert result.ok and result.pushed, result.error
    assert git(server, "log", "-1", "--format=%s", "main") == "Start"


# --- T10: Klonen ------------------------------------------------------------------------------


def test_clone_rejects_option_like_and_unsafe_addresses(tmp_path: Path):
    for url in (
        "--upload-pack=touch boese",
        f"https://u:{SECRET}@127.0.0.1:1/r.git",
        "../relativ.git",
        "file:///tmp/x",
        "git://127.0.0.1/x",
        "ext::sh -c touch% x",
    ):
        with pytest.raises(GitError) as info:
            clone_repository(url, tmp_path / "ziel")
        assert info.value.kind in {"bad_url", "secret_in_url"}, url
        assert_no_secret(info.value)
        assert not (tmp_path / "ziel").exists()


def test_clone_works_and_restricts_the_protocols(
    alice: Person, remote: Path, tmp_path: Path, monkeypatch
):
    spy = SpyPopen(monkeypatch)
    clone_repository(str(remote), tmp_path / "geklont")
    assert (tmp_path / "geklont" / "teams" / "a" / "team.yaml").exists()
    [(args, env)] = spy.with_command("clone")
    assert env["GIT_ALLOW_PROTOCOL"] == "https:http:ssh:file"
    assert args[args.index("clone") + 1] == "--"
