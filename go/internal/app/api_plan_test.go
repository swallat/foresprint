package app

import (
	"math"
	"os"
	"path/filepath"
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
	if err := api.SetEarmark(team, "T-1", next); err != nil {
		t.Fatal(err)
	}
	if err := api.SetEarmark(team, "T-2", next); err != nil {
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
	if err := api.SetEarmark(team, "T-1", ""); err != nil {
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
	_ = api.SetEarmark(team, "T-1", next)
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
	_ = api.SetEarmark(team, "T-1", next)
	_ = api.SetEarmark(team, "T-2", next)
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
	if planned != 5 { // T-2 has no product
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
