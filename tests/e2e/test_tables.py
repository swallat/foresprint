# SPDX-License-Identifier: EUPL-1.2
"""Tabellen und Kennzahlen: keine „None“-Zellen und nichts mit „…“ abgeschnitten."""

import pytest
from harness import App, all_tables, main_area, open_page
from playwright.sync_api import expect

from sprintforecast.web.ui import PAGES

# Seiten mit Datenrastern und die Zahl der Raster, die sie in den Demo-Daten mindestens zeigen.
GRIDS = {
    "fehltage": 3,
    "vorplanung": 3,
    "planning": 1,
    "review": 1,
    "forecast": 2,
    "analyse": 2,
    "produkte": 3,
    "sprints": 1,
    "personen": 1,
    "produktliste": 1,
}
PAGE_KEYS = [key for entries in PAGES.values() for key in entries]
MISSING_WORDS = {"none", "nan", "<na>", "nat", "null"}

# Elemente mit „…“ am Ende, deren Text breiter ist als der Platz (abgeschnitten). Ohne Breite
# (clientWidth 0) ist nichts zu sehen: das verborgene Dateifeld des Uploads gehört dazu.
TRUNCATED = """() => [...document.querySelectorAll('[data-testid=stMain] *')]
    .filter(el => getComputedStyle(el).textOverflow === 'ellipsis' && el.clientWidth > 0
        && el.scrollWidth > el.clientWidth)
    .map(el => el.innerText.trim().slice(0, 80))"""


@pytest.mark.parametrize(("key", "minimum"), GRIDS.items())
def test_grids_show_no_none_cells(page, app: App, key: str, minimum: int):
    open_page(page, app, key)
    tables = all_tables(page, minimum)
    assert len(tables) >= minimum
    cells = [cell.strip() for table in tables for row in table for cell in row]
    assert cells, "Die Raster sind leer – dann prüft der Test nichts."
    assert not [c for c in cells if c.lower() in MISSING_WORDS]


def test_unrecorded_values_show_no_none_in_the_product_overview(page, app: App):
    """Nicht erfasste Werte erscheinen nie als „None“; Spalten ohne jeden Wert (hier Planning und
    Erledigt) werden gar nicht gezeigt."""
    open_page(page, app, "produkte")
    tables = all_tables(page, 3)
    cells = [cell for table in tables for row in table for cell in row]
    assert "None" not in cells
    headers = [h for table in tables for h in table[0]]
    assert not [h for h in headers if h.startswith(("Planning", "Erledigt"))]


def test_grids_are_readable_through_the_accessible_table(page, app: App):
    """Der Weg dieser Tests – der Text steht in der barrierefreien Tabelle – liefert lesbare Zeilen:
    Kopfzeile mit den Spalten, darunter die Personen und ihre Fehltage je Sprint."""
    open_page(page, app, "fehltage")
    absences = all_tables(page, 3)[0]
    assert absences[0] == ["Person", "2026.21", "2026.22", "2026.23", "2026.24"]
    assert absences[1] == ["Anna", "0", "0", "0", "0"]
    assert absences[2] == ["Ben", "3", "0", "0", "0"]


@pytest.mark.parametrize("width", [1900, 1400])
@pytest.mark.parametrize("key", PAGE_KEYS)
def test_nothing_is_cut_off_with_an_ellipsis(new_page, app: App, key: str, width: int):
    page = new_page(width)
    open_page(page, app, "" if key == "start" else key)
    expect(main_area(page).locator("h1, h2, h3").first).to_be_visible()
    assert page.evaluate(TRUNCATED) == []


@pytest.mark.parametrize("key", ["forecast", "vorplanung", "planning", "analyse"])
def test_metrics_are_shown_in_full(new_page, app: App, key: str):
    """Jede Kennzahl zeigt Beschriftung, Zahl und Zusatz vollständig (auch beim Fenster der App,
    1400 px breit)."""
    page = new_page(1400)
    open_page(page, app, key)
    metrics = main_area(page).get_by_test_id("stMetric")
    expect(metrics.first).to_be_visible()
    for metric in metrics.all():
        for part in ("stMetricLabel", "stMetricValue", "stMetricDelta"):
            for element in metric.get_by_test_id(part).all():
                fits = element.evaluate(
                    "e => [...e.querySelectorAll('*'), e].every(n => n.scrollWidth <= n.clientWidth + 1)"
                )
                assert fits, (key, part, element.inner_text())
