# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the sprint ID arithmetic for odd IDs (``calendar.next_id`` and
``id_fits_numbering``): numbers in every spelling Python's ``float()`` and ``int()`` accept or
refuse. Non-ASCII digits are left out on purpose: the Go port reads ASCII digits only (sprint
IDs are file names; see go/README.md)."""

from __future__ import annotations

from datetime import date

from foresprint import calendar as cal
from foresprint.model import Numbering, Person, Team
from foresprint.storage import DataError

IDS = [
    "",
    " ",
    "7",
    "007",
    "7.0",
    "7.9",
    "-3",
    "+3",
    "1e3",
    "1_0",
    "1__0",
    "_1",
    "0x10",
    "nan",
    "inf",
    "-inf",
    "Infinity",
    "1e400",
    ".5",
    "5.",
    "2026.7",
    "2026.07",
    "2026.7.1",
    "2026.x",
    "2026.",
    ".7",
    "02026.3",
    "2026.-1",
    "2026. 4 ",
    "2026.1_0",
    "2026.1__0",
    "2025.9",
    "abc",
    "22b",
    " 12 ",
    "\t8\n",
    "99999999999999999999",
    "1e30",
    "-0",
    "2026.99999999999999999999",
    "2026.+5",
    "2026",
    "2026.0",
    "2027.4",
    "١٢",
    "2026.٤",
]
IDS = [i for i in IDS if i.isascii()]


def generate(ctx) -> None:
    rows = []
    for numbering in Numbering:
        for start in (date(2026, 3, 1), date(2027, 1, 6)):
            for previous in IDS:
                try:
                    result = cal.next_id(previous, start, numbering)
                except DataError:
                    result = None
                rows.append(
                    {
                        "previous": previous,
                        "start": start.isoformat(),
                        "numbering": numbering.value,
                        "id": result,
                        "fits": cal.id_fits_numbering(previous, start, numbering),
                    }
                )
    ctx.write("calendar/ids.json", ctx.dump_json(rows))
    generate_workweeks(ctx)


WORKWEEKS = [
    "",
    " ",
    "auto",
    "AUTO",
    "Auto ",
    "mon-fri",
    "MON-FRI",
    " Sun-Thu ",
    "mon-sat",
    "mon;tue",
    "mon,,tue",
    ",",
    ";",
    "mon, tue ,wed",
    "mon\ttue",
    "mon-fri,sat",
    "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
    "mon,tue,wed,thu,fri",
    "sat,sun",
    "sat",
    "mon",
    "mon mon",
    "mo",
    "fri,sat",
    "tue;wed;thu",
    "xyz",
    "mon,foo",
    "mon-thu",
]


def generate_workweeks(ctx) -> None:
    rows = []
    for value in WORKWEEKS:
        try:
            result = cal.weekend_from_workweek(value)
            weekend = None if result is None else sorted(result)
        except ValueError:
            weekend = "error"
        row = {"value": value, "weekend": weekend}
        for country in ("DE", "SA", "XX"):
            team = Team(key="x", name="x")
            team.capacity.country = country
            team.capacity.workweek = value
            row[f"team_{country}"] = sorted(cal.team_weekend(team))
            base = Team(key="x", name="x")
            base.capacity.country = country
            for own in ("SA", "IL", None):
                person = Person(id="p", name="p", country=own, workweek=value or None)
                row[f"person_{country}_{own}"] = sorted(cal.person_weekend(base, person))
        rows.append(row)
    ctx.write("calendar/workweeks.json", ctx.dump_json(rows))
