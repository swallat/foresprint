package coretypes_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/coretypes"
)

func TestPlanningTotalSumsLikePython(t *testing.T) {
	// The corrections are added like Python's sum(): compensated, so 0.1 + 0.2 + 0.3 is 0.6.
	p := coretypes.Planning{Carryover: 5, Backlog: 10, Corrections: []float64{0.1, 0.2, 0.3}}
	if got := p.Total(); got != 15-0.6 {
		t.Errorf("Total = %v", got)
	}
	if got := p.Committed(); got != 15 {
		t.Errorf("Committed = %v", got)
	}
}

func TestAbsenceStatus(t *testing.T) {
	unknown, confirmed := coretypes.Unknown, coretypes.Confirmed
	hundred := coretypes.Float(100)
	cases := []struct {
		name   string
		sprint coretypes.Sprint
		want   coretypes.AbsenceState
	}{
		{"nothing", coretypes.Sprint{}, coretypes.Unknown},
		{"stored unknown", coretypes.Sprint{AbsenceState: &unknown}, coretypes.Unknown},
		{"stored confirmed", coretypes.Sprint{AbsenceState: &confirmed}, coretypes.Confirmed},
		{"absences entered", coretypes.Sprint{AbsenceState: &unknown, Absences: map[string]float64{"a": 1}}, coretypes.Confirmed},
		{"announced", coretypes.Sprint{AbsenceState: &unknown, ExpectedAbsences: map[string]float64{"a": 1}}, coretypes.Expected},
		{"legacy planned", coretypes.Sprint{Commitment: hundred}, coretypes.Confirmed},
		{"legacy announced only", coretypes.Sprint{ExpectedAbsences: map[string]float64{"a": 1}}, coretypes.Expected},
	}
	for _, c := range cases {
		if got := coretypes.AbsenceStatus(c.sprint); got != c.want {
			t.Errorf("%s: %s, want %s", c.name, got, c.want)
		}
	}
}
