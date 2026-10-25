package capacity_test

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/model"
)

func day(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

func member() []model.Membership {
	return []model.Membership{{Start: day(2025, 1, 1), FTE: 1}}
}

func TestProductionTime(t *testing.T) {
	team := model.NewTeam("t", "t")
	people := []model.Person{
		{ID: "ines", Name: "Ines", ProductionAccess: true, Memberships: member()},
		{ID: "jonas", Name: "Jonas", ProductionAccess: true, Memberships: member()},
		{ID: "anna", Name: "Anna", Memberships: member()},
	}
	sprint := model.Sprint{ID: "s", Start: day(2026, 10, 5), End: day(2026, 10, 19), Absences: map[string]float64{"ines": 2, "anna": 1}}
	// ten working days: ines 10 − 2 = 8, jonas 10, anna is not in the group
	for _, c := range []struct{ cap, want float64 }{{100, 18}, {50, 9}, {0, 0}, {-5, 0}} {
		got := capacity.ProductionTimeOf(&team, people, sprint, 0, c.cap)
		if got.Time != 18 || got.Available != c.want || len(got.People) != 2 {
			t.Errorf("cap %v: %+v, want time 18, available %v, 2 people", c.cap, got, c.want)
		}
	}
	// A person with more absence days than working days has no negative time.
	sprint.Absences["ines"] = 30
	if got := capacity.ProductionTimeOf(&team, people, sprint, 0, 100); got.Time != 10 {
		t.Errorf("time with excessive absence = %v, want 10", got.Time)
	}
	// Nobody has production access.
	if got := capacity.ProductionTimeOf(&team, people[2:], sprint, 0, 100); got.Available != 0 || len(got.People) != 0 {
		t.Errorf("no group: %+v", got)
	}
}

func TestPeriodDays(t *testing.T) {
	team := model.NewTeam("t", "t")
	person := model.Person{ID: "a", Name: "A", Memberships: member()}
	sprints := []model.Sprint{
		{ID: "a", Start: day(2026, 10, 5), End: day(2026, 10, 19)},
		{ID: "b", Start: day(2026, 10, 19), End: day(2026, 11, 2)},
		{ID: "c", Start: day(2026, 11, 2), End: day(2026, 11, 16)},
	}
	got := capacity.PeriodDays(&team, person, day(2026, 10, 12), day(2026, 10, 23), sprints)
	if len(got) != 2 || got["a"] != 5 || got["b"] != 5 {
		t.Errorf("two weeks over two sprints: %v", got)
	}
	// Weekend days and the end day count by their own: Fri to Mon.
	got = capacity.PeriodDays(&team, person, day(2026, 10, 9), day(2026, 10, 12), sprints)
	if len(got) != 1 || got["a"] != 2 {
		t.Errorf("Fri to Mon: %v", got)
	}
	// Christmas 2026: Dec 21-24 count, the 25th is a holiday and the 26th a Saturday.
	xmas := []model.Sprint{{ID: "x", Start: day(2026, 12, 14), End: day(2026, 12, 28)}}
	if got = capacity.PeriodDays(&team, person, day(2026, 12, 21), day(2026, 12, 31), xmas); got["x"] != 4 {
		t.Errorf("christmas: %v", got)
	}
	// Not in the team yet: no days.
	late := model.Person{ID: "b", Name: "B", Memberships: []model.Membership{{Start: day(2026, 10, 14), FTE: 1}}}
	got = capacity.PeriodDays(&team, late, day(2026, 10, 12), day(2026, 10, 16), sprints)
	if got["a"] != 3 {
		t.Errorf("joined on Wednesday: %v", got)
	}
	if got = capacity.PeriodDays(&team, person, day(2026, 10, 16), day(2026, 10, 12), sprints); len(got) != 0 {
		t.Errorf("reversed period: %v", got)
	}
}
