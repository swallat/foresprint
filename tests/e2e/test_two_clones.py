# SPDX-License-Identifier: EUPL-1.2
"""Zwei Klone desselben Bare-Repositorys, je eine App-Instanz (Alice und Bob): Änderungen
verschiedener Personen, ein absichtlicher Wertkonflikt samt Konfliktseite, Neustart mitten im
Konflikt und Tags. (Zwei Tabs im selben Klon gibt es in der Praxis nicht und werden nicht getestet.)"""

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
    """Trägt für ``person`` im Sprint 2026.22 Fehltage ein und speichert sie (noch nicht geteilt)."""
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
    shared(pb, "von anderen übernommen")  # Bob holt Annas Änderung und lädt beides hoch
    assert not pb.get_by_test_id("stException").count()
    expect(main_area(pb).get_by_role("heading", name="Konflikte lösen")).to_have_count(0)
    on_server = server_absences(bare)
    assert on_server["anna"] == 2 and on_server["dana"] == 1
    assert git(bare, "log", "-1", "--format=%an", "main") == "Bob"
    # Alice holt Bobs Änderung: Beide Werte stehen in ihrem Raster.
    open_page(pa, alice, "fehltage")
    shared(pa, "von anderen übernommen")
    open_page(pa, alice, "fehltage")
    expect(main_area(pa).get_by_test_id("stDataFrame").first).to_be_visible()
    assert absence_cell(pa, "Anna", SPRINT) == "2"
    assert absence_cell(pa, "Dana", SPRINT) == "1"
    assert git(alice.data_dir.parent, "status", "--porcelain") == ""


def make_value_conflict(clones, new_page) -> tuple[App, App, Path, Page]:
    """Alice und Bob tragen für Anna im selben Sprint verschiedene Werte ein; Alice teilt zuerst,
    Bob läuft danach in den Konflikt. Liefert Bobs geöffnete Seite."""
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
    expect(decide).to_be_disabled()  # erst nach einer Entscheidung je Eintrag
    main_area(page).get_by_text(f"{choice}: {value}").click()
    expect(decide).to_be_enabled()
    decide.click()
    expect(sidebar(page).get_by_text("Hochgeladen")).to_be_visible()
    expect(main_area(page).get_by_role("heading", name="Planbare Fehltage")).to_be_visible()
    assert server_absences(bare)["anna"] == value
    assert git(bob.data_dir.parent, "status", "--porcelain") == ""


def test_app_restart_in_the_middle_of_a_conflict_keeps_it_open(clones, new_page):
    _, bob, bare, _ = make_value_conflict(clones, new_page)
    bob.restart()  # der Konflikt steht in Git, nicht im Speicher der App
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
    assert server_absences(bare)["anna"] == 2  # Alices Stand liegt unverändert auf dem Server
    assert git(bob.data_dir.parent, "status", "--short", "--untracked-files=no") == ""
    open_page(page, bob, "fehltage")
    expect(main_area(page).get_by_test_id("stDataFrame").first).to_be_visible()
    assert absence_cell(page, "Anna", SPRINT) == "3"  # Bobs eigener Stand ist erhalten


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
    # Bob sieht ihn erst nach dem Abgleich mit dem Server – und nur dort.
    tags_tab(pb, bob)
    expect(main_area(pb).get_by_text("Noch keine Tags.")).to_be_visible()
    main_area(pb).get_by_role("button", name="Mit dem Server abgleichen").click()
    row = main_area(pb).get_by_role("row").filter(has_text=TAG)
    expect(row).to_contain_text("nur auf dem Server")
    assert git(bob.data_dir.parent, "tag", "-l") == ""
    # „Speichern und teilen“ holt ihn: danach gibt es ihn lokal und auf dem Server.
    shared(pb, "Hochgeladen")
    tags_tab(pb, bob)
    main_area(pb).get_by_role("button", name="Mit dem Server abgleichen").click()
    expect(main_area(pb).get_by_role("row").filter(has_text=TAG)).to_contain_text("auf dem Server")
    expect(main_area(pb).get_by_role("row").filter(has_text=TAG)).not_to_contain_text("nur")
    assert git(bob.data_dir.parent, "tag", "-l") == TAG


def test_same_tag_name_on_different_states_is_shown_as_different(clones, new_page):
    alice, bob, _ = clones()
    pa, pb = new_page(), new_page()
    git(bob.data_dir.parent, "tag", TAG, name="Bob")  # Bob hat den Namen schon, auf dem alten Stand
    change_absence(pa, alice, "Anna", "2")
    shared(pa, "Hochgeladen")
    tags_tab(pa, alice)
    main_area(pa).get_by_label("Neuer Tag").fill(TAG)
    main_area(pa).get_by_role("button", name="Tag setzen").click()
    expect(pa.get_by_test_id("stAlert").filter(has_text="gesetzt und geteilt")).to_be_visible()
    tags_tab(pb, bob)
    main_area(pb).get_by_role("button", name="Mit dem Server abgleichen").click()
    expect(main_area(pb).get_by_role("row").filter(has_text=TAG)).to_contain_text("unterschiedlich")
