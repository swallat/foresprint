package planning_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/planning"
	"github.com/swallat/foresprint/internal/rules"
)

func TestShareOf(t *testing.T) {
	label := "PROD"
	tracker := model.TrackerSettings{
		ProductionLabel: &label,
		ProductionRules: []model.ProductionRule{
			{Match: rules.NewLeaf("component", "Ops"), Percent: 50},
			{Match: rules.NewLeaf("component", "Ops", "Web"), Percent: 20},
		},
	}
	preplan := model.Preplan{Production: []model.ProductionShare{{Ticket: "T-1", Percent: 30}}}
	cases := []struct {
		name   string
		ticket model.Ticket
		field  *float64
		want   float64
		source planning.ShareSource
	}{
		{"by hand beats everything", model.Ticket{Key: "T-1", Labels: []string{"PROD"}}, fp(80), 0.3, planning.ShareByHand},
		{"field beats label and rule", model.Ticket{Key: "T-2", Labels: []string{"PROD"}}, fp(80), 0.8, planning.ShareField},
		{"label means all", model.Ticket{Key: "T-3", Labels: []string{"PROD"}, Components: []string{"Ops"}}, nil, 1, planning.ShareLabel},
		{"first rule wins", model.Ticket{Key: "T-4", Components: []string{"Ops"}}, nil, 0.5, planning.ShareRule},
		{"second rule", model.Ticket{Key: "T-5", Components: []string{"Web"}}, nil, 0.2, planning.ShareRule},
		{"nothing", model.Ticket{Key: "T-6"}, nil, 0, planning.ShareNone},
		{"field over 100 is cut", model.Ticket{Key: "T-7"}, fp(250), 1, planning.ShareField},
		{"negative field is cut", model.Ticket{Key: "T-8"}, fp(-3), 0, planning.ShareField},
	}
	for _, c := range cases {
		got, source := planning.ShareOf(c.ticket, preplan, tracker, c.field)
		if got != c.want || source != c.source {
			t.Errorf("%s: %v %v, want %v %v", c.name, got, source, c.want, c.source)
		}
	}
}
