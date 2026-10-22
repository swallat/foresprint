package app

import (
	"os"
	"testing"
)

func TestDemoModeLoadsTutorialTeam(t *testing.T) {
	a := newAPI(t, t.TempDir())
	home := a.DataDir()
	key, err := a.EnterDemo("en")
	if err != nil || key != "atlas" {
		t.Fatalf("%q %v", key, err)
	}
	if !a.InDemo() || a.DataDir() == home {
		t.Fatal("demo not on")
	}
	teams := a.Teams()
	if len(teams) != 1 || teams[0].Name != "Team Atlas" || teams[0].Problem != "" || teams[0].Products != 4 {
		t.Fatalf("%+v", teams)
	}
	projects, err := a.Projects(key)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, p := range projects.Projects {
		found = found || p.ID == "self-service"
	}
	if !found {
		t.Errorf("no project self-service: %+v", projects)
	}
	if st := a.Status(); st.Storage != StorageLocal {
		t.Errorf("status %+v", st)
	}
	if r, err := a.Save(); err != nil || !r.OK {
		t.Errorf("save %+v %v", r, err)
	}
	dir := a.DataDir()
	if err := a.LeaveDemo(); err != nil {
		t.Fatal(err)
	}
	if a.InDemo() || a.DataDir() != home {
		t.Error("still in demo")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Errorf("demo folder stays: %v", err)
	}
}

// The pages the guided flows open must have data in the tutorial team.
func TestDemoServesTheGuidedFlows(t *testing.T) {
	a := newAPI(t, t.TempDir())
	key, err := a.EnterDemo("de")
	if err != nil {
		t.Fatal(err)
	}
	defer a.LeaveDemo()
	if v, err := a.Forecast(key); err != nil || v.Team == "" {
		t.Errorf("forecast %v", err)
	}
	if p, err := a.PlanSprint(key, "8", nil); err != nil || p == nil {
		t.Errorf("plan %v", err)
	}
	if p, err := a.SprintPrepare(key, "8"); err != nil || p.CapacityBase <= 0 {
		t.Errorf("prepare %+v %v", p, err)
	}
	if r, err := a.SprintReview(key, "7"); err != nil {
		t.Errorf("review %+v %v", r, err)
	}
	if _, err := a.RunningTickets(key, "7"); err != nil {
		t.Errorf("running %v", err)
	}
	if _, err := a.SprintOverview(key, 6); err != nil {
		t.Errorf("overview %v", err)
	}
}

func TestDemoEnteredTwiceAndDataDirChange(t *testing.T) {
	home := t.TempDir()
	a := newAPI(t, home)
	if _, err := a.EnterDemo("en"); err != nil {
		t.Fatal(err)
	}
	first := a.DataDir()
	if _, err := a.EnterDemo("en"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(first); !os.IsNotExist(err) {
		t.Error("first demo folder leaked")
	}
	if err := a.LeaveDemo(); err != nil || a.DataDir() != home {
		t.Fatalf("back to %q: %v", a.DataDir(), err)
	}
	if _, err := a.EnterDemo("en"); err != nil {
		t.Fatal(err)
	}
	other := t.TempDir()
	if err := a.SetDataDir(other); err != nil || a.InDemo() || a.DataDir() != other {
		t.Errorf("SetDataDir in demo: %v %v %q", err, a.InDemo(), a.DataDir())
	}
}
