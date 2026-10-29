package validate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func ptr[T any](v T) *T { return &v }

func d(s string) time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return t
}

// ticketTeam loads the golden team with tickets and products.
func ticketTeam(t *testing.T) *storage.TeamData {
	t.Helper()
	root := filepath.Join(golden.RepoRoot(t), "golden", "inputs", "tickets-products")
	data, err := storage.NewRepository(root).Load("tickets-products")
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func messages(issues []Issue) string {
	var b strings.Builder
	for _, i := range issues {
		b.WriteString(string(i.Level) + " " + i.Where + ": " + i.Message + "\n")
	}
	return b.String()
}

func TestCheckV1(t *testing.T) {
	i18n.SetLanguage("en")
	t.Cleanup(func() { i18n.SetLanguage("") })
	today := d("2026-07-08")
	base := messages(CheckTeam(ticketTeam(t), today))
	tests := []struct {
		name   string
		change func(*storage.TeamData)
		want   []string
	}{
		{"closed without end", func(x *storage.TeamData) { x.Projects[0].State = model.ProjectFinished },
			[]string{"closed project without an end date", "open tickets still belong to the closed project"}},
		{"milestone", func(x *storage.TeamData) {
			x.Projects[0].Start = ptr(d("2026-06-01"))
			x.Projects[0].End = ptr(d("2026-09-01"))
			x.Projects[0].Milestones = []model.Milestone{
				{ID: "m1", Date: d("2026-10-01"), Tickets: []string{"NOPE-1"}}, {ID: "m1", Date: d("2026-07-01")}}
		}, []string{"milestone id is duplicated", "lies outside the project period", "unknown ticket 'NOPE-1'"}},
		{"contingent", func(x *storage.TeamData) {
			x.Projects[0].Contingent.Total = ptr(10.0)
			x.Projects[0].Contingent.PerMonth.Set("2026-07", 8)
			x.Projects[0].Contingent.PerMonth.Set("2026-08", 8)
			x.Projects[0].Contingent.PerMonth.Set("July", 1)
		}, []string{"exceed the total", "'July' is not a month"}},
		{"several products", func(x *storage.TeamData) { x.Projects[0].AlsoProducts = []string{"nowhere"} },
			[]string{"unknown product 'nowhere'"}},
		{"overrides", func(x *storage.TeamData) {
			x.Preplan.Overrides = []model.TicketOverride{
				{Ticket: "W-1", Product: ptr("nowhere")}, {Ticket: "W-1", Project: ptr("pay"), Daily: true},
				{Ticket: "X-9", Project: ptr("zzz")}}
		}, []string{"unknown product 'nowhere'", "several decisions", "exclude each other", "unknown project 'zzz'", "unknown ticket"}},
		{"production", func(x *storage.TeamData) {
			x.Team.Features.Production = false
			x.Preplan.Production = []model.ProductionShare{{Ticket: "W-1", Percent: 50}, {Ticket: "W-1", Percent: 120}}
		}, []string{"several production shares", "'share' must be between 0 and 100", "production feature is off"}},
		{"nobody with access", func(x *storage.TeamData) {
			x.Team.Features.Production = true
			x.Preplan.Production = []model.ProductionShare{{Ticket: "W-1", Percent: 50}}
		}, []string{"nobody has production access"}},
		{"carry", func(x *storage.TeamData) {
			x.Sprints[len(x.Sprints)-1].Carry = []model.CarryItem{
				{Ticket: ptr("NOPE-2"), Rest: -1, Target: "2099.9"}, {Ticket: ptr("W-1"), Rest: 2, Target: "proforma:Nope"}}
			x.Sprints[len(x.Sprints)-1].RestNext = ptr(-3.0)
		}, []string{"rest_next must not be negative", "unknown ticket", "rest must not be negative", "not a known sprint", "not a pro-forma sprint"}},
		{"absence periods", func(x *storage.TeamData) {
			x.People = []model.Person{{ID: "anna"}}
			x.AbsencePeriods.Set("ghost", []model.AbsencePeriod{{From: d("2026-08-01"), To: d("2026-08-10")}, {From: d("2026-08-05"), To: d("2026-08-12")}})
		}, []string{"unknown person 'ghost'", "overlap"}},
		{"removed target", func(x *storage.TeamData) { x.Team.Tracker.RemovedTarget = "elsewhere" },
			[]string{"tracker.removed_target must be one of"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			data := ticketTeam(t)
			tc.change(data)
			got := messages(CheckTeam(data, today))
			for _, want := range tc.want {
				if !strings.Contains(got, want) {
					t.Errorf("missing %q in\n%s", want, got)
				}
			}
		})
	}
	if strings.Contains(base, "closed project") {
		t.Errorf("the unchanged team reports closed projects:\n%s", base)
	}
}

func TestProjectsWithoutTickets(t *testing.T) {
	i18n.SetLanguage("en")
	t.Cleanup(func() { i18n.SetLanguage("") })
	data := ticketTeam(t)
	data.Team.Features.Tickets = false
	data.Team.Features.Projects = true
	data.Tickets = nil
	data.Projects[0].Contingent.Total = ptr(-1.0)
	got := messages(CheckTeam(data, d("2026-07-08")))
	if !strings.Contains(got, "contingent.total must not be negative") {
		t.Errorf("a project without tickets is not checked:\n%s", got)
	}
	if strings.Contains(got, "neither a match rule") {
		t.Errorf("rules are checked although there is no tracker:\n%s", got)
	}
}

func TestCheckFilesProjects(t *testing.T) {
	root := t.TempDir()
	if err := writeFile(filepath.Join(root, "projects.yaml"), "projects:\n- id: a\n  id: b\n"); err != nil {
		t.Fatal(err)
	}
	if got := CheckFiles(root, model.Features{}); len(got) != 0 {
		t.Errorf("projects.yaml is not read without the feature: %v", got)
	}
	if got := CheckFiles(root, model.Features{Projects: true}); len(got) == 0 {
		t.Error("projects.yaml is not checked with features.projects")
	}
}

func writeFile(path, text string) error { return os.WriteFile(path, []byte(text), 0o644) }

// Tickets with projects switched off: projects.yaml is not read, so the project ids that
// tickets and decisions still carry are not reported as unknown.
func TestTicketsWithoutProjectsDoNotReportUnknownProjects(t *testing.T) {
	i18n.SetLanguage("en")
	t.Cleanup(func() { i18n.SetLanguage("") })
	data := ticketTeam(t)
	data.Team.Features.Projects = false
	data.Projects = nil
	got := messages(CheckTeam(data, d("2026-07-08")))
	if strings.Contains(got, "unknown project") {
		t.Errorf("unknown project reported although projects are off:\n%s", got)
	}
}
