# SPDX-License-Identifier: EUPL-1.2
"""Server (Remote) auf der Seite „Datenordner“ eintragen, prüfen und speichern (AppTest mit
echten Git-Repositories)."""

import re
import shutil
from pathlib import Path

import pytest
from gitrepos import SECRET, Denying, add_branches, make_server, serve

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from test_web_k3_ui import git, goto, open_merge, sidebar_button, start

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
    """Alles, was die Seite zeigt oder im Sitzungszustand hält (Elemente samt Beschriftungen,
    Eingabewerte, Zustand)."""
    parts = [str(e.proto) for root in (at.main, at.sidebar) for e in walk(root)]
    parts += [str(e.value) for e in at.text_input]
    parts += [f"{key}={value!r}" for key, value in at.session_state.items()]
    return "\n".join(parts)


def shown(at: AppTest, kind: str, where: str = "main") -> str:
    return "\n".join(e.value for e in getattr(getattr(at, where), kind))


def page_links(at: AppTest) -> list[str]:
    return [e.proto.label for e in walk(at.sidebar) if type(e).__name__ == "PageLink"]


def offers(at: AppTest) -> set[str]:
    """Die Knöpfe „Trotzdem speichern“ bzw. „Ja, dies ist das richtige Daten-Repository“."""
    return {b.key for b in at.button if b.key in OFFERS}


def enter(at: AppTest, value: str) -> AppTest:
    at.text_input(key=FIELD).set_value(value).run()
    assert not at.exception, at.exception
    return at


def click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def datenordner(data_dir: Path, monkeypatch) -> AppTest:
    return goto(start(data_dir, monkeypatch), "datenordner")


def remotes(root: Path) -> str:
    return git(root, "remote")


def servers(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("server")


# --- U1/U2: von „kein Server“ bis „Speichern und teilen“ --------------------------------------


def test_sidebar_offers_the_setup_and_the_page_shows_the_section(
    repo: Path, data_dir: Path, monkeypatch
):
    at = start(data_dir, monkeypatch)
    assert "Kein Server eingerichtet" in shown(at, "caption", "sidebar")
    assert page_links(at) == ["Server einrichten"]
    assert not [b for b in at.sidebar.button if b.label == "Speichern und teilen"]
    goto(at, "datenordner")
    assert [s.value for s in at.main.subheader] == ["Server (Remote)"]
    assert "noch kein Server" in shown(at, "info")
    assert "Repository klonen" in shown(at, "info")  # der Weg für den Beitritt zu einem Team
    assert at.button(key="git-remote-check").disabled and at.button(key="git-remote-save").disabled
    assert at.text_input(key=FIELD).value == ""


def test_check_and_save_buttons_sit_next_to_each_other(repo: Path, data_dir: Path, monkeypatch):
    """„Verbindung prüfen“ und „Speichern“ gehören zusammen: ein waagerechter Container, in dem
    die Knöpfe links beginnen und nur so breit wie ihr Text sind (früher zwei gleich breite
    Spalten, die Knöpfe weit auseinander)."""
    from streamlit.proto.Block_pb2 import Block

    at = datenordner(data_dir, monkeypatch)
    group = next(
        node
        for node in walk(at.main)
        if {"git-remote-check", "git-remote-save"}
        <= {getattr(c, "key", None) for c in getattr(node, "children", {}).values()}
    )
    assert group.type == "flex_container"
    assert group.proto.flex_container.direction == Block.FlexContainer.Direction.HORIZONTAL
    assert [c.key for c in group.children.values()] == ["git-remote-check", "git-remote-save"]
    # linksbündig (nicht auseinandergezogen)
    assert group.proto.flex_container.justify == Block.FlexContainer.Justify.JUSTIFY_START


def test_check_then_save_then_share(repo: Path, data_dir: Path, tmp_path_factory, monkeypatch):
    server = make_server(servers(tmp_path_factory))
    at = datenordner(data_dir, monkeypatch)
    enter(at, str(server))
    assert not at.button(key="git-remote-check").disabled

    click(at, "git-remote-check")
    assert any("Verbindung hergestellt" in s.value for s in at.success)
    assert "noch keine Branches" in shown(at, "info")
    assert remotes(repo) == ""  # prüfen ändert nichts

    click(at, "git-remote-save")
    assert git(repo, "remote", "get-url", "origin") == str(server)
    assert any("Server gespeichert" in s.value for s in at.success)
    assert at.text_input(key=FIELD).value == ""
    status = shown(at, "caption", "sidebar")
    assert "Serverstand noch nicht geprüft" in status
    # Auf dem leeren Server liegt noch nichts: „synchron“ wäre falsch.
    assert "noch nicht auf dem Server" in status and "synchron" not in status
    assert page_links(at) == []
    assert sidebar_button(at, "Speichern und teilen")

    sidebar_button(at, "Speichern und teilen").click().run()
    assert not at.exception, at.exception
    assert any("Hochgeladen" in s.value for s in at.sidebar.success)
    assert git(server, "log", "-1", "--format=%s", "main") == "init"
    assert "synchron mit `origin/main`" in shown(at, "caption", "sidebar")


# --- U3/U4: Zugangsdaten und gefährliche Adressen ---------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        f"https://nutzer:{SECRET}@git.example.com/t/d.git",
        f"https://{SECRET}@git.example.com/t/d.git",
        f"https://git.example.com/t/d.git?token={SECRET}",
        f"ssh://nutzer:{SECRET}@git.example.com/t/d.git",
        "https://anna@bitbucket.org/team/daten.git",  # so zeigen Bitbucket und Azure DevOps sie an
    ],
)
def test_credentials_in_the_address_are_rejected_and_never_shown(
    repo: Path, data_dir: Path, monkeypatch, raw: str
):
    at = datenordner(data_dir, monkeypatch)
    enter(at, raw)
    errors = shown(at, "error")
    assert errors.count("Zugangsdaten gehören nicht in die Adresse") == 1  # nur als Überschrift
    assert "Benutzernamen" in errors
    # Die Meldung sagt, dass die Eingabe verworfen wurde und was zu tun ist.
    assert "Feld geleert" in shown(at, "caption") and "neu eintragen" in shown(at, "caption")
    assert at.text_input(key=FIELD).value == ""
    assert at.button(key="git-remote-check").disabled and at.button(key="git-remote-save").disabled
    assert SECRET not in all_text(at)
    assert remotes(repo) == "" and SECRET not in (repo / ".git" / "config").read_text()
    enter(at, "")  # der Hinweis erscheint nur einmal
    assert "Zugangsdaten gehören nicht in die Adresse" not in shown(at, "error")
    assert "Feld geleert" not in shown(at, "caption")


