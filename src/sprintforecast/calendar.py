# SPDX-License-Identifier: EUPL-1.2
"""Sprint-Kalender: Folgesprints, Arbeitstage und Feiertage."""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import cache

import holidays

from sprintforecast.model import Numbering, Person, Sprint, Team


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


# Wochenende als Wochentagsnummern (Montag = 0): Sa/So.
DEFAULT_WEEKEND: frozenset[int] = frozenset({5, 6})
DEFAULT_COUNTRY = "DE"
# Arbeitswochen, die sich unabhängig vom Land einstellen lassen (Wert = Wochenende).
WORKWEEKS: dict[str, frozenset[int]] = {
    "mon-fri": frozenset({5, 6}),
    "sun-thu": frozenset({4, 5}),
    "mon-sat": frozenset({6}),
}


@cache
def countries() -> dict[str, str]:
    """Unterstützte Länder: ISO-Code → Name (aus der holidays-Bibliothek)."""
    from holidays import registry

    supported = set(holidays.list_supported_countries())
    names = {}
    for cls_name, *codes in registry.COUNTRIES.values():
        code = codes[0]
        if code in supported:
            names[code] = re.sub(r"(?<!^)(?=[A-Z])", " ", cls_name)
    return dict(sorted(names.items()))


@cache
def subdivisions(country: str) -> list[str]:
    """Gültige Regionscodes (Bundesland, Staat, Provinz …) eines Landes."""
    return list(holidays.list_supported_countries().get(country.upper(), []))


@cache
def country_weekend(country: str) -> frozenset[int]:
    """Wochenende des Landes laut holidays-Bibliothek (z. B. Fr/Sa in Saudi-Arabien)."""
    try:
        return frozenset(holidays.country_holidays(country.upper()).weekend)
    except NotImplementedError:
        return DEFAULT_WEEKEND


def team_weekend(team: Team) -> frozenset[int]:
    """Wochenende des Teams: eingestellte Arbeitswoche, sonst das des Landes."""
    return WORKWEEKS.get(team.capacity.workweek) or country_weekend(team.capacity.country)


def person_weekend(team: Team, person: Person) -> frozenset[int]:
    """Eine Person in einem anderen Land folgt dessen Wochenende."""
    return country_weekend(person.country) if person.country else team_weekend(team)


def workdays(start: date, end: date, weekend: frozenset[int] = DEFAULT_WEEKEND) -> list[date]:
    """Werktage im halboffenen Intervall [start, end); ``weekend`` = freie Wochentage."""
    days = []
    day = start
    while day < end:
        if day.weekday() not in weekend:
            days.append(day)
        day += timedelta(days=1)
    return days


def team_workdays(team: Team, start: date, end: date) -> list[date]:
    return workdays(start, end, team_weekend(team))


@cache
def _holiday_calendar(
    country: str, region: str | None, year: int, lang: str = "de"
) -> holidays.HolidayBase:
    # Nicht jede Sprache gibt es für jedes Land – die Bibliothek fällt dann auf die Landessprache.
    # Unbekanntes Land oder unpassende Region lässt die Rechnung nicht abstürzen (die Prüfung
    # meldet den Fehler); es gelten dann nur die landesweiten bzw. keine Feiertage.
    language = "en_US" if lang == "en" else "de"
    for subdiv in (region or None, None):
        try:
            return holidays.country_holidays(
                country.upper(), subdiv=subdiv, years=year, language=language
            )
        except NotImplementedError:
            continue
    return holidays.HolidayBase()


def is_holiday(day: date, region: str | None, country: str = DEFAULT_COUNTRY) -> bool:
    return day in _holiday_calendar(country, region, day.year)


def holiday_name(day: date, region: str | None, country: str = DEFAULT_COUNTRY) -> str | None:
    """Name des Feiertags in der eingestellten Sprache – oder None."""
    from sprintforecast.i18n import language

    return _holiday_calendar(country, region, day.year, language()).get(day)
