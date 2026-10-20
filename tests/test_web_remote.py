# SPDX-License-Identifier: EUPL-1.2
"""Enter, check and save the server (remote) on the "Data folder" page (AppTest with real Git
repositories)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from gitrepos import SECRET, Denying, add_branches, assume_foreign_owner, make_server, serve

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from test_web_k3_ui import git, goto, main_button, open_merge, sidebar_button, start

from sprintforecast import git as gitmod
from sprintforecast import gitsync
from sprintforecast.git import classify, invalidate_status
from sprintforecast.storage import save_data_dir

FIELD = "git-remote-url"
OFFERS = {"git-remote-offline-save", "git-remote-branch-save"}


def walk(node, found: list | None = None) -> list:
    found = [] if found is None else found
    for child in getattr(node, "children", {}).values():
        found.append(child)
        walk(child, found)
    return found


def all_text(at: AppTest) -> str:
    """Everything the page shows or holds in the session state (elements with labels, input values,
    state)."""
    parts = [str(e.proto) for root in (at.main, at.sidebar) for e in walk(root)]
    parts += [str(e.value) for e in at.text_input]
    parts += [f"{key}={value!r}" for key, value in at.session_state.items()]
    return "\n".join(parts)


def shown(at: AppTest, kind: str, where: str = "main") -> str:
    return "\n".join(e.value for e in getattr(getattr(at, where), kind))


def page_links(at: AppTest) -> list[str]:
    return [e.proto.label for e in walk(at.sidebar) if type(e).__name__ == "PageLink"]


def offers(at: AppTest) -> set[str]:
    """The buttons "Save anyway" and "Yes, this is the right data repository"."""
    return {b.key for b in at.button if b.key in OFFERS}


def enter(at: AppTest, value: str) -> AppTest:
    at.text_input(key=FIELD).set_value(value).run()
    assert not at.exception, at.exception
    return at


def click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def data_folder_page(data_dir: Path, monkeypatch) -> AppTest:
    return goto(start(data_dir, monkeypatch), "data_dir")


def remotes(root: Path) -> str:
    return git(root, "remote")


def servers(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("server")


# --- U1/U2: from "no server" to "Save and share" ----------------------------------------------


def test_sidebar_offers_the_setup_and_the_page_shows_the_section(
    repo: Path, data_dir: Path, monkeypatch
):
    at = start(data_dir, monkeypatch)
    assert "Kein Server eingerichtet" in shown(at, "caption", "sidebar")
    assert page_links(at) == ["Server einrichten"]
    assert not [b for b in at.sidebar.button if b.label == "Speichern und teilen"]
    goto(at, "data_dir")
    assert [s.value for s in at.main.subheader] == ["Server (Remote)", "Zeilenenden festlegen"]
    assert "noch kein Server" in shown(at, "info")
    assert "Repository klonen" in shown(at, "info")  # the way to join a team
    assert at.button(key="git-remote-check").disabled and at.button(key="git-remote-save").disabled
    assert at.text_input(key=FIELD).value == ""


def test_check_and_save_buttons_sit_next_to_each_other(repo: Path, data_dir: Path, monkeypatch):
    """The "Check connection" and "Save" buttons belong together: one horizontal container in
    which the buttons start on the left and are only as wide as their text (formerly two
    equally wide columns, the buttons far apart)."""
    from streamlit.proto.Block_pb2 import Block

    at = data_folder_page(data_dir, monkeypatch)
    group = next(
        node
        for node in walk(at.main)
        if {"git-remote-check", "git-remote-save"}
        <= {getattr(c, "key", None) for c in getattr(node, "children", {}).values()}
    )
    assert group.type == "flex_container"
    assert group.proto.flex_container.direction == Block.FlexContainer.Direction.HORIZONTAL
    assert [c.key for c in group.children.values()] == ["git-remote-check", "git-remote-save"]
    # left-aligned (not spread apart)
    assert group.proto.flex_container.justify == Block.FlexContainer.Justify.JUSTIFY_START


def test_check_then_save_then_share(repo: Path, data_dir: Path, tmp_path_factory, monkeypatch):
    server = make_server(servers(tmp_path_factory))
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, str(server))
    assert not at.button(key="git-remote-check").disabled

    click(at, "git-remote-check")
    assert any("Verbindung hergestellt" in s.value for s in at.success)
    assert "noch keine Branches" in shown(at, "info")
    assert remotes(repo) == ""  # checking changes nothing

    click(at, "git-remote-save")
    assert git(repo, "remote", "get-url", "origin") == str(server)
    assert any("Server gespeichert" in s.value for s in at.success)
    assert at.text_input(key=FIELD).value == ""
    status = shown(at, "caption", "sidebar")
    assert "Serverstand noch nicht geprüft" in status
    # Nothing is on the empty server yet: "in sync" would be wrong.
    assert "noch nicht auf dem Server" in status and "synchron" not in status
    assert page_links(at) == []
    assert sidebar_button(at, "Speichern und teilen")

    sidebar_button(at, "Speichern und teilen").click().run()
    assert not at.exception, at.exception
    assert any("Hochgeladen" in s.value for s in at.sidebar.success)
    assert git(server, "log", "-1", "--format=%s", "main") == "init"
    assert "synchron mit `origin/main`" in shown(at, "caption", "sidebar")


# --- U3/U4: credentials and dangerous addresses -----------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        f"https://nutzer:{SECRET}@git.example.com/t/d.git",
        f"https://{SECRET}@git.example.com/t/d.git",
        f"https://git.example.com/t/d.git?token={SECRET}",
        f"ssh://nutzer:{SECRET}@git.example.com/t/d.git",
        "https://anna@bitbucket.org/team/daten.git",  # how Bitbucket and Azure DevOps show them
    ],
)
def test_credentials_in_the_address_are_rejected_and_never_shown(
    repo: Path, data_dir: Path, monkeypatch, raw: str
):
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, raw)
    errors = shown(at, "error")
    assert errors.count("Zugangsdaten gehören nicht in die Adresse") == 1  # only as a heading
    assert "Benutzernamen" in errors
    # The message says that the input was discarded and what to do.
    assert "Feld geleert" in shown(at, "caption") and "neu eintragen" in shown(at, "caption")
    assert at.text_input(key=FIELD).value == ""
    assert at.button(key="git-remote-check").disabled and at.button(key="git-remote-save").disabled
    assert SECRET not in all_text(at)
    assert remotes(repo) == "" and SECRET not in (repo / ".git" / "config").read_text()
    enter(at, "")  # the notice appears only once
    assert "Zugangsdaten gehören nicht in die Adresse" not in shown(at, "error")
    assert "Feld geleert" not in shown(at, "caption")


@pytest.mark.parametrize("raw", ['ext::sh -c "touch marker"', "-oProxyCommand=x", "git://h/x"])
def test_dangerous_addresses_are_rejected(repo: Path, data_dir: Path, monkeypatch, raw: str):
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, raw)
    assert "Ungültige Adresse" in shown(at, "error")
    assert at.button(key="git-remote-check").disabled and at.button(key="git-remote-save").disabled
    assert remotes(repo) == ""
    assert not (repo / "marker").exists() and not Path("marker").exists()


def test_invalid_address_shows_its_title_once(repo: Path, data_dir: Path, monkeypatch):
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, "github.com/team/daten")
    errors = shown(at, "error")
    assert errors.count("Ungültige Adresse") == 1
    assert "Das Format wird nicht erkannt" in errors and "https://server/team/daten.git" in errors


def test_clone_tab_names_the_reason_for_a_bad_address(repo: Path, data_dir: Path, monkeypatch):
    """As with the server: the heading (exactly once) above the reason."""
    at = data_folder_page(data_dir, monkeypatch)
    address = next(e for e in at.text_input if e.label == "Adresse")
    address.set_value("github.com/team/daten").run()
    click(at, "data-clone-go")
    errors = shown(at, "error")
    assert errors.count("Ungültige Adresse") == 1
    assert errors.startswith("**Ungültige Adresse**") and "Das Format wird nicht erkannt" in errors


def clone(at: AppTest, url: str, target: Path) -> AppTest:
    next(e for e in at.text_input if e.label == "Adresse").set_value(url).run()  # enables "Clone"
    at.text_input(key="data-clone").set_value(str(target))
    return click(at, "data-clone-go")


def test_clone_tab_shows_the_next_step_for_a_missing_repository(
    repo: Path, data_dir: Path, tmp_path: Path, monkeypatch
):
    """Only Git's message was there; the next step (check the address) was missing."""
    at = clone(
        data_folder_page(data_dir, monkeypatch), str(tmp_path / "gibt-es-nicht.git"), tmp_path / "z"
    )
    errors = shown(at, "error")
    # Git's message is under "Technical message". Which one it is depends on the path:
    # "repository '...' does not exist" for a path without a colon (Linux, macOS), on Windows
    # with a drive letter "'...' does not appear to be a git repository".
    assert "Repository nicht gefunden" in errors and re.search(
        r"does not exist|does not appear to be a git repository",
        "\n".join(c.value for c in at.code),
    )
    assert "Das Repository wurde nicht gefunden" in errors and "VPN" not in errors


