# SPDX-License-Identifier: EUPL-1.2
"""Two clones of the same bare repository, one app instance each (Alice and Bob): changes by
different people, a deliberate value conflict with the conflict page, restart in the middle of
the conflict, and tags. (Two tabs in the same clone do not occur in practice and are not tested.)"""

import time
from pathlib import Path

import pytest
import yaml
from harness import (
    App,
    absence_cell,
    edit_absence,
    git,
    main_area,
    open_page,
    share,
    sidebar,
)
from playwright.sync_api import Page, expect

SPRINT = "2026.22"
SPRINT_FILE = f"teams/demo/sprints/{SPRINT}.yaml"
DECIDE = "Entscheidungen übernehmen und teilen"


def change_absence(page: Page, app: App, person: str, value: str) -> None:
    """Enters absences for ``person`` in sprint 2026.22 and saves them (not shared yet)."""
    open_page(page, app, "fehltage")
    edit_absence(page, person, SPRINT, value)
    save = main_area(page).get_by_role("button", name="Fehltage speichern")
    expect(save).to_be_enabled()
    save.click()
    expect(sidebar(page).get_by_text("1 offene Änderung")).to_be_visible()


def server_absences(bare: Path) -> dict:
    return yaml.safe_load(git(bare, "show", f"main:{SPRINT_FILE}"))["absences"]


def shared(page: Page, text: str) -> None:
    expect(share(page).filter(has_text=text).first).to_be_visible()


def test_absences_of_different_people_merge_without_conflict(clones, new_page):
    alice, bob, bare = clones()
    pa, pb = new_page(), new_page()
    change_absence(pa, alice, "Anna", "2")
    shared(pa, "Hochgeladen")
    change_absence(pb, bob, "Dana", "1")
    shared(pb, "von anderen übernommen")  # Bob fetches Anna's change and uploads both
    assert not pb.get_by_test_id("stException").count()
    expect(main_area(pb).get_by_role("heading", name="Konflikte lösen")).to_have_count(0)
    on_server = server_absences(bare)
    assert on_server["anna"] == 2 and on_server["dana"] == 1
    assert git(bare, "log", "-1", "--format=%an", "main") == "Bob"
    # Alice fetches Bob's change: both values are in her grid.
    open_page(pa, alice, "fehltage")
    shared(pa, "von anderen übernommen")
    open_page(pa, alice, "fehltage")
    expect(main_area(pa).get_by_test_id("stDataFrame").first).to_be_visible()
    assert absence_cell(pa, "Anna", SPRINT) == "2"
    assert absence_cell(pa, "Dana", SPRINT) == "1"
    assert git(alice.data_dir.parent, "status", "--porcelain") == ""


def test_sharing_still_reports_when_another_rerun_comes_during_the_sync(clones, new_page):
    """Streamlit stops the "Save and share" callback as soon as another run is requested in the
    middle of the sync (here: an input on the page). The sync runs to the end; the message must
    still not be missing and the sidebar must not show the state from the middle. The upload
    takes a while (hook in the clone) so that the second run surely falls into the sync; the
    marker shows that the sync got that far."""
    alice, bob, bare = clones()
    pa, pb = new_page(), new_page()
    change_absence(pa, alice, "Anna", "2")
    shared(pa, "Hochgeladen")
    change_absence(pb, bob, "Dana", "1")
    mark = bob.data_dir.parent.parent / "push-started"
    hook = bob.data_dir.parent / ".git" / "hooks" / "pre-push"
    # Line feed, not CRLF: on Windows ``write_text`` otherwise writes CRLF, and a carriage return
    # after the shebang line or after ``sleep 3`` breaks the hook for ``sh`` (depending on the
    # shell it then does not run or aborts).
    hook.write_text(
        f"#!/bin/sh\ntouch '{mark.as_posix()}'\nsleep 3\n", encoding="utf-8", newline="\n"
    )
    hook.chmod(0o755)
    alerts = share(pb)
    deadline = time.monotonic() + 20
    while not mark.exists():
        assert time.monotonic() < deadline, "der Abgleich kam nicht bis zum Hochladen"
        pb.wait_for_timeout(50)
    main_area(pb).get_by_role("button", name="Increment").first.click()  # second run
    expect(alerts.filter(has_text="von anderen übernommen").first).to_be_visible()
    expect(alerts.filter(has_text="Hochgeladen").first).to_be_visible()
    on_server = server_absences(bare)
    assert on_server["anna"] == 2 and on_server["dana"] == 1


def make_value_conflict(clones, new_page) -> tuple[App, App, Path, Page]:
    """Alice and Bob enter different values for Anna in the same sprint; Alice shares first,
    Bob then runs into the conflict. Returns Bob's open page."""
    alice, bob, bare = clones()
    pa, pb = new_page(), new_page()
    change_absence(pa, alice, "Anna", "2")
    change_absence(pb, bob, "Anna", "3")
    shared(pa, "Hochgeladen")
    shared(pb, "Konflikt beim Zusammenführen")
    expect(main_area(pb).get_by_role("heading", name="Konflikte lösen")).to_be_visible()
    return alice, bob, bare, pb


