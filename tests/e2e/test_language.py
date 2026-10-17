# SPDX-License-Identifier: EUPL-1.2
"""Englische Oberfläche: Umschalten in der Seitenleiste und Start in Englisch."""

import pytest
from harness import choose, main_area, navigate, no_exception, open_page, selected, sidebar
from playwright.sync_api import Page, expect

from sprintforecast.web.ui import PAGES

PAGE_KEYS = [key for entries in PAGES.values() for key in entries]


def test_language_can_be_switched_in_the_sidebar(page: Page, make_app):
    app = make_app("sprache")
    open_page(page, app)
    expect(main_area(page).get_by_role("heading", name="Was möchtest du tun?")).to_be_visible()
    choose(page, "language", "English")
    expect(
        main_area(page).get_by_role("heading", name="What would you like to do?")
    ).to_be_visible()
    expect(sidebar(page).get_by_role("link", name="Prepare the sprint: absences")).to_be_visible()
    expect(sidebar(page).get_by_text("Tasks", exact=True)).to_be_visible()
    # Die Wahl bleibt beim Seitenwechsel erhalten ...
    navigate(page, "fehltage")
    expect(main_area(page).get_by_role("heading", name="Planned absences")).to_be_visible()
    # ... und gilt auch für ein neues Fenster (gespeichert in den Einstellungen).
    open_page(page, app, "fehltage")
    expect(main_area(page).get_by_role("heading", name="Planned absences")).to_be_visible()
    expect(selected(page, "language")).to_have_value("English")


def test_start_in_english_through_the_environment(page: Page, app_english):
    """Die Vorgabe SPRINTFORECAST_LANG=en gilt ohne jede Einstellung in der Oberfläche."""
    open_page(page, app_english)
    expect(
        main_area(page).get_by_role("heading", name="What would you like to do?")
    ).to_be_visible()


@pytest.mark.parametrize("key", PAGE_KEYS)
def test_every_page_renders_in_english(page: Page, app_english, key: str):
    open_page(page, app_english, "" if key == "start" else key)
    expect(main_area(page).locator("h1, h2, h3").first).to_be_visible()
    # Die Seitenleiste ist auf jeder Seite englisch – sonst liefe der Test auch in Deutsch grün.
    expect(sidebar(page).get_by_text("Tasks", exact=True)).to_be_visible()
    no_exception(page)
