package app

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// projectDir copies the demo team into a temporary data folder with the projects switched on
// (and, if tickets is set, the ticket pre-planning with a few tickets).
func projectDir(t *testing.T, tickets bool) (*API, string) {
	t.Helper()
	src := filepath.Join(demoDir(t), "demo")
	dst := filepath.Join(t.TempDir(), "demo")
	if err := os.CopyFS(dst, os.DirFS(src)); err != nil {
		t.Fatal(err)
	}
	root := filepath.Dir(dst)
	repo := storage.NewRepository(root)
	data, err := repo.Load("demo")
	if err != nil {
		t.Fatal(err)
	}
	data.Team.Features.Projects = true
	data.Team.Features.Tickets = tickets
	data.Team.Features.Explicit = true
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	if tickets {
		est := func(v float64) *float64 { return &v }
		p := "alpha"
		f := storage.TicketsFile{Tickets: []model.Ticket{
			{Key: "T-1", Title: "One", Estimate: est(1), Remaining: est(1), EstimateSource: model.EstimateRefined, Project: &p, Rank: model.Ptr("a")},
			{Key: "T-2", Title: "Two", Estimate: est(2), Remaining: est(2), EstimateSource: model.EstimateRefined, Project: &p, Rank: model.Ptr("b")},
			{Key: "T-3", Title: "Done", Estimate: est(2), EstimateSource: model.EstimateRefined, Project: &p, Done: true, InSprint: model.Ptr("2026.21")},
		}}
		if _, err := repo.SaveTickets("demo", f); err != nil {
			t.Fatal(err)
		}
		data.Projects = []model.Project{{ID: "alpha", Name: "Alpha", Priority: 1, Product: model.Ptr("portal"), End: model.Ptr(time.Date(2026, 12, 18, 0, 0, 0, 0, time.UTC))}}
		if _, err := repo.SaveProjects("demo", data.Projects); err != nil {
			t.Fatal(err)
		}
	}
	api := newAPI(t, root)
	api.Now = func() time.Time { return time.Date(2026, 10, 22, 12, 0, 0, 0, time.UTC) }
	return api, "demo"
}

func TestProjectLifecycleWithoutTickets(t *testing.T) {
	api, team := projectDir(t, false)
	v, err := api.Projects(team)
	if err != nil || !v.Enabled || len(v.Projects) != 0 {
		t.Fatalf("view = %+v, %v", v, err)
	}
	total := 40.0
	id, err := api.SaveProject(team, ProjectInput{
		Name: "Self-Service", Products: []string{"portal"}, End: "2027-01-29", Booked: &total,
		Months:     map[string]float64{"2026-11": 12, "2026-12": 14},
		Milestones: []MilestoneInput{{Name: "Beta", Date: "2026-11-20"}},
	})
	if err != nil || id != "self-service" {
		t.Fatalf("SaveProject = %q, %v", id, err)
	}
	d, err := api.Project(team, id)
	if err != nil {
		t.Fatal(err)
	}
	p := d.Project
	if p.End != "2027-01-29" || p.Booked == nil || *p.Booked != 40 || len(p.Months) != 2 || len(p.Milestones) != 1 || p.Milestones[0].Light != "none" {
		t.Fatalf("project = %+v", p)
	}
	if p.History {
		t.Error("a new project has no history")
	}
	if _, err := api.SaveProject(team, ProjectInput{Name: "self-service", Products: []string{"portal"}, End: "2027-01-29"}); err == nil {
		t.Error("a duplicate name must be refused")
	}
	if _, err := api.SaveProject(team, ProjectInput{Name: "X", Products: []string{"portal"}, End: "29.01.2027"}); err == nil {
		t.Error("a wrong date must be refused")
	}
	if err := api.CloseProject(team, CloseInput{ID: id, How: "finished", At: "2026-12-01"}); err != nil {
		t.Fatal(err)
	}
	if v, _ = api.Projects(team); len(v.Projects) != 0 || len(v.Closed) != 1 || v.Closed[0].State != "finished" {
		t.Fatalf("after closing: %+v", v)
	}
	if err := api.ReopenProject(team, id); err != nil {
		t.Fatal(err)
	}
	if err := api.UndoProjects(team); err != nil { // takes back the reopening
		t.Fatal(err)
	}
	if v, _ = api.Projects(team); len(v.Closed) != 1 {
		t.Fatalf("undo of reopening: %+v", v)
	}
	if err := api.UndoProjects(team); err != nil { // takes back the closing
		t.Fatal(err)
	}
	if err := api.DeleteProject(team, id); err != nil {
		t.Fatal(err)
	}
	if v, _ = api.Projects(team); len(v.Projects)+len(v.Closed) != 0 {
		t.Fatalf("after delete: %+v", v)
	}
}

