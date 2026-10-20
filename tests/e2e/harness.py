# SPDX-License-Identifier: EUPL-1.2
"""Helpers for the browser tests: start and stop app instances, prepare Git repositories and
read Streamlit pages.

Nothing here relies on fixed waits: we wait for states (server health check, Playwright
locators with automatic waiting).
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path

import yaml
from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from foresprint.config import PACKAGE
from foresprint.i18n import LANG_ENV
from foresprint.launcher import free_port
from foresprint.proctree import popen_options, terminate_tree
from foresprint.storage import AS_OF_ENV, DATA_ENV

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "teams"
# "Today" in the tests: sprint 2026.21 is running, 2026.22 is the next one (demo data).
AS_OF = "2026-10-15"
START_TIMEOUT = 90  # seconds until the server first shows signs of life


# --- Git -----------------------------------------------------------------------------------


@functools.cache
def _empty_gitconfig() -> Path:
    folder = Path(tempfile.mkdtemp(prefix="foresprint-e2e-"))
    config = folder / "gitconfig"
    config.touch()
    return config


def git_env(name: str = "Test", config: Path | None = None) -> dict[str, str]:
    """Environment for Git: fixed person, none of the machine's user and system settings.
    The "global" config is a separate, empty file and not ``/dev/null``: the app writes name and
    email with ``git config --global``, and Git replaces the file with a new one in the process
    (as root that would destroy the ``/dev/null`` device itself)."""
    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": f"{name.lower()}@example.invalid",
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": f"{name.lower()}@example.invalid",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(config or _empty_gitconfig()),
        "GIT_TERMINAL_PROMPT": "0",
    }


def git(cwd: Path, *args: str, check: bool = True, name: str = "Test") -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=os.environ | git_env(name),
    )
    return (done.stdout + done.stderr).strip() if not check else done.stdout.strip()


# --- Daten ---------------------------------------------------------------------------------


def copy_demo(target: Path, name: str = "demo") -> Path:
    """Copy of the demo data as ``target/teams/<name>``; returns the ``teams`` folder."""
    teams = target / "teams"
    teams.mkdir(parents=True, exist_ok=True)
    shutil.copytree(EXAMPLES / "demo", teams / name)
    return teams


def make_team_without_products(teams: Path, key: str = "ohne-produkte") -> None:
    """Creates a team without the products, PO and production access sections (copy of the demo)."""
    folder = teams / key
    shutil.copytree(EXAMPLES / "demo", folder)
    (folder / "products.yaml").unlink()
    team = folder / "team.yaml"
    raw = yaml.safe_load(team.read_text(encoding="utf-8"))
    raw["name"] = "Team ohne Produkte"
    raw["features"] = {"products": False, "po": False, "production": False}
    team.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    people = folder / "people.yaml"
    raw = yaml.safe_load(people.read_text(encoding="utf-8"))
    for person in raw.get("people", raw if isinstance(raw, list) else []):
        if isinstance(person, dict):
            person.pop("production_access", None)
    people.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for sprint in (folder / "sprints").glob("*.yaml"):
        content = yaml.safe_load(sprint.read_text(encoding="utf-8"))
        content.pop("products", None)
        content.pop("expected_absences", None)
        sprint.write_text(
            yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )


def init_repository(root: Path, remote: Path | None = None, name: str = "Test") -> None:
    """Git repository with all files as the first commit on ``main``; with ``remote``
    (bare repository) as ``origin`` and pushed."""
    git(root, "init", "-q", "-b", "main", name=name)
    if remote is not None:
        git(root, "remote", "add", "origin", str(remote), name=name)
    git(root, "add", "-A", name=name)
    git(root, "commit", "-qm", "Start", name=name)
    if remote is not None:
        git(root, "push", "-q", "-u", "origin", "main", name=name)


def make_bare(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "--bare", "-b", "main")
    return path


# --- App-Instanzen -------------------------------------------------------------------------


def _child_processes(pid: int) -> list[int]:
    """Child processes (Linux/macOS only; on Windows ``taskkill /T`` ends the whole tree).
    Without ``pgrep`` (slim containers without procps) it reads ``/proc``."""
    if sys.platform == "win32":
        return []
    try:
        done = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True)
    except FileNotFoundError:
        return _children_from_proc(pid)
    return [int(line) for line in done.stdout.split()]


def _children_from_proc(pid: int) -> list[int]:
    found = []
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            # "PID (name) state PPID ...": the name may contain spaces and parentheses.
            fields = (entry / "stat").read_text().rpartition(")")[2].split()
            if int(fields[1]) == pid:
                found.append(int(entry.name))
        except OSError, ValueError, IndexError:
            continue
    return found


class App:
    """A running web UI (own process, own settings folder, free port)."""

    def __init__(
        self,
        name: str,
        data_dir: Path,
        work: Path,
        *,
        language: str | None = None,
        person: str = "Test",
    ) -> None:
        self.name = name
        self.data_dir = data_dir
        # Settings and log live next to the data folder, never inside its Git repository.
        home = work.parent / f"{name}-app"
        home.mkdir(parents=True, exist_ok=True)
        self.config = home / "einstellungen"
        self.log = home / "server.log"
        self.gitconfig = home / "gitconfig"
        self.gitconfig.touch()
        self.language = language
        self.person = person
        self.port = 0
        self._process: subprocess.Popen | None = None
        self._log_file = None

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def _environment(self) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("FORESPRINT_", "SPRINTFORECAST_", "STREAMLIT_"))
        }
        env |= git_env(self.person, self.gitconfig)
        env |= {
            DATA_ENV: str(self.data_dir),
            AS_OF_ENV: AS_OF,
            "FORESPRINT_AUTOUPDATE": "off",
            "XDG_CONFIG_HOME": str(self.config),
            "APPDATA": str(self.config),
            "PYTHONUTF8": "1",
        }
        if self.language:
            env[LANG_ENV] = self.language
        return env

    def start(self) -> App:
        self.config.mkdir(parents=True, exist_ok=True)
        if not self.language:
            # Without a setting the UI is English; the browser tests expect German.
            # Stored as a setting instead of via the environment so that switching language in the
            # sidebar still works (the environment variable would take precedence).
            settings = self.config / PACKAGE / "settings.json"
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps({"language": "de"}), encoding="utf-8")
        self.port = free_port(0)
        self._log_file = open(self.log, "ab")  # noqa: SIM115 – lives until the server ends
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from foresprint import main; main()",
                "web",
                "--no-browser",
                "--port",
                str(self.port),
            ],
            env=self._environment(),
            cwd=self.data_dir,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            **popen_options(),
        )
        try:
            self._wait_until_healthy()
        except BaseException:
            self.stop()  # else the half-started server keeps running after the test
            raise
        return self

    def _wait_until_healthy(self) -> None:
        # Without a proxy: a proxy setting from the environment (http_proxy) would never reach the
        # local server and make the start fail for 90 seconds.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                break
            try:
                with opener.open(f"{self.url}/_stcore/health", timeout=2) as reply:
                    if reply.status == 200:
                        return
            except urllib.error.URLError, OSError:
                pass
            time.sleep(0.2)
        raise RuntimeError(f"App {self.name} startete nicht:\n{self.output()[-3000:]}")

    def output(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace") if self.log.exists() else ""

    def stop(self) -> None:
        """Stops the server together with everything it started. `web` puts the Streamlit server in
        its own session: killing only the start process leaves it running."""
        process = self._process
        self._process = None
        try:
            if process is not None:
                servers: list[int] = []
                with contextlib.suppress(OSError):  # without the list, terminate_tree still runs
                    servers = _child_processes(process.pid)
                try:
                    terminate_tree(process, timeout=10)
                finally:
                    for server in servers:
                        # Uvicorn waits for open connections after SIGTERM: kill it for good.
                        with contextlib.suppress(OSError):
                            os.killpg(server, signal.SIGKILL)
        finally:
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None

    def restart(self) -> App:
        """Stops the server and starts it again (same data and settings)."""
        self.stop()
        return self.start()


# --- Streamlit-Seiten ----------------------------------------------------------------------

APP_STATE = "[data-testid=stApp]"


def settle(page: Page) -> None:
    """Waits until the script has finished (Streamlit reports ``notRunning``)."""
    expect(page.locator(APP_STATE)).to_have_attribute("data-test-script-state", "notRunning")


def rerun_finished(page: Page) -> None:
    """Waits after an input (click, Enter) until Streamlit has started *and* finished the run.
    A plain ``settle`` might still see the state *before* the run. In the end only the
    expectation on the result is reliable (``expect`` on text or element state)."""
    with contextlib.suppress(PlaywrightTimeoutError):
        page.wait_for_function(
            "() => document.querySelector('[data-testid=stApp]')"
            "?.getAttribute('data-test-script-state') !== 'notRunning'",
            timeout=2_000,
        )
    settle(page)


def open_page(page: Page, app: App, path: str = "") -> None:
    page.goto(f"{app.url}/{path}")
    expect(page.get_by_test_id("stMain")).to_be_visible()
    settle(page)


def navigate(page: Page, path: str) -> None:
    """Switches via the sidebar (the session state is kept)."""
    page.get_by_test_id("stSidebarNav").locator(f'a[href$="/{path}"]').click()
    expect(page).to_have_url(f"{page.url.rsplit('/', 1)[0]}/{path}")
    settle(page)


def choose(page: Page, key: str, option: str) -> None:
    """Selects the entry ``option`` in the select box with the key ``key``."""
    page.locator(f".st-key-{key}").get_by_role("combobox").click()
    page.get_by_role("option", name=option, exact=True).click()


def selected(page: Page, key: str) -> Locator:
    """The input field of the select box with the key ``key`` (value = selected entry);
    check with ``expect(...).to_have_value(...)``."""
    return page.locator(f".st-key-{key}").get_by_role("combobox")


def main_area(page: Page) -> Locator:
    return page.get_by_test_id("stMain")


def sidebar(page: Page) -> Locator:
    return page.get_by_test_id("stSidebar")


def table_rows(table: Locator) -> list[list[str]]:
    """Rows of a data grid through its accessible table (the grid itself is a canvas).
    The table is invisible to the eye but present in the DOM."""
    expect(table).to_be_attached()
    rows = table.locator("tr")
    return [[cell.inner_text() for cell in row.locator("th, td").all()] for row in rows.all()]


STABLE_COUNT = """([selector, quietMs]) => {
    const n = document.querySelectorAll(selector).length;
    const now = performance.now();
    const state = window.__e2eStable = window.__e2eStable || {};
    if (state.selector !== selector || state.count !== n) {
        window.__e2eStable = {selector, count: n, since: now};
        return false;
    }
    return now - state.since >= quietMs;
}"""


def wait_until_stable(page: Page, selector: str, quiet_ms: int = 600) -> None:
    """Waits until the number of elements for ``selector`` has not changed for ``quiet_ms``.
    Needed for elements Streamlit loads after the script has ended (data grids, charts)."""
    page.wait_for_function(STABLE_COUNT, arg=[selector, quiet_ms])


def data_frames(page: Page, minimum: int = 0) -> list[Locator]:
    """All data grids of the main area once they are loaded (at least ``minimum``)."""
    selector = '[data-testid="stMain"] [data-testid="stDataFrame"]'
    frames = main_area(page).get_by_test_id("stDataFrame")
    if minimum:
        expect(frames.nth(minimum - 1)).to_be_attached()
    wait_until_stable(page, selector)
    # Grids in closed sections (expanders) are not drawn and are left out.
    found = [frame for frame in frames.all() if frame.is_visible()]
    for frame in found:
        frame.scroll_into_view_if_needed()  # off-screen grids load only on scrolling
        expect(frame.locator("table")).to_be_attached()
    return found


def all_tables(page: Page, minimum: int = 0) -> list[list[list[str]]]:
    return [table_rows(frame.locator("table")) for frame in data_frames(page, minimum)]


def no_exception(page: Page) -> None:
    """The page shows no Python error message from Streamlit."""
    expect(page.get_by_test_id("stException")).to_have_count(0)


def texts(locators: Iterable[Locator]) -> list[str]:
    return [loc.inner_text() for loc in locators]


# --- Absences grid and sharing -------------------------------------------------------------

HEADER_HEIGHT = 36  # px: header row of the data grid (Streamlit default)
ROW_HEIGHT = 35  # px: row height of the data grid


def absence_grid(page: Page) -> Locator:
    """The first data grid of the Absences page (person x sprint)."""
    return main_area(page).get_by_test_id("stDataFrame").first


def edit_absence(page: Page, person: str, sprint: str, value: str) -> None:
    """Enters a value in the absences grid. The grid is a canvas: the cell is reached by keyboard
    (click in the last column of the first row, then arrow keys to the target cell) and the
    value is typed; Enter commits it."""
    frame = absence_grid(page)
    frame.scroll_into_view_if_needed()
    rows = table_rows(frame.locator("table"))
    column = rows[0].index(sprint)
    row = [r[0] for r in rows[1:]].index(person)
    # Above the canvas lies a surface that receives the mouse events. The click on it waits
    # until it is stable (no scrolling, no reloading above it).
    surface = frame.locator(".dvn-scroller").first
    box = surface.bounding_box()
    assert box is not None
    surface.click(position={"x": box["width"] - 20, "y": HEADER_HEIGHT + ROW_HEIGHT / 2})
    # Send each key only after the previous one has arrived: the accessible table marks the
    # selected cell with aria-selected.
    here = [len(rows[0]) - 1, 0]  # column, row (the person column is column 0)
    selected_cell = lambda: frame.locator(  # noqa: E731
        f"[data-testid=glide-cell-{here[0]}-{here[1]}]"
    )
    expect(selected_cell()).to_have_attribute("aria-selected", "true")
    for key, step in [("ArrowLeft", (-1, 0))] * (here[0] - column) + [("ArrowDown", (0, 1))] * row:
        page.keyboard.press(key)
        here[0] += step[0]
        here[1] += step[1]
        expect(selected_cell()).to_have_attribute("aria-selected", "true")
    # The first character opens the input editor; an Enter sent too early would be lost.
    editor = page.locator("input.gdg-input")
    page.keyboard.press(value[0])
    expect(editor).to_have_value(value[0])
    if value[1:]:
        page.keyboard.type(value[1:])
        expect(editor).to_have_value(value)
    page.keyboard.press("Enter")
    # The input has arrived only once the cell shows the value.
    expect(frame.locator(f"[data-testid=glide-cell-{column}-{row}]")).to_have_text(value)


def absence_cell(page: Page, person: str, sprint: str) -> str:
    rows = table_rows(absence_grid(page).locator("table"))
    return rows[[r[0] for r in rows[1:]].index(person) + 1][rows[0].index(sprint)]


def share(page: Page) -> Locator:
    """Clicks "Save and share" in the sidebar and returns the sidebar messages
    (success, error, warning)."""
    button = sidebar(page).get_by_role("button", name="Speichern und teilen")
    # With pending changes the "Git" section opens by itself after the run (shortly after the
    # label appears). An immediate ``is_visible`` would still see it closed, and the click on the
    # heading would close it again right away.
    with contextlib.suppress(PlaywrightTimeoutError):
        button.wait_for(state="visible", timeout=2_000)
    if not button.is_visible():  # no pending changes: "Git" stays closed
        sidebar(page).locator("summary").filter(has_text="Git:").click()
    button.click()
    return sidebar(page).get_by_test_id("stAlert")
