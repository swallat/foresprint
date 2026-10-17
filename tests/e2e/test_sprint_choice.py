# SPDX-License-Identifier: EUPL-1.2
"""Die Sprintwahl gilt seitenübergreifend: Wer auf einer Seite einen Sprint wählt, findet ihn auf
den anderen Boards wieder."""

import pytest
from harness import App, choose, navigate, no_exception, open_page, selected
from playwright.sync_api import Page, expect

SPRINT_KEYS = {
    "fehltage": "absences-sprint",
    "vorplanung": "vorplanung-sprint",
    "planning": "planning-sprint",
    "review": "review-sprint",
}


@pytest.mark.parametrize("start", list(SPRINT_KEYS))
def test_chosen_sprint_carries_over_to_the_other_boards(page: Page, app: App, start: str):
    open_page(page, app, start)
    choose(page, SPRINT_KEYS[start], "2026.23" if start != "review" else "2026.20")
    wanted = "2026.23" if start != "review" else "2026.20"
    expect(selected(page, SPRINT_KEYS[start])).to_have_value(wanted)
    for other, key in SPRINT_KEYS.items():
        if other == start:
            continue
        navigate(page, other)
        expect(selected(page, key)).to_have_value(wanted)
        no_exception(page)


def test_sprint_choice_is_not_shared_between_browser_sessions(page: Page, app: App, new_page):
    """Die Wahl gehört zur Sitzung: ein zweites Fenster beginnt wieder beim Standard."""
    open_page(page, app, "planning")
    choose(page, "planning-sprint", "2026.23")
    expect(selected(page, "planning-sprint")).to_have_value("2026.23")
    other = new_page()
    open_page(other, app, "planning")
    expect(selected(other, "planning-sprint")).to_have_value("2026.22")
