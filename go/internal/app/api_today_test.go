package app

import (
	"testing"

	"github.com/swallat/foresprint/internal/storage"
)

func TestTodayOfTheDemoTeam(t *testing.T) {
	api := newAPI(t, demoDir(t))
	teams := api.Teams()
	if len(teams) == 0 {
		t.Fatal("no teams")
	}
	// A day inside the last sprint of the demo team.
	sprints, err := api.Sprints(teams[0].Key)
	if err != nil || len(sprints) < 3 {
		t.Fatalf("sprints = %v, %v", sprints, err)
	}
	// the selector also offers coming sprints of the calendar, so take the recorded ones
	data, err := storage.NewRepository(api.DataDir()).Load(teams[0].Key)
	if err != nil || len(data.Sprints) < 3 {
		t.Fatalf("recorded sprints = %d, %v", len(data.Sprints), err)
	}
	mid := data.Sprints[len(data.Sprints)-3].Start
	today, err := api.todayAt(teams[0].Key, mid.AddDate(0, 0, 3))
	if err != nil {
		t.Fatal(err)
	}
	if today.Name == "" || today.Source != SourceNone && today.Source != SourceTracker && today.Source != SourcePackages {
		t.Fatalf("today = %+v", today)
	}
	var states []string
	for _, s := range today.Sprints {
		states = append(states, s.State)
		if len(s.Steps) == 0 {
			t.Errorf("sprint %s has no steps", s.ID)
		}
	}
	want := []string{"running", "next", "later"}
	if len(states) < 2 || states[0] != "running" || states[1] != "next" {
		t.Fatalf("states = %v, want prefix %v", states, want)
	}
	if today.Sprints[0].Steps[0].Key != StepReview {
		t.Errorf("running sprint shows %v, want the review", today.Sprints[0].Steps)
	}
	if today.Sprints[1].Steps[0].Key != StepAbsences {
		t.Errorf("next sprint shows %v, want the absences first", today.Sprints[1].Steps)
	}
	if len(today.Findings) > MaxFindings {
		t.Errorf("%d findings, at most %d are listed", len(today.Findings), MaxFindings)
	}
}

func TestTodayUnknownTeam(t *testing.T) {
	api := newAPI(t, t.TempDir())
	if _, err := api.Today("nobody"); err == nil {
		t.Fatal("want an error for a team that does not exist")
	}
}

func TestRouteOf(t *testing.T) {
	for where, want := range map[string]string{
		"people.yaml: anna":      "/team/people",
		"sprints/2026.22.yaml":   "/sprints",
		"team.yaml":              "/settings/team",
		"products.yaml":          "/team/products",
		"tickets.yaml: ATL-1":    "/backlog",
		"something-else.yaml":    "/data",
		`sprints\2026.1.yaml: x`: "/sprints",
	} {
		if got := routeOf(where); got != want {
			t.Errorf("routeOf(%q) = %q, want %q", where, got, want)
		}
	}
}
