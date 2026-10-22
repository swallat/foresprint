package app

import (
	"os"
	"strings"
	"testing"
)

func TestCalendarShowsFinishedRunningAndPlanned(t *testing.T) {
	api, team := demoCopy(t)
	view, err := api.Calendar(team, 6)
	if err != nil {
		t.Fatal(err)
	}
	if len(view.Rows) < 6 {
		t.Fatalf("rows = %d", len(view.Rows))
	}
	states := map[string]bool{}
	for _, r := range view.Rows {
		states[r.State] = true
		if r.State == CalFinished != r.Locked {
			t.Errorf("%s: locked = %v for state %s", r.ID, r.Locked, r.State)
		}
		if r.Workdays <= 0 || r.Last < r.Start {
			t.Errorf("row %+v", r)
		}
	}
	if !states[CalFinished] || !states[CalRunning] {
		t.Errorf("states = %v", states)
	}
}

func TestSaveLastDaysMovesFollowingSprintsAndRefusesFinished(t *testing.T) {
	api, team := demoCopy(t)
	view, _ := api.Calendar(team, 5)
	var running, next CalendarRow
	for i, r := range view.Rows {
		if r.State == CalRunning {
			running, next = r, view.Rows[i+1]
		}
	}
	if _, err := api.SaveLastDays(team, []LastDay{{ID: view.Rows[0].ID, Last: view.Rows[0].Last}}, 5); err == nil {
		t.Error("finished sprint accepted")
	}
	// one day later
	late := running.Last[:8] + "29"
	if running.Last >= late {
		late = next.Start
	}
	res, err := api.SaveLastDays(team, []LastDay{{ID: running.ID, Last: late}}, 5)
	if err != nil {
		t.Fatal(err)
	}
	var got CalendarRow
	for _, r := range res.View.Rows {
		if r.ID == running.ID {
			got = r
		}
	}
	if got.Last != late {
		t.Errorf("last = %s, want %s", got.Last, late)
	}
	if res.Moved == 0 || res.Undo == 0 {
		t.Errorf("result %+v", res)
	}
	if err := api.Undo(team, res.Undo); err != nil {
		t.Fatal(err)
	}
	back, _ := api.Calendar(team, 5)
	for _, r := range back.Rows {
		if r.ID == running.ID && r.Last != running.Last {
			t.Errorf("after undo last = %s, want %s", r.Last, running.Last)
		}
	}
}

func TestNamingPreviewAndApply(t *testing.T) {
	api, team := demoCopy(t)
	if p, _ := api.NamingPreview(team, "{JJJJ", "", false, 4); p.Problem == "" {
		t.Error("broken pattern not reported")
	}
	if p, _ := api.NamingPreview(team, "Atlas", "", false, 4); !p.NoNumber {
		t.Error("pattern without number not reported")
	}
	prev, err := api.NamingPreview(team, "Atlas {JJ}-{NN}", "", false, 4)
	if err != nil {
		t.Fatal(err)
	}
	if prev.Count == 0 || prev.Duplicate != "" {
		t.Fatalf("preview %+v", prev)
	}
	for _, r := range prev.Rows {
		if r.Changes && !strings.HasPrefix(r.New, "Atlas 26-") {
			t.Errorf("new name %q", r.New)
		}
		if r.Locked && r.Changes {
			t.Errorf("locked sprint changes: %+v", r)
		}
	}
	res, err := api.ApplyNaming(team, "Atlas {JJ}-{NN}", "", false, 4)
	if err != nil {
		t.Fatal(err)
	}
	if res.View.Pattern != "Atlas {JJ}-{NN}" {
		t.Errorf("pattern = %q", res.View.Pattern)
	}
	// the sprints after the last recorded one now come out named, and the calendar still builds
	view, err := api.Calendar(team, 6)
	if err != nil {
		t.Fatal(err)
	}
	named := 0
	for _, r := range view.Rows {
		if strings.HasPrefix(r.ID, "Atlas ") {
			named++
		}
	}
	if named == 0 {
		t.Errorf("no sprint named: %+v", view.Rows)
	}
	// nothing left to rename
	again, _ := api.NamingPreview(team, "Atlas {JJ}-{NN}", "", false, 4)
	if again.Count != 0 {
		t.Errorf("second preview wants %d renames", again.Count)
	}
	// the files moved
	entries, _ := os.ReadDir(api.teamFile(team, "sprints"))
	found := false
	for _, e := range entries {
		found = found || strings.HasPrefix(e.Name(), "Atlas")
	}
	if !found {
		t.Error("no renamed sprint file")
	}
}

func TestRenameSprintIsAnException(t *testing.T) {
	api, team := demoCopy(t)
	view, _ := api.Calendar(team, 4)
	var open CalendarRow
	for _, r := range view.Rows {
		if r.Saved && r.State != CalFinished {
			open = r
			break
		}
	}
	if open.ID == "" {
		t.Skip("no saved open sprint in the demo")
	}
	if _, err := api.RenameSprint(team, open.ID, view.Rows[0].ID, 4); err == nil {
		t.Error("duplicate ID accepted")
	}
	res, err := api.RenameSprint(team, open.ID, "Sonder 1", 4)
	if err != nil {
		t.Fatal(err)
	}
	ok := false
	for _, r := range res.View.Rows {
		ok = ok || r.ID == "Sonder 1"
	}
	if !ok {
		t.Error("renamed sprint missing")
	}
}