func TestProjectsOffByDefault(t *testing.T) {
	api := newAPI(t, demoDir(t))
	v, err := api.Projects("demo")
	if err != nil || v.Enabled {
		t.Fatalf("view = %+v, %v", v, err)
	}
	if _, err := api.SaveProject("demo", ProjectInput{Name: "X", End: "2027-01-01"}); err == nil {
		t.Error("saving must be refused while the projects are off")
	}
}

func TestProjectNumbersWithTickets(t *testing.T) {
	api, team := projectDir(t, true)
	d, err := api.Project(team, "alpha")
	if err != nil {
		t.Fatal(err)
	}
	p := d.Project
	if d.Problem != "" {
		t.Fatalf("problem: %s", d.Problem)
	}
	if p.Done == nil || *p.Done != 2 || p.Planned == nil || *p.Planned != 3 || p.Open != 2 || !p.History {
		t.Fatalf("project = %+v (done %v planned %v)", p, p.Done, p.Planned)
	}
	if p.Light != "ok" && p.Light != "warn" && p.Light != "bad" {
		t.Errorf("light = %q", p.Light)
	}
	if len(d.Tickets) != 3 || len(d.Report) == 0 {
		t.Errorf("tickets %d, report %d", len(d.Tickets), len(d.Report))
	}
	// The open tickets of a closed project become daily business by themselves; a target project
	// is a decision per open ticket.
	save := ProjectInput{Name: "Beta", Products: []string{"portal"}, End: "2027-02-01"}
	beta, err := api.SaveProject(team, save)
	if err != nil {
		t.Fatal(err)
	}
	if err := api.CloseProject(team, CloseInput{ID: "alpha", How: "cancelled", At: "2026-10-30", MoveTo: beta}); err != nil {
		t.Fatal(err)
	}
	data, _ := storage.NewRepository(api.DataDir()).Load(team)
	if o := data.Preplan.OverrideFor("T-1"); o == nil || o.Project == nil || *o.Project != beta {
		t.Errorf("override = %+v", o)
	}
	if o := data.Preplan.OverrideFor("T-3"); o != nil {
		t.Errorf("a finished ticket stays: %+v", o)
	}
	if b, _ := api.Project(team, beta); b.Project.Open != 2 {
		t.Errorf("the target project takes the open tickets: %+v", b.Project)
	}
	if err := api.DeleteProject(team, "alpha"); err == nil {
		t.Error("a project with history cannot be deleted")
	}
}