def test_clone_tab_names_the_fingerprint_for_an_unknown_ssh_server(
    repo: Path, data_dir: Path, tmp_path: Path, monkeypatch
):
    real = gitmod._git_result

    def host_key_failure(cwd, *args, **kwargs):
        if args[:1] == ("clone",):
            message = "Host key verification failed.\nfatal: Could not read from remote repository."
            return subprocess.CompletedProcess(args, 128, "", message)
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(gitmod, "_git_result", host_key_failure)
    at = clone(
        data_folder_page(data_dir, monkeypatch), "git@example.org:team/daten.git", tmp_path / "z"
    )
    errors = shown(at, "error")
    assert "Fingerabdruck" in errors and "ssh-keygen" not in errors


def test_unsafe_folder_is_named_on_the_data_folder_page(repo: Path, data_dir: Path, monkeypatch):
    """Instead of "is not inside a Git repository" (and the offer to create one)."""
    assume_foreign_owner(monkeypatch, repo)
    at = data_folder_page(data_dir, monkeypatch)
    assert "Git hält den Ordner für unsicher" in shown(at, "error")
    assert "keinem Git-Repository" not in shown(at, "caption")
    at.text_input(key="data-path").set_value(str(repo))
    main_button(at, "Übernehmen").click().run()
    assert not at.exception, at.exception
    assert "Git hält den Ordner für unsicher" in shown(at, "error")
    assert not [w for w in at.warning if "keinem Git-Repository" in w.value]
    # Git's advice about "safe.directory" appears nowhere, not even under "Technical message".
    assert "safe.directory" not in shown(at, "error") + "\n".join(c.value for c in at.code)
    # The app also works without Git: "Use without Git" remains, creating a repository there
    # (git init in a foreign folder) is not offered.
    assert "offer-init" in at.session_state
    labels = [b.label for b in at.button]
    assert "Ohne Git verwenden" in labels
    assert not [label for label in labels if label.startswith("Git-Repository in")]
    assert not (repo / ".gitignore").exists()


