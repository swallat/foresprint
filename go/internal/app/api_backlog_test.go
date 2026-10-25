package app

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
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

func TestBacklogDriftComparesFrozenListOfRunningSprint(t *testing.T) {
	now := time.Date(2026, 3, 10, 0, 0, 0, 0, time.UTC)
	in := func(id string) *string { return &id }
	data := &storage.TeamData{Team: model.NewTeam("t", "T")}
	data.Team.Tracker.Kind = "jira"
	data.Team.Features.Tickets = true
	data.Sprints = []model.Sprint{
		{ID: "S0", Start: now.AddDate(0, 0, -30), End: now.AddDate(0, 0, -20), CommittedTickets: []string{"X-9"}},
		{ID: "S1", Start: now.AddDate(0, 0, -5), End: now.AddDate(0, 0, 5), CommittedTickets: []string{"X-1", "X-2"}},
	}
	data.Tickets = []model.Ticket{
		{Key: "X-1", InSprint: in("S1")},
		{Key: "X-2"},
		{Key: "X-3", InSprint: in("S1")},
	}
	d := backlogDrift(data, now)
	if d == nil || d.Sprint != "S1" || len(d.PulledIn) != 1 || d.PulledIn[0] != "X-3" || len(d.Dropped) != 1 || d.Dropped[0] != "X-2" {
		t.Fatalf("drift %+v", d)
	}
	data.Sprints[1].CommittedTickets = nil
	if backlogDrift(data, now) != nil {
		t.Error("a sprint that is not frozen has no drift")
	}
	data.Sprints[1].CommittedTickets = []string{"X-1", "X-3", "X-2"}
	data.Tickets[1].InSprint = in("S1")
	if backlogDrift(data, now) != nil {
		t.Error("no difference, no drift")
	}
	// On the changeover day the finished sprint (exclusive end) is not the running one.
	data.Sprints = []model.Sprint{
		{ID: "S0", Start: now.AddDate(0, 0, -14), End: now, CommittedTickets: []string{"X-9"}},
		{ID: "S1", Start: now, End: now.AddDate(0, 0, 14), CommittedTickets: []string{"X-1"}},
	}
	data.Tickets = []model.Ticket{{Key: "X-1", InSprint: in("S1")}}
	if d := backlogDrift(data, now); d != nil {
		t.Errorf("S1 has no drift, got %+v", d)
	}
	data.Tickets = append(data.Tickets, model.Ticket{Key: "X-4", InSprint: in("S1")})
	if d := backlogDrift(data, now); d == nil || d.Sprint != "S1" {
		t.Errorf("the running sprint is S1, got %+v", d)
	}
}

func TestMoveToProFormaKeepsOnlyWhatDiffersFromTracker(t *testing.T) {
	api := packagesTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load("t")
	data.Team.Tracker.Kind = "jira"
	data.Team.Sprint.ProForma = []string{"Refinement"}
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	refinement, running := "Refinement", "2026.1"
	tf := storage.TicketsFile{Tickets: []model.Ticket{
		{Key: "X-1", Title: "Free", EstimateSource: model.EstimateNone},
		{Key: "X-2", Title: "In refinement", SprintName: &refinement, EstimateSource: model.EstimateNone},
		{Key: "X-3", Title: "In a sprint", InSprint: &running, EstimateSource: model.EstimateNone},
	}, Imported: func() *time.Time { n := time.Now(); return &n }()}
	if _, err := repo.SaveTickets("t", tf); err != nil {
		t.Fatal(err)
	}
	inPro := func(view *BacklogView) string {
		var keys []string
		for _, tk := range view.ProForma[0].Tickets {
			keys = append(keys, tk.Key)
		}
		return strings.Join(keys, ",")
	}
	if err := api.MoveToProForma("t", "X-1", "refinement"); err != nil {
		t.Fatal(err)
	}
	view, _ := api.Backlog("t")
	if inPro(view) != "X-1,X-2" || len(view.Adjust) != 1 || view.Adjust[0].Key != "X-1" || view.Adjust[0].To != "Refinement" || view.Adjust[0].From != "" {
		t.Fatalf("pro-forma %s adjust %+v", inPro(view), view.Adjust)
	}
	if err := api.MoveToProForma("t", "X-2", ""); err != nil {
		t.Fatal(err)
	}
	view, _ = api.Backlog("t")
	if inPro(view) != "X-1" || len(view.Adjust) != 2 || view.Adjust[1].From != "Refinement" || view.Adjust[1].To != "" {
		t.Fatalf("pro-forma %s adjust %+v", inPro(view), view.Adjust)
	}
	// Back to what the tracker says: nothing is left to adjust for the ticket.
	if err := api.MoveToProForma("t", "X-2", "Refinement"); err != nil {
		t.Fatal(err)
	}
	if err := api.MoveToProForma("t", "X-1", ""); err != nil {
		t.Fatal(err)
	}
	view, _ = api.Backlog("t")
	if len(view.Adjust) != 0 {
		t.Errorf("adjust %+v", view.Adjust)
	}
	// Earmarking a ticket the tracker has in Refinement takes it out of there (to be adjusted).
	if err := api.EarmarkTicket("t", "X-2", "2026.5", ""); err != nil {
		t.Fatal(err)
	}
	view, _ = api.Backlog("t")
	if len(view.ProForma[0].Tickets) != 0 || len(view.Adjust) != 1 || view.Adjust[0].Key != "X-2" || view.Adjust[0].To != "" {
		t.Errorf("pro-forma %s adjust %+v", inPro(view), view.Adjust)
	}
	if err := api.MoveToProForma("t", "X-3", "Refinement"); err == nil {
		t.Error("a ticket in a real sprint stays there")
	}
	if err := api.MoveToProForma("t", "X-1", "Nowhere"); err == nil {
		t.Error("an unknown pro-forma sprint should be refused")
	}
}

