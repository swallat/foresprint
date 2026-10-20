# SPDX-License-Identifier: EUPL-1.2
"""Start page: three task tiles, each leads to the right page with the right sprint."""

import re

import pytest
from harness import App, main_area, no_exception, open_page, selected, settle
from playwright.sync_api import Page, expect

# Reference date 2026-10-15: sprint 2026.21 is running, 2026.22 is the next (absences confirmed).
TILES = [
    ("prepare", "✅ Sprint vorbereiten", "Sprint 2026.22: vorbereitet.", "absences", "absences-sprint", "2026.22"),
    ("planning", "⬜ Planning", "Sprint 2026.22: Commitment fehlt noch.", "planning", "planning-sprint", "2026.22"),
    ("review", "⬜ Sprint abschließen", "Sprint 2026.21 läuft noch", "review", "review-sprint", "2026.21"),
]  # fmt: skip


def tile(page: Page, heading: str):
    return main_area(page).get_by_test_id("stColumn").filter(has_text=heading)


def test_start_shows_three_tiles(page: Page, app: App):
    open_page(page, app)
    expect(main_area(page).get_by_role("heading", name="Was möchtest du tun?")).to_be_visible()
    headings = main_area(page).get_by_role("heading", level=3)
    assert headings.all_inner_texts() == [heading for _, heading, *_ in TILES]
    for _, heading, hint, *_ in TILES:
        expect(tile(page, heading)).to_contain_text(hint)
        expect(tile(page, heading).get_by_role("button", name="Öffnen")).to_be_visible()
    no_exception(page)


@pytest.mark.parametrize(("key", "heading", "hint", "target", "sprint_key", "sprint"), TILES)
def test_tile_leads_to_the_matching_page_and_sprint(
    page: Page,
    app: App,
    key: str,
    heading: str,
    hint: str,
    target: str,
    sprint_key: str,
    sprint: str,
):
    open_page(page, app)
    tile(page, heading).get_by_role("button", name="Öffnen").click()
    expect(page).to_have_url(re.compile(rf"/{target}$"))
    settle(page)
    expect(selected(page, sprint_key)).to_have_value(sprint)
    no_exception(page)
