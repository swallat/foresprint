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
	cur := model.Sprint{ID: "s2", Start: day(14), End: day(28)}
	horizon := []model.Sprint{{ID: "s3", Start: day(28), End: day(42)}, {ID: "s4", Start: day(42), End: day(56)}}
	d.Tickets = []model.Ticket{{Key: "T-1"}, {Key: "T-2"}}
	vel := 5.0
	d.Sprints = []model.Sprint{
		// An old sprint whose rest went into the running one: no effect on the horizon.
		{ID: "s1", Start: day(0), End: day(14), Velocity: &vel, Carry: []model.CarryItem{{Rest: 5}}},
		{ID: "s2", Start: cur.Start, End: cur.End, Carry: []model.CarryItem{
			{Ticket: sp("T-1"), Rest: 3},
			{Ticket: sp("T-2"), Rest: 2, Target: "s4"},
			{Ticket: sp("T-3"), Rest: 9, Target: model.CarryBacklog},
			{Rest: 4},
		}},
	}
	got := carryInsOf(d, horizon, func(model.Ticket) *string { return nil })
	if got.Amount[keyOf("s3", nil)] != 7 || got.Amount[keyOf("s4", nil)] != 2 {
		t.Fatalf("amounts %v", got.Amount)
	}
	if got.Target["T-1"] != "s3" || got.Target["T-2"] != "s4" || got.Target["T-3"] != "" {
		t.Fatalf("targets %v", got.Target)
	}
}

func TestCarryRestWithoutProductIsSplit(t *testing.T) {
	d := decisionData() // products on, two products without fixed shares
	day := func(n int) time.Time { return time.Date(2026, 1, 1+n, 0, 0, 0, 0, time.UTC) }
	horizon := []model.Sprint{{ID: "s3", Start: day(28), End: day(42)}}
	d.Sprints = []model.Sprint{{ID: "s2", Start: day(14), End: day(28),
		Carry: []model.CarryItem{{Ticket: sp("GONE"), Rest: 4}}}}
	got := carryInsOf(d, horizon, func(model.Ticket) *string { return nil })
	var sum float64
	for _, v := range got.Amount {
		sum += v
	}
	if sum != 4 || got.Amount[keyOf("s3", nil)] != 0 {
		t.Fatalf("rest must be split over the products, got %v", got.Amount)
	}
}

func TestSplitByShare(t *testing.T) {
	d := decisionData() // products a and b without fixed shares
	got := SplitByShare(d, model.Sprint{ID: "s"}, 10)
	if len(got) != 2 || got["a"] != 5 || got["b"] != 5 {
		t.Fatalf("%v", got)
	}
	d.Team.Features.Products = false
	if got := SplitByShare(d, model.Sprint{ID: "s"}, 10); len(got) != 0 {
		t.Fatalf("without products: %v", got)
	}
}