# --- U5-U8: error cases and confirmations -----------------------------------------------------


def test_missing_repository_is_not_found_and_not_offered(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    missing = servers(tmp_path_factory) / "gibt-es-nicht.git"
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, str(missing))
    for key in ("git-remote-check", "git-remote-save"):
        click(at, key)
        assert "Repository nicht gefunden" in shown(at, "error")
        assert "Server nicht erreichbar" not in shown(at, "error")
        assert not offers(at)
    assert remotes(repo) == ""


@pytest.mark.parametrize(
    ("stderr", "title"),
    [
        # GitLab over SSH, typo in the project name: the server responds.
        (
            "remote: ERROR: The project you were looking for could not be found or you don't "
            "have permission to view it.\nfatal: Could not read from remote repository.",
            "Repository nicht gefunden",
        ),
        (
            "fatal: unable to access 'https://h/r.git/': SSL certificate problem: unable to "
            "get local issuer certificate",
            "Zertifikat des Servers nicht anerkannt",
        ),
        ("fatal: Could not read from remote repository.", "Git-Fehler"),
    ],
)
def test_answers_that_are_not_unreachability_are_never_offered_for_saving(
    repo: Path, data_dir: Path, monkeypatch, stderr: str, title: str
):
    monkeypatch.setattr(gitmod, "_probe_run", lambda *a: gitmod._ProbeRun(128, "", stderr))
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, "git@gitlab.example:team/tippfehler.git")
    for key in ("git-remote-check", "git-remote-save"):
        click(at, key)
        assert title in shown(at, "error")
        assert "Server nicht erreichbar" not in shown(at, "error")
        assert "Internet" not in shown(at, "error")  # no hint about internet or VPN
        assert not offers(at)
    assert remotes(repo) == ""