// The window reads these names (frontend/src/lib/types.projects.ts).
func TestProjectJSONNames(t *testing.T) {
	api, team := projectDir(t, true)
	d, err := api.Project(team, "alpha")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(d)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	for _, k := range []string{"today", "enabled", "source", "unit", "rate", "products", "projects", "closed", "sprints", "sprintDays", "conflictSprint", "conflict", "problem", "project", "report", "tickets"} {
		if _, ok := m[k]; !ok {
			t.Errorf("missing key %q", k)
		}
	}
	p, _ := m["project"].(map[string]any)
	for _, k := range []string{"id", "name", "products", "start", "end", "note", "rule", "light", "reason", "priority", "booked", "done", "planned", "donePoints", "plannedPoints", "months", "openScope", "open", "milestones", "state", "history"} {
		if _, ok := p[k]; !ok {
			t.Errorf("project: missing key %q", k)
		}
	}
	for _, k := range []string{"products", "milestones", "months"} {
		if p[k] == nil {
			t.Errorf("project.%s is null, want a list", k)
		}
	}
}

func TestSaveClearsTargetAndUndoChecksState(t *testing.T) {
	api, team := projectDir(t, true)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load(team)
	data.Projects[0].Target = model.Ptr(time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC))
	if _, err := repo.SaveProjects(team, data.Projects); err != nil {
		t.Fatal(err)
	}
	storage.ClearTeamCache()
	if _, err := api.SaveProject(team, ProjectInput{ID: "alpha", Name: "Alpha", Products: []string{"portal"}, End: "2027-02-01", Months: map[string]float64{}}); err != nil {
		t.Fatal(err)
	}
	storage.ClearTeamCache()
	data, _ = repo.Load(team)
	if got := data.Projects[0].Target; got == nil || got.Format(dateLayout) != "2027-02-01" {
		t.Fatalf("target = %v", got)
	}
	// Another change after the save: the first one can no longer be taken back on its own.
	if err := api.CloseProject(team, CloseInput{ID: "alpha", How: "finished", At: "2026-10-22"}); err != nil {
		t.Fatal(err)
	}
	data, _ = repo.Load(team)
	data.Projects[0].Name = "Changed elsewhere"
	if _, err := repo.SaveProjects(team, data.Projects); err != nil {
		t.Fatal(err)
	}
	storage.ClearTeamCache()
	if err := api.UndoProjects(team); err == nil {
		t.Fatal("undo should refuse after an outside change")
	}
}

func TestProjectHandValuesFromTheCore(t *testing.T) {
	api, team := projectDir(t, true)
	used, booked := 12.0, 20.0
	in := ProjectInput{
		ID: "alpha", Name: "Alpha", Products: []string{"portal"}, End: "2026-12-18", Contact: "Dana Example",
		Booked: &booked, Used: &used, Months: map[string]float64{"2026-10": 10}, UsedMonths: map[string]float64{"2026-10": 11},
		Milestones: []MilestoneInput{{Name: "Beta", Date: "2026-11-20", Light: "red"}},
	}
	if _, err := api.SaveProject(team, in); err != nil {
		t.Fatal(err)
	}
	d, err := api.Project(team, "alpha")
	if err != nil {
		t.Fatal(err)
	}
	p := d.Project
	if p.Contact != "Dana Example" || p.Used == nil || *p.Used != 12 || p.UsedStatus != "tight" && p.UsedStatus != "ok" && p.UsedStatus != "over" {
		t.Fatalf("project = %+v", p)
	}
	if len(p.Milestones) != 1 || p.Milestones[0].Light != "bad" || p.Milestones[0].Source != "hand" || p.Milestones[0].Hand != "red" {
		t.Fatalf("milestone = %+v", p.Milestones)
	}
	if len(p.Months) == 0 || p.Months[0].Used == nil || *p.Months[0].Used != 11 || p.Months[0].Status == "" {
		t.Fatalf("months = %+v", p.Months)
	}
	// Saving again without the hand values in the form must not touch what the form keeps.
	in.Used, in.UsedMonths = nil, map[string]float64{}
	in.Milestones[0].Light = ""
	if _, err := api.SaveProject(team, in); err != nil {
		t.Fatal(err)
	}
	d, _ = api.Project(team, "alpha")
	if d.Project.Used != nil || d.Project.Milestones[0].Hand != "" {
		t.Fatalf("project = %+v", d.Project)
	}
}
