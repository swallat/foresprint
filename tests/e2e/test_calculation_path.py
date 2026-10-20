# SPDX-License-Identifier: EUPL-1.2
"""Forecast page, "Rechenweg: Formeln": structured steps, formulas fully visible."""

import os
from pathlib import Path

from harness import App, main_area, no_exception, open_page
from playwright.sync_api import Page, expect


def test_calculation_path_is_structured_and_formulas_are_not_cut_off(page: Page, app: App):
    open_page(page, app, "forecast")
    main_area(page).get_by_text("Rechenweg: Formeln").click()
    area = main_area(page)
    expect(area.get_by_text("Grundlage: Sprints")).to_be_visible()
    expect(area.get_by_text("Forecast PLAN (abgerundet)")).to_be_visible()
    expect(area.get_by_text("Eingesetzte Werte und Quellen")).to_be_visible()
    table = area.get_by_test_id("stTable").last
    table.scroll_into_view_if_needed()
    cells = table.locator("td, th")
    assert cells.count() > 0
    for i in range(cells.count()):  # nothing is cut off: content fits the cell
        box = cells.nth(i).evaluate("e => [e.scrollWidth, e.clientWidth]")
        assert box[0] <= box[1] + 1, cells.nth(i).inner_text()
    if shots := os.environ.get("CALC_SHOTS"):
        page.screenshot(path=str(Path(shots) / "rechenweg.png"), full_page=True)
    no_exception(page)
