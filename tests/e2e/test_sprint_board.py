# SPDX-License-Identifier: EUPL-1.2
"""Sprint board of the tickets page: a card dragged onto another sprint is earmarked there, a card
dropped on the release bar goes back to the automatic distribution."""

import sys
from collections.abc import Callable
from pathlib import Path

from harness import App, open_page, rerun_finished
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).parent.parent))
from ticketfixtures import enable, seed

from sprintforecast.storage import Repository


def test_dragging_a_card_earmarks_it_and_the_release_bar_undoes_it(
    page, make_app: Callable[..., App], tmp_path: Path
):
    app = make_app("board", language="en")
    enable(app.data_dir)
    seed(app.data_dir)
    app.stop()
    app.start()
    open_page(page, app, "tickets")
    page.get_by_role("tab", name="Sprints").click()
    page.get_by_text("Drag and drop", exact=True).click()
    rerun_finished(page)
    board = page.locator("[data-testid=stBidiComponentIsolated]").first
    cards = board.locator(".card")
    expect(cards.first).to_be_visible()
    card = board.locator(".card:not(.fixed)").first
    key = card.locator(".key").inner_text()
    columns = board.locator(".column")
    target = columns.nth(1)
    target_sprint = target.locator("h4").inner_text()
    card.drag_to(target)
    rerun_finished(page)
    earmarks = Repository(app.data_dir).load("demo").preplan.earmarks
    assert [(e.ticket, e.sprint) for e in earmarks] == [(key, target_sprint)]
    expect(
        page.locator("[data-testid=stBidiComponentIsolated]")
        .first.locator(".column")
        .nth(1)
        .locator(".card.earmark", has_text=key)
    ).to_be_visible()
    moved = page.locator("[data-testid=stBidiComponentIsolated]").first
    moved.locator(".card.earmark", has_text=key).drag_to(moved.locator(".release"))
    rerun_finished(page)
    assert not Repository(app.data_dir).load("demo").preplan.earmarks
