package capacity_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/model"
)

func TestWithOpenAbsencesCountsConfirmedAndAnnounced(t *testing.T) {
	team := model.NewTeam("t", "t")
	people := []model.Person{{ID: "a", Name: "A", Memberships: member()}, {ID: "b", Name: "B", Memberships: member()}}
	sprint := model.Sprint{ID: "s", Start: day(2026, 10, 5), End: day(2026, 10, 19)}
	base := capacity.Sprint(&team, people, sprint, 0).Capacity

	sprint.SetCell("a", 2, model.AbsencesConfirmed)
	sprint.SetCell("b", 3, model.AbsencesExpected)
	if got := capacity.WithOpenAbsences(&team, people, sprint); got != base-5 {
		t.Errorf("open capacity %v, want %v", got, base-5)
	}
	// Without confirmed cells it is the capacity with the announced absences.
	only := model.Sprint{ID: "s", Start: sprint.Start, End: sprint.End, ExpectedAbsences: map[string]float64{"b": 3}}
	if got, want := capacity.WithOpenAbsences(&team, people, only), capacity.WithExpectedAbsences(&team, people, only); got != want {
		t.Errorf("announced only: %v, want %v", got, want)
	}
}

func TestApplyPeriodsKeepsTypedCellsOfEitherKind(t *testing.T) {
	team := model.NewTeam("t", "t")
	people := []model.Person{{ID: "a", Name: "A", Memberships: member()}, {ID: "b", Name: "B", Memberships: member()}}
	sprint := model.Sprint{ID: "s", Start: day(2026, 10, 5), End: day(2026, 10, 19)}
	sprint.SetCell("a", 2, model.AbsencesConfirmed)
	sprint.SetCell("b", 1, model.AbsencesExpected)
	periods := periodsOf(map[string][]model.AbsencePeriod{
		"a": {{From: day(2026, 10, 5), To: day(2026, 10, 7)}},                  // announced, 3 days
		"b": {{From: day(2026, 10, 5), To: day(2026, 10, 7), Confirmed: true}}, // confirmed, 3 days
	}, "a", "b")
	got := capacity.ApplyPeriods(&team, people, periods, sprint)
	if got.Sprint.CellDays("a") != 2 || got.Sprint.CellDays("b") != 1 {
		t.Errorf("typed cells changed: a %v b %v", got.Sprint.CellDays("a"), got.Sprint.CellDays("b"))
	}
	if len(got.HandWins) != 2 {
		t.Errorf("hand wins %v", got.HandWins)
	}
}
