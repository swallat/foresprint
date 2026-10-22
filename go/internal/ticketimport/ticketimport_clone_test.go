package ticketimport

import (
	"testing"

	"github.com/swallat/foresprint/internal/model"
)

func TestClonePreplanKeepsWhatTheFetchDoesNotOwn(t *testing.T) {
	in := model.Preplan{
		Earmarks:   []model.Earmark{{Ticket: "A-1", Sprint: "2026.5"}},
		Production: []model.ProductionShare{{Ticket: "A-1", Percent: 10}},
		Overrides:  []model.TicketOverride{{Ticket: "A-1"}},
		ProForma:   []model.ProFormaPlacement{{Ticket: "A-1", Name: "Refinement"}},
		Order:      []string{"A-2", "A-1"},
	}
	out := clonePreplan(in)
	if len(out.Production) != 1 || len(out.Overrides) != 1 || len(out.ProForma) != 1 || len(out.Order) != 2 {
		t.Errorf("lost: %+v", out)
	}
}

func TestFetchTakesOverTheOrderOfTheTracker(t *testing.T) {
	env := Env{Preplan: model.Preplan{Order: []string{"A-2", "A-1"}}}
	plan := PlanImport(env, nil, nil, false)
	if len(plan.Preplan.Order) != 0 || !plan.PreplanChanged {
		t.Errorf("order %v changed %v", plan.Preplan.Order, plan.PreplanChanged)
	}
}
