# SPDX-License-Identifier: EUPL-1.2
"""Sprint-Kalender: Folgesprints, Arbeitstage und Feiertage."""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache

import holidays

from sprintforecast.model import Numbering, Sprint, Team


def next_id(previous_id: str, next_start: date, numbering: Numbering) -> str:
    if numbering is Numbering.SEQUENTIAL:
        return str(int(float(previous_id)) + 1)
    year, sep, counter = previous_id.partition(".")
    if sep and year.isdigit() and int(year) == next_start.year:
        return f"{year}.{int(counter) + 1}"
    return f"{next_start.year}.1"


def following_sprint(team: Team, previous: Sprint | None) -> Sprint:
    """Erzeugt den Sprint, der auf ``previous`` folgt (oder den ersten Sprint des Teams)."""
    length = timedelta(days=team.sprint.length_days)
    if previous is None:
        if team.sprint.first_id is None or team.sprint.first_start is None:
            raise ValueError(
                f"Team {team.key}: Es ist noch kein Sprint erfasst und "
                "sprint.first_id/first_start fehlen in team.yaml."
            )
        start = team.sprint.first_start
        return Sprint(id=team.sprint.first_id, start=start, end=start + length)
    start = previous.end
    return Sprint(
        id=next_id(previous.id, start, team.sprint.numbering),
        start=start,
        end=start + length,
    )


WEEKDAYS = {
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


def day_label(d: date) -> str:
    """„Mi 28.10.2026“ bzw. „Wed 28.10.2026“."""
    from sprintforecast.i18n import language

    return f"{WEEKDAYS[language()][d.weekday()]} {d:%d.%m.%Y}"


def workdays(start: date, end: date) -> list[date]:
    """Werktage (Mo–Fr) im halboffenen Intervall [start, end)."""
    days = []
    day = start
    while day < end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


@cache
def _holiday_calendar(region: str | None, year: int, lang: str = "de") -> holidays.HolidayBase:
    return holidays.country_holidays(
        "DE", subdiv=region, years=year, language="en_US" if lang == "en" else "de"
    )


def is_holiday(day: date, region: str | None) -> bool:
    return day in _holiday_calendar(region, day.year)


def holiday_name(day: date, region: str | None) -> str | None:
    """Name des Feiertags in der eingestellten Sprache – oder None."""
    from sprintforecast.i18n import language

    return _holiday_calendar(region, day.year, language()).get(day)
