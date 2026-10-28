package app

import (
	"os"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/storage"
)

// A team with as_of counts that day as today, whatever the clock says; other teams and the
// team without it keep the clock.
func TestTeamAsOfOverridesTheClock(t *testing.T) {
	api, team := planTeam(t) // the clock stands at 2026-10-14
	state := func() map[string]string {
		list, err := api.Sprints(team)
		if err != nil {
			t.Fatal(err)
		}
		out := map[string]string{}
		for _, s := range list {
			out[s.ID] = s.State
		}
		return out
	}
	before := state()

	old := now
	now = func() time.Time { return time.Date(2031, 1, 5, 9, 0, 0, 0, time.UTC) } // far away
	t.Cleanup(func() { now = old })
	if got := state(); got["2026.21"] == before["2026.21"] {
		t.Fatalf("the clock moved but the states did not: %v", got)
	}

	repo := storage.NewRepository(api.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		t.Fatal(err)
	}
	day := time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC)
	data.Team.AsOf = &day
	path, err := repo.SaveTeam(data.Team)
	if err != nil {
		t.Fatal(err)
	}
	if raw, _ := os.ReadFile(path); !strings.Contains(string(raw), "as_of: 2026-10-14") {
		t.Fatalf("team.yaml lacks as_of:\n%s", raw)
	}
	storage.ClearTeamCache()
	for id, s := range before {
		if got := state()[id]; got != s {
			t.Errorf("sprint %s is %q with as_of, want %q (as on the day itself)", id, got, s)
		}
	}
	for _, s := range api.Teams() {
		if s.Key == team && s.AsOf != "2026-10-14" {
			t.Errorf("TeamSummary.AsOf = %q", s.AsOf)
		}
	}
	if td, err := api.Today(team); err != nil || td.Date != "2026-10-14" {
		t.Errorf("Today = %q err=%v, want 2026-10-14", td.Date, err)
	}

	// Without the field the file is as before.
	data, _ = repo.Load(team)
	data.Team.AsOf = nil
	if path, err = repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	if raw, _ := os.ReadFile(path); strings.Contains(string(raw), "as_of") {
		t.Errorf("as_of stays in team.yaml after removing it:\n%s", raw)
	}
}
