package report

import (
	"testing"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/storage"
)

// The rounding of the team decides the decimals of the plan and of what is calculated from it, but
// never fewer than the reports always had (one and two), so the golden output stays as it is.
func TestPlanAndSplitDigits(t *testing.T) {
	for _, c := range []struct{ rounding, plan, split int }{{0, 1, 2}, {1, 1, 2}, {2, 2, 2}, {3, 3, 3}} {
		fc := &forecast.Forecast{Data: &storage.TeamData{}}
		fc.Data.Team.Forecast.Rounding = c.rounding
		if got := PlanDigits(fc); got != c.plan {
			t.Errorf("rounding %d: PlanDigits = %d, want %d", c.rounding, got, c.plan)
		}
		if got := SplitDigits(fc); got != c.split {
			t.Errorf("rounding %d: SplitDigits = %d, want %d", c.rounding, got, c.split)
		}
	}
}
