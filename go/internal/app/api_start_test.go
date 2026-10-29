package app

import (
	"testing"
	"time"
)

// The changeover day: the old sprint is still being reviewed, the new one is planned. The new
// sprint is not running until it is started, and starting it can name an earlier day.
func TestSprintRunsOnlyOnceItIsStarted(t *testing.T) {
	api, team := planTeam(t)
	var cur, next string
	sprints, _ := api.Sprints(team)
	for i, s := range sprints {
		if s.State == "current" {
			cur, next = s.ID, sprints[i+1].ID
		}
	}
	if cur == "" {
		t.Fatal("planTeam starts no sprint")
	}
	// The clock reaches the first day of the next sprint: the old one keeps running.
	nextInfo := sprints[len(sprints)-1]
	for _, s := range sprints {
		if s.ID == next {
			nextInfo = s
		}
	}
	first, _ := time.Parse("2006-01-02", nextInfo.Start)
	old := now
	now = func() time.Time { return first.Add(9 * time.Hour) }
	defer func() { now = old }()

	v, err := api.PlanSprint(team, next, nil)
	if err != nil || v.Stage != "open" || !v.StartDue || v.StartedOn != "" {
		t.Fatalf("plan view of the next sprint = %s due=%v on=%q err=%v", v.Stage, v.StartDue, v.StartedOn, err)
	}
	if o, _ := api.PlanSprint(team, cur, nil); o.Stage != "current" {
		t.Fatalf("the old sprint is %s, want current until the Review or the start of the next", o.Stage)
	}
	if _, err := api.StartSprint(team, next, first.AddDate(0, 0, -1).Format("2006-01-02")); err == nil {
		t.Error("a start before the first day must be refused")
	}
	if _, err := api.StartSprint(team, next, first.AddDate(0, 0, 1).Format("2006-01-02")); err == nil {
		t.Error("a start in the future must be refused")
	}
	if _, err := api.StartSprint(team, next, ""); err == nil {
		t.Error("starting without a plan must be refused: the plan page starts and freezes together")
	}
	got, err := api.StartSprintWithPlan(team, next, "", FreezeInput{Tickets: []string{"T-1"}})
	if err != nil || got.Stage != "current" || got.StartedOn != nextInfo.Start {
		t.Fatalf("start = %+v err=%v", got, err)
	}
	if v, _ := api.PlanSprint(team, next, nil); v.Frozen == nil || v.Committed == nil {
		t.Errorf("the plan is frozen with the start: %+v", v.Frozen)
	}
	if o, _ := api.PlanSprint(team, cur, nil); o.Stage != "past" {
		t.Errorf("the old sprint is %s after the next one started", o.Stage)
	}
	today, err := api.todayAt(team, first)
	if err != nil || len(today.Sprints) == 0 {
		t.Fatalf("today = %+v err=%v", today, err)
	}
	running := ""
	for _, s := range today.Sprints {
		if s.State == "running" {
			running = s.ID
		}
	}
	if running != next {
		t.Errorf("start page runs %q, want %s: %+v", running, next, today.Sprints)
	}
	moved, err := api.StartSprint(team, next, first.Format("2006-01-02"))
	if err != nil || moved.StartedOn != nextInfo.Start {
		t.Fatalf("moving the start day = %+v err=%v", moved, err)
	}
	if _, err := api.StartSprintWithPlan(team, next, "", FreezeInput{}); err == nil {
		t.Error("a running sprint cannot be started again")
	}
	back, err := api.WithdrawSprintStart(team, next)
	if err != nil || back.Stage != "open" || back.StartedOn != "" {
		t.Fatalf("take back = %+v err=%v", back, err)
	}
	if v, _ := api.PlanSprint(team, next, nil); v.Frozen != nil {
		t.Errorf("taking the start back reopens the plan: %+v", v.Frozen)
	}
	if o, _ := api.PlanSprint(team, cur, nil); o.Stage != "current" {
		t.Errorf("the old sprint is %s after the start was taken back", o.Stage)
	}
	// A plan frozen before this version waits for its start, also after its first day, and can
	// then be started without a new plan.
	if _, err := freezeOnly(api, team, next, FreezeInput{Tickets: []string{"T-1"}}); err != nil {
		t.Fatal(err)
	}
	now = func() time.Time { return first.AddDate(0, 0, 3) }
	if v, _ := api.PlanSprint(team, next, nil); v.Stage != "planned" || !v.StartDue {
		t.Errorf("frozen but not started: stage %s due %v", v.Stage, v.StartDue)
	}
	if got, err := api.StartSprint(team, next, ""); err != nil || got.Stage != "current" {
		t.Errorf("starting a frozen plan = %+v err=%v", got, err)
	}
}
