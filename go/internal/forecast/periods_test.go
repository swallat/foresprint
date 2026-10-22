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

func TestPlanSpan(t *testing.T) {
	for _, c := range golden.Cases(t) {
		data := coretest.Load(t, c)
		fc, err := forecast.Build(data, coretest.Today(t, c))
		if err != nil {
			continue
		}
		for i, e := range fc.Entries {
			span, ok := fc.PlanSpanOf(i)
			if !ok {
				continue
			}
			if span.Low > span.High || span.Samples == 0 {
				t.Errorf("%s %s: %+v", c.Name, e.Sprint.ID, span)
			}
		}
	}
	data := &storage.TeamData{Team: model.NewTeam("t", "t")}
	data.Team.Forecast.ReferenceCapacity = 10
	data.Team.Forecast.Window = 2
	data.Team.Forecast.Rounding = 0
	plan, cap := 20.0, 5.0
	src := engine.PlanForecast
	norm := func(v float64) engine.SprintResult {
		return engine.SprintResult{NormalizedVelocity: engine.Metric{Value: &v}}
	}
	// window of 2 before index 3: 20 and 40 (the 8 before is outside); capacity 5, ref 10
	fc := &forecast.Forecast{Data: data, Entries: []forecast.TimelineEntry{
		{Result: norm(8)}, {Result: norm(20)}, {Result: norm(40)},
		{Result: engine.SprintResult{Plan: &plan, PlanSource: &src, PlanCapacity: &cap}},
	}}
	span, ok := fc.PlanSpanOf(3)
	if !ok || span.Low != 10 || span.High != 20 || span.Samples != 2 {
		t.Errorf("span %+v %v, want 10..20 over 2", span, ok)
	}
	if _, ok := fc.PlanSpanOf(1); ok {
		t.Error("a sprint that is not a projection has no span")
	}
}
