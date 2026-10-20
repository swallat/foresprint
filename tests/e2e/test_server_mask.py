# SPDX-License-Identifier: EUPL-1.2
"""Server mask of the "Data folder" page against local bare repositories: success, wrong
address, not found, unreachable, branch missing, folder without commit, lock during an open merge."""

from pathlib import Path

import pytest
from harness import App, copy_demo, git, init_repository, main_area, make_bare, open_page
from playwright.sync_api import Locator, Page, expect

UNREACHABLE = "https://127.0.0.1:1/daten.git"  # port 1: nothing is listening


@pytest.fixture
def servers(tmp_path: Path) -> dict[str, Path]:
    """Three local remotes: with branch ``main``, with another branch, empty."""
    good = make_bare(tmp_path / "gut.git")
    seed = tmp_path / "seed"
    copy_demo(seed)
    init_repository(seed, good)
    other = make_bare(tmp_path / "anderer-branch.git")
    git(seed, "push", "-q", str(other), "main:other")
    empty = make_bare(tmp_path / "leer.git")
    return {"good": good, "other": other, "empty": empty, "missing": tmp_path / "gibt-es-nicht.git"}


@pytest.fixture
def mask(page: Page, make_app) -> tuple[Page, App]:
    """The Data folder page of an app with a Git repository (one commit, no server yet)."""
    app = make_app("maske", git=True)
    open_page(page, app, "data_dir")
    expect(main_area(page).get_by_role("heading", name="Server (Remote)")).to_be_visible()
    return page, app


def alert(page: Page, text: str) -> Locator:
    return page.get_by_test_id("stAlert").filter(has_text=text)


def enter(page: Page, address: str) -> None:
    """Enters the address (Enter commits it, only then do the buttons react)."""
    field = page.locator(".st-key-git-remote-url input")
    field.fill(address)
    field.press("Enter")


def button(page: Page, name: str) -> Locator:
    return main_area(page).get_by_role("button", name=name, exact=True)


def remote_of(app: App) -> str:
    return git(app.data_dir.parent, "config", "--get", "remote.origin.url", check=False)


def test_check_and_save_a_reachable_server(mask, servers):
    page, app = mask
    expect(alert(page, "gehört noch kein Server")).to_be_visible()
    enter(page, str(servers["good"]))
    expect(button(page, "Verbindung prüfen")).to_be_enabled()
    button(page, "Verbindung prüfen").click()
    expect(alert(page, "Verbindung hergestellt.")).to_be_visible()
    expect(main_area(page).get_by_text("Branches auf dem Server: main")).to_be_visible()
    assert remote_of(app) != str(servers["good"])  # checking changes nothing
    button(page, "Speichern").click()
    expect(alert(page, "Server gespeichert:")).to_be_visible()
    expect(main_area(page).get_by_text(f"Server origin: {servers['good']}")).to_be_visible()
    assert remote_of(app) == str(servers["good"])
    expect(page.locator(".st-key-git-remote-url input")).to_have_value("")  # field cleared


@pytest.mark.parametrize(
    ("address", "message"),
    [
        ("daten.git", "Das Format wird nicht erkannt"),  # relative path
        ("git://server/daten.git", "Dieses Verfahren wird nicht unterstützt"),
        ("file:///tmp/daten.git", "Dieses Verfahren wird nicht unterstützt"),
        ("http://127.0.0.1:1/daten.git", "Unverschlüsselte Verbindung"),
    ],
)
def test_invalid_address_is_explained_and_nothing_can_be_saved(mask, address: str, message: str):
    page, app = mask
    enter(page, address)
    expect(
        alert(page, "Ungültige Adresse" if "Unverschl" not in message else message)
    ).to_be_visible()
    expect(alert(page, message)).to_be_visible()
    expect(button(page, "Verbindung prüfen")).to_be_disabled()
    expect(button(page, "Speichern")).to_be_disabled()
    assert remote_of(app) == ""


def test_credentials_in_the_address_are_dropped_and_never_shown(mask):
    page, app = mask
    enter(page, "https://nutzer:geheim123@server.example/team/daten.git")
    expect(alert(page, "Zugangsdaten gehören nicht in die Adresse")).to_be_visible()
    expect(page.locator(".st-key-git-remote-url input")).to_have_value("")
    expect(main_area(page).get_by_text("Die Eingabe wurde verworfen")).to_be_visible()
    text = page.get_by_test_id("stApp").inner_text()
    assert "geheim123" not in text and "nutzer:" not in text
    assert remote_of(app) == ""


