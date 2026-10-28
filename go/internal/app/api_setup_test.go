package app

import (
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/validate"
)

func newTeamRequest(source string) NewTeam {
	return NewTeam{
		Name: "Team Nord", Country: "DE", Region: "NW",
		FirstSprintID: "2026.22", FirstStart: "2026-10-28", Source: source,
		TrackerURL: "https://jira.example.com", TrackerQuery: "project = NRD",
	}
}

func TestSetupCreateTeamForEverySource(t *testing.T) {
	for _, source := range []string{SourceTracker, SourcePackages, SourceNone} {
		t.Run(source, func(t *testing.T) {
			api := newAPI(t, t.TempDir())
			got, err := api.SetupCreateTeam(newTeamRequest(source))
			if err != nil {
				t.Fatal(err)
			}
			if got.Key != "team-nord" || got.Name != "Team Nord" || got.Sprints != 3 {
				t.Fatalf("team = %+v", got)
			}
			if got.Tickets != (source != SourceNone) {
				t.Errorf("tickets = %v for source %s", got.Tickets, source)
			}
			data, err := storage.NewRepository(api.DataDir()).Load(got.Key)
			if err != nil {
				t.Fatal(err)
			}
			if sourceOf(data.Team) != source {
				t.Errorf("source = %s, want %s", sourceOf(data.Team), source)
			}
			for _, is := range validate.CheckTeam(data, time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC)) {
				if is.Level == validate.Error {
					t.Errorf("new team has an error: %s: %s", is.Where, is.Message)
				}
			}
			// The start page works for a team that was just created.
			today, err := api.todayAt(got.Key, time.Date(2026, 10, 29, 0, 0, 0, 0, time.UTC))
			// Nothing is running before the first sprint is started.
			if err != nil || len(today.Sprints) == 0 || today.Sprints[0].State != "next" || !today.Sprints[0].StartDue {
				t.Fatalf("today = %+v, %v", today, err)
			}
		})
	}
}

func TestSetupCreateTeamKeysDoNotClash(t *testing.T) {
	api := newAPI(t, t.TempDir())
	first, err := api.SetupCreateTeam(newTeamRequest(SourceNone))
	if err != nil {
		t.Fatal(err)
	}
	second, err := api.SetupCreateTeam(newTeamRequest(SourceNone))
	if err != nil {
		t.Fatal(err)
	}
	if first.Key == second.Key || second.Key != "team-nord-2" {
		t.Fatalf("keys %q and %q", first.Key, second.Key)
	}
}

func TestSetupCreateTeamRefusals(t *testing.T) {
	api := newAPI(t, t.TempDir())
	for name, mutate := range map[string]func(*NewTeam){
		"no name":          func(r *NewTeam) { r.Name = " " },
		"bad date":         func(r *NewTeam) { r.FirstStart = "28.10.2026" },
		"no id":            func(r *NewTeam) { r.FirstSprintID = "" },
		"id not a number":  func(r *NewTeam) { r.FirstSprintID = "next-one" },
		"tracker no url":   func(r *NewTeam) { r.Source = SourceTracker; r.TrackerURL = "" },
		"tracker no query": func(r *NewTeam) { r.Source = SourceTracker; r.TrackerQuery = "" },
		"tracker bad url":  func(r *NewTeam) { r.Source = SourceTracker; r.TrackerURL = "https://u:p@jira.example.com" },
		"unknown source":   func(r *NewTeam) { r.Source = "carrier-pigeon" },
	} {
		req := newTeamRequest(SourceNone)
		mutate(&req)
		if _, err := api.SetupCreateTeam(req); err == nil {
			t.Errorf("%s: want an error", name)
		}
	}
	if teams := api.Teams(); len(teams) != 0 {
		t.Errorf("refused requests left teams behind: %+v", teams)
	}
}

func TestTeamKey(t *testing.T) {
	repo := storage.NewRepository(t.TempDir())
	for name, want := range map[string]string{"Team Nord": "team-nord", "Größe & Ärger": "groesse-aerger", "***": "team"} {
		if got := teamKey(name, repo); got != want {
			t.Errorf("teamKey(%q) = %q, want %q", name, got, want)
		}
	}
	if got := teamKey(strings.Repeat("a", 80), repo); len(got) != 48 {
		t.Errorf("long key has %d characters", len(got))
	}
}

func TestSetupStorageNewFolderAndRegions(t *testing.T) {
	api := newAPI(t, t.TempDir())
	folder := t.TempDir() + "/data"
	out := api.SetupStorage("new", "", folder)
	if out.Problem != nil {
		t.Skip("git not usable here: " + out.Problem.Message)
	}
	if api.DataDir() != out.Folder {
		t.Errorf("data dir = %q, want %q", api.DataDir(), out.Folder)
	}
	if got := api.SetupStorage("teleport", "", folder); got.Problem == nil {
		t.Error("unknown kind must be refused")
	}
	regions := api.SetupRegions()
	if len(regions) == 0 || regions[0].Name == "" {
		t.Fatalf("regions = %v", regions)
	}
}

func TestSetupCreateTeamFreeSprintName(t *testing.T) {
	api := newAPI(t, t.TempDir())
	req := newTeamRequest(SourceNone)
	req.FirstSprintID = "Team Nord Sprint 2026.16"
	req.FirstStart = "2026-10-20"
	got, err := api.SetupCreateTeam(req)
	if err != nil {
		t.Fatalf("a free name with a number must be read as a pattern: %v", err)
	}
	repo := storage.NewRepository(api.DataDir())
	data, err := repo.Load(got.Key)
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, s := range data.Sprints {
		ids = append(ids, s.ID)
	}
	want := []string{"Team Nord Sprint 2026.16", "Team Nord Sprint 2026.17", "Team Nord Sprint 2026.18"}
	if strings.Join(ids, "|") != strings.Join(want, "|") {
		t.Fatalf("sprints = %v, want %v", ids, want)
	}
}

func TestSetupCreateTeamNamingPattern(t *testing.T) {
	api := newAPI(t, t.TempDir())
	req := newTeamRequest(SourceNone)
	req.FirstSprintID, req.FirstStart, req.NamingPattern = "Sprint 7", "2026-10-20", "Sprint {LFD}"
	if _, err := api.SetupCreateTeam(req); err != nil {
		t.Fatal(err)
	}
	bad := newTeamRequest(SourceNone)
	bad.Name = "Anderes Team"
	bad.FirstSprintID, bad.NamingPattern = "Sprint 7", "Lauf {JJJJ}.{N}"
	if _, err := api.SetupCreateTeam(bad); err == nil {
		t.Fatal("a name that does not fit the pattern must be refused")
	}
	bad.NamingPattern = "Lauf {XX}"
	if _, err := api.SetupCreateTeam(bad); err == nil {
		t.Fatal("an unknown placeholder must be refused")
	}
	bad.NamingPattern, bad.FirstSprintID = "", "Sprint ohne Zahl"
	if _, err := api.SetupCreateTeam(bad); err == nil {
		t.Fatal("a name without a number and without a pattern must be refused")
	}
}

func TestSetupCreateTeamPatternWithoutNumberRefused(t *testing.T) {
	api := newAPI(t, t.TempDir())
	req := newTeamRequest(SourceNone)
	req.FirstSprintID, req.NamingPattern = "Sprint", "Sprint"
	if _, err := api.SetupCreateTeam(req); err == nil {
		t.Fatal("a pattern that names all sprints alike must be refused")
	}
}
