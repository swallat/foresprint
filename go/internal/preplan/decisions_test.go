package preplan

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/ticketimport"
)

func sp(s string) *string { return &s }

func decisionData() *storage.TeamData {
	d := &storage.TeamData{}
	d.Team.Features = model.Features{Products: true, Production: true}
	d.Products = []model.Product{{ID: "a"}, {ID: "b"}}
	d.Projects = []model.Project{
		{ID: "p1", Product: sp("a"), State: model.ProjectOpen},
		{ID: "old", Product: sp("a"), State: model.ProjectFinished},
	}
	return d
}

func TestProjectOfAndProduct(t *testing.T) {
	d := decisionData()
	tk := model.Ticket{Key: "T-1", Project: sp("p1")}
	if p := ProjectOf(tk, d); p == nil || p.ID != "p1" {
		t.Fatalf("project = %v", p)
	}
	if id, _ := TicketProduct(tk, d); id == nil || *id != "a" {
		t.Fatalf("product = %v", id)
	}
	d.Preplan.Overrides = []model.TicketOverride{{Ticket: "T-1", Daily: true, Product: sp("b")}}
	if p := ProjectOf(tk, d); p != nil {
		t.Fatalf("daily override should drop the project, got %v", p)
	}
	if id, _ := TicketProduct(tk, d); id == nil || *id != "b" {
		t.Fatalf("override product = %v", id)
	}
	closed := model.Ticket{Key: "T-2", Project: sp("old")}
	if ProjectOf(closed, d) != nil {
		t.Fatal("closed project must count as none")
	}
}

func TestProductionShareOf(t *testing.T) {
	d := decisionData()
	label := "prod"
	d.Team.Tracker.ProductionLabel = &label
	tk := model.Ticket{Key: "T-1", Labels: []string{"prod"}}
	if v, src := ProductionShareOf(tk, d); v != 100 || src != ticketimport.ProductionLabel {
		t.Fatalf("label: %v %v", v, src)
	}
	d.Preplan.Production = []model.ProductionShare{{Ticket: "T-1", Percent: 30}}
	if v, src := ProductionShareOf(tk, d); v != 30 || src != ticketimport.ProductionHand {
		t.Fatalf("hand: %v %v", v, src)
	}
	d.Team.Features.Production = false
	if v, src := ProductionShareOf(tk, d); v != 0 || src != ticketimport.ProductionNone {
		t.Fatalf("off: %v %v", v, src)
	}
}

func TestEffectiveProjectID(t *testing.T) {
	d := decisionData()
	if id := effectiveProjectID(model.Ticket{Key: "X", Project: sp("ghost")}, d); id == nil || *id != "ghost" {
		t.Fatalf("unknown project id must be kept, got %v", id)
	}
	if id := effectiveProjectID(model.Ticket{Key: "X", Project: sp("old")}, d); id != nil {
		t.Fatalf("closed project must drop, got %v", *id)
	}
}

func TestCarryInsOf(t *testing.T) {
	d := decisionData()
	d.Team.Features.Products = false
	day := func(n int) time.Time { return time.Date(2026, 1, 1+n, 0, 0, 0, 0, time.UTC) }
	sprints := []model.Sprint{{ID: "s2", Start: day(14), End: day(28)}, {ID: "s3", Start: day(28), End: day(42)}}
	d.Sprints = []model.Sprint{{ID: "s1", Start: day(0), End: day(14), Carry: []model.CarryItem{
		{Ticket: sp("T-1"), Rest: 3},
		{Ticket: sp("T-2"), Rest: 2, Target: "s3"},
		{Ticket: sp("T-3"), Rest: 9, Target: model.CarryBacklog},
		{Rest: 4},
	}}}
	got := carryInsOf(d, sprints, func(model.Ticket) *string { return nil })
	if got.Amount[keyOf("s2", nil)] != 7 || got.Amount[keyOf("s3", nil)] != 2 {
		t.Fatalf("amounts %v", got.Amount)
	}
	if !got.Tickets["s2"]["T-1"] || got.Tickets["s2"]["T-3"] {
		t.Fatalf("tickets %v", got.Tickets)
	}
}
