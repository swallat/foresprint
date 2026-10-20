# SPDX-License-Identifier: EUPL-1.2
"""Fixtures of the browser tests.

Browser: the default is the Chromium installed with ``playwright install chromium``. Environment
variables: ``E2E_CHANNEL`` (e.g. ``msedge`` or ``chrome``: an installed browser),
``E2E_EXECUTABLE`` (path to a Chromium), ``E2E_HEADED=1`` (visible window),
``E2E_ARTIFACTS`` (folder for screenshots and server logs of failed tests, default
``test-results/e2e``).
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from harness import (
    App,
    copy_demo,
    init_repository,
    make_bare,
    make_team_without_products,
)
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    expect,
    sync_playwright,
)

HERE = Path(__file__).parent
# The first page load of a freshly started app still loads libraries (a few seconds), so all
# expectations wait longer than the default 5 seconds.
expect.set_options(timeout=20_000)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything in tests/e2e is a browser test, even without a marker in the module."""
    for item in items:
        if Path(str(item.fspath)).is_relative_to(HERE):
            item.add_marker(pytest.mark.e2e)


def _track(item: pytest.Item, attribute: str, value: object) -> None:
    """Remembers the pages and apps of the test so the failure report can still capture them
    before cleanup (the apps are still running then)."""
    if not hasattr(item, attribute):
        setattr(item, attribute, [])
    getattr(item, attribute).append(value)


def _save_failure(item: pytest.Item) -> None:
    folder = Path(os.environ.get("E2E_ARTIFACTS", "test-results/e2e"))
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", item.name)
    pages: list[Page] = getattr(item, "e2e_pages", [])
    for number, shown in enumerate(pages, 1):
        suffix = f"-{number}" if len(pages) > 1 else ""
        with contextlib.suppress(Exception):  # the screenshot is only a debugging aid
            shown.screenshot(path=str(folder / f"{name}{suffix}.png"), full_page=True)
    apps = {
        id(a): a for a in [*getattr(item, "e2e_apps", []), *getattr(item, "funcargs", {}).values()]
    }
    for running in apps.values():
        if isinstance(running, App):
            with contextlib.suppress(Exception):
                (folder / f"{name}-{running.name}.log").write_text(
                    running.output()[-200_000:], encoding="utf-8"
                )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    setattr(item, f"rep_{report.when}", report)
    # In the report of the test function itself: pages and servers still run (cleanup follows).
    if report.failed and report.when in ("setup", "call"):
        _save_failure(item)
    return report


# --- Browser -------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def playwright_driver() -> Iterator[Playwright]:
    with sync_playwright() as driver:
        yield driver


@pytest.fixture(scope="session")
def browser(playwright_driver: Playwright) -> Iterator[Browser]:
    options: dict = {"headless": os.environ.get("E2E_HEADED") != "1"}
    if channel := os.environ.get("E2E_CHANNEL"):
        options["channel"] = channel
    if executable := os.environ.get("E2E_EXECUTABLE"):
        options["executable_path"] = executable
    try:
        instance = playwright_driver.chromium.launch(**options)
    except Exception as e:  # missing browser: a hint instead of a long error output
        pytest.fail(
            "Der Browser startet nicht. Einmalig `uv run playwright install chromium` ausführen "
            "(unter Linux mit --with-deps) oder E2E_CHANNEL=msedge bzw. E2E_EXECUTABLE=… setzen."
            f"\n{e}",
            pytrace=False,
        )
    yield instance
    instance.close()


@pytest.fixture
def context(browser: Browser) -> Iterator[BrowserContext]:
    """Ein frischer Browserkontext je Test (eigene Sitzung, eigener Speicher)."""
    new = browser.new_context(viewport={"width": 1400, "height": 900}, locale="de-DE")
    new.set_default_timeout(20_000)
    yield new
    new.close()


@pytest.fixture
def page(context: BrowserContext, request: pytest.FixtureRequest) -> Page:
    opened = context.new_page()
    _track(request.node, "e2e_pages", opened)
    return opened


@pytest.fixture
def new_page(browser: Browser, request: pytest.FixtureRequest) -> Iterator[Callable[..., Page]]:
    """Additional pages in their own context, e.g. for two apps in the same test."""
    contexts: list[BrowserContext] = []

    def make(width: int = 1400, height: int = 900) -> Page:
        created = browser.new_context(viewport={"width": width, "height": height}, locale="de-DE")
        created.set_default_timeout(20_000)
        contexts.append(created)
        opened = created.new_page()
        _track(request.node, "e2e_pages", opened)
        return opened

    yield make
    for created in contexts:
        created.close()


# --- Apps ----------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def e2e_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("e2e")


@pytest.fixture(scope="session")
def app(e2e_dir: Path) -> Iterator[App]:
    """The demo data with one team; read-only (tests change nothing here)."""
    work = e2e_dir / "demo"
    data = copy_demo(work)
    server = App("demo", data, work).start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def app_without_products(e2e_dir: Path) -> Iterator[App]:
    """A team without the products, PO and production access sections; read-only."""
    work = e2e_dir / "ohne-produkte"
    teams = work / "teams"
    make_team_without_products(teams)
    server = App("ohne-produkte", teams, work).start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def app_english(e2e_dir: Path) -> Iterator[App]:
    """The demo data with an English UI (environment variable); read-only."""
    work = e2e_dir / "english"
    data = copy_demo(work)
    server = App("english", data, work, language="en").start()
    yield server
    server.stop()


@pytest.fixture
def make_app(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Callable[..., App]]:
    """Starts a separate app per test (for tests that change data or settings)."""
    started: list[App] = []

    def make(name: str = "app", *, language: str | None = None, git: bool = False) -> App:
        work = tmp_path / name
        data = copy_demo(work)
        if git:
            init_repository(work)
        server = App(name, data, work, language=language).start()
        started.append(server)
        _track(request.node, "e2e_apps", server)
        return server

    yield make
    for server in started:
        server.stop()


@pytest.fixture
def clones(
    tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[Callable[[], tuple[App, App, Path]]]:
    """Two clones of the same bare repository, one app instance each (Alice and Bob)."""
    started: list[App] = []

    def make() -> tuple[App, App, Path]:
        from harness import git

        bare = make_bare(tmp_path / "server.git")
        alice_work = tmp_path / "alice"
        data = copy_demo(alice_work)
        init_repository(alice_work, bare, "Alice")
        bob_work = tmp_path / "bob"
        git(tmp_path, "clone", "-q", str(bare), str(bob_work), name="Bob")
        alice = App("alice", data, alice_work, person="Alice").start()
        started.append(alice)  # immediately: if Bob fails to start, Alice must still be stopped
        _track(request.node, "e2e_apps", alice)
        bob = App("bob", bob_work / "teams", bob_work, person="Bob").start()
        started.append(bob)
        _track(request.node, "e2e_apps", bob)
        return alice, bob, bare

    yield make
    for server in started:
        server.stop()
