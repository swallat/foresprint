package app

import (
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// planTeam copies the demo team into a temp folder, switches the tickets on and adds a few
// tickets. today is fixed so that the running and the next sprint are known.
func planTeam(t *testing.T) (*API, string) {
	t.Helper()
	src := filepath.Join(demoDir(t), "demo")
	dst := filepath.Join(t.TempDir(), "teams")
	if err := os.CopyFS(filepath.Join(dst, "demo"), os.DirFS(src)); err != nil {
		t.Fatal(err)
	}
	old := now
	now = func() time.Time { return time.Date(2026, 10, 14, 9, 0, 0, 0, time.UTC) }
	t.Cleanup(func() { now = old })
	api := newAPI(t, dst)
	repo := storage.NewRepository(dst)
	data, err := repo.Load("demo")
	if err != nil {
		t.Fatal(err)
	}
	team := data.Team
	team.Features.Tickets = true
	team.Tracker.Kind = "csv"
	if _, err := repo.SaveTeam(team); err != nil {
		t.Fatal(err)
	}
	f := func(v float64) *float64 { return &v }
	s := func(v string) *string { return &v }
	tickets := []model.Ticket{
		{Key: "T-1", Title: "One", Estimate: f(5), EstimateSource: model.EstimateRefined, Product: s("portal")},
		{Key: "T-2", Title: "Two", Estimate: f(8), EstimateSource: model.EstimateRefined, Labels: []string{"ops"}},
		{Key: "T-3", Title: "Three", EstimateSource: model.EstimateNone},
	}
	if _, err := repo.SaveTickets("demo", storage.TicketsFile{Tickets: tickets}); err != nil {
		t.Fatal(err)
	}
	return api, "demo"
}

func TestPlanSprintHasTheFigures(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	v, err := api.PlanSprint(team, next, nil)
	if err != nil {
		t.Fatal(err)
	}
	if v.Source != "tracker" || v.Plan == nil || v.Capacity == nil || v.Split == nil {
		t.Fatalf("view = %+v", v)
	}
	if v.Stage != "open" {
		t.Errorf("stage = %s", v.Stage)
	}
	if len(v.Products) == 0 || !v.MultiProduct {
		t.Errorf("products = %+v", v.Products)
	}
	if len(v.Candidates) != 3 {
		t.Errorf("candidates = %d", len(v.Candidates))
	}
	if math.Abs(v.Split.Plannable+v.Split.SmallStuff-(v.Split.Plan-v.Split.CarryIn)) > 1e-9 {
		t.Errorf("split does not add up: %+v", v.Split)
	}
}

func TestEarmarkAndPreplanned(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	if err := api.EarmarkTicket(team, "T-1", next, ""); err != nil {
		t.Fatal(err)
	}
	if err := api.EarmarkTicket(team, "T-2", next, ""); err != nil {
		t.Fatal(err)
	}
	v, _ := api.PlanSprint(team, next, nil)
	if len(v.Tickets) != 2 || v.Earmarked != 13 {
		t.Fatalf("tickets = %d, earmarked = %v", len(v.Tickets), v.Earmarked)
	}
	if err := api.TakeEarmarks(team, next); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if v.Preplanned == 0 {
		t.Errorf("take earmarks left nothing pre-planned: %+v", v.Products)
	}
	one := 7.0
	if err := api.SetPreplanned(team, next, v.Products[0].ID, &one); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if v.Products[0].Pre == nil || *v.Products[0].Pre != 7 {
		t.Errorf("pre = %v", v.Products[0].Pre)
	}
	if err := api.SetPreplanned(team, next, "nope", &one); err == nil {
		t.Error("unknown product accepted")
	}
	neg := -1.0
	if err := api.SetPreplanned(team, next, v.Products[0].ID, &neg); err == nil {
		t.Error("negative amount accepted")
	}
	if err := api.EarmarkTicket(team, "T-1", "", ""); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if len(v.Tickets) != 1 {
		t.Errorf("earmark not removed: %d", len(v.Tickets))
	}
}

func TestProductionShareSources(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	_ = api.EarmarkTicket(team, "T-1", next, "")
	half := 50.0
	if err := api.SetProductionPercent(team, "T-1", &half); err != nil {
		t.Fatal(err)
	}
	v, _ := api.PlanSprint(team, next, nil)
	if v.Prod == nil {
		t.Fatal("no production card")
	}
	if v.Tickets[0].ProdPct != 50 || v.Tickets[0].ProdSource != "manual" {
		t.Errorf("ticket = %+v", v.Tickets[0])
	}
	if !v.Prod.DemandSet || v.Prod.Demand <= 0 {
		t.Errorf("prod = %+v", v.Prod)
	}
	if err := api.SetProductionPercent(team, "T-1", nil); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if v.Tickets[0].ProdSource != "none" {
		t.Errorf("source = %s", v.Tickets[0].ProdSource)
	}
}

func TestWhatIfLowersWhatIsPlannable(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var cur, next string
	for i, s := range sprints {
		if s.State == "current" {
			cur, next = s.ID, sprints[i+1].ID
		}
	}
	if cur == "" {
		t.Skip("no running sprint in the demo data")
	}
	// put two tickets into the running sprint through the tracker field
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load(team)
	for i := range data.Tickets[:2] {
		data.Tickets[i].InSprint = &cur
	}
	if _, err := repo.SaveTickets(team, storage.TicketsFile{Tickets: data.Tickets}); err != nil {
		t.Fatal(err)
	}
	base, err := api.PlanSprint(team, next, nil)
	if err != nil || base.Running != cur {
		t.Fatalf("running = %q err = %v", base.Running, err)
	}
	as := Assumption{Label: "A", Carry: []CarryInput{{Ticket: "T-2", Rest: 3}}}
	v, err := api.PlanSprint(team, next, &as)
	if err != nil {
		t.Fatal(err)
	}
	if v.Split.CarryIn != 3 || v.Split.Plannable > base.Split.Plannable {
		t.Errorf("carry-over did not lower the plannable amount: %+v vs %+v", v.Split, base.Split)
	}
	w, err := api.WhatIf(team, next, as)
	if err != nil || w == nil || !w.Touched || w.NotDone != 8 || w.Rest != 3 {
		t.Fatalf("what-if = %+v err = %v", w, err)
	}
	if err := api.SaveAssumption(team, next, as); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if len(v.Assumptions) != 1 || v.Assumptions[0].Label != "A" || v.Split.CarryIn != 3 {
		t.Errorf("saved assumption not used: %+v %+v", v.Assumptions, v.Split)
	}
}

func TestFreezeAndReopen(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	_ = api.EarmarkTicket(team, "T-1", next, "")
	_ = api.EarmarkTicket(team, "T-2", next, "")
	name, err := api.FreezePlan(team, next, FreezeInput{Tickets: []string{"T-1", "T-2"}, Removed: []string{"T-3"}})
	if err != nil || name == "" {
		t.Fatalf("freeze: %q %v", name, err)
	}
	v, _ := api.PlanSprint(team, next, nil)
	if v.Stage != "planned" || v.Frozen == nil || v.Frozen.Tickets != 2 || v.Committed == nil || *v.Committed != 13 {
		t.Fatalf("view after freeze = %+v %+v", v.Stage, v.Frozen)
	}
	planned := 0.0
	for _, p := range v.Products {
		if p.Planned != nil {
			planned += *p.Planned
		}
	}
	if math.Abs(planned-13) > 1e-3 { // T-2 has no product: its size is split over the products
		t.Errorf("planned per product = %v", planned)
	}
	if err := api.ReopenPlan(team, next); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if v.Stage != "open" || v.Frozen != nil {
		t.Errorf("not reopened: %s", v.Stage)
	}
	if _, err := api.FreezePlan(team, sprints[0].ID, FreezeInput{}); err == nil {
		t.Error("a past sprint was frozen")
	}
}

func TestRemovedTicketsLeaveTheLaneAndStayListed(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	_ = api.EarmarkTicket(team, "T-1", next, "")
	_ = api.EarmarkTicket(team, "T-2", next, "")
	if err := api.SetRemoved(team, next, "T-1", true); err != nil {
		t.Fatal(err)
	}
	v, _ := api.PlanSprint(team, next, nil)
	if len(v.Tickets) != 1 || v.Tickets[0].Key != "T-2" {
		t.Errorf("lane = %+v", v.Tickets)
	}
	if len(v.Removed) != 1 || v.Removed[0] != "T-1" {
		t.Errorf("removed = %v", v.Removed)
	}
	found := false
	for _, c := range v.Candidates {
		found = found || c.Key == "T-1"
	}
	if !found {
		t.Error("removed ticket is not a candidate")
	}
	if err := api.SetRemoved(team, next, "T-1", false); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if len(v.Tickets) != 2 || len(v.Removed) != 0 {
		t.Errorf("after undo: lane %d, removed %v", len(v.Tickets), v.Removed)
	}
	if err := api.SetRemoved(team, next, "nope", true); err == nil {
		t.Error("unknown ticket accepted")
	}
}

func TestSprintPreplannedForTeamsWithoutProducts(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	if err := api.SetSprintPreplanned(team, next, nil); err != nil {
		t.Fatal(err)
	}
	neg := -2.0
	if err := api.SetSprintPreplanned(team, next, &neg); err == nil {
		t.Error("negative amount accepted")
	}
	// the demo team has products, so the sprint amount is stored but the view sums the products
	v, _ := api.PlanSprint(team, next, nil)
	if v.SprintPre != nil {
		t.Errorf("sprintPre = %v", v.SprintPre)
	}
}

func TestProductionCapLowersWhatIsAvailable(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load(team)
	tm := data.Team
	tm.Features.Production = true
	if _, err := repo.SaveTeam(tm); err != nil {
		t.Fatal(err)
	}
	people := data.People
	people[0].ProductionAccess = true
	if _, err := repo.SavePeople(team, people); err != nil {
		t.Fatal(err)
	}
	before, err := api.PlanSprint(team, next, nil)
	if err != nil || before.Prod == nil || before.Prod.Time <= 0 {
		t.Fatalf("no production time to compare with: %+v %v", before.Prod, err)
	}
	half := 50.0
	tm.Features.ProductionMax = &half
	if _, err := repo.SaveTeam(tm); err != nil {
		t.Fatal(err)
	}
	after, err := api.PlanSprint(team, next, nil)
	if err != nil {
		t.Fatal(err)
	}
	if after.Prod.CapPercent != 50 || math.Abs(after.Prod.Available-before.Prod.Time/2) > 1e-9 {
		t.Errorf("cap %v, available %v of %v", after.Prod.CapPercent, after.Prod.Available, before.Prod.Time)
	}
}

func TestMatrixCellsAndUseMatrix(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	repo := storage.NewRepository(api.DataDir())
	if _, err := repo.SaveProjects(team, []model.Project{{ID: "alpha", Name: "Alpha"}}); err != nil {
		t.Fatal(err)
	}
	v, err := api.PlanSprint(team, next, nil)
	if err != nil {
		t.Fatal(err)
	}
	if v.Matrix == nil || len(v.Matrix.Projects) == 0 {
		t.Fatalf("no matrix: %+v", v.Matrix)
	}
	product, project := v.Products[0].ID, v.Matrix.Projects[0].ID
	f := func(x float64) *float64 { return &x }
	if err := api.SetMatrixCell(team, next, product, project, f(7)); err != nil {
		t.Fatal(err)
	}
	if err := api.SetMatrixCell(team, next, product, "nope", f(1)); err == nil {
		t.Error("an unknown project was accepted")
	}
	if err := api.SetMatrixCell(team, next, product, project, f(-1)); err == nil {
		t.Error("a negative amount was accepted")
	}
	v, _ = api.PlanSprint(team, next, nil)
	if len(v.Matrix.Cells) != 1 || v.Matrix.Cells[0].Value != 7 {
		t.Fatalf("cells = %+v", v.Matrix.Cells)
	}
	if err := api.UseMatrix(team, next); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if v.Products[0].Pre == nil || *v.Products[0].Pre < 7 {
		t.Errorf("product amount = %v", v.Products[0].Pre)
	}
	if err := api.SetMatrixCell(team, next, product, project, nil); err != nil {
		t.Fatal(err)
	}
	if v, _ = api.PlanSprint(team, next, nil); len(v.Matrix.Cells) != 0 {
		t.Errorf("cell not cleared: %+v", v.Matrix.Cells)
	}
}

func TestUseMatrixNeverLowersAndSkipsClosedProjects(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	repo := storage.NewRepository(api.DataDir())
	projects := []model.Project{{ID: "alpha", Name: "Alpha"}, {ID: "beta", Name: "Beta"}}
	if _, err := repo.SaveProjects(team, projects); err != nil {
		t.Fatal(err)
	}
	v, _ := api.PlanSprint(team, next, nil)
	product := v.Products[0].ID
	budget := v.Products[0].Budget
	f := func(x float64) *float64 { return &x }
	// A row smaller than the standard amount leaves the product as it is.
	if err := api.SetMatrixCell(team, next, product, "alpha", f(1)); err != nil {
		t.Fatal(err)
	}
	if err := api.UseMatrix(team, next); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if v.Products[0].Budget != budget {
		t.Errorf("budget %v -> %v", budget, v.Products[0].Budget)
	}
	// A project that was closed afterwards no longer counts, and its cell can still be cleared.
	if err := api.SetMatrixCell(team, next, product, "beta", f(budget+50)); err != nil {
		t.Fatal(err)
	}
	projects[1].State = model.ProjectFinished
	if _, err := repo.SaveProjects(team, projects); err != nil {
		t.Fatal(err)
	}
	if err := api.UseMatrix(team, next); err != nil {
		t.Fatal(err)
	}
	v, _ = api.PlanSprint(team, next, nil)
	if v.Products[0].Budget != budget {
		t.Errorf("a closed project raised the budget to %v", v.Products[0].Budget)
	}
	if err := api.SetMatrixCell(team, next, product, "beta", f(3)); err == nil {
		t.Error("a closed project took an amount")
	}
	if err := api.SetMatrixCell(team, next, product, "beta", nil); err != nil {
		t.Errorf("clearing a closed project's cell: %v", err)
	}
}

func TestWhatIfIgnoresTypedCommitmentWithTickets(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var cur, next string
	for i, s := range sprints {
		if s.State == "current" {
			cur, next = s.ID, sprints[i+1].ID
		}
	}
	if cur == "" {
		t.Skip("no running sprint in the demo data")
	}
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load(team)
	for i := range data.Tickets[:2] {
		data.Tickets[i].InSprint = &cur
	}
	if _, err := repo.SaveTickets(team, storage.TicketsFile{Tickets: data.Tickets}); err != nil {
		t.Fatal(err)
	}
	typed := 99.0
	w, err := api.WhatIf(team, next, Assumption{Label: "A", Carry: []CarryInput{}, Commitment: &typed})
	if err != nil || w == nil {
		t.Fatalf("what-if = %+v err = %v", w, err)
	}
	if w.Commitment == 99 || w.Touched {
		t.Errorf("typed commitment counted with tickets: %+v", w)
	}
}

func TestRunningHintNamesUnknownTrackerSprints(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load(team)
	name := "Board X wave 9"
	data.Tickets[0].InSprint, data.Tickets[0].SprintName, data.Tickets[0].Done = nil, &name, false
	if _, err := repo.SaveTickets(team, storage.TicketsFile{Tickets: data.Tickets}); err != nil {
		t.Fatal(err)
	}
	h, err := api.RunningHint(team, next)
	if err != nil || h.Unresolved < 1 || len(h.Names) == 0 || h.Names[0] != name {
		t.Errorf("hint = %+v err = %v", h, err)
	}
}

// A fixed conversion factor wins over the measured rate in the plan view and in the project
// contingents (decision 19).
func TestFixedFactorWinsInPlanAndProjects(t *testing.T) {
	api, team := planTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		t.Fatal(err)
	}
	if data.Team.Unit != model.UnitSP {
		tm := data.Team
		tm.Unit = model.UnitSP
		if _, err := repo.SaveTeam(tm); err != nil {
			t.Fatal(err)
		}
		if data, err = repo.Load(team); err != nil {
			t.Fatal(err)
		}
	}
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	before, err := api.PlanSprint(team, next, nil)
	if err != nil || before.Rate == nil {
		t.Fatalf("view = %+v, err %v", before, err)
	}
	factor := math.Round(*before.Rate) + 1.5
	tm := data.Team
	tm.Estimation.Factor = &factor
	if _, err := repo.SaveTeam(tm); err != nil {
		t.Fatal(err)
	}
	after, err := api.PlanSprint(team, next, nil)
	if err != nil {
		t.Fatal(err)
	}
	if after.Rate == nil || math.Abs(*after.Rate-factor) > 1e-6 {
		t.Fatalf("plan rate = %v, want the fixed %v", floatOr(after.Rate, -1), factor)
	}
	pv, err := api.Projects(team)
	if err != nil {
		t.Fatal(err)
	}
	fv, err := api.Forecast(team)
	if err != nil {
		t.Fatal(err)
	}
	if !fv.RateFixed || fv.Rate == nil || math.Abs(*fv.Rate-factor) > 1e-6 {
		t.Errorf("forecast rate = %v fixed %v, want the fixed %v", floatOr(fv.Rate, -1), fv.RateFixed, factor)
	}
	ov, err := api.SprintOverview(team, -1)
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range ov.Rows {
		if r.ID == next && (r.Factor == nil || math.Abs(*r.Factor-factor) > 1e-6) {
			t.Errorf("sprint row factor = %v", r.Factor)
		}
	}
	if pv.Rate == nil || math.Abs(*pv.Rate-factor) > 1e-6 {
		t.Errorf("project rate = %v, want the fixed %v", pv.Rate, factor)
	}
}