def test_unknown_repository_is_reported_as_not_found(mask, servers):
    page, app = mask
    enter(page, str(servers["missing"]))
    expect(button(page, "Verbindung prüfen")).to_be_enabled()
    button(page, "Verbindung prüfen").click()
    expect(alert(page, "Repository nicht gefunden")).to_be_visible()
    assert remote_of(app) == ""


def test_unreachable_server_can_be_saved_on_explicit_confirmation(mask):
    page, app = mask
    enter(page, UNREACHABLE)
    expect(button(page, "Verbindung prüfen")).to_be_enabled()
    button(page, "Verbindung prüfen").click()
    expect(alert(page, "Server nicht erreichbar")).to_be_visible()
    assert remote_of(app) == ""
    button(page, "Trotzdem speichern").click()
    expect(alert(page, "Server gespeichert, aber nicht geprüft")).to_be_visible()
    assert remote_of(app) == UNREACHABLE


def test_missing_branch_needs_an_explicit_yes(mask, servers):
    page, app = mask
    enter(page, str(servers["other"]))
    expect(button(page, "Verbindung prüfen")).to_be_enabled()
    button(page, "Verbindung prüfen").click()
    expect(alert(page, "Branch fehlt auf dem Server")).to_be_visible()
    expect(alert(page, "(vorhanden: other)")).to_be_visible()
    assert remote_of(app) == ""
    button(page, "Ja, dies ist das richtige Daten-Repository").click()
    expect(alert(page, "Server gespeichert:")).to_be_visible()
    assert remote_of(app) == str(servers["other"])


def test_empty_server_is_reachable_but_says_so(mask, servers):
    page, _ = mask
    enter(page, str(servers["empty"]))
    expect(button(page, "Verbindung prüfen")).to_be_enabled()
    button(page, "Verbindung prüfen").click()
    expect(alert(page, "Verbindung hergestellt.")).to_be_visible()
    expect(alert(page, "enthält aber noch keine Branches")).to_be_visible()


def test_folder_without_any_commit_can_still_get_a_server(page: Page, make_app, servers):
    """A freshly created repository without a commit: the mask still checks and saves."""
    app = make_app("ohne-commit")
    git(app.data_dir.parent, "init", "-q", "-b", "main")  # Git repository, but no commit
    open_page(page, app, "data_dir")
    enter(page, str(servers["good"]))
    expect(button(page, "Verbindung prüfen")).to_be_enabled()
    button(page, "Verbindung prüfen").click()
    expect(alert(page, "Verbindung hergestellt.")).to_be_visible()
    button(page, "Speichern").click()
    expect(alert(page, "Server gespeichert:")).to_be_visible()
    assert remote_of(app) == str(servers["good"])


def test_open_merge_locks_saving_but_not_checking(page: Page, make_app, servers):
    app = make_app("merge", git=True)
    root = app.data_dir.parent
    sprint = app.data_dir / "demo" / "sprints" / "2026.20.yaml"
    git(root, "checkout", "-q", "-b", "andere")
    sprint.write_text(sprint.read_text(encoding="utf-8").replace("velocity: 9.75", "velocity: 1"))
    git(root, "commit", "-qam", "andere")
    git(root, "checkout", "-q", "main")
    sprint.write_text(sprint.read_text(encoding="utf-8").replace("velocity: 9.75", "velocity: 2"))
    git(root, "commit", "-qam", "eigene")
    git(root, "merge", "andere", check=False)  # conflict: the merge stays open
    open_page(page, app, "data_dir")
    expect(alert(page, "Ein Zusammenführen ist unvollständig")).to_be_visible()
    enter(page, str(servers["good"]))
    expect(button(page, "Verbindung prüfen")).to_be_enabled()
    expect(button(page, "Speichern")).to_be_disabled()
    button(page, "Verbindung prüfen").click()
    expect(alert(page, "Verbindung hergestellt.")).to_be_visible()
    expect(button(page, "Speichern")).to_be_disabled()
    assert remote_of(app) == ""
