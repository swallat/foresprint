# SPDX-License-Identifier: EUPL-1.2
"""Hilfen der Browsertests: App-Instanzen starten und beenden, Git-Repositories vorbereiten und
Streamlit-Seiten auslesen.

Nichts hier hängt an festen Wartezeiten: Gewartet wird auf Zustände (Gesundheitsprüfung des
Servers, Playwright-Locatoren mit automatischem Warten).
"""

from __future__ import annotations

import contextlib
import functools
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

from sprintforecast.i18n import LANG_ENV
from sprintforecast.launcher import free_port
from sprintforecast.proctree import popen_options, terminate_tree
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "teams"
# „Heute“ in den Tests: Sprint 2026.21 läuft, 2026.22 ist der nächste (Demo-Daten).
STICHTAG = "2026-10-15"
START_TIMEOUT = 90  # Sekunden bis zum ersten Lebenszeichen des Servers


# --- Git -----------------------------------------------------------------------------------


@functools.cache
def _empty_gitconfig() -> Path:
    folder = Path(tempfile.mkdtemp(prefix="sprintforecast-e2e-"))
    config = folder / "gitconfig"
    config.touch()
    return config


def git_env(name: str = "Test", config: Path | None = None) -> dict[str, str]:
    """Umgebung für Git: feste Person, keine Benutzer- und Systemeinstellungen des Rechners.
    Die „globale“ Konfiguration ist eine eigene, leere Datei und nicht ``/dev/null``: Die App
    schreibt Name und E-Mail mit ``git config --global``, und Git ersetzt die Datei dabei durch
    eine neue (unter root wäre das Gerät ``/dev/null`` selbst zerstört)."""
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
    """Kopie der Demo-Daten als ``target/teams/<name>``; liefert den Ordner ``teams``."""
    teams = target / "teams"
    teams.mkdir(parents=True, exist_ok=True)
    shutil.copytree(EXAMPLES / "demo", teams / name)
    return teams


def make_team_without_products(teams: Path, key: str = "ohne-produkte") -> None:
    """Legt ein Team ohne die Bereiche Produkte, PO und Produktionszugriff an (Kopie der Demo)."""
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
    """Git-Repository mit allen Dateien als erstem Commit auf ``main``; mit ``remote``
    (Bare-Repository) als ``origin`` und hochgeladen."""
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
    """Kindprozesse (nur Linux/macOS; unter Windows beendet ``taskkill /T`` den ganzen Baum).
    Ohne ``pgrep`` (schlanke Container ohne procps) liest es ``/proc``."""
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
            # „PID (Name) Zustand PPID …“: der Name darf Leerzeichen und Klammern enthalten.
            fields = (entry / "stat").read_text().rpartition(")")[2].split()
            if int(fields[1]) == pid:
                found.append(int(entry.name))
        except OSError, ValueError, IndexError:
            continue
    return found


class App:
    """Eine laufende Weboberfläche (eigener Prozess, eigener Einstellungsordner, freier Port)."""

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
        # Einstellungen und Protokoll liegen neben dem Datenordner, nie im Git-Repository darin.
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
            if not key.startswith(("SPRINTFORECAST_", "STREAMLIT_"))
        }
        env |= git_env(self.person, self.gitconfig)
        env |= {
            DATA_ENV: str(self.data_dir),
            STICHTAG_ENV: STICHTAG,
            "SPRINTFORECAST_AUTOUPDATE": "off",
            "XDG_CONFIG_HOME": str(self.config),
            "APPDATA": str(self.config),
            "PYTHONUTF8": "1",
        }
        # Ohne Einstellung ist die Oberfläche englisch; die Browsertests erwarten Deutsch.
        env[LANG_ENV] = self.language or "de"
        return env

    def start(self) -> App:
        self.config.mkdir(parents=True, exist_ok=True)
        self.port = free_port(0)
        self._log_file = open(self.log, "ab")  # noqa: SIM115 – lebt, bis der Server endet
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from sprintforecast import main; main()",
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
            self.stop()  # sonst läuft der halb gestartete Server nach dem Testlauf weiter
            raise
        return self

    def _wait_until_healthy(self) -> None:
        # Ohne Proxy: eine Proxy-Vorgabe der Umgebung (http_proxy) würde den lokalen Server nie
        # erreichen und den Start 90 Sekunden lang scheitern lassen.
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
        """Beendet den Server samt allem, was er gestartet hat. `web` setzt den Streamlit-Server in
        eine eigene Sitzung: Wer nur den Startprozess abschießt, lässt ihn laufen."""
        process = self._process
        self._process = None
        try:
            if process is not None:
                servers: list[int] = []
                with contextlib.suppress(OSError):  # ohne Liste bleibt immer noch terminate_tree
                    servers = _child_processes(process.pid)
                try:
                    terminate_tree(process, timeout=10)
                finally:
                    for server in servers:
                        # Uvicorn wartet nach SIGTERM auf offene Verbindungen: endgültig beenden.
                        with contextlib.suppress(OSError):
                            os.killpg(server, signal.SIGKILL)
        finally:
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None

    def restart(self) -> App:
        """Beendet den Server und startet ihn neu (gleiche Daten und Einstellungen)."""
        self.stop()
        return self.start()


