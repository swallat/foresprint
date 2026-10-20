# SPDX-License-Identifier: EUPL-1.2
"""Every page can be opened without Streamlit showing a Python error."""

import pytest
from harness import App, main_area, no_exception, open_page, settle
from playwright.sync_api import Page, expect

from sprintforecast.web.ui import PAGE_FEATURES, PAGES

PAGE_KEYS = [key for entries in PAGES.values() for key in entries]
PRODUCT_PAGES = {key for key, feature in PAGE_FEATURES.items() if feature == "products"}


def url_path(key: str) -> str:
    return "" if key == "start" else key


@pytest.mark.parametrize("key", PAGE_KEYS)
def test_page_renders_without_error(page: Page, app: App, key: str):
    open_page(page, app, url_path(key))
    expect(main_area(page).locator("h1, h2, h3").first).to_be_visible()
    no_exception(page)


@pytest.mark.parametrize("key", [k for k in PAGE_KEYS if k not in PRODUCT_PAGES])
def test_page_renders_without_error_in_a_team_without_products(
    page: Page, app_without_products: App, key: str
):
    open_page(page, app_without_products, url_path(key))
    expect(main_area(page).locator("h1, h2, h3").first).to_be_visible()
    no_exception(page)


def test_team_without_products_has_no_product_pages(page: Page, app_without_products: App):
    open_page(page, app_without_products)
    links = page.get_by_test_id("stSidebarNav").locator("a")
    hrefs = [href for link in links.all() if (href := link.get_attribute("href"))]
    paths = {href.rstrip("/").rsplit("/", 1)[-1] for href in hrefs}
    assert not paths & PRODUCT_PAGES
    assert {"fehltage", "planning", "review"} <= paths
    settle(page)