def test_http_needs_confirmation_and_unreachable_server_can_be_saved_anyway(
    repo: Path, data_dir: Path, monkeypatch
):
    url = "http://127.0.0.1:1/r.git"
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, url)
    assert "Unverschlüsselte Verbindung" in shown(at, "error")
    assert at.button(key="git-remote-check").disabled and at.button(key="git-remote-save").disabled
    at.checkbox(key="git-remote-insecure").check().run()
    assert not at.exception, at.exception
    assert not at.button(key="git-remote-check").disabled

    click(at, "git-remote-check")
    assert "Server nicht erreichbar" in shown(at, "error")
    assert "Tippfehler" in shown(at, "error")
    assert remotes(repo) == ""
    click(at, "git-remote-offline-save")
    assert git(repo, "remote", "get-url", "origin") == url
    assert any("nicht geprüft" in w.value for w in at.warning)
    assert at.text_input(key=FIELD).value == ""
    assert "git-remote-offer" not in at.session_state


def test_the_offer_disappears_when_the_address_changes(repo: Path, data_dir: Path, monkeypatch):
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, "http://127.0.0.1:1/r.git")
    at.checkbox(key="git-remote-insecure").check().run()
    click(at, "git-remote-save")
    assert offers(at) == {"git-remote-offline-save"}
    enter(at, "http://127.0.0.1:1/andere.git")
    assert not offers(at)
    assert "git-remote-offer" not in at.session_state
    assert remotes(repo) == ""


@pytest.mark.usefixtures("no_login_prompt")
def test_missing_login_is_explained_and_nothing_is_saved(repo: Path, data_dir: Path, monkeypatch):
    with serve(Denying) as port:
        at = data_folder_page(data_dir, monkeypatch)
        enter(at, f"http://127.0.0.1:{port}/r.git")
        at.checkbox(key="git-remote-insecure").check().run()
        click(at, "git-remote-save")
    assert "Anmeldung fehlt oder wurde abgelehnt" in shown(at, "error")
    assert "Zugangstoken" in shown(at, "error")
    assert shown(at, "error").count("fehlt oder wurde abgelehnt") == 1  # heading only once
    assert "gh auth setup-git" in shown(at, "error")  # https: the steps for https
    assert "ssh-keygen" not in shown(at, "error")
    assert not offers(at)
    assert remotes(repo) == ""


def test_missing_branch_needs_confirmation(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    server = make_server(servers(tmp_path_factory), branch="master")
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, str(server))
    click(at, "git-remote-save")
    warning = shown(at, "warning")
    assert "Branch fehlt auf dem Server" in warning and "master" in warning
    assert remotes(repo) == ""
    assert not at.exception

    click(at, "git-remote-branch-save")
    assert git(repo, "remote", "get-url", "origin") == str(server)
    assert any("Server gespeichert" in s.value for s in at.success)


def test_check_with_a_missing_branch_leads_to_the_confirmation(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    """First check, then confirm the branch: the offer already comes from the check."""
    server = make_server(servers(tmp_path_factory), branch="master")
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, str(server))
    click(at, "git-remote-check")
    assert any("Verbindung hergestellt" in s.value for s in at.success)
    assert "Branches auf dem Server: `master`" in shown(at, "caption")
    warning = shown(at, "warning")
    assert "Branch fehlt auf dem Server" in warning
    assert "„`main`“" in warning and "(vorhanden: `master`)" in warning
    assert "Repository klonen" in warning  # the way to join a team
    assert offers(at) == {"git-remote-branch-save"}
    assert remotes(repo) == ""

    click(at, "git-remote-branch-save")
    assert git(repo, "remote", "get-url", "origin") == str(server)
    assert any("Server gespeichert" in s.value for s in at.success)


