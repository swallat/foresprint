# SPDX-License-Identifier: EUPL-1.2
"""Regenerates the README screenshots in docs/assets/screenshots/ from the demo data.

Usage: ``uv run python scripts/readme_screenshots.py [--out DIR]``

Runs the app on a copy of the demo data (a Git repository, so the start page shows no setup
hints) in English, once light and once dark. Aborts without writing a file for a page that shows
an error message ("Page not found", a Python exception, a Streamlit alert about a failure), so a
broken screenshot cannot reach the README unnoticed.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
sys.path.insert(0, str(ROOT / "tests"))

from harness import (  # noqa: E402
    App,
    copy_demo,
    init_repository,
    main_area,
    make_bare,
    open_page,
    settle,
    wait_until_stable,
)
from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402
from ticketfixtures import enable, seed  # noqa: E402

# name -> (URL path, heading that must be visible)
PAGES = {
    "start": ("", "What would you like to do?"),
    "forecast": ("forecast", "Forecast"),
    "planning": ("planning", "Sprint Planning"),
    "tickets": ("tickets", "Tickets"),
    "products": ("products", "Product distribution"),
    "analysis": ("analysis", "Analysis"),
}
THEMES = {"light": "Light", "dark": "Dark"}
ERRORS = ("Page not found", "Traceback", "Error")


class BrokenScreenshot(RuntimeError):
    pass


def check(page: Page, name: str, heading: str) -> None:
    """Raises when the page shows an error instead of the expected content."""
    expect(main_area(page).get_by_role("heading", name=heading).first).to_be_visible()
    problems = []
    if page.get_by_test_id("stException").count():
        problems.append("Python exception")
    if page.get_by_role("dialog").count():
        problems.append("dialog open: " + page.get_by_role("dialog").first.inner_text()[:80])
    if page.get_by_test_id("stAlert").filter(has_text="Error").count():
        problems.append("error alert")
    for text in ERRORS[:2]:
        if page.get_by_text(text).count():
            problems.append(f"text '{text}' on the page")
    if problems:
        raise BrokenScreenshot(f"{name}: " + "; ".join(problems))


def set_theme(page: Page, app: App, label: str) -> None:
    open_page(page, app, "app_settings")
    page.locator(".st-key-theme").get_by_text(label, exact=True).click()
    settle(page)


def relax_targets(data: Path) -> None:
    """Later target dates than the test fixtures use, so the traffic lights are not all red."""
    file = data / "demo" / "projects.yaml"
    file.write_text(
        file.read_text(encoding="utf-8")
        .replace("2027-03-31", "2028-06-30")
        .replace("2026-11-30", "2027-09-30"),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "assets" / "screenshots")
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="foresprint-shots-") as tmp:
        work = Path(tmp) / "demo"
        data = copy_demo(work)
        enable(data)  # the Tickets page only exists for teams with the ticket feature
        relax_targets(data)
        seed(data)
        # Remote and author, so the start page shows no setup hints.
        init_repository(data, make_bare(Path(tmp) / "remote.git"))
        app = App("demo", data, work, language="en")
        app.gitconfig.write_text("[user]\n\tname = Alex\n\temail = alex@example.invalid\n")
        app.start()
        try:
            with sync_playwright() as driver:
                options = {}
                if channel := os.environ.get("E2E_CHANNEL"):
                    options["channel"] = channel
                if executable := os.environ.get("E2E_EXECUTABLE"):
                    options["executable_path"] = executable
                browser = driver.chromium.launch(**options)
                page = browser.new_page(viewport={"width": 1400, "height": 1000})
                for theme, label in THEMES.items():
                    set_theme(page, app, label)
                    for name, (path, heading) in PAGES.items():
                        open_page(page, app, path)
                        wait_until_stable(page, '[data-testid="stMain"] [data-testid]')
                        page.mouse.move(0, 0)  # no tooltip from a hovered element
                        check(page, name, heading)
                        target = out / f"{name}-{theme}.png"
                        page.screenshot(path=str(target))
                        print("wrote", target)
                browser.close()
        finally:
            app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
