package ticketimport

import (
	"testing"
	"time"

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

func TestFetchCanKeepTheOwnOrder(t *testing.T) {
	env := Env{Preplan: model.Preplan{Order: []string{"A-2", "A-1"}}, KeepOrder: true}
	plan := PlanImport(env, nil, nil, false)
	if len(plan.Preplan.Order) != 2 || plan.PreplanChanged {
		t.Errorf("order %v changed %v", plan.Preplan.Order, plan.PreplanChanged)
	}
}

type listedSprints []string

func (l listedSprints) End(id string) (time.Time, bool) {
	for _, s := range l {
		if s == id {
			return time.Now(), true
		}
	}
	return time.Time{}, false
}
func (l listedSprints) IDs() []string { return l }

func TestResolveSprintByNumberInPrefixedIDs(t *testing.T) {
	sprints := listedSprints{"TEAM - 2026.20", "TEAM - 2026.21"}
	got := ResolveSprint("Old Board Sprint 2026.20", model.TrackerSettings{}, sprints)
	if got == nil || *got != "TEAM - 2026.20" {
		t.Fatalf("got %v", got)
	}
	if ResolveSprint("Sprint 16", model.TrackerSettings{}, sprints) != nil {
		t.Error("a name without a yearly number must stay unresolved")
	}
	two := listedSprints{"A - 2026.20", "B - 2026.20"}
	if ResolveSprint("Sprint 2026.20", model.TrackerSettings{}, two) != nil {
		t.Error("two candidates are ambiguous")
	}
}
