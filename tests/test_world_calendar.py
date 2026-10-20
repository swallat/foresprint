# SPDX-License-Identifier: EUPL-1.2
"""Countries, regions and working weeks outside of Germany."""

from datetime import date
from pathlib import Path

import pytest
import yaml

from sprintforecast.calendar import (
    countries,
    country_weekend,
    holiday_name,
    is_holiday,
    subdivisions,
    team_weekend,
    workdays,
    workweek_label,
)
from sprintforecast.capacity import sprint_capacity
from sprintforecast.model import Membership, Person, Sprint, Team
from sprintforecast.storage import Repository
from sprintforecast.validate import check_team


def test_supported_countries_and_regions():
    names = countries()
    assert names["DE"] == "Germany" and names["US"] == "United States" and "SA" in names
    assert len(names) > 150
    assert "NW" in subdivisions("DE") and "CA" in subdivisions("US") and "ON" in subdivisions("CA")
    assert subdivisions("XX") == []


def test_holidays_per_country_and_region():
    assert is_holiday(date(2026, 10, 3), None)  # German Unity Day, default stays DE
    assert not is_holiday(date(2026, 10, 3), None, "US")
    assert is_holiday(date(2026, 11, 26), None, "US")  # Thanksgiving
    assert not is_holiday(date(2026, 11, 26), None, "DE")
    assert is_holiday(date(2026, 3, 31), "CA", "US")  # only in California
    assert not is_holiday(date(2026, 3, 31), None, "US")
    assert is_holiday(date(2026, 11, 1), "NW", "DE") and not is_holiday(date(2026, 11, 1), "HH")
    assert holiday_name(date(2026, 11, 26), None, "US")


def test_weekends_follow_the_country():
    assert country_weekend("DE") == {5, 6}
    assert country_weekend("SA") == {4, 5}  # Friday/Saturday
    assert country_weekend("XX") == {5, 6}  # unknown: default
    week = (date(2026, 10, 18), date(2026, 10, 25))  # Sun-Sat
    assert [d.weekday() for d in workdays(*week, country_weekend("SA"))] == [6, 0, 1, 2, 3]
    assert [d.weekday() for d in workdays(*week)] == [0, 1, 2, 3, 4]


def test_team_workweek_setting_overrides_the_country():
    team = Team(key="t", name="T")
    assert team_weekend(team) == {5, 6}
    team.capacity.country = "SA"
    assert team_weekend(team) == {4, 5}
    team.capacity.workweek = "mon-fri"
    assert team_weekend(team) == {5, 6}
    team.capacity.workweek = "mon-sat"
    assert team_weekend(team) == {6}


def test_workweek_label_follows_the_configured_week():
    team = Team(key="t", name="T")
    assert workweek_label(team) == "Mo–Fr"
    team.capacity.workweek = "mon,tue,wed,thu"
    assert workweek_label(team) == "Mo–Do"
    team.capacity.workweek = "mon,wed,thu"
    assert workweek_label(team) == "Mo, Mi, Do"
    team.capacity.workweek = "mon-sat"
    assert workweek_label(team) == "Mo–Sa"
    team.capacity.workweek = "auto"
    team.capacity.country = "SA"
    assert workweek_label(team) == "So–Do"


def _team(country: str = "DE", region: str | None = None) -> Team:
    team = Team(key="t", name="T")
    team.capacity.country = country
    team.capacity.region = region
    return team


def _person(**kwargs) -> Person:
    return Person(
        id="p",
        name="P",
        memberships=[Membership(start=date(2025, 1, 1), fte=1.0)],
        **kwargs,
    )


def test_capacity_uses_country_holidays_and_weekend():
    sprint = Sprint(id="1", start=date(2026, 11, 23), end=date(2026, 12, 7))
    people = [_person()]
    de = sprint_capacity(_team("DE"), people, sprint)
    us = sprint_capacity(_team("US"), people, sprint)  # Thanksgiving 11/26
    assert de.gross == 10 and us.gross == 9
    sa = sprint_capacity(_team("SA"), people, sprint)  # Sun-Thu: 5 working days per week
    assert sa.gross == 10 and sa.people[0].workdays == 10


def test_person_with_own_country_follows_it():
    sprint = Sprint(id="1", start=date(2026, 11, 23), end=date(2026, 12, 7))
    team = _team("DE")
    local = sprint_capacity(team, [_person()], sprint).gross
    abroad = sprint_capacity(team, [_person(country="US")], sprint).gross
    assert abroad == local - 1  # Thanksgiving counts only for the person in the US team
    # The team region does not apply to people of another country
    team.capacity.region = "NW"
    assert sprint_capacity(team, [_person(country="US")], sprint).gross == abroad


