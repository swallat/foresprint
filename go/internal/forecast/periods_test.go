package forecast_test

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func TestResolveCapacityUsesAbsencePeriods(t *testing.T) {
	d := func(day int) time.Time { return time.Date(2026, 10, day, 0, 0, 0, 0, time.UTC) }
	data := &storage.TeamData{Team: model.NewTeam("t", "t")}
	data.People = []model.Person{{ID: "a", Name: "A", Memberships: []model.Membership{{Start: d(1).AddDate(-1, 0, 0), FTE: 1}}}}
	sprint := model.Sprint{ID: "s", Start: d(5), End: d(19)}

	calendar, source := forecast.ResolveCapacity(data, sprint, nil)
	if source == nil || *source != engine.SourceCalendar {
		t.Fatalf("source without periods = %v", source)
	}
	data.AbsencePeriods.Set("a", []model.AbsencePeriod{{From: d(5), To: d(9), Confirmed: true}})
	got, source := forecast.ResolveCapacity(data, sprint, nil)
	if *got != *calendar-5 {
		t.Errorf("capacity %v, want %v", *got, *calendar-5)
	}
	if *source != engine.SourcePeople {
		t.Errorf("confirmed period: source %v, want people", *source)
	}
	if sprint.Absences != nil {
		t.Error("the sprint was changed")
	}
	data.AbsencePeriods = model.Absences{}
	data.AbsencePeriods.Set("a", []model.AbsencePeriod{{From: d(5), To: d(9)}})
	if _, source := forecast.ResolveCapacity(data, sprint, nil); *source != engine.SourceExpected {
		t.Errorf("announced period: source %v, want expected", *source)
	}
}

func TestWhatIfDoesNotChangeData(t *testing.T) {
	p := model.Prognosis{Commitment: model.Ptr(30.0), NotDone: model.Ptr(5.0), AdditionalDone: model.Ptr(2.0)}
	if v, ok := forecast.ExpectedDone(p); !ok || v != 27 {
		t.Fatalf("expected done = %v %v, want 27", v, ok)
	}
	if _, ok := forecast.ExpectedDone(model.Prognosis{}); ok {
		t.Error("an empty assumption has no result")
	}
	for _, c := range golden.Cases(t) {
		data := coretest.Load(t, c)
		if len(data.Sprints) == 0 {
			continue
		}
		last := data.Sprints[len(data.Sprints)-1]
		wasSet := last.Velocity != nil
		fc, err := forecast.WhatIf(data, coretest.Today(t, c), last.ID, p)
		if err != nil {
			t.Fatalf("%s: %v", c.Name, err)
		}
		if got := data.Sprints[len(data.Sprints)-1].Velocity; (got != nil) != wasSet {
			t.Errorf("%s: the data was changed", c.Name)
		}
		found := false
		for _, e := range fc.Entries {
			if e.Sprint.ID == last.ID {
				found = true
				if e.Sprint.Velocity == nil || *e.Sprint.Velocity != 27 {
					t.Errorf("%s: velocity %v, want 27", c.Name, e.Sprint.Velocity)
				}
			}
		}
		if !found {
			t.Errorf("%s: sprint missing", c.Name)
		}
		return
	}
	t.Skip("no golden case with sprints")
}
