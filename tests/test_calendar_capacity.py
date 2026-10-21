# SPDX-License-Identifier: EUPL-1.2
from datetime import date

import pytest

from foresprint.calendar import following_sprint, is_holiday, next_id, workdays
from foresprint.capacity import sprint_capacity
from foresprint.model import Membership, Numbering, Person, Sprint, Team
from foresprint.storage import DataError


def test_next_id_yearly_rolls_over_with_start_year():
    assert next_id("2026.20", date(2026, 10, 28), Numbering.YEARLY) == "2026.21"
    assert next_id("2026.26", date(2027, 1, 6), Numbering.YEARLY) == "2027.1"
    # Switch from continuous to yearly numbering
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
    with pytest.raises(DataError, match="Start und ID des ersten Sprints"):
        following_sprint(Team(key="t", name="T"), None)


def test_workdays_half_open():
    # Wed 14.10. to Wed 28.10.: 10 working days, the end day does not count.
    assert len(workdays(date(2026, 10, 14), date(2026, 10, 28))) == 10


def test_regional_holidays():
    assert is_holiday(date(2026, 6, 4), "NW")  # Corpus Christi
    assert not is_holiday(date(2026, 6, 4), "HH")
    assert is_holiday(date(2026, 10, 3), None)  # German Unity Day


def _team(region="NW", overhead=0.0):
    team = Team(key="t", name="T")
    team.capacity.region = region
    team.capacity.overhead_share = overhead
    return team


def test_capacity_with_holiday_absence_fte_and_membership():
    # 27.05.–10.06.2026: 10 working days, Corpus Christi 04.06. in NW
    sprint = Sprint("x", date(2026, 5, 27), date(2026, 6, 10), absences={"a": 2})
    people = [
        Person("a", "A", memberships=[Membership(date(2020, 1, 1))]),
        Person("b", "B", memberships=[Membership(date(2020, 1, 1), fte=0.5)]),
        # joins on Monday 08.06. → 2 working days (08. + 09.06.)
        Person("c", "C", memberships=[Membership(date(2026, 6, 8))]),
        # half position from 01.06.; ends in Hamburg without Corpus Christi
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
    # 27.–29.05. full (3 days) + 01.–09.06. half (7 days) = 6.5
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
    from foresprint.model import new_person_id

    assert new_person_id("Jörg Müller-Weiß", set()) == "joerg-mueller-weiss"
    assert new_person_id("Anna", {"anna", "anna-2"}) == "anna-3"
    assert new_person_id("!!!", set()) == "person"


def test_overhead_in_days_and_percent(data_dir):
    from datetime import date

    from foresprint.capacity import sprint_capacity
    from foresprint.storage import Repository

    data = Repository(data_dir).load("demo")
    sprint = data.sprint("2026.22")
    base = sprint_capacity(data.team, data.people, sprint)
    data.team.capacity.overhead_days = 1
    fixed = sprint_capacity(data.team, data.people, sprint)
    # Anna 1, Ben 0.5 (FTE), Cem 1, Dana 1 → 3.5 PD
    assert fixed.overhead_days_part == 3.5
    assert fixed.capacity == base.capacity - 3.5
    # With a PD deduction the percentage does not apply on top (same deduction in two units).
    data.team.capacity.overhead_share = 0.1
    both = sprint_capacity(data.team, data.people, sprint)
    assert both.overhead == pytest.approx(3.5)
    assert sprint.start == date(2026, 10, 28)


def test_expected_absences_estimate_future_capacity(data_dir):
    from datetime import date

    from foresprint.capacity import expected_absence_rate
    from foresprint.engine import CapacitySource
    from foresprint.forecast import build_forecast
    from foresprint.storage import Repository

    data = Repository(data_dir).load("demo")
    today = date(2026, 10, 15)
    base = build_forecast(data, today)
    unrecorded = [e for e in base.upcoming() if not e.recorded]
    # Absences unknown: capacity from calendar and people, rate from confirmed sprints
    assert unrecorded and unrecorded[0].result.plan_capacity_source is CapacitySource.ESTIMATED
    data.team.capacity.absence_history = 0
    unrecorded = [e for e in build_forecast(data, today).upcoming() if not e.recorded]
    assert unrecorded[0].result.plan_capacity_source is CapacitySource.CALENDAR
    data.people = []
    unrecorded = [e for e in build_forecast(data, today).upcoming() if not e.recorded]
    assert unrecorded[0].result.plan_capacity_source is CapacitySource.TREND  # no people list
    data = Repository(data_dir).load("demo")

    past = [e.sprint for e in base.history() if e.recorded]
    assert expected_absence_rate(data.team, data.people, past, 0) is None
    sprint = past[-1]
    sprint.absences = {data.people[0].id: 5.0}
    rate = expected_absence_rate(data.team, data.people, [sprint], 1)
    assert rate is not None and 0 < rate < 1

    data.team.capacity.absence_history = 3
    estimated = build_forecast(data, today)
    entry = next(e for e in estimated.upcoming() if not e.recorded)
    assert entry.result.plan_capacity_source is CapacitySource.ESTIMATED
    assert entry.result.plan_capacity > 0
