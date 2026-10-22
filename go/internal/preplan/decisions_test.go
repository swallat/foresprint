package preplan

import (
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
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
	tk := model.Ticket{Key: "T-1", Labels: []string{"Prod"}}
	if v, src := ProductionShareOf(tk, d); v != 100 || src != SourceLabel {
		t.Fatalf("label: %v %v", v, src)
	}
	d.Preplan.Production = []model.ProductionShare{{Ticket: "T-1", Percent: 30}}
	if v, src := ProductionShareOf(tk, d); v != 30 || src != SourceHand {
		t.Fatalf("hand: %v %v", v, src)
	}
	d.Team.Features.Production = false
	if v, src := ProductionShareOf(tk, d); v != 0 || src != SourceNone {
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
