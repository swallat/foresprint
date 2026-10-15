# SPDX-License-Identifier: EUPL-1.2
from datetime import date

import pytest

from sprintforecast.calendar import following_sprint, is_holiday, next_id, workdays
from sprintforecast.capacity import sprint_capacity
from sprintforecast.model import Membership, Numbering, Person, Sprint, Team


def test_next_id_yearly_rolls_over_with_start_year():
    assert next_id("2026.20", date(2026, 10, 28), Numbering.YEARLY) == "2026.21"
    assert next_id("2026.26", date(2027, 1, 6), Numbering.YEARLY) == "2027.1"
    # Wechsel von fortlaufender auf jährliche Nummerierung
    assert next_id("39", date(2026, 1, 7), Numbering.YEARLY) == "2026.1"
    assert next_id("39", date(2026, 1, 7), Numbering.SEQUENTIAL) == "40"


def test_following_sprint():
    team = Team(key="t", name="T")
    team.sprint.first_id, team.sprint.first_start = "2026.1", date(2026, 1, 7)
    first = following_sprint(team, None)
    assert (first.id, first.start, first.end) == ("2026.1", date(2026, 1, 7), date(2026, 1, 21))
    second = following_sprint(team, first)
    assert (second.id, second.start) == ("2026.2", date(2026, 1, 21))


def test_following_sprint_without_start_fails():
    with pytest.raises(ValueError, match="first_id"):
        following_sprint(Team(key="t", name="T"), None)


def test_workdays_half_open():
    # Mi 14.10. bis Mi 28.10.: 10 Arbeitstage, der Endtag zählt nicht.
    assert len(workdays(date(2026, 10, 14), date(2026, 10, 28))) == 10


def test_regional_holidays():
    assert is_holiday(date(2026, 6, 4), "NW")  # Fronleichnam
    assert not is_holiday(date(2026, 6, 4), "HH")
    assert is_holiday(date(2026, 10, 3), None)  # Tag der Deutschen Einheit


def _team(region="NW", overhead=0.0):
    team = Team(key="t", name="T")
    team.capacity.region = region
    team.capacity.overhead_share = overhead
    return team


def test_capacity_with_holiday_absence_fte_and_membership():
    # 27.05.–10.06.2026: 10 Arbeitstage, Fronleichnam 04.06. in NW
    sprint = Sprint("x", date(2026, 5, 27), date(2026, 6, 10), absences={"a": 2})
    people = [
        Person("a", "A", memberships=[Membership(date(2020, 1, 1))]),
        Person("b", "B", memberships=[Membership(date(2020, 1, 1), fte=0.5)]),
        # tritt am Montag 08.06. ein → 2 Arbeitstage (08. + 09.06.)
        Person("c", "C", memberships=[Membership(date(2026, 6, 8))]),
        # ab 01.06. halbe Stelle; Ende in Hamburg ohne Fronleichnam
        Person(
            "d",
            "D",
            region="HH",
            memberships=[
                Membership(date(2020, 1, 1), date(2026, 5, 31)),
                Membership(date(2026, 6, 1), fte=0.5),
            ],
        ),
        Person("e", "E", memberships=[Membership(date(2020, 1, 1), date(2026, 1, 1))]),
    ]
    b = sprint_capacity(_team(), people, sprint)
    by_id = {pc.person.id: pc for pc in b.people}
    assert set(by_id) == {"a", "b", "c", "d"}
    assert by_id["a"].holidays == 1 and by_id["a"].capacity == pytest.approx(7.0)
    assert by_id["b"].capacity == pytest.approx(4.5)
    assert by_id["c"].capacity == pytest.approx(2.0)
    # 27.–29.05. voll (3 Tage) + 01.–09.06. halb (7 Tage) = 6.5
    assert by_id["d"].holidays == 0 and by_id["d"].capacity == pytest.approx(6.5)
    assert b.capacity == pytest.approx(20.0)


def test_capacity_overhead_and_absence_cap():
    sprint = Sprint("x", date(2026, 10, 14), date(2026, 10, 28), absences={"a": 99})
    people = [
        Person("a", "A", memberships=[Membership(date(2020, 1, 1))]),
        Person("b", "B", memberships=[Membership(date(2020, 1, 1))]),
    ]
    b = sprint_capacity(_team(overhead=0.1), people, sprint)
    assert b.gross == pytest.approx(10.0)
    assert b.capacity == pytest.approx(9.0)


def test_new_person_id():
    from sprintforecast.model import new_person_id

    assert new_person_id("Jörg Müller-Weiß", set()) == "joerg-mueller-weiss"
    assert new_person_id("Anna", {"anna", "anna-2"}) == "anna-3"
    assert new_person_id("!!!", set()) == "person"