func TestStaleProFormaPlacementsDoNotCount(t *testing.T) {
	api := packagesTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load("t")
	data.Team.Tracker.Kind = "jira"
	data.Team.Sprint.ProForma = []string{"Refinement"}
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	refinement, running := "Refinement", "2026.1"
	save := func(tickets ...model.Ticket) {
		tf := storage.TicketsFile{Tickets: tickets, Imported: func() *time.Time { n := time.Now(); return &n }()}
		if _, err := repo.SaveTickets("t", tf); err != nil {
			t.Fatal(err)
		}
	}
	save(model.Ticket{Key: "X-1", Title: "Free", EstimateSource: model.EstimateNone})
	if err := api.MoveToProForma("t", "X-1", "Refinement"); err != nil {
		t.Fatal(err)
	}
	// The tracker now agrees: nothing is left to adjust.
	save(model.Ticket{Key: "X-1", Title: "Free", SprintName: &refinement, EstimateSource: model.EstimateNone})
	view, _ := api.Backlog("t")
	if len(view.Adjust) != 0 || len(view.ProForma[0].Tickets) != 1 {
		t.Errorf("adjust %+v", view.Adjust)
	}
	// The tracker put it into a real sprint: that wins over the placement.
	save(model.Ticket{Key: "X-1", Title: "Free", InSprint: &running, EstimateSource: model.EstimateNone})
	view, _ = api.Backlog("t")
	if len(view.Adjust) != 0 || len(view.ProForma[0].Tickets) != 0 {
		t.Errorf("adjust %+v pro-forma %+v", view.Adjust, view.ProForma)
	}
}