// A team that started in person days and switched to story points by a unit change gets the
// fixed factor from that sprint on.
func TestFixedFactorAfterUnitChange(t *testing.T) {
	api, team := planTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		t.Fatal(err)
	}
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	factor := 3.5
	tm := data.Team
	tm.Unit = model.UnitPT
	tm.Estimation.Changes = []model.UnitChange{{From: next, Unit: model.UnitSP, Factor: &factor}}
	if _, err := repo.SaveTeam(tm); err != nil {
		t.Fatal(err)
	}
	v, err := api.PlanSprint(team, next, nil)
	if err != nil {
		t.Fatal(err)
	}
	if v.Rate == nil || math.Abs(*v.Rate-factor) > 1e-6 || v.OtherUnit != "PT" {
		t.Errorf("rate = %v, other unit %q", floatOr(v.Rate, -1), v.OtherUnit)
	}
}

// Focus and extra absence of a saved prognosis lower the plan on the plan page like on the
// Forecast page, and they survive the round trip through the sprint file.
func TestAssumptionFocusAndAbsenceLowerThePlan(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var cur, next string
	for i, s := range sprints {
		if s.State == "current" {
			cur, next = s.ID, sprints[i+1].ID
		}
	}
	if cur == "" {
		t.Skip("no running sprint in the demo data")
	}
	base, err := api.WhatIf(team, next, Assumption{Label: "A", Carry: []CarryInput{}})
	if err != nil || base == nil || base.Plan == nil {
		t.Fatalf("base = %+v err = %v", base, err)
	}
	focus, absence := 50.0, 2.0
	as := Assumption{Label: "B", Carry: []CarryInput{}, FocusPercent: &focus, ExtraAbsenceDays: &absence}
	w, err := api.WhatIf(team, next, as)
	if err != nil || w == nil || w.Plan == nil {
		t.Fatalf("what-if = %+v err = %v", w, err)
	}
	if !w.Touched || *w.Plan >= *base.Plan {
		t.Errorf("plan %v should be below %v", *w.Plan, *base.Plan)
	}
	if err := api.SaveAssumption(team, next, as); err != nil {
		t.Fatal(err)
	}
	v, err := api.PlanSprint(team, next, nil)
	if err != nil {
		t.Fatal(err)
	}
	var saved *Assumption
	for i := range v.Assumptions {
		if v.Assumptions[i].Label == "B" {
			saved = &v.Assumptions[i]
		}
	}
	if saved == nil || saved.FocusPercent == nil || *saved.FocusPercent != 50 || saved.ExtraAbsenceDays == nil || *saved.ExtraAbsenceDays != 2 {
		t.Fatalf("saved = %+v", saved)
	}
}

func TestMoveWorkPackageShowsInThePlanLane(t *testing.T) {
	api, team := planTeam(t)
	sprints, _ := api.Sprints(team)
	var next string
	for _, s := range sprints {
		if s.State == "future" {
			next = s.ID
			break
		}
	}
	for _, k := range []string{"T-2", "T-3"} {
		if err := api.EarmarkTicket(team, k, next, ""); err != nil {
			t.Fatal(err)
		}
	}
	keys := func() string {
		v, err := api.PlanSprint(team, next, nil)
		if err != nil {
			t.Fatal(err)
		}
		var out []string
		for _, x := range v.Tickets {
			out = append(out, x.Key)
		}
		return strings.Join(out, ",")
	}
	before := keys()
	if err := api.MoveWorkPackage(team, "T-3", "T-2", false); err != nil {
		t.Fatal(err)
	}
	if got := keys(); got != "T-3,T-2" {
		t.Errorf("lane after the move = %s (before %s)", got, before)
	}
}
