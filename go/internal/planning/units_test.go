package planning_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/planning"
)

func fp(v float64) *float64 { return &v }
func sp(v string) *string   { return &v }

func TestUnitAt(t *testing.T) {
	team := model.NewTeam("t", "t")
	team.Unit = model.UnitSP
	team.Estimation.Factor = fp(2)
	team.Estimation.Changes = []model.UnitChange{
		{From: "s3", Unit: model.UnitPT},
		{From: "s5", Unit: model.UnitSP, Factor: fp(4)},
		{From: "nowhere", Unit: model.UnitPT},
	}
	order := []string{"s1", "s2", "s3", "s4", "s5", "s6"}
	want := map[string]struct {
		unit   model.Unit
		factor float64
	}{
		"s1": {model.UnitSP, 2}, "s2": {model.UnitSP, 2}, "s3": {model.UnitPT, 2},
		"s4": {model.UnitPT, 2}, "s5": {model.UnitSP, 4}, "s6": {model.UnitSP, 4},
		"unknown": {model.UnitSP, 2},
	}
	for id, w := range want {
		if u := planning.UnitAt(&team, order, id); u != w.unit {
			t.Errorf("%s: unit %v, want %v", id, u, w.unit)
		}
		if f := planning.FactorAt(&team, order, id); f == nil || *f != w.factor {
			t.Errorf("%s: factor %v, want %v", id, f, w.factor)
		}
	}
	team.Estimation.Factor = nil
	if f := planning.FactorAt(&team, order, "s1"); f != nil {
		t.Errorf("no factor: %v", *f)
	}
}

func TestConvert(t *testing.T) {
	// same unit: no estimate
	if v, ok := planning.Convert(10, model.UnitSP, model.UnitSP, nil, 0); !ok || v.Amount != 10 || v.Estimate {
		t.Errorf("same unit: %+v %v", v, ok)
	}
	// factor 2 points per PD: 10 SP = 5 PD, 5 PD = 10 SP
	if v, ok := planning.Convert(10, model.UnitSP, model.UnitPT, fp(2), 99); !ok || v.Amount != 5 || !v.Estimate || v.Unit != model.UnitPT {
		t.Errorf("SP to PT: %+v %v", v, ok)
	}
	if v, ok := planning.Convert(5, model.UnitPT, model.UnitSP, fp(2), 99); !ok || v.Amount != 10 || !v.Estimate {
		t.Errorf("PT to SP: %+v %v", v, ok)
	}
	// measured rate 2.5: 10 SP = 4 PD
	if v, ok := planning.Convert(10, model.UnitSP, model.UnitPT, nil, 2.5); !ok || v.Amount != 4 {
		t.Errorf("measured: %+v %v", v, ok)
	}
	if _, ok := planning.Convert(10, model.UnitSP, model.UnitPT, nil, 0); ok {
		t.Error("no rate must not convert")
	}
}

func TestCarryInto(t *testing.T) {
	ticket := sp("T-1")
	sprints := []model.Sprint{
		// definitive rest: 3 to the next sprint (empty target), 2 to the backlog
		{ID: "s1", Carry: []model.CarryItem{{Ticket: ticket, Rest: 3}, {Rest: 2, Target: model.CarryBacklog}}},
		// running sprint: assumptions A (rest 4 next) and B (rest 1 next, 6 explicit to s4)
		{ID: "s2", Prognoses: []model.Prognosis{
			{Label: sp("A"), RestNext: fp(4)},
			{Label: sp("B"), Carry: []model.CarryItem{{Rest: 1}, {Rest: 6, Target: "s4"}}},
		}},
		{ID: "s3"},
		{ID: "s4"},
	}
	in := planning.CarryInto(sprints, "s2", "")
	if in.Rest != 3 || in.Assumed || len(in.Items) != 1 || in.Items[0].Sprint != "s1" {
		t.Errorf("into s2: %+v", in)
	}
	// assumption A of s2 into s3, newest label would be B
	if in := planning.CarryInto(sprints, "s3", "A"); in.Rest != 4 || !in.Assumed {
		t.Errorf("A into s3: %+v", in)
	}
	if in := planning.CarryInto(sprints, "s3", ""); in.Rest != 1 || !in.Assumed {
		t.Errorf("newest into s3: %+v", in)
	}
	if in := planning.CarryInto(sprints, "s4", "B"); in.Rest != 6 {
		t.Errorf("B into s4: %+v", in)
	}
	// definitive rest of s2 replaces the assumption
	sprints[1].RestNext = fp(5)
	if in := planning.CarryInto(sprints, "s3", "A"); in.Rest != 5 || in.Assumed {
		t.Errorf("definitive: %+v", in)
	}
	// the backlog is never a sprint
	if in := planning.CarryInto(sprints, "s3", "B"); in.Rest != 5 {
		t.Errorf("backlog counted: %+v", in)
	}
}