@pytest.mark.parametrize(("choice", "value"), [("Andere Änderung", 2), ("Meine Änderung", 3)])
def test_value_conflict_is_resolved_on_the_conflict_page(clones, new_page, choice, value):
    _, bob, bare, page = make_value_conflict(clones, new_page)
    expect(main_area(page).get_by_text("absences.anna")).to_be_visible()
    expect(main_area(page).get_by_text("Meine Änderung: 3")).to_be_visible()
    expect(main_area(page).get_by_text("Andere Änderung: 2")).to_be_visible()
    decide = main_area(page).get_by_role("button", name=DECIDE)
    expect(decide).to_be_disabled()  # only after a decision per entry
    main_area(page).get_by_text(f"{choice}: {value}").click()
    expect(decide).to_be_enabled()
    decide.click()
    expect(sidebar(page).get_by_text("Hochgeladen")).to_be_visible()
    expect(main_area(page).get_by_role("heading", name="Planbare Fehltage")).to_be_visible()
    assert server_absences(bare)["anna"] == value
    assert git(bob.data_dir.parent, "status", "--porcelain") == ""


def test_app_restart_in_the_middle_of_a_conflict_keeps_it_open(clones, new_page):
    _, bob, bare, _ = make_value_conflict(clones, new_page)
    bob.restart()  # the conflict is in Git, not in the app's memory
    fresh = new_page()
    open_page(fresh, bob, "fehltage")
    expect(main_area(fresh).get_by_role("heading", name="Konflikte lösen")).to_be_visible()
    expect(main_area(fresh).get_by_role("button", name="Fehltage speichern")).to_have_count(0)
    expect(main_area(fresh).get_by_text("Meine Änderung: 3")).to_be_visible()
    expect(main_area(fresh).get_by_text("Andere Änderung: 2")).to_be_visible()
    main_area(fresh).get_by_text("Meine Änderung: 3").click()
    main_area(fresh).get_by_role("button", name=DECIDE).click()
    expect(sidebar(fresh).get_by_text("Hochgeladen")).to_be_visible()
    assert server_absences(bare)["anna"] == 3
    open_page(fresh, bob, "fehltage")
    expect(main_area(fresh).get_by_role("heading", name="Planbare Fehltage")).to_be_visible()


def test_aborting_the_merge_keeps_both_versions(clones, new_page):
    _, bob, bare, page = make_value_conflict(clones, new_page)
    main_area(page).get_by_role("button", name="Zusammenführen abbrechen").click()
    expect(main_area(page).get_by_role("heading", name="Konflikte lösen")).to_have_count(0)
    assert server_absences(bare)["anna"] == 2  # Alice's state is unchanged on the server
    assert git(bob.data_dir.parent, "status", "--short", "--untracked-files=no") == ""
    open_page(page, bob, "fehltage")
    expect(main_area(page).get_by_test_id("stDataFrame").first).to_be_visible()
    assert absence_cell(page, "Anna", SPRINT) == "3"  # Bob's own state is kept


TAG = "team/2026.21"


def tags_tab(page: Page, app: App) -> None:
    open_page(page, app, "verlauf")
    main_area(page).get_by_role("tab", name="Tags").click()


def test_tag_set_by_alice_appears_for_bob_and_is_fetched_when_sharing(clones, new_page):
    alice, bob, bare = clones()
    pa, pb = new_page(), new_page()
    tags_tab(pa, alice)
    expect(main_area(pa).get_by_text("Noch keine Tags.")).to_be_visible()
    main_area(pa).get_by_label("Neuer Tag").fill(TAG)
    main_area(pa).get_by_role("button", name="Tag setzen").click()
    expect(
        pa.get_by_test_id("stAlert").filter(has_text=f"Tag {TAG} gesetzt und geteilt.")
    ).to_be_visible()
    assert git(bare, "tag", "-l") == TAG
    # Bob sees it only after syncing with the server, and only there.
    tags_tab(pb, bob)
    expect(main_area(pb).get_by_text("Noch keine Tags.")).to_be_visible()
    main_area(pb).get_by_role("button", name="Mit dem Server abgleichen").click()
    row = main_area(pb).get_by_role("row").filter(has_text=TAG)
    expect(row).to_contain_text("nur auf dem Server")
    assert git(bob.data_dir.parent, "tag", "-l") == ""
    # "Save and share" fetches it: afterwards it exists locally and on the server.
    shared(pb, "Hochgeladen")
    tags_tab(pb, bob)
    main_area(pb).get_by_role("button", name="Mit dem Server abgleichen").click()
    expect(main_area(pb).get_by_role("row").filter(has_text=TAG)).to_contain_text("auf dem Server")
    expect(main_area(pb).get_by_role("row").filter(has_text=TAG)).not_to_contain_text("nur")
    assert git(bob.data_dir.parent, "tag", "-l") == TAG


def test_same_tag_name_on_different_states_is_shown_as_different(clones, new_page):
    alice, bob, _ = clones()
    pa, pb = new_page(), new_page()
    git(bob.data_dir.parent, "tag", TAG, name="Bob")  # Bob already has the name, on the old state
    change_absence(pa, alice, "Anna", "2")
    shared(pa, "Hochgeladen")
    tags_tab(pa, alice)
    main_area(pa).get_by_label("Neuer Tag").fill(TAG)
    main_area(pa).get_by_role("button", name="Tag setzen").click()
    expect(pa.get_by_test_id("stAlert").filter(has_text="gesetzt und geteilt")).to_be_visible()
    tags_tab(pb, bob)
    main_area(pb).get_by_role("button", name="Mit dem Server abgleichen").click()
    expect(main_area(pb).get_by_role("row").filter(has_text=TAG)).to_contain_text("unterschiedlich")