# --- Streamlit-Seiten ----------------------------------------------------------------------

APP_STATE = "[data-testid=stApp]"


def settle(page: Page) -> None:
    """Wartet, bis das Skript durchgelaufen ist (Streamlit meldet ``notRunning``)."""
    expect(page.locator(APP_STATE)).to_have_attribute("data-test-script-state", "notRunning")


def rerun_finished(page: Page) -> None:
    """Wartet nach einer Eingabe (Klick, Enter), bis Streamlit den Lauf begonnen *und* beendet hat.
    Ein bloßes ``settle`` könnte noch den Zustand *vor* dem Lauf sehen. Verlässlich bleibt am Ende
    nur die Erwartung an das Ergebnis (``expect`` auf Text oder Zustand eines Elements)."""
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
    """Wechselt über die Seitenleiste (der Sitzungsstand bleibt erhalten)."""
    page.get_by_test_id("stSidebarNav").locator(f'a[href$="/{path}"]').click()
    expect(page).to_have_url(f"{page.url.rsplit('/', 1)[0]}/{path}")
    settle(page)


def choose(page: Page, key: str, option: str) -> None:
    """Wählt in der Auswahlliste mit dem Schlüssel ``key`` den Eintrag ``option``."""
    page.locator(f".st-key-{key}").get_by_role("combobox").click()
    page.get_by_role("option", name=option, exact=True).click()


def selected(page: Page, key: str) -> Locator:
    """Das Eingabefeld der Auswahlliste mit dem Schlüssel ``key`` (Wert = gewählter Eintrag);
    prüfen mit ``expect(...).to_have_value(...)``."""
    return page.locator(f".st-key-{key}").get_by_role("combobox")


def main_area(page: Page) -> Locator:
    return page.get_by_test_id("stMain")


def sidebar(page: Page) -> Locator:
    return page.get_by_test_id("stSidebar")


def table_rows(table: Locator) -> list[list[str]]:
    """Zeilen eines Datenrasters über dessen barrierefreie Tabelle (das Raster selbst ist eine
    Zeichenfläche). Die Tabelle ist für das Auge unsichtbar, aber im DOM."""
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
    """Wartet, bis sich die Zahl der Elemente zu ``selector`` ``quiet_ms`` lang nicht mehr ändert.
    Nötig für Elemente, die Streamlit nach dem Ende des Skripts nachlädt (Datenraster, Diagramme)."""
    page.wait_for_function(STABLE_COUNT, arg=[selector, quiet_ms])


def data_frames(page: Page, minimum: int = 0) -> list[Locator]:
    """Alle Datenraster des Hauptbereichs, sobald sie geladen sind (mindestens ``minimum``)."""
    selector = '[data-testid="stMain"] [data-testid="stDataFrame"]'
    frames = main_area(page).get_by_test_id("stDataFrame")
    if minimum:
        expect(frames.nth(minimum - 1)).to_be_attached()
    wait_until_stable(page, selector)
    # Raster in geschlossenen Bereichen (Expander) sind nicht gezeichnet und bleiben außen vor.
    found = [frame for frame in frames.all() if frame.is_visible()]
    for frame in found:
        frame.scroll_into_view_if_needed()  # Raster außerhalb des Bildes laden erst beim Scrollen
        expect(frame.locator("table")).to_be_attached()
    return found


def all_tables(page: Page, minimum: int = 0) -> list[list[list[str]]]:
    return [table_rows(frame.locator("table")) for frame in data_frames(page, minimum)]