def test_check_lists_the_branches_and_offers_nothing_when_the_branch_exists(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    server = make_server(servers(tmp_path_factory), branch="main")
    add_branches(server, [f"feature/{n}" for n in range(8)])
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, str(server))
    click(at, "git-remote-check")
    names = ", ".join(f"`feature/{n}`" for n in range(5))
    assert f"Branches auf dem Server: {names}, …" in shown(at, "caption")  # shortened to five
    assert not offers(at) and "git-remote-offer" not in at.session_state
    assert "Branch fehlt auf dem Server" not in shown(at, "warning")


def test_names_from_the_server_are_shown_as_code_not_as_links(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    """A branch is named like a web address: as Markdown it would become a link."""
    server = make_server(servers(tmp_path_factory), branch="master")
    add_branches(server, ["www.evil.example/anmelden", "a`b"])
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, str(server))
    click(at, "git-remote-check")
    text = shown(at, "caption") + "\n" + shown(at, "warning")
    assert "`www.evil.example/anmelden`" in text and "``a`b``" in text
    outside = re.sub(r"(`+).+?\1", "", text)  # everything outside of code spans
    assert "evil" not in outside and "anmelden" not in outside

    click(at, "git-remote-save")  # the same warning when saving
    outside = re.sub(r"(`+).+?\1", "", shown(at, "warning"))
    assert "Branch fehlt auf dem Server" in outside and "evil" not in outside


def test_a_stored_address_with_a_backtick_is_shown_as_code(repo: Path, data_dir: Path, monkeypatch):
    git(repo, "remote", "add", "origin", "https://h.example/a`b.git")
    invalidate_status()
    at = data_folder_page(data_dir, monkeypatch)
    assert "Server `origin`: ``https://h.example/a`b.git``" in shown(at, "markdown")


def test_a_saved_address_with_a_backtick_is_shown_as_code(repo: Path, data_dir: Path, monkeypatch):
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, "http://127.0.0.1:1/a`b.git")
    at.checkbox(key="git-remote-insecure").check().run()
    click(at, "git-remote-save")
    click(at, "git-remote-offline-save")
    assert any("``http://127.0.0.1:1/a`b.git``" in w.value for w in at.warning)


# --- Freshly created folder: joining a team -----------------------------------------------------


def test_a_new_folder_with_the_address_of_a_team_server_warns_and_names_cloning(
    data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    git(data_dir.parent, "init", "-q", "-b", "main")  # a repository, still without a commit
    invalidate_status()
    server = make_server(servers(tmp_path_factory), branch="master")
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, str(server))
    click(at, "git-remote-check")
    warning = shown(at, "warning")
    assert "noch keine gespeicherten Daten" in warning and "Repository klonen" in warning
    assert offers(at) == {"git-remote-branch-save"}
    assert remotes(data_dir.parent) == ""

    click(at, "git-remote-save")
    assert "noch keine gespeicherten Daten" in shown(at, "warning")
    assert remotes(data_dir.parent) == ""
    click(at, "git-remote-branch-save")
    assert git(data_dir.parent, "remote", "get-url", "origin") == str(server)
    assert "noch keine Daten gespeichert" in shown(at, "caption", "sidebar")


# --- Notices point to the form ------------------------------------------------------------------


def test_a_wrong_address_error_links_to_the_server_section(shared, data_dir: Path, monkeypatch):
    at = start(data_dir, monkeypatch)
    assert page_links(at) == []  # there is a server: no "Set up server"
    at.session_state["sync_result"] = gitsync.SyncResult(
        error=classify("remote: Repository not found.")
    )
    at.run()
    assert not at.exception, at.exception
    assert page_links(at) == ["Server-Adresse ändern"]
    assert "Repository nicht gefunden" in shown(at, "error", "sidebar")
    assert "Server (Remote)" in shown(at, "error", "sidebar")


# --- U9: legacy data with credentials ---------------------------------------------------------


