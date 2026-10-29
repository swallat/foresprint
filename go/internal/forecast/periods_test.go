package forecast_test

import (
	"math"
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
	if *source != engine.SourceExpected { // decision G1: an open sprint only announces
		t.Errorf("confirmed period: source %v, want expected", *source)
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
	// the window gives 10 / 15 / 20 for the lowest / median / highest value: 5 below, 5 above
	span, ok := fc.PlanSpanOf(3)
	if !ok || span.Low != 15 || span.High != 25 || span.Samples != 2 {
		t.Errorf("span %+v %v, want 15..25 around the plan 20 over 2", span, ok)
	}
	// the range follows the plan, wherever the trend has put it, and never goes below 0
	for _, p := range []float64{6, 30} {
		fc.Entries[3].Result.Plan = &p
		span, _ := fc.PlanSpanOf(3)
		if span.Low != math.Max(p-5, 0) || span.High != p+5 {
			t.Errorf("plan %v: span %+v, want %v..%v", p, span, math.Max(p-5, 0), p+5)
		}
	}
	if _, ok := fc.PlanSpanOf(1); ok {
		t.Error("a sprint that is not a projection has no span")
	}
}

func TestCarryInSplitsPlan(t *testing.T) {
	d := func(day int) time.Time { return time.Date(2026, 3, day, 0, 0, 0, 0, time.UTC) }
	data := &storage.TeamData{Team: model.NewTeam("t", "t")}
	data.Team.Forecast.Rounding = 0
	commit := 20.0
	data.Sprints = []model.Sprint{
		{ID: "s1", Start: d(2), End: d(13), Commitment: &commit, Velocity: &commit},
		{ID: "s2", Start: d(16), End: d(27), Commitment: &commit},
	}
	today := d(1)

	plain, err := forecast.Build(data, today)
	if err != nil {
		t.Fatal(err)
	}
	for i, e := range plain.Entries[:2] {
		if e.CarryIn != 0 || *e.Result.Roadmap != 16 || *e.Result.SmallStuff != 4 {
			t.Errorf("entry %d without carry-in: carry %v roadmap %v small %v", i, e.CarryIn, *e.Result.Roadmap, *e.Result.SmallStuff)
		}
	}

	data.Sprints[0].Carry = []model.CarryItem{{Rest: 5}}
	fc, err := forecast.Build(data, today)
	if err != nil {
		t.Fatal(err)
	}
	if e := fc.Entry("s1"); e.CarryIn != 0 || *e.Result.Roadmap != 16 {
		t.Errorf("s1 takes nothing over: carry %v roadmap %v", e.CarryIn, *e.Result.Roadmap)
	}
	e := fc.Entry("s2")
	if e.CarryIn != 5 || *e.Result.Roadmap != 12 || *e.Result.SmallStuff != 3 {
		t.Errorf("s2: carry %v roadmap %v small %v, want 5 / 12 / 3", e.CarryIn, *e.Result.Roadmap, *e.Result.SmallStuff)
	}

	data.Sprints[0].Carry = []model.CarryItem{{Rest: 30}}
	e = mustBuild(t, data, today).Entry("s2")
	if *e.Result.Roadmap != 0 || *e.Result.SmallStuff != 0 {
		t.Errorf("overbooked s2: roadmap %v small %v, want 0 / 0", *e.Result.Roadmap, *e.Result.SmallStuff)
	}
}

func mustBuild(t *testing.T, data *storage.TeamData, today time.Time) *forecast.Forecast {
	t.Helper()
	fc, err := forecast.Build(data, today)
	if err != nil {
		t.Fatal(err)
	}
	return fc
}

func TestCarryIntoGeneratedSprint(t *testing.T) {
	d := func(day int) time.Time { return time.Date(2026, 3, day, 0, 0, 0, 0, time.UTC) }
	data := &storage.TeamData{Team: model.NewTeam("t", "t")}
	data.Team.Forecast.Rounding = 1
	commit := 20.0
	capa := 40.0
	hist := func(id string, from int) model.Sprint {
		return model.Sprint{ID: id, Start: d(from).AddDate(0, 0, 0), End: d(from).AddDate(0, 0, 11), Commitment: &commit, Velocity: &commit, Capacity: &capa}
	}
	s3 := hist("s3", 30)
	s3.Carry = []model.CarryItem{{Rest: 2.5}}
	data.Sprints = []model.Sprint{hist("s1", 2), hist("s2", 16), s3}
	fc := mustBuild(t, data, time.Date(2026, 5, 1, 0, 0, 0, 0, time.UTC))
	var next *forecast.TimelineEntry
	for i := range fc.Entries {
		if !fc.Entries[i].Recorded && fc.Entries[i].Result.Plan != nil {
			next = &fc.Entries[i]
			break
		}
	}
	if next == nil {
		t.Skip("no generated sprint with a PLAN")
	}
	if next.CarryIn != 2.5 {
		t.Fatalf("carry-in of the generated sprint = %v, want 2.5", next.CarryIn)
	}
	want := float64(int(((*next.Result.Plan-2.5)*0.8)*10)) / 10
	if *next.Result.Roadmap != want {
		t.Errorf("roadmap %v, want %v", *next.Result.Roadmap, want)
	}
}