def no_exception(page: Page) -> None:
    """Die Seite zeigt keine Python-Fehlermeldung von Streamlit."""
    expect(page.get_by_test_id("stException")).to_have_count(0)


def texts(locators: Iterable[Locator]) -> list[str]:
    return [loc.inner_text() for loc in locators]


# --- Fehltage-Raster und Teilen ------------------------------------------------------------

HEADER_HEIGHT = 36  # px: Kopfzeile des Datenrasters (Streamlit-Vorgabe)
ROW_HEIGHT = 35  # px: Zeilenhöhe des Datenrasters


def absence_grid(page: Page) -> Locator:
    """Das erste Datenraster der Seite Fehltage (Person × Sprint)."""
    return main_area(page).get_by_test_id("stDataFrame").first


def edit_absence(page: Page, person: str, sprint: str, value: str) -> None:
    """Trägt in das Fehltage-Raster einen Wert ein. Das Raster ist eine Zeichenfläche: Die Zelle
    wird über die Tastatur angesteuert (Klick in die letzte Spalte der ersten Zeile, dann mit den
    Pfeiltasten zur Zielzelle) und der Wert getippt; Enter übernimmt ihn."""
    frame = absence_grid(page)
    frame.scroll_into_view_if_needed()
    rows = table_rows(frame.locator("table"))
    column = rows[0].index(sprint)
    row = [r[0] for r in rows[1:]].index(person)
    # Über der Zeichenfläche liegt eine Fläche, die die Mausereignisse annimmt. Der Klick darauf
    # wartet, bis sie ruhig steht (kein Scrollen, kein Nachladen darüber).
    surface = frame.locator(".dvn-scroller").first
    box = surface.bounding_box()
    assert box is not None
    surface.click(position={"x": box["width"] - 20, "y": HEADER_HEIGHT + ROW_HEIGHT / 2})
    # Jede Taste erst senden, wenn die vorige angekommen ist: Die barrierefreie Tabelle markiert
    # die gewählte Zelle mit aria-selected.
    here = [len(rows[0]) - 1, 0]  # Spalte, Zeile (die Personenspalte hat die Spalte 0)
    selected_cell = lambda: frame.locator(  # noqa: E731
        f"[data-testid=glide-cell-{here[0]}-{here[1]}]"
    )
    expect(selected_cell()).to_have_attribute("aria-selected", "true")
    for key, step in [("ArrowLeft", (-1, 0))] * (here[0] - column) + [("ArrowDown", (0, 1))] * row:
        page.keyboard.press(key)
        here[0] += step[0]
        here[1] += step[1]
        expect(selected_cell()).to_have_attribute("aria-selected", "true")
    # Das erste Zeichen öffnet den Eingabeeditor; ein zu früh gesendetes Enter ginge verloren.
    editor = page.locator("input.gdg-input")
    page.keyboard.press(value[0])
    expect(editor).to_have_value(value[0])
    if value[1:]:
        page.keyboard.type(value[1:])
        expect(editor).to_have_value(value)
    page.keyboard.press("Enter")
    # Erst wenn die Zelle den Wert zeigt, ist die Eingabe angekommen.
    expect(frame.locator(f"[data-testid=glide-cell-{column}-{row}]")).to_have_text(value)


def absence_cell(page: Page, person: str, sprint: str) -> str:
    rows = table_rows(absence_grid(page).locator("table"))
    return rows[[r[0] for r in rows[1:]].index(person) + 1][rows[0].index(sprint)]


def share(page: Page) -> Locator:
    """Klickt in der Seitenleiste „Speichern und teilen“ und liefert die Meldungen der
    Seitenleiste (Erfolg, Fehler, Warnung)."""
    button = sidebar(page).get_by_role("button", name="Speichern und teilen")
    # Mit offenen Änderungen klappt der Bereich „Git“ nach dem Durchlauf von selbst auf (kurz
    # nachdem die Beschriftung erscheint). Ein sofortiges ``is_visible`` sähe ihn noch zu und der
    # Klick auf die Überschrift würde ihn gleich wieder schließen.
    with contextlib.suppress(PlaywrightTimeoutError):
        button.wait_for(state="visible", timeout=2_000)
    if not button.is_visible():  # ohne offene Änderungen bleibt der Bereich „Git“ zugeklappt
        sidebar(page).locator("summary").filter(has_text="Git:").click()
    button.click()
    return sidebar(page).get_by_test_id("stAlert")
