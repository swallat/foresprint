# SPDX-License-Identifier: EUPL-1.2
"""English UI: switching in the sidebar and starting in English."""

import pytest
from harness import choose, main_area, navigate, no_exception, open_page, selected, sidebar
from playwright.sync_api import Page, expect

from foresprint.web.ui import PAGES

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
    # The choice is kept across page changes ...
    navigate(page, "absences")
    expect(main_area(page).get_by_role("heading", name="Planned absences")).to_be_visible()
    # ... and also applies to a new window (stored in the settings).
    open_page(page, app, "absences")
    expect(main_area(page).get_by_role("heading", name="Planned absences")).to_be_visible()
    expect(selected(page, "language")).to_have_value("English")


def test_start_in_english_through_the_environment(page: Page, app_english):
    """The default FORESPRINT_LANG=en applies without any setting in the UI."""
    open_page(page, app_english)
    expect(
        main_area(page).get_by_role("heading", name="What would you like to do?")
    ).to_be_visible()


@pytest.mark.parametrize("key", PAGE_KEYS)
def test_every_page_renders_in_english(page: Page, app_english, key: str):
    open_page(page, app_english, "" if key == "start" else key)
    expect(main_area(page).locator("h1, h2, h3").first).to_be_visible()
    # The sidebar is English on every page, otherwise the test would also pass in German.
    expect(sidebar(page).get_by_text("Tasks", exact=True)).to_be_visible()
    no_exception(page)
