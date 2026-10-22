package capacity_test

import (
	"reflect"
	"testing"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/model"
)

func periodsOf(entries map[string][]model.AbsencePeriod, order ...string) model.Absences {
	var a model.Absences
	for _, id := range order {
		a.Set(id, entries[id])
	}
	return a
}

func TestApplyPeriods(t *testing.T) {
	team := model.NewTeam("t", "t")
	people := []model.Person{
		{ID: "a", Name: "A", Memberships: member()},
		{ID: "b", Name: "B", Memberships: member()},
	}
	// Ten working days: Mon 2026-10-05 to Mon 2026-10-19 (end excluded as workday count of the sprint).
	sprint := model.Sprint{ID: "s", Start: day(2026, 10, 5), End: day(2026, 10, 19)}
	base := capacity.Sprint(&team, people, sprint, 0).Capacity

	t.Run("no periods leave the sprint alone", func(t *testing.T) {
		got := capacity.ApplyPeriods(&team, people, model.Absences{}, sprint)
		if !reflect.DeepEqual(got.Sprint, sprint) || len(got.HandWins) != 0 {
			t.Errorf("changed: %+v", got)
		}
	})

	t.Run("announced and confirmed periods", func(t *testing.T) {
		periods := periodsOf(map[string][]model.AbsencePeriod{
			// a: Mon-Wed announced (3 days) + Tue-Thu confirmed (3 days): Tue, Wed count once, as confirmed
			"a": {
				{From: day(2026, 10, 5), To: day(2026, 10, 7)},
				{From: day(2026, 10, 6), To: day(2026, 10, 8), Confirmed: true},
			},
			// b: a whole weekend plus Monday: only Monday works
			"b": {{From: day(2026, 10, 10), To: day(2026, 10, 12)}},
		}, "a", "b")
		got := capacity.ApplyPeriods(&team, people, periods, sprint).Sprint
		// confirmed makes the sprint confirmed, so announced days count with the absences
		if got.Absences["a"] != 4 || got.Absences["b"] != 1 || got.ExpectedAbsences != nil {
			t.Errorf("absences %v expected %v", got.Absences, got.ExpectedAbsences)
		}
		if sprint.Absences != nil || sprint.ExpectedAbsences != nil {
			t.Error("the stored sprint was changed")
		}
		if got.AbsenceStatus() != model.AbsencesConfirmed {
			t.Errorf("status %v", got.AbsenceStatus())
		}
	})

	t.Run("typed expected days win", func(t *testing.T) {
		s := sprint
		s.ExpectedAbsences = map[string]float64{"a": 4}
		periods := periodsOf(map[string][]model.AbsencePeriod{
			"a": {{From: day(2026, 10, 5), To: day(2026, 10, 6)}},
			"b": {{From: day(2026, 10, 5), To: day(2026, 10, 5)}},
		}, "a", "b")
		got := capacity.ApplyPeriods(&team, people, periods, s)
		if got.Sprint.ExpectedAbsences["a"] != 4 || got.Sprint.ExpectedAbsences["b"] != 1 {
			t.Errorf("expected %v", got.Sprint.ExpectedAbsences)
		}
		if !reflect.DeepEqual(got.HandWins, []string{"a"}) {
			t.Errorf("hand wins %v", got.HandWins)
		}
	})

	t.Run("confirmed sprint is untouched", func(t *testing.T) {
		s := sprint
		s.Absences = map[string]float64{"b": 1}
		periods := periodsOf(map[string][]model.AbsencePeriod{
			"a": {{From: day(2026, 10, 5), To: day(2026, 10, 9), Confirmed: true}},
		}, "a")
		got := capacity.ApplyPeriods(&team, people, periods, s)
		if !reflect.DeepEqual(got.Sprint, s) {
			t.Errorf("changed: %+v", got.Sprint)
		}
	})

	t.Run("capacity shrinks by the counted days", func(t *testing.T) {
		periods := periodsOf(map[string][]model.AbsencePeriod{
			"a": {{From: day(2026, 10, 5), To: day(2026, 10, 9), Confirmed: true}},
		}, "a")
		got := capacity.Sprint(&team, people, capacity.ApplyPeriods(&team, people, periods, sprint).Sprint, 0).Capacity
		if got != base-5 {
			t.Errorf("capacity %v, want %v", got, base-5)
		}
	})
}