@pytest.mark.parametrize("raw", ['ext::sh -c "touch marker"', "-oProxyCommand=x", "git://h/x"])
def test_dangerous_addresses_are_rejected(repo: Path, data_dir: Path, monkeypatch, raw: str):
    at = datenordner(data_dir, monkeypatch)
    enter(at, raw)
    assert "Ungültige Adresse" in shown(at, "error")
    assert at.button(key="git-remote-check").disabled and at.button(key="git-remote-save").disabled
    assert remotes(repo) == ""
    assert not (repo / "marker").exists() and not Path("marker").exists()


def test_invalid_address_shows_its_title_once(repo: Path, data_dir: Path, monkeypatch):
    at = datenordner(data_dir, monkeypatch)
    enter(at, "github.com/team/daten")
    errors = shown(at, "error")
    assert errors.count("Ungültige Adresse") == 1
    assert "Das Format wird nicht erkannt" in errors and "https://server/team/daten.git" in errors


def test_clone_tab_names_the_reason_for_a_bad_address(repo: Path, data_dir: Path, monkeypatch):
    """Dort steht keine Überschrift über der Meldung: Der Grund gehört mit dem Titel in den Satz."""
    at = datenordner(data_dir, monkeypatch)
    address = next(e for e in at.text_input if e.label == "Adresse")
    address.set_value("github.com/team/daten").run()
    click(at, "data-clone-go")
    errors = shown(at, "error")
    assert errors.count("Ungültige Adresse") == 1
    assert "Klonen fehlgeschlagen: Ungültige Adresse: Das Format wird nicht erkannt" in errors


# --- U5-U8: Fehlerfälle und Bestätigungen -----------------------------------------------------


