# SPDX-License-Identifier: EUPL-1.2
"""Step bar of the boards: all steps equally high (active and inactive), nothing jumps on page
change, the text never wraps, at every window width."""

import contextlib
import re

import pytest
from harness import App, open_page, settle
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

BOARDS = ["fehltage", "vorplanung", "planning", "review"]
STEP_HEIGHT = 40  # 2.5 rem at 16 px font size
ACTIVE_BACKGROUND = "rgb(42, 120, 214)"

# In narrow windows Streamlit draws each link twice (one is hidden): the visible one is always
# measured.
HELPERS = """
const visibleLink = el => [...el.querySelectorAll('[data-testid="stPageLink-NavLink"]')]
    .find(link => link.getClientRects().length > 0);
const stepContainers = () => [...document.querySelectorAll(
    'div.st-key-board-nav [class*="st-key-board-step-"], div.st-key-board-nav [class*="st-key-board-active-"]'
)];
"""

LAYOUT_DONE = (
    "() => {"
    + HELPERS
    + f"""
    const links = stepContainers().map(visibleLink);
    return links.length > 0 && links.every(l => l && l.getBoundingClientRect().height === {STEP_HEIGHT});
}}"""
)

MEASURE = (
    "() => {"
    + HELPERS
    + """
    return stepContainers().map(el => {
        const cls = [...el.classList].find(c => /^st-key-board-(step|active)-/.test(c));
        const link = visibleLink(el);
        const label = link.querySelector('p');
        const box = link.getBoundingClientRect();
        return {
            key: cls.replace(/^st-key-board-(step|active)-/, ''),
            active: cls.startsWith('st-key-board-active-'),
            x: box.x, y: box.y, width: box.width, height: box.height,
            wrapHeight: el.getBoundingClientRect().height,
            labelLines: Math.round(label.getBoundingClientRect().height / parseFloat(getComputedStyle(label).lineHeight)),
            labelFits: label.scrollWidth <= label.clientWidth,
            background: getComputedStyle(link).backgroundColor,
        };
    });
}"""
)


def measure(page: Page) -> list[dict]:
    """Measures the steps once the layout is stable. If the page never reaches the expected height,
    the wait times out and the test assertions report the measured values."""
    expect(page.locator("div.st-key-board-nav")).to_be_visible()
    with contextlib.suppress(PlaywrightTimeoutError):
        page.wait_for_function(LAYOUT_DONE, timeout=10_000)
    return page.evaluate(MEASURE)


def go_to_step(page: Page, board: str) -> None:
    """Switches with the step of the bar (in narrow windows the sidebar is closed)."""
    page.locator(f"div.st-key-board-nav .st-key-board-step-{board} a:visible").click()
    expect(page).to_have_url(re.compile(rf"/{board}$"))
    settle(page)


def rounded(box: dict) -> tuple:
    return tuple(round(box[k], 1) for k in ("x", "y", "width", "height"))


@pytest.mark.parametrize("width", [1900, 1400, 900, 500])
def test_steps_are_equally_tall_and_stay_in_place(new_page, app: App, width: int):
    page = new_page(width)
    open_page(page, app, "fehltage")
    seen: dict[str, list[dict]] = {}
    for board in BOARDS:
        if board != "fehltage":
            go_to_step(page, board)
        steps = measure(page)
        seen[board] = steps
        assert [s["key"] for s in steps] == BOARDS
        assert [s["key"] for s in steps if s["active"]] == [board]
        for step in steps:
            assert round(step["height"], 1) == STEP_HEIGHT, (board, step)
            assert round(step["wrapHeight"], 1) == STEP_HEIGHT, (board, step)
            assert step["labelLines"] == 1 and step["labelFits"], (board, step)
            expected = ACTIVE_BACKGROUND if step["active"] else "rgba(0, 0, 0, 0)"
            assert step["background"] == expected, (board, step)
    first = [rounded(s) for s in seen["fehltage"]]
    for board in BOARDS[1:]:
        assert [rounded(s) for s in seen[board]] == first, f"Schritte springen auf {board}"


@pytest.mark.parametrize(("width", "rows"), [(1900, 1), (1400, 2), (500, 4)])
def test_steps_line_up_by_the_available_width(new_page, app: App, width: int, rows: int):
    page = new_page(width)
    open_page(page, app, "planning")
    steps = measure(page)
    assert len(steps) == 4
    assert len({round(s["y"]) for s in steps}) == rows


def test_team_without_products_has_three_equally_tall_steps(new_page, app_without_products: App):
    page = new_page(1400)
    open_page(page, app_without_products, "fehltage")
    for board in ["fehltage", "planning", "review"]:
        if board != "fehltage":
            go_to_step(page, board)
        steps = measure(page)
        assert [s["key"] for s in steps] == ["fehltage", "planning", "review"]
        assert {round(s["height"], 1) for s in steps} == {STEP_HEIGHT}
        assert [s["key"] for s in steps if s["active"]] == [board]