def test_stored_credentials_are_neither_shown_nor_prefilled(
    shared, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    root, _bob, _server = shared
    git(root, "remote", "set-url", "origin", f"https://nutzer:{SECRET}@h.example/x.git")
    invalidate_status()
    at = data_folder_page(data_dir, monkeypatch)
    assert SECRET not in all_text(at)
    assert "`https://h.example/x.git`" in shown(at, "markdown")
    assert "Zugangsdaten" in shown(at, "warning")
    assert at.text_input(key=FIELD).value == ""
    assert at.text_input(key=FIELD).label == "Neue Server-Adresse"

    new = make_server(servers(tmp_path_factory))
    enter(at, str(new))
    click(at, "git-remote-save")
    assert git(root, "remote", "get-url", "origin") == str(new)
    assert git(root, "config", "branch.main.remote") == "origin"
    assert SECRET not in (root / ".git" / "config").read_text()
    assert SECRET not in all_text(at)


# --- U10: open merge, unusual server settings -------------------------------------------------


def test_open_merge_blocks_saving_but_not_checking(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    open_merge(repo)
    config = (repo / ".git" / "config").read_bytes()
    server = make_server(servers(tmp_path_factory))
    at = data_folder_page(data_dir, monkeypatch)
    assert "Zusammenführen ist unvollständig" in shown(at, "warning")
    enter(at, str(server))
    assert at.button(key="git-remote-save").disabled
    assert not at.button(key="git-remote-check").disabled
    click(at, "git-remote-check")
    assert any("Verbindung hergestellt" in s.value for s in at.success)
    assert (repo / ".git" / "config").read_bytes() == config


@pytest.mark.parametrize("special", ["pushurl", "multi_url"])
def test_unusual_server_settings_block_saving_but_not_checking(
    repo: Path,
    data_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch,
    special: str,
):
    work = servers(tmp_path_factory)
    git(repo, "remote", "add", "origin", str(make_server(work, "alt.git")))
    if special == "pushurl":
        git(repo, "config", "remote.origin.pushurl", str(work / "anderswo.git"))
    else:
        git(repo, "config", "--add", "remote.origin.url", str(work / "zweite.git"))
    invalidate_status()
    config = (repo / ".git" / "config").read_bytes()
    at = data_folder_page(data_dir, monkeypatch)
    assert "mehrere Adressen" in shown(at, "warning")  # the explanation of why nothing works
    enter(at, str(make_server(work, "neu.git")))
    assert at.button(key="git-remote-save").disabled
    assert not at.button(key="git-remote-check").disabled
    click(at, "git-remote-check")
    assert any("Verbindung hergestellt" in s.value for s in at.success)
    assert (repo / ".git" / "config").read_bytes() == config


def test_other_servers_are_listed_and_stay_untouched(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    work = servers(tmp_path_factory)
    first, second = make_server(work, "eins.git"), make_server(work, "zwei.git")
    git(repo, "remote", "add", "origin", str(first))
    git(repo, "push", "-q", "-u", "origin", "main")
    git(repo, "remote", "add", "zweit", str(second))
    invalidate_status()
    at = data_folder_page(data_dir, monkeypatch)
    assert "Weitere Server (werden nicht verändert): `zweit`" in shown(at, "caption")

    new = make_server(work, "neu.git")
    enter(at, str(new))
    click(at, "git-remote-save")
    assert git(repo, "remote", "get-url", "origin") == str(new)
    assert git(repo, "remote", "get-url", "zweit") == str(second)


# --- U11: folder switch -----------------------------------------------------------------------


def test_folder_switch_drops_input_and_never_writes_to_the_wrong_folder(
    repo: Path,
    data_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch,
):
    first_server = make_server(servers(tmp_path_factory), "eins.git")
    git(repo, "remote", "add", "origin", str(first_server))
    other = tmp_path_factory.mktemp("zweiter")
    other_data = other / "teams"
    shutil.copytree(data_dir / "demo", other_data / "zweit")
    git(other, "init", "-q", "-b", "main")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "init")
    other_server = make_server(servers(tmp_path_factory), "zwei.git")
    git(other, "remote", "add", "origin", str(other_server))
    save_data_dir(other_data)
    save_data_dir(data_dir)
    typed = make_server(servers(tmp_path_factory), "getippt.git")

    at = data_folder_page(data_dir, monkeypatch)
    enter(at, str(typed))
    sidebar_button(at, "Wechseln").click().run()
    assert not at.exception, at.exception
    assert at.text_input(key=FIELD).value == ""  # the input belonged to the old folder
    assert "git-remote-offer" not in at.session_state
    assert git(other, "remote", "get-url", "origin") == str(other_server)

    # In folder B the address must be typed again; it is saved only there.
    assert at.button(key="git-remote-save").disabled
    enter(at, str(typed))
    click(at, "git-remote-save")
    assert git(other, "remote", "get-url", "origin") == str(typed)
    assert git(repo, "remote", "get-url", "origin") == str(first_server)  # folder A unchanged


def test_folder_switch_drops_a_pending_offer(repo: Path, data_dir: Path, monkeypatch):
    other = repo.parent / "zweiter-ordner"
    shutil.copytree(data_dir / "demo", other / "zweit")
    save_data_dir(other)
    save_data_dir(data_dir)
    at = data_folder_page(data_dir, monkeypatch)
    enter(at, "http://127.0.0.1:1/r.git")
    at.checkbox(key="git-remote-insecure").check().run()
    click(at, "git-remote-save")
    assert "git-remote-offer" in at.session_state
    sidebar_button(at, "Wechseln").click().run()
    assert not at.exception, at.exception
    assert "git-remote-offer" not in at.session_state
    assert not offers(at)
    assert remotes(repo) == ""


# --- U12: without repository, setup, English --------------------------------------------------


def test_no_section_without_a_git_repository(data_dir: Path, monkeypatch):
    at = data_folder_page(data_dir, monkeypatch)
    assert [e for e in at.text_input if e.key == FIELD] == []
    assert "Server (Remote)" not in [s.value for s in at.subheader]
    assert "liegt in keinem Git-Repository" in shown(at, "caption")


def test_no_section_in_the_setup(tmp_path: Path, monkeypatch):
    empty = tmp_path / "leer"
    empty.mkdir()
    at = start(empty, monkeypatch)
    assert [h.value for h in at.header] == ["Datenordner"]
    assert [e for e in at.text_input if e.key == FIELD] == []


def test_section_in_english(repo: Path, data_dir: Path, monkeypatch, english):
    at = data_folder_page(data_dir, monkeypatch)
    assert [s.value for s in at.subheader] == ["Server (remote)", "Set line endings"]
    assert at.text_input(key=FIELD).label == "Server address"
    assert page_links(at) == ["Set up server"]
    assert "Clone repository" in shown(at, "info")
    enter(at, "x.git")
    errors = shown(at, "error")
    assert "Invalid address" in errors and "The format is not recognised" in errors
    assert "Ungültig" not in errors and "Das Format" not in errors


# --- U13: "no server" notice ------------------------------------------------------------------


def test_no_server_hint_names_the_page_and_link_and_problem_can_share_a_run(
    repo: Path, data_dir: Path, monkeypatch
):
    at = start(data_dir, monkeypatch)
    at.session_state["sync_result"] = gitsync.sync(data_dir, "egal")
    at.run()
    assert not at.exception, at.exception
    errors = shown(at, "error", "sidebar")
    assert "Kein Server eingerichtet" in errors and "Datenordner" in errors
    assert "remote add" not in all_text(at) and "Terminal" not in errors
    assert page_links(at) == ["Server einrichten"]
    # Also on the "Data folder" page itself (link, problem and form in the same run).
    at.session_state["sync_result"] = gitsync.sync(data_dir, "egal")
    goto(at, "data_dir")
    assert at.text_input(key=FIELD) is not None
    assert "Datenordner" in shown(at, "error", "sidebar")


def test_attributes_offer_is_written_only_on_click_and_shows_as_a_change(
    repo: Path, data_dir: Path, monkeypatch
):
    (data_dir / "crlf.yaml").write_bytes(b"x: 1\r\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "CRLF")
    at = data_folder_page(data_dir, monkeypatch)
    assert not (data_dir / ".gitattributes").exists()
    assert "crlf.yaml" in [row for df in at.main.dataframe for row in df.value["Datei"]]
    click(at, "attributes-apply")
    assert (data_dir / ".gitattributes").is_file()
    assert not [s for s in at.main.subheader if s.value == "Zeilenenden festlegen"]