def test_missing_repository_is_not_found_and_not_offered(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    missing = servers(tmp_path_factory) / "gibt-es-nicht.git"
    at = datenordner(data_dir, monkeypatch)
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
        # GitLab über SSH, Tippfehler im Projektnamen: Der Server antwortet.
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
    at = datenordner(data_dir, monkeypatch)
    enter(at, "git@gitlab.example:team/tippfehler.git")
    for key in ("git-remote-check", "git-remote-save"):
        click(at, key)
        assert title in shown(at, "error")
        assert "Server nicht erreichbar" not in shown(at, "error")
        assert "Internet" not in shown(at, "error")  # kein Hinweis auf Internet oder VPN
        assert not offers(at)
    assert remotes(repo) == ""


def test_http_needs_confirmation_and_unreachable_server_can_be_saved_anyway(
    repo: Path, data_dir: Path, monkeypatch
):
    url = "http://127.0.0.1:1/r.git"
    at = datenordner(data_dir, monkeypatch)
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
    at = datenordner(data_dir, monkeypatch)
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
        at = datenordner(data_dir, monkeypatch)
        enter(at, f"http://127.0.0.1:{port}/r.git")
        at.checkbox(key="git-remote-insecure").check().run()
        click(at, "git-remote-save")
    assert "Anmeldung fehlt oder wurde abgelehnt" in shown(at, "error")
    assert "Zugangstoken" in shown(at, "error")
    assert shown(at, "error").count("fehlt oder wurde abgelehnt") == 1  # Überschrift nur einmal
    assert "gh auth setup-git" in shown(at, "error")  # https: die Schritte für https
    assert "ssh-keygen" not in shown(at, "error")
    assert not offers(at)
    assert remotes(repo) == ""


def test_missing_branch_needs_confirmation(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    server = make_server(servers(tmp_path_factory), branch="master")
    at = datenordner(data_dir, monkeypatch)
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
    """Erst prüfen, dann den Branch bestätigen: Das Angebot kommt schon vom Prüfen."""
    server = make_server(servers(tmp_path_factory), branch="master")
    at = datenordner(data_dir, monkeypatch)
    enter(at, str(server))
    click(at, "git-remote-check")
    assert any("Verbindung hergestellt" in s.value for s in at.success)
    assert "Branches auf dem Server: `master`" in shown(at, "caption")
    warning = shown(at, "warning")
    assert "Branch fehlt auf dem Server" in warning
    assert "„`main`“" in warning and "(vorhanden: `master`)" in warning
    assert "Repository klonen" in warning  # der Weg für den Beitritt zu einem Team
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
    at = datenordner(data_dir, monkeypatch)
    enter(at, str(server))
    click(at, "git-remote-check")
    names = ", ".join(f"`feature/{n}`" for n in range(5))
    assert f"Branches auf dem Server: {names}, …" in shown(at, "caption")  # gekürzt auf fünf
    assert not offers(at) and "git-remote-offer" not in at.session_state
    assert "Branch fehlt auf dem Server" not in shown(at, "warning")


def test_names_from_the_server_are_shown_as_code_not_as_links(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    """Ein Branch heißt wie eine Webadresse: Als Markdown würde daraus ein Link."""
    server = make_server(servers(tmp_path_factory), branch="master")
    add_branches(server, ["www.evil.example/anmelden", "a`b"])
    at = datenordner(data_dir, monkeypatch)
    enter(at, str(server))
    click(at, "git-remote-check")
    text = shown(at, "caption") + "\n" + shown(at, "warning")
    assert "`www.evil.example/anmelden`" in text and "``a`b``" in text
    outside = re.sub(r"(`+).+?\1", "", text)  # alles außerhalb von Code-Spans
    assert "evil" not in outside and "anmelden" not in outside

    click(at, "git-remote-save")  # dieselbe Warnung beim Speichern
    outside = re.sub(r"(`+).+?\1", "", shown(at, "warning"))
    assert "Branch fehlt auf dem Server" in outside and "evil" not in outside


def test_a_stored_address_with_a_backtick_is_shown_as_code(repo: Path, data_dir: Path, monkeypatch):
    git(repo, "remote", "add", "origin", "https://h.example/a`b.git")
    invalidate_status()
    at = datenordner(data_dir, monkeypatch)
    assert "Server `origin`: ``https://h.example/a`b.git``" in shown(at, "markdown")


def test_a_saved_address_with_a_backtick_is_shown_as_code(repo: Path, data_dir: Path, monkeypatch):
    at = datenordner(data_dir, monkeypatch)
    enter(at, "http://127.0.0.1:1/a`b.git")
    at.checkbox(key="git-remote-insecure").check().run()
    click(at, "git-remote-save")
    click(at, "git-remote-offline-save")
    assert any("``http://127.0.0.1:1/a`b.git``" in w.value for w in at.warning)


# --- Frisch angelegter Ordner: Beitritt zu einem Team -------------------------------------------


def test_a_new_folder_with_the_address_of_a_team_server_warns_and_names_cloning(
    data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    git(data_dir.parent, "init", "-q", "-b", "main")  # ein Repository, noch ohne Commit
    invalidate_status()
    server = make_server(servers(tmp_path_factory), branch="master")
    at = datenordner(data_dir, monkeypatch)
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


# --- Hinweise verweisen auf die Maske -----------------------------------------------------------


def test_a_wrong_address_error_links_to_the_server_section(shared, data_dir: Path, monkeypatch):
    at = start(data_dir, monkeypatch)
    assert page_links(at) == []  # es gibt einen Server: kein „Server einrichten“
    at.session_state["sync_result"] = gitsync.SyncResult(
        error=classify("remote: Repository not found.")
    )
    at.run()
    assert not at.exception, at.exception
    assert page_links(at) == ["Server-Adresse ändern"]
    assert "Repository nicht gefunden" in shown(at, "error", "sidebar")
    assert "Server (Remote)" in shown(at, "error", "sidebar")


# --- U9: Altbestand mit Zugangsdaten ----------------------------------------------------------


def test_stored_credentials_are_neither_shown_nor_prefilled(
    shared, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    root, _bob, _server = shared
    git(root, "remote", "set-url", "origin", f"https://nutzer:{SECRET}@h.example/x.git")
    invalidate_status()
    at = datenordner(data_dir, monkeypatch)
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


# --- U10: offenes Zusammenführen, ungewöhnliche Server-Einstellungen --------------------------


def test_open_merge_blocks_saving_but_not_checking(
    repo: Path, data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch
):
    open_merge(repo)
    config = (repo / ".git" / "config").read_bytes()
    server = make_server(servers(tmp_path_factory))
    at = datenordner(data_dir, monkeypatch)
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
    at = datenordner(data_dir, monkeypatch)
    assert "mehrere Adressen" in shown(at, "warning")  # die Erklärung, warum nichts geht
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
    at = datenordner(data_dir, monkeypatch)
    assert "Weitere Server (werden nicht verändert): `zweit`" in shown(at, "caption")

    new = make_server(work, "neu.git")
    enter(at, str(new))
    click(at, "git-remote-save")
    assert git(repo, "remote", "get-url", "origin") == str(new)
    assert git(repo, "remote", "get-url", "zweit") == str(second)


# --- U11: Ordnerwechsel -----------------------------------------------------------------------


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

    at = datenordner(data_dir, monkeypatch)
    enter(at, str(typed))
    sidebar_button(at, "Wechseln").click().run()
    assert not at.exception, at.exception
    assert at.text_input(key=FIELD).value == ""  # die Eingabe gehörte zum alten Ordner
    assert "git-remote-offer" not in at.session_state
    assert git(other, "remote", "get-url", "origin") == str(other_server)

    # In Ordner B muss die Adresse neu getippt werden; gespeichert wird nur dort.
    assert at.button(key="git-remote-save").disabled
    enter(at, str(typed))
    click(at, "git-remote-save")
    assert git(other, "remote", "get-url", "origin") == str(typed)
    assert git(repo, "remote", "get-url", "origin") == str(first_server)  # Ordner A unverändert


def test_folder_switch_drops_a_pending_offer(repo: Path, data_dir: Path, monkeypatch):
    other = repo.parent / "zweiter-ordner"
    shutil.copytree(data_dir / "demo", other / "zweit")
    save_data_dir(other)
    save_data_dir(data_dir)
    at = datenordner(data_dir, monkeypatch)
    enter(at, "http://127.0.0.1:1/r.git")
    at.checkbox(key="git-remote-insecure").check().run()
    click(at, "git-remote-save")
    assert "git-remote-offer" in at.session_state
    sidebar_button(at, "Wechseln").click().run()
    assert not at.exception, at.exception
    assert "git-remote-offer" not in at.session_state
    assert not offers(at)
    assert remotes(repo) == ""


# --- U12: ohne Repository, Einrichtung, Englisch ----------------------------------------------


def test_no_section_without_a_git_repository(data_dir: Path, monkeypatch):
    at = datenordner(data_dir, monkeypatch)
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
    at = datenordner(data_dir, monkeypatch)
    assert [s.value for s in at.subheader] == ["Server (remote)"]
    assert at.text_input(key=FIELD).label == "Server address"
    assert page_links(at) == ["Set up server"]
    assert "Clone repository" in shown(at, "info")
    enter(at, "x.git")
    errors = shown(at, "error")
    assert "Invalid address" in errors and "The format is not recognised" in errors
    assert "Ungültig" not in errors and "Das Format" not in errors


# --- U13: Hinweis „kein Server“ ---------------------------------------------------------------


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
    # Auch auf der Seite „Datenordner“ selbst (Link, Problem und Maske im selben Lauf).
    at.session_state["sync_result"] = gitsync.sync(data_dir, "egal")
    goto(at, "datenordner")
    assert at.text_input(key=FIELD) is not None
    assert "Datenordner" in shown(at, "error", "sidebar")
