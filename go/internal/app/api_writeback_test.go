package app

import (
	"errors"
	"strconv"
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/storage"
)

// fakeTracker stands in for Jira: it keeps the sprint of every ticket, records the moves and never
// talks to a network.
type fakeTracker struct {
	sprints  []sources.SprintValue
	where    map[string]string // ticket key -> name of its sprint ("" = backlog)
	toSprint map[int][]string
	backlog  []string
	enabled  bool
	failNext bool
}

func (f *fakeTracker) Fetch() ([]sources.RawTicket, error) {
	var out []sources.RawTicket
	for _, k := range []string{"T-1", "T-2", "T-3"} {
		est := 5.0
		out = append(out, sources.RawTicket{Key: k, Title: k, SprintName: f.where[k], Estimate: &est})
	}
	return out, nil
}
func (f *fakeTracker) KnownSprints() []sources.SprintValue { return f.sprints }
func (f *fakeTracker) EnableSprintWrite()                  { f.enabled = true }
func (f *fakeTracker) Close()                              {}
func (f *fakeTracker) MoveToSprint(id int, keys []string) error {
	if !f.enabled {
		return errors.New("not switched on")
	}
	if f.failNext {
		return errors.New("tracker said no")
	}
	if f.toSprint == nil {
		f.toSprint = map[int][]string{}
	}
	f.toSprint[id] = append(f.toSprint[id], keys...)
	for _, s := range f.sprints {
		if s.ID == strconv.Itoa(id) {
			for _, k := range keys {
				f.where[k] = s.Name
			}
		}
	}
	return nil
}
func (f *fakeTracker) MoveToBacklog(keys []string) error {
	if !f.enabled {
		return errors.New("not switched on")
	}
	f.backlog = append(f.backlog, keys...)
	for _, k := range keys {
		f.where[k] = ""
	}
	return nil
}

// writeTeam makes the plan team a Jira team with write-back on and a frozen plan: T-1 and T-2 are
// agreed, T-3 sits in the tracker's sprint but was taken out.
func writeTeam(t *testing.T) (api *API, team, next string, fake *fakeTracker) {
	t.Helper()
	api, team = planTeam(t)
	sprints, _ := api.Sprints(team)
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	repo := storage.NewRepository(api.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		t.Fatal(err)
	}
	tm := data.Team
	url := "https://jira.example.com"
	tm.Tracker.Kind, tm.Tracker.BaseURL, tm.Tracker.WriteSprint = "jira", &url, true
	if _, err := repo.SaveTeam(tm); err != nil {
		t.Fatal(err)
	}
	name := func(v string) *string { return &v }
	for i := range data.Tickets {
		if data.Tickets[i].Key == "T-3" {
			data.Tickets[i].SprintName, data.Tickets[i].InSprint = name(next), name(next)
		}
	}
	if _, err := repo.SaveTickets(team, storage.TicketsFile{Tickets: data.Tickets}); err != nil {
		t.Fatal(err)
	}
	if err := api.SetRemoved(team, next, "T-3", true); err != nil {
		t.Fatal(err)
	}
	if _, err := api.FreezePlan(team, next, FreezeInput{Tickets: []string{"T-1", "T-2"}, Removed: []string{"T-3"}}); err != nil {
		t.Fatal(err)
	}
	fake = &fakeTracker{sprints: []sources.SprintValue{{ID: "7", Name: next, State: "FUTURE"}}, where: map[string]string{"T-3": next}}
	old := writebackOpen
	writebackOpen = func(model.TrackerSettings) (writebackTracker, error) { return fake, nil }
	t.Cleanup(func() { writebackOpen = old })
	return api, team, next, fake
}

func TestWritePreviewChangesNothing(t *testing.T) {
	api, team, next, fake := writeTeam(t)
	p, err := api.PlanWritePreview(team, next)
	if err != nil {
		t.Fatal(err)
	}
	if !p.Enabled || p.Sprint != next || len(p.Moves) != 3 || len(p.Problems) != 0 {
		t.Fatalf("preview = %+v", p)
	}
	byKey := map[string]WriteMove{}
	for _, m := range p.Moves {
		byKey[m.Key] = m
	}
	if byKey["T-1"].Reason != "committed" || byKey["T-1"].To != next || byKey["T-3"].Reason != "taken_out" || byKey["T-3"].To != "" {
		t.Errorf("moves = %+v", p.Moves)
	}
	if len(fake.toSprint) != 0 || len(fake.backlog) != 0 || fake.enabled {
		t.Errorf("the preview wrote: %+v", fake)
	}
}

