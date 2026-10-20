# SPDX-License-Identifier: EUPL-1.2
"""Theme from the App settings page: applied after a reload and kept for new windows."""

import os
from pathlib import Path

from harness import main_area, open_page
from playwright.sync_api import Page, expect

DARK = "rgb(18, 18, 31)"
LIGHT = "rgb(255, 255, 255)"


def pick(page: Page, label: str) -> None:
    page.locator(".st-key-theme").get_by_text(label, exact=True).click()


def snapshot(page: Page, name: str) -> None:
    if folder := os.environ.get("E2E_SCREENSHOTS"):
        Path(folder).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(folder) / f"{name}.png"), full_page=True)


def test_theme_can_be_switched_and_is_kept(page: Page, app_english):
    open_page(page, app_english, "app_settings")
    expect(main_area(page).get_by_role("heading", name="App settings")).to_be_visible()
    pick(page, "Dark")  # the page reloads once so Streamlit sends the theme again
    expect(page.get_by_test_id("stApp")).to_have_css("background-color", DARK)
    snapshot(page, "dark")
    open_page(page, app_english, "app_settings")  # a new window keeps it
    expect(page.get_by_test_id("stApp")).to_have_css("background-color", DARK)
    pick(page, "Light")
    expect(page.get_by_test_id("stApp")).to_have_css("background-color", LIGHT)
    snapshot(page, "light")
