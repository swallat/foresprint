# SPDX-License-Identifier: EUPL-1.2
"""Token sign-in (A4.4) and setup checklist (A4.5): the token goes only to Git's credential
helper. The tests use a stand-in helper that writes its input to a file, and no real network."""

import subprocess
import sys
from pathlib import Path

import pytest
from gitrepos import make_server

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from test_web_k3_ui import git, goto, start
from test_web_remote import all_text, shown

from sprintforecast import signin
from sprintforecast.git import GitError, invalidate_status
from sprintforecast.web import ui

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Ersatz-Dienst ist ein Shell-Skript"
)

URL = "https://git.example.com/team/sprint-daten.git"
TOKEN = "glpat-GEHEIM-12345"


@pytest.fixture(autouse=True)
def own_git_config(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """The tests write ``--global`` settings: never into the computer's own."""
    home = tmp_path_factory.mktemp("home")
    config = home / "gitconfig"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GCM_INTERACTIVE", "never")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture
def helper_log(tmp_path: Path) -> Path:
    """Registers a stand-in credential helper: it appends action and input to a file."""
    log = tmp_path / "helper.log"
    script = tmp_path / "helper.sh"
    script.write_text(f'#!/bin/sh\necho "== $1" >> "{log}"\ncat >> "{log}"\n')
    script.chmod(0o755)
    subprocess.run(
        ["git", "config", "--global", "credential.helper", f"!{script}"],
        check=True,
    )
    return log


def test_https_parts_accepts_only_plain_https():
    assert signin.https_parts(URL) == ("git.example.com", "team/sprint-daten.git")
    assert signin.https_parts("https://git.example.com:8443/a.git")[0] == "git.example.com:8443"
    for bad in ("git@git.example.com:t/r.git", "http://h/r.git", "https://u:p@h/r.git", "/tmp/x"):
        with pytest.raises(GitError):
            signin.https_parts(bad)
        assert not signin.is_https(bad)


def test_store_token_hands_it_to_the_helper(tmp_path: Path, helper_log: Path):
    signin.store_token(tmp_path, URL, "oauth2", TOKEN)
    log = helper_log.read_text()
    assert "== store" in log
    assert "host=git.example.com" in log and "username=oauth2" in log
    assert f"password={TOKEN}" in log


def test_store_token_refuses_without_helper(tmp_path: Path):
    with pytest.raises(GitError) as caught:
        signin.store_token(tmp_path, URL, "oauth2", TOKEN)
    assert TOKEN not in str(caught.value) and TOKEN not in caught.value.hint


def test_store_token_refuses_plain_text_helper(tmp_path: Path):
    subprocess.run(["git", "config", "--global", "credential.helper", "store"], check=True)
    assert signin.helper_state(tmp_path) == "plain"
    with pytest.raises(GitError) as caught:
        signin.store_token(tmp_path, URL, "oauth2", TOKEN)
    assert "Klartext" in str(caught.value)
    assert not (Path.home() / ".git-credentials").exists()


@pytest.mark.parametrize(
    ("user", "token"), [("", TOKEN), ("u", ""), ("u", "a\nb"), ("u\nhost=evil", TOKEN)]
)
def test_store_token_rejects_empty_and_multiline_input(tmp_path, helper_log, user, token):
    with pytest.raises(GitError) as caught:
        signin.store_token(tmp_path, URL, user, token)
    assert TOKEN not in str(caught.value)
    assert not helper_log.exists()


def test_helper_given_by_full_path_is_still_recognised(tmp_path: Path):
    for value in (
        "/usr/lib/git-core/git-credential-store --file=x",
        "C:/Program Files/Git/git-credential-store.exe",
        "C:\\Git\\git-credential-store.exe",
    ):
        subprocess.run(["git", "config", "--global", "credential.helper", value], check=True)
        assert signin.helper_state(tmp_path) == "plain", value


def test_odd_addresses_do_not_crash():
    assert not signin.is_https("https://h:abc/x")
    assert signin.https_parts("https://[::1]:8443/x.git")[0] == "[::1]:8443"


def test_forget_one_token_names_user_and_password(tmp_path: Path, helper_log: Path):
    signin.forget_token(tmp_path, URL, "oauth2", TOKEN)
    assert f"password={TOKEN}" in helper_log.read_text()


def test_forget_token_rejects_the_entry(tmp_path: Path, helper_log: Path):
    signin.forget_token(tmp_path, URL)
    log = helper_log.read_text()
    assert "== erase" in log and "host=git.example.com" in log and "password" not in log


def test_verify_lists_branches(tmp_path: Path):
    server = make_server(tmp_path)
    assert isinstance(signin.verify(tmp_path, str(server)), tuple)


def test_enable_helper_only_offers_the_suggested_one(monkeypatch):
    monkeypatch.setattr(signin, "_helper_exists", lambda name: name == "libsecret")
    monkeypatch.setattr(sys, "platform", "linux")
    assert signin.suggested_helper() == "libsecret"
    for bad in ("store", "cache", "!rm -rf"):
        with pytest.raises(GitError):
            signin.enable_helper(bad)
    signin.enable_helper("libsecret")
    out = subprocess.run(
        ["git", "config", "--global", "credential.helper"], capture_output=True, text=True
    ).stdout.strip()
    assert out == "libsecret"


def test_no_suggestion_without_a_safe_helper(monkeypatch):
    monkeypatch.setattr(signin, "_helper_exists", lambda name: False)
    assert signin.suggested_helper() is None


def test_setup_items_follow_the_state(repo: Path, helper_log: Path):
    items = {i.key: i for i in signin.setup_items(repo)}
    assert items["git"].ok and items["folder"].ok and not items["server"].ok
    git(repo, "remote", "add", "origin", URL)
    invalidate_status()
    items = {i.key: i for i in signin.setup_items(repo)}
    assert items["server"].ok and items["login"].ok  # Ersatz-Dienst eingetragen
    subprocess.run(["git", "config", "--global", "--unset", "credential.helper"], check=True)
    items = {i.key: i for i in signin.setup_items(repo)}
    assert not items["login"].ok
    git(repo, "remote", "set-url", "origin", "git@git.example.com:team/daten.git")
    invalidate_status()
    assert {i.key: i for i in signin.setup_items(repo)}["login"].ok  # SSH: no token sign-in


def test_setup_items_without_repository(tmp_path: Path):
    keys = [i.key for i in signin.setup_items(tmp_path)]
    assert keys == ["git", "folder"]


# --- UI -------------------------------------------------------------------------------


def with_remote(repo: Path, data_dir: Path, monkeypatch) -> AppTest:
    git(repo, "remote", "add", "origin", URL)
    return goto(start(data_dir, monkeypatch), "datenordner")


def submit(at: AppTest, user: str, token: str) -> AppTest:
    at.text_input(key="signin-user").set_value(user)
    at.text_input(key="signin-token").set_value(token)
    next(b for b in at.button if b.label == "Token speichern und prüfen").click().run()
    assert not at.exception, at.exception
    return at


def test_page_stores_the_token_and_never_shows_it(
    repo: Path, data_dir: Path, helper_log: Path, monkeypatch
):
    monkeypatch.setattr(ui, "verify", lambda root, url: ("main",))
    at = with_remote(repo, data_dir, monkeypatch)
    assert "Anmeldung einrichten" in [s.value for s in at.main.subheader]
    submit(at, "oauth2", TOKEN)
    assert f"password={TOKEN}" in helper_log.read_text()
    assert any("Angemeldet" in s.value for s in at.success)
    assert TOKEN not in all_text(at)
    assert at.text_input(key="signin-token").value == ""


def test_page_forgets_a_rejected_token(repo: Path, data_dir: Path, helper_log: Path, monkeypatch):
    def refuse(root, url):
        raise GitError("HTTP Basic: Access denied", "auth", "Token abgelehnt")

    monkeypatch.setattr(ui, "verify", refuse)
    at = with_remote(repo, data_dir, monkeypatch)
    submit(at, "oauth2", TOKEN)
    assert "== erase" in helper_log.read_text()
    assert "Token abgelehnt" in shown(at, "error")
    assert TOKEN not in all_text(at)


def test_page_offers_no_token_entry_without_a_helper(repo: Path, data_dir: Path, monkeypatch):
    monkeypatch.setattr(signin, "_helper_exists", lambda name: False)
    at = with_remote(repo, data_dir, monkeypatch)
    assert "keinen sicheren Anmeldedienst" in shown(at, "info")
    submit_button = next(b for b in at.button if b.label == "Token speichern und prüfen")
    assert submit_button.disabled


def test_page_enables_the_suggested_helper_on_request(repo: Path, data_dir: Path, monkeypatch):
    monkeypatch.setattr(signin, "_helper_exists", lambda name: name == "libsecret")
    monkeypatch.setattr(sys, "platform", "linux")
    at = with_remote(repo, data_dir, monkeypatch)
    at.button(key="signin-helper").click().run()
    assert not at.exception, at.exception
    assert signin.helper_state(repo) == "ok"
    assert not [b for b in at.button if b.key == "signin-helper"]


def test_no_token_section_for_ssh_addresses(repo: Path, data_dir: Path, monkeypatch):
    git(repo, "remote", "add", "origin", "git@git.example.com:team/daten.git")
    at = goto(start(data_dir, monkeypatch), "datenordner")
    assert "Anmeldung einrichten" not in [s.value for s in at.main.subheader]


def test_start_page_shows_and_hides_the_checklist(repo: Path, data_dir: Path, monkeypatch):
    at = start(data_dir, monkeypatch)
    text = "\n".join(w.value for w in at.main.markdown)
    assert "**Einrichtung**" in text and "noch kein Server" in "\n".join(
        w.value for w in at.main.markdown
    )
    at.button(key="setup-hide").click().run()
    assert "**Einrichtung**" not in "\n".join(w.value for w in at.main.markdown)