func TestWriteApplyLeavesOutSkippedAndCanBeUndone(t *testing.T) {
	api, team, next, fake := writeTeam(t)
	res, err := api.PlanWriteApply(team, next, []string{"T-1", "T-3"})
	if err != nil || res.Error != "" {
		t.Fatalf("apply: %+v %v", res, err)
	}
	if got := fake.toSprint[7]; len(got) != 1 || got[0] != "T-1" {
		t.Errorf("sprint got %v", got)
	}
	if len(fake.backlog) != 1 || fake.backlog[0] != "T-3" {
		t.Errorf("backlog got %v", fake.backlog)
	}
	if !res.CanUndo || len(res.Done) != 2 {
		t.Fatalf("result = %+v", res)
	}
	back, err := api.PlanWriteUndo(team, next)
	if err != nil || back.Error != "" || back.CanUndo {
		t.Fatalf("undo: %+v %v", back, err)
	}
	// T-1 had no sprint (back to the backlog), T-3 went back into the sprint.
	if len(fake.backlog) != 2 || fake.backlog[1] != "T-1" || len(fake.toSprint[7]) != 2 || fake.toSprint[7][1] != "T-3" {
		t.Errorf("after undo: backlog %v, sprint %v", fake.backlog, fake.toSprint)
	}
	if _, err := api.PlanWriteUndo(team, next); err == nil {
		t.Error("undid twice")
	}
}

func TestWriteApplyReportsAFailure(t *testing.T) {
	api, team, next, fake := writeTeam(t)
	fake.failNext = true
	res, err := api.PlanWriteApply(team, next, []string{"T-1", "T-2", "T-3"})
	if err != nil {
		t.Fatal(err)
	}
	if res.Error == "" || len(res.Failed) == 0 || res.CanUndo {
		t.Errorf("result = %+v", res)
	}
}

func TestWriteIsOffUnlessSwitchedOn(t *testing.T) {
	api, team, next, fake := writeTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load(team)
	tm := data.Team
	tm.Tracker.WriteSprint = false
	if _, err := repo.SaveTeam(tm); err != nil {
		t.Fatal(err)
	}
	p, err := api.PlanWritePreview(team, next)
	if err != nil || p.Enabled || len(p.Moves) != 0 {
		t.Fatalf("preview = %+v %v", p, err)
	}
	if _, err := api.PlanWriteApply(team, next, nil); err == nil {
		t.Error("applied although write-back is off")
	}
	if len(fake.toSprint)+len(fake.backlog) != 0 {
		t.Error("something was written")
	}
}

func TestWriteNeedsAFrozenPlan(t *testing.T) {
	api, team, next, _ := writeTeam(t)
	if err := api.ReopenPlan(team, next); err != nil {
		t.Fatal(err)
	}
	p, err := api.PlanWritePreview(team, next)
	if err != nil || !p.Enabled || len(p.Problems) != 1 || len(p.Moves) != 0 {
		t.Fatalf("preview = %+v %v", p, err)
	}
	if _, err := api.PlanWriteApply(team, next, nil); err == nil {
		t.Error("applied an unfrozen plan")
	}
}

func TestWritePlansFromTheTrackerAsItIsNow(t *testing.T) {
	api, team, next, fake := writeTeam(t)
	if _, err := api.PlanWriteApply(team, next, []string{"T-1", "T-2", "T-3"}); err != nil {
		t.Fatal(err)
	}
	// Written once: a second preview finds nothing left to do, although tickets.yaml is stale.
	p, err := api.PlanWritePreview(team, next)
	if err != nil || len(p.Moves) != 0 {
		t.Fatalf("second preview = %+v %v", p, err)
	}
	// Only approved moves are written: nothing is approved, nothing moves.
	fake.where["T-1"] = ""
	before := len(fake.toSprint[7])
	if _, err := api.PlanWriteApply(team, next, nil); err != nil {
		t.Fatal(err)
	}
	if len(fake.toSprint[7]) != before {
		t.Error("an unapproved move was written")
	}
	if v, _ := api.PlanSprint(team, next, nil); !v.WriteUndo {
		t.Error("the view does not offer to take the write back")
	}
}