func TestMoveTrackerTicketKeepsOwnOrderBesideTrackerRank(t *testing.T) {
	api := packagesTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load("t")
	data.Team.Tracker.Kind = "jira"
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	r1, r2, r3 := "0|a", "0|b", "0|c"
	tf := storage.TicketsFile{Tickets: []model.Ticket{
		{Key: "X-1", Title: "One", Rank: &r1, EstimateSource: model.EstimateNone},
		{Key: "X-2", Title: "Two", Rank: &r2, EstimateSource: model.EstimateNone},
		{Key: "X-3", Title: "Three", Rank: &r3, EstimateSource: model.EstimateNone},
	}, Imported: func() *time.Time { n := time.Now(); return &n }()}
	if _, err := repo.SaveTickets("t", tf); err != nil {
		t.Fatal(err)
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
	if got := keys(); got != "X-1,X-2,X-3" {
		t.Fatalf("order %s", got)
	}
	if err := api.MoveWorkPackage("t", "X-3", "X-1", false); err != nil {
		t.Fatal(err)
	}
	if got := keys(); got != "X-3,X-1,X-2" {
		t.Fatalf("order %s", got)
	}
	// The tracker's rank is untouched; a new ticket from a later fetch comes after the own order.
	after, _ := repo.Load("t")
	if after.TicketByKey("X-3").Rank == nil || *after.TicketByKey("X-3").Rank != "0|c" {
		t.Errorf("tracker rank changed: %+v", after.TicketByKey("X-3").Rank)
	}
}

func TestBacklogShowsEveryComingSprint(t *testing.T) {
	api := packagesTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load("t")
	data.Team.Tracker.Kind = "jira"
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	far := "2027.2" // well beyond the recorded sprints and the forecast horizon
	tf := storage.TicketsFile{Tickets: []model.Ticket{
		{Key: "X-1", Title: "Far ahead", InSprint: &far, EstimateSource: model.EstimateNone},
	}, Imported: func() *time.Time { n := time.Now(); return &n }()}
	if _, err := repo.SaveTickets("t", tf); err != nil {
		t.Fatal(err)
	}
	view, err := api.Backlog("t")
	if err != nil {
		t.Fatal(err)
	}
	upcoming := 0
	for _, s := range data.Sprints {
		if s.Start.After(today()) {
			upcoming++
		}
	}
	if len(view.Lanes) < upcoming || len(view.Lanes) <= 3 {
		t.Errorf("%d lanes for %d recorded coming sprints: all of them show, not only three", len(view.Lanes), upcoming)
	}
	found := false
	for _, l := range view.Lanes {
		for _, tk := range l.Tickets {
			found = found || tk.Key == "X-1"
		}
	}
	if !found {
		t.Errorf("X-1 is in sprint %s in the tracker and must show in its lane", far)
	}
	for _, tk := range view.Tickets {
		if tk.Key == "X-1" {
			t.Error("X-1 must not be in the plain backlog")
		}
	}
	// A lane beyond the horizon takes earmarks like any other.
	other := "2027.3"
	tf.Tickets = append(tf.Tickets, model.Ticket{Key: "X-2", Title: "Free", EstimateSource: model.EstimateNone})
	if _, err := repo.SaveTickets("t", tf); err != nil {
		t.Fatal(err)
	}
	if err := api.EarmarkTicket("t", "X-2", other, ""); err != nil {
		t.Errorf("earmark into a sprint beyond the horizon: %v", err)
	}
}

func TestRankPositionAndMoveByRankIgnorePriority(t *testing.T) {
	api := packagesTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load("t")
	data.Team.Tracker.Kind = "jira"
	data.Team.Tracker.PriorityOrder = []string{"High", "Low"}
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	r1, r2, r3 := "0|a", "0|b", "0|c"
	low, high := "Low", "High"
	tf := storage.TicketsFile{Tickets: []model.Ticket{
		{Key: "X-1", Title: "One", Rank: &r1, Priority: &low, EstimateSource: model.EstimateNone},
		{Key: "X-2", Title: "Two", Rank: &r2, Priority: &high, EstimateSource: model.EstimateNone},
		{Key: "X-3", Title: "Three", Rank: &r3, Priority: &high, EstimateSource: model.EstimateNone},
	}, Imported: func() *time.Time { n := time.Now(); return &n }()}
	if _, err := repo.SaveTickets("t", tf); err != nil {
		t.Fatal(err)
	}
	pos := func() string {
		view, err := api.Backlog("t")
		if err != nil {
			t.Fatal(err)
		}
		m := map[string]int{}
		for _, tk := range view.Tickets {
			m[tk.Key] = tk.RankPos
		}
		return fmt.Sprintf("%d%d%d", m["X-1"], m["X-2"], m["X-3"])
	}
	if got := pos(); got != "123" {
		t.Fatalf("rank positions %s: the tracker's rank counts, not the priority", got)
	}
	// X-3 is High, X-1 Low: the planning order refuses this move, the rank order does it.
	if err := api.MoveTicketByRank("t", "X-3", "X-1", false); err != nil {
		t.Fatal(err)
	}
	if got := pos(); got != "231" {
		t.Errorf("rank positions %s, want X-3 first", got)
	}
	if err := api.MoveTicketByRank("t", "X-3", "", false); err != nil {
		t.Fatal(err)
	}
	if got := pos(); got != "123" {
		t.Errorf("rank positions %s, want X-3 last again", got)
	}
}

func TestBacklogShowsEmptyBoardSprints(t *testing.T) {
	api := packagesTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load("t")
	data.Team.Tracker.Kind = "jira"
	board := 7
	data.Team.Tracker.BoardID = &board
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	tf := storage.TicketsFile{Tickets: []model.Ticket{
		{Key: "X-1", Title: "Free", EstimateSource: model.EstimateNone},
	}, Imported: func() *time.Time { n := time.Now(); return &n }()}
	if _, err := repo.SaveTickets("t", tf); err != nil {
		t.Fatal(err)
	}
	api.run.board = map[string][]sources.SprintValue{"t": {
		{ID: "11", Name: "Team Sprint 2027.4", State: "FUTURE"},
		{ID: "12", Name: "Some Release Train", State: "FUTURE"},
		{ID: "13", Name: "Team Sprint 2026.1", State: "CLOSED"},
	}}
	view, err := api.Backlog("t")
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, l := range view.Lanes {
		found = found || l.Sprint == "2027.4"
	}
	if !found {
		t.Errorf("the empty board sprint 2027.4 must be a lane, lanes: %+v", view.Lanes)
	}
	if len(view.UnmatchedSprints) != 1 || view.UnmatchedSprints[0] != "Some Release Train" {
		t.Errorf("unmatched %v: only the open sprint without a match counts", view.UnmatchedSprints)
	}
	if err := api.EarmarkTicket("t", "X-1", "2027.4", ""); err != nil {
		t.Errorf("a ticket can be earmarked into the empty board sprint: %v", err)
	}
}
