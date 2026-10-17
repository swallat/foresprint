# SPDX-License-Identifier: EUPL-1.2
"""Fixtures der Browsertests.

Browser: Standard ist das mit ``playwright install chromium`` geladene Chromium. Umgebungs-
variablen: ``E2E_CHANNEL`` (z. B. ``msedge`` oder ``chrome``: ein installierter Browser),
``E2E_EXECUTABLE`` (Pfad zu einem Chromium), ``E2E_HEADED=1`` (sichtbares Fenster),
``E2E_ARTIFACTS`` (Ordner für Bilder fehlgeschlagener Tests, Standard ``test-results/e2e``).
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
# Der erste Seitenaufruf einer frisch gestarteten App lädt noch Bibliotheken nach (einige
# Sekunden); alle Erwartungen warten darum länger als die 5 Sekunden der Vorgabe.
expect.set_options(timeout=20_000)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Alles in tests/e2e ist ein Browsertest – auch ohne Marker im Modul."""
    for item in items:
        if Path(str(item.fspath)).is_relative_to(HERE):
            item.add_marker(pytest.mark.e2e)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    setattr(item, f"rep_{report.when}", report)
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
    except Exception as e:  # fehlender Browser: Hinweis statt langer Fehlerausgabe
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
def page(context: BrowserContext, request: pytest.FixtureRequest) -> Iterator[Page]:
    opened = context.new_page()
    yield opened
    report = getattr(request.node, "rep_call", None)
    if report is not None and report.failed:
        folder = Path(os.environ.get("E2E_ARTIFACTS", "test-results/e2e"))
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
        with contextlib.suppress(Exception):  # das Bild ist nur eine Hilfe bei der Fehlersuche
            opened.screenshot(path=str(folder / f"{name}.png"), full_page=True)


@pytest.fixture
def new_page(browser: Browser) -> Iterator[Callable[..., Page]]:
    """Weitere Seiten in eigenem Kontext, z. B. für zwei Apps im selben Test."""
    contexts: list[BrowserContext] = []

    def make(width: int = 1400, height: int = 900) -> Page:
        created = browser.new_context(viewport={"width": width, "height": height}, locale="de-DE")
        created.set_default_timeout(20_000)
        contexts.append(created)
        return created.new_page()

    yield make
    for created in contexts:
        created.close()


# --- Apps ----------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def e2e_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("e2e")


@pytest.fixture(scope="session")
def app(e2e_dir: Path) -> Iterator[App]:
    """Die Demo-Daten mit einem Team; nur zum Lesen (Tests ändern hier nichts)."""
    work = e2e_dir / "demo"
    data = copy_demo(work)
    server = App("demo", data, work).start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def app_without_products(e2e_dir: Path) -> Iterator[App]:
    """Ein Team ohne die Bereiche Produkte, PO und Produktionszugriff; nur zum Lesen."""
    work = e2e_dir / "ohne-produkte"
    teams = work / "teams"
    make_team_without_products(teams)
    server = App("ohne-produkte", teams, work).start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def app_english(e2e_dir: Path) -> Iterator[App]:
    """Die Demo-Daten mit englischer Oberfläche (Umgebungsvariable); nur zum Lesen."""
    work = e2e_dir / "english"
    data = copy_demo(work)
    server = App("english", data, work, language="en").start()
    yield server
    server.stop()


@pytest.fixture
def make_app(tmp_path: Path) -> Iterator[Callable[..., App]]:
    """Startet eine eigene App je Test (für Tests, die Daten oder Einstellungen ändern)."""
    started: list[App] = []

    def make(name: str = "app", *, language: str | None = None, git: bool = False) -> App:
        work = tmp_path / name
        data = copy_demo(work)
        if git:
            init_repository(work)
        server = App(name, data, work, language=language).start()
        started.append(server)
        return server

    yield make
    for server in started:
        server.stop()


@pytest.fixture
def clones(tmp_path: Path) -> Iterator[Callable[[], tuple[App, App, Path]]]:
    """Zwei Klone desselben Bare-Repositorys mit je einer App-Instanz (Alice und Bob)."""
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
        bob = App("bob", bob_work / "teams", bob_work, person="Bob").start()
        started.extend([alice, bob])
        return alice, bob, bare

    yield make
    for server in started:
        server.stop()