def test_files_roundtrip_country_region_workweek(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    data.team.capacity.country = "US"
    data.team.capacity.region = "CA"
    data.team.capacity.workweek = "sun-thu"
    data.people[0].country = "AT"
    repo.save_team(data.team)
    repo.save_people("demo", data.people)
    saved = yaml.safe_load((data_dir / "demo" / "team.yaml").read_text())["capacity"]
    assert (saved["country"], saved["region"], saved["workweek"]) == ("US", "CA", "sun-thu")
    again = repo.load("demo")
    assert again.team.capacity.country == "US" and again.people[0].country == "AT"
    # Default values stay out of the file
    data.team.capacity.country, data.team.capacity.workweek = "DE", "auto"
    repo.save_team(data.team)
    plain = yaml.safe_load((data_dir / "demo" / "team.yaml").read_text())["capacity"]
    assert "country" not in plain and "workweek" not in plain


def test_validation_of_country_region_and_workweek(data_dir: Path):
    data = Repository(data_dir).load("demo")
    for person in data.people:
        person.region = None  # Demo: Cem has BY
    today = date(2026, 10, 15)

    def errors() -> list[str]:
        return [i.message for i in check_team(data, today) if i.level.value == "Error"]

    assert errors() == []
    data.team.capacity.country = "XX"
    assert any("XX" in m for m in errors())
    data.team.capacity.country, data.team.capacity.region = "US", "NW"
    assert any("NW" in m for m in errors())
    data.team.capacity.region = "CA"
    assert errors() == []
    data.team.capacity.workweek = "wochenende"
    assert any("wochenende" in m for m in errors())
    data.team.capacity.workweek = "auto"
    data.people[0].country, data.people[0].region = "DE", "ZZ"
    assert any("ZZ" in m for m in errors())


def test_settings_page_changes_country(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from sprintforecast.storage import AS_OF_ENV, DATA_ENV

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, "2026-10-15")
    app = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
    at = AppTest.from_file(str(app), default_timeout=30)
    at.run()
    at.switch_page("page_scripts/settings.py").run()
    assert not at.exception, at.exception
    at.selectbox(key="settings-demo-capacity.country").set_value("US")
    at.text_input(key="settings-demo-capacity.region").set_value("CA")
    next(b for b in at.button if b.label == "Speichern").click().run()
    assert not at.exception, at.exception
    saved = yaml.safe_load((data_dir / "demo" / "team.yaml").read_text())["capacity"]
    assert saved["country"] == "US" and saved["region"] == "CA"
    # The pages then calculate with US holidays
    at.switch_page("page_scripts/forecast.py").run()
    assert not at.exception, at.exception  # also with Cem's (no longer fitting) region BY


def test_four_day_week_person():
    sprint = Sprint(id="1", start=date(2026, 10, 12), end=date(2026, 10, 26))  # Mon-Sun, 2 weeks
    team = _team("DE")
    full = sprint_capacity(team, [_person()], sprint)
    four = sprint_capacity(team, [_person(workweek="mon,tue,wed,thu")], sprint)
    assert full.gross == 10 and four.gross == 8
    assert four.people[0].workdays == 8
    # A holiday on a day off (Friday) costs nothing, on a working day it does
    friday = Sprint(id="2", start=date(2026, 10, 26), end=date(2026, 11, 9))
    with_holiday = sprint_capacity(_team("DE", "NW"), [_person(workweek="mon,tue,wed,thu")], friday)
    assert with_holiday.gross == 8  # 11/1 is a Sunday, not a working day
    team_day = Sprint(id="3", start=date(2026, 12, 21), end=date(2027, 1, 4))  # 12/25, 12/26 + 1/1
    five = sprint_capacity(_team("DE"), [_person()], team_day).gross
    four_days = sprint_capacity(_team("DE"), [_person(workweek="mon,tue,wed,thu")], team_day).gross
    # 12/25 and 1/1 fall on Fridays: the full-time person loses two days (10 -> 8), the person
    # with a Mon-Thu week loses nothing (8 -> 8)
    assert five == 8 and four_days == 8
    assert sprint_capacity(_team("DE"), [_person(workweek="mon-sat")], team_day).gross >= five


def test_workweek_parsing_and_validation(data_dir: Path):
    from sprintforecast.calendar import weekend_from_workweek

    assert weekend_from_workweek("auto") is None and weekend_from_workweek(None) is None
    assert weekend_from_workweek("mon,tue,wed,thu") == {4, 5, 6}
    assert weekend_from_workweek("Mon Tue Wed") == {3, 4, 5, 6}
    assert weekend_from_workweek("sun-thu") == {4, 5}
    for bad in ("xyz", "mon,foo", ","):
        with pytest.raises(ValueError):
            weekend_from_workweek(bad)
    data = Repository(data_dir).load("demo")
    data.people[0].workweek = "mon,xyz"
    errors = [i for i in check_team(data, date(2026, 10, 15)) if i.level.value == "Error"]
    assert any("xyz" in i.message for i in errors)
    # round trip
    repo = Repository(data_dir)
    data.people[0].workweek = "mon,tue,wed,thu"
    repo.save_people("demo", data.people)
    assert repo.load("demo").people[0].workweek == "mon,tue,wed,thu"


def test_people_table_keeps_workweek(data_dir: Path):
    from sprintforecast.web.logic import people_from_table, people_table

    data = Repository(data_dir).load("demo")
    data.people[0].workweek = "mon,tue,wed,thu"
    rows, hidden = people_table(data.people, date(2026, 10, 15), show_former=True)
    assert rows[0]["Work week"] == "mon,tue,wed,thu"
    assert people_from_table(rows, data.people, hidden).people[0].workweek == "mon,tue,wed,thu"
    rows[0]["Work week"] = "kaputt"
    assert people_from_table(rows, data.people, hidden).errors
