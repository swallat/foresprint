# SPDX-License-Identifier: EUPL-1.2
"""Länder, Regionen und Arbeitswochen außerhalb von Deutschland."""

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
    assert is_holiday(date(2026, 10, 3), None)  # Deutsche Einheit, Standard bleibt DE
    assert not is_holiday(date(2026, 10, 3), None, "US")
    assert is_holiday(date(2026, 11, 26), None, "US")  # Thanksgiving
    assert not is_holiday(date(2026, 11, 26), None, "DE")
    assert is_holiday(date(2026, 3, 31), "CA", "US")  # nur in Kalifornien
    assert not is_holiday(date(2026, 3, 31), None, "US")
    assert is_holiday(date(2026, 11, 1), "NW", "DE") and not is_holiday(date(2026, 11, 1), "HH")
    assert holiday_name(date(2026, 11, 26), None, "US")


def test_weekends_follow_the_country():
    assert country_weekend("DE") == {5, 6}
    assert country_weekend("SA") == {4, 5}  # Freitag/Samstag
    assert country_weekend("XX") == {5, 6}  # unbekannt: Standard
    week = (date(2026, 10, 18), date(2026, 10, 25))  # So–Sa
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
    us = sprint_capacity(_team("US"), people, sprint)  # Thanksgiving 26.11.
    assert de.gross == 10 and us.gross == 9
    sa = sprint_capacity(_team("SA"), people, sprint)  # So–Do: 5 Arbeitstage je Woche
    assert sa.gross == 10 and sa.people[0].workdays == 10


def test_person_with_own_country_follows_it():
    sprint = Sprint(id="1", start=date(2026, 11, 23), end=date(2026, 12, 7))
    team = _team("DE")
    local = sprint_capacity(team, [_person()], sprint).gross
    abroad = sprint_capacity(team, [_person(country="US")], sprint).gross
    assert abroad == local - 1  # Thanksgiving zählt nur für die Person im US-Team
    # Teamregion gilt nicht für Personen eines anderen Landes
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
    # Standardwerte bleiben aus der Datei heraus
    data.team.capacity.country, data.team.capacity.workweek = "DE", "auto"
    repo.save_team(data.team)
    plain = yaml.safe_load((data_dir / "demo" / "team.yaml").read_text())["capacity"]
    assert "country" not in plain and "workweek" not in plain


def test_validation_of_country_region_and_workweek(data_dir: Path):
    data = Repository(data_dir).load("demo")
    for person in data.people:
        person.region = None  # Demo: Cem hat BY
    today = date(2026, 10, 15)

    def errors() -> list[str]:
        return [i.message for i in check_team(data, today) if i.level.value == "Fehler"]

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

    from sprintforecast.storage import DATA_ENV, STICHTAG_ENV

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    app = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
    at = AppTest.from_file(str(app), default_timeout=30)
    at.run()
    at.switch_page("seiten/einstellungen.py").run()
    assert not at.exception, at.exception
    at.selectbox(key="settings-demo-capacity.country").set_value("US")
    at.text_input(key="settings-demo-capacity.region").set_value("CA")
    next(b for b in at.button if b.label == "Speichern").click().run()
    assert not at.exception, at.exception
    saved = yaml.safe_load((data_dir / "demo" / "team.yaml").read_text())["capacity"]
    assert saved["country"] == "US" and saved["region"] == "CA"
    # Die Seiten rechnen danach mit US-Feiertagen
    at.switch_page("seiten/forecast.py").run()
    assert not at.exception, at.exception  # auch mit Cems (nicht mehr passender) Region BY
