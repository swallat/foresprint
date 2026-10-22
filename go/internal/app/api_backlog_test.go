package app

import (
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// packagesTeam writes a team with work packages, two products, one project and sprints around
// today, and returns the API on it.
func packagesTeam(t *testing.T) *API {
	t.Helper()
	dir := t.TempDir()
	repo := storage.NewRepository(dir)
	team := model.NewTeam("t", "Team T")
	team.Features = model.Features{Explicit: true, Tickets: true, Products: true, Projects: true}
	team.Tracker.Kind = model.PackagesKind
	if _, err := repo.SaveTeam(team); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.SaveProducts("t", []model.Product{{ID: "web", Name: "Web"}, {ID: "app", Name: "App"}}); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.SaveProjects("t", []model.Project{{ID: "p1", Name: "Relaunch"}}); err != nil {
		t.Fatal(err)
	}
	start := today().AddDate(0, 0, -20)
	for i := 0; i < 6; i++ {
		s := model.Sprint{ID: "2026." + string(rune('1'+i)), Start: start.AddDate(0, 0, 14*i), End: start.AddDate(0, 0, 14*i+11)}
		if _, err := repo.SaveSprint("t", &s); err != nil {
			t.Fatal(err)
		}
	}
	return newAPI(t, dir)
}

func TestWorkPackageLifecycle(t *testing.T) {
	api := packagesTeam(t)
	est := 5.0
	key, err := api.SaveWorkPackage("t", WorkPackageInput{Title: "First", Product: "web", Estimate: &est, Refined: true})
	if err != nil || key != "AP-1" {
		t.Fatalf("key %q err %v", key, err)
	}
	second, err := api.SaveWorkPackage("t", WorkPackageInput{Title: "Second", Product: "app", Project: "p1", DependsOn: []string{key}})
	if err != nil || second != "AP-2" {
		t.Fatalf("key %q err %v", second, err)
	}
	view, err := api.Backlog("t")
	if err != nil {
		t.Fatal(err)
	}
	if view.Source != "packages" || len(view.Tickets) != 2 {
		t.Fatalf("view %+v", view)
	}
	for _, tk := range view.Tickets {
		if tk.Key == "AP-1" && (!tk.Refined || tk.SizeSource != "refined") {
			t.Errorf("AP-1 should be refined: %+v", tk)
		}
	}
	third, _ := api.SaveWorkPackage("t", WorkPackageInput{Title: "Third", Product: "web"})
	fourth, _ := api.SaveWorkPackage("t", WorkPackageInput{Title: "Fourth", Product: "web"})
	view, _ = api.Backlog("t")
	var order []string
	for _, tk := range view.Tickets {
		order = append(order, tk.Key)
	}
	pos := map[string]int{}
	for i, k := range order {
		pos[k] = i
	}
	if pos[fourth] > pos[third] || pos[third] > pos[key] {
		t.Errorf("a new work package goes first among its equals: %v", order)
	}
	_ = api.DeleteWorkPackage("t", third)
	_ = api.DeleteWorkPackage("t", fourth)
	if len(view.Lanes) == 0 {
		t.Fatal("no lanes")
	}

	lane := view.Lanes[0].Sprint
	if err := api.EarmarkTicket("t", second, lane, ""); err != nil {
		t.Fatal(err)
	}
	view, _ = api.Backlog("t")
	if len(view.Lanes[0].Tickets) != 1 || view.Lanes[0].Tickets[0].Key != second || !view.Lanes[0].Tickets[0].Blocked {
		t.Errorf("lane %+v (AP-2 depends on AP-1, which is not planned: blocked)", view.Lanes[0].Tickets)
	}
	if err := api.EarmarkTicket("t", key, lane, "agreed"); err != nil {
		t.Fatal(err)
	}
	view, _ = api.Backlog("t")
	for _, tk := range view.Lanes[0].Tickets {
		if tk.Blocked && tk.Key == second {
			// gap 1: the dependency in the same sprint still blocks
			continue
		}
	}
	d, err := api.Ticket("t", key)
	if err != nil || d.Note != "agreed" || !d.Editable {
		t.Fatalf("detail %+v err %v", d, err)
	}
	if err := api.SetEarmarkNote("t", key, ""); err != nil {
		t.Fatal(err)
	}
	if d, _ = api.Ticket("t", key); d.Note != "" || d.EarmarkNote != "" || d.Earmark != lane {
		t.Errorf("clearing the note keeps the earmark: %+v", d.BacklogTicket)
	}
	if err := api.EarmarkTicket("t", key, "", ""); err != nil {
		t.Fatal(err)
	}
	if err := api.EarmarkTicket("t", key, "2026.1", ""); err == nil {
		t.Error("earmark for a past sprint should fail")
	}

	if err := api.SetEstimate("t", second, &est); err != nil {
		t.Fatal(err)
	}
	if err := api.SetRefined("t", second, true); err != nil {
		t.Fatal(err)
	}
	if err := api.SetAssignment("t", second, "web", "", false); err != nil {
		t.Fatal(err)
	}
	pct := 40.0
	if err := api.SetProduction("t", second, &pct); err != nil {
		t.Fatal(err)
	}
	if d, _ = api.Ticket("t", second); d.Product != "web" || d.Project != "" || d.Production == nil || !d.Refined {
		t.Errorf("detail after edits %+v", d.BacklogTicket)
	}
	bad := 120.0
	if err := api.SetProduction("t", second, &bad); err == nil {
		t.Error("production share over 100 should fail")
	}

	if err := api.DeleteWorkPackage("t", key); err != nil {
		t.Fatal(err)
	}
	if d, _ = api.Ticket("t", second); len(d.DependsOn) != 0 {
		t.Errorf("dependency on a deleted package should go: %v", d.DependsOn)
	}
	if _, err := api.Ticket("t", key); err == nil || !strings.Contains(err.Error(), key) {
		t.Errorf("deleted ticket still found: %v", err)
	}
	if _, err := api.SaveWorkPackage("t", WorkPackageInput{Title: " "}); err == nil {
		t.Error("a title is needed")
	}
}

func TestTrackerTicketsAreReadOnlyWithRuleHints(t *testing.T) {
	api := packagesTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load("t")
	data.Team.Tracker.Kind = "jira"
	base := "https://jira.example.com/"
	data.Team.Tracker.BaseURL = &base
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	prog, est := "In progress", 3.0
	tf := storage.TicketsFile{Tickets: []model.Ticket{
		{Key: "X-1", Title: "Has estimate", Estimate: &est, EstimateSource: model.EstimateRough, Status: &prog},
		{Key: "X-2", Title: "No estimate", EstimateSource: model.EstimateNone},
	}, Imported: func() *time.Time { n := time.Now(); return &n }()}
	if _, err := repo.SaveTickets("t", tf); err != nil {
		t.Fatal(err)
	}
	if err := api.SetEstimate("t", "X-1", &est); err == nil {
		t.Error("the tracker's estimate is read only")
	}
	if err := api.SetEstimate("t", "X-2", &est); err != nil {
		t.Fatal(err)
	}
	if err := api.SetRefined("t", "X-1", true); err == nil {
		t.Error("refined is set in the tracker")
	}
	if err := api.SetAssignment("t", "X-1", "web", "", false); err != nil {
		t.Fatal(err)
	}
	view, err := api.Backlog("t")
	if err != nil {
		t.Fatal(err)
	}
	if view.Tracker != "Jira" || len(view.Tickets) != 2 {
		t.Fatalf("view %+v", view)
	}
	for _, tk := range view.Tickets {
		switch tk.Key {
		case "X-1":
			if tk.Product != "web" || !tk.ProductSet || tk.RuleHint != "" || tk.URL != "https://jira.example.com/browse/X-1" {
				t.Errorf("X-1 %+v", tk)
			}
		case "X-2":
			if tk.SizeSource != "manual" || tk.RuleHint != "none" {
				t.Errorf("X-2 %+v", tk)
			}
		}
	}
	d, _ := api.Ticket("t", "X-1")
	if d.Editable {
		t.Error("a tracker ticket is not editable")
	}
}

func TestNoTicketsTeamHasEmptyBacklog(t *testing.T) {
	api := newAPI(t, demoDir(t))
	teams := api.Teams()
	view, err := api.Backlog(teams[0].Key)
	if err != nil {
		t.Fatal(err)
	}
	if view.Source != "none" || len(view.Tickets) != 0 {
		t.Errorf("%+v", view)
	}
}

func TestMoveWorkPackage(t *testing.T) {
	api := packagesTeam(t)
	for _, title := range []string{"A", "B", "C"} {
		if _, err := api.SaveWorkPackage("t", WorkPackageInput{Title: title, Product: "web"}); err != nil {
			t.Fatal(err)
		}
	}
	keys := func() string {
		view, err := api.Backlog("t")
		if err != nil {
			t.Fatal(err)
		}
		var out []string
		for _, tk := range view.Tickets {
			out = append(out, tk.Key)
		}
		return strings.Join(out, ",")
	}
	if err := api.MoveWorkPackage("t", "AP-3", "AP-1", false); err != nil {
		t.Fatal(err)
	}
	if got := keys(); got != "AP-2,AP-3,AP-1" {
		t.Fatalf("order %s", got)
	}
	if err := api.MoveWorkPackage("t", "AP-3", "", false); err != nil {
		t.Fatal(err)
	}
	if got := keys(); got != "AP-2,AP-1,AP-3" {
		t.Fatalf("order %s", got)
	}
	if err := api.MoveWorkPackage("t", "AP-1", "AP-9", false); err == nil {
		t.Error("an unknown neighbour should be refused")
	}
	if err := api.MoveWorkPackage("t", "AP-2", "AP-1", true); err != nil {
		t.Fatal(err)
	}
	if got := keys(); got != "AP-1,AP-2,AP-3" {
		t.Fatalf("order %s", got)
	}
}
