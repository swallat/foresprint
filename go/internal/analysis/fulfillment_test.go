package analysis_test

import (
	"math"
	"testing"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/golden"
)

// The fulfillment of the analysis is the value of the forecast table; sprints without a value
// stay out of the mean, minimum and maximum.
func TestFulfillmentMatchesTable(t *testing.T) {
	withValues := 0
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			data := coretest.Load(t, c)
			fc, err := forecast.Build(data, coretest.Today(t, c))
			if err != nil {
				t.Skip("no forecast")
			}
			h := analysis.Fulfillment(fc)
			if h.Rows == nil {
				t.Fatal("Rows must not be nil")
			}
			last := fc.HistoryLast(data.Team.Forecast.Window)
			if len(h.Rows) != len(last) {
				t.Fatalf("rows = %d, want %d", len(h.Rows), len(last))
			}
			sum, n := 0.0, 0
			for i, e := range last {
				want := e.Result.Fulfillment.Value
				if (h.Rows[i].Value == nil) != (want == nil) || (want != nil && *h.Rows[i].Value != *want) {
					t.Fatalf("row %s differs from the table", h.Rows[i].Sprint)
				}
				if want != nil {
					sum += *want
					n++
				}
			}
			if h.Samples != n {
				t.Fatalf("samples = %d, want %d", h.Samples, n)
			}
			if n == 0 {
				if h.Average != nil || h.Min != nil || h.Max != nil {
					t.Fatal("no values: expected no mean")
				}
				return
			}
			withValues++
			if math.Abs(*h.Average-sum/float64(n)) > 1e-9 {
				t.Fatalf("average = %v, want %v", *h.Average, sum/float64(n))
			}
			if *h.Min > *h.Average || *h.Max < *h.Average {
				t.Fatal("min/max do not enclose the mean")
			}
		})
	}
	if withValues == 0 {
		t.Fatal("no golden case has a fulfillment")
	}
}

func TestFulfillmentLimits(t *testing.T) {
	v := func(x float64) *float64 { return &x }
	cases := []struct {
		name            string
		h               analysis.FulfillmentHint
		sufficient, low bool
	}{
		{"two samples", analysis.FulfillmentHint{Samples: 2, Average: v(0.5)}, false, false},
		{"three samples, low", analysis.FulfillmentHint{Samples: 3, Average: v(0.89)}, true, true},
		{"exactly 90 %", analysis.FulfillmentHint{Samples: 3, Average: v(0.9)}, true, false},
		{"no values", analysis.FulfillmentHint{Samples: 0}, false, false},
	}
	for _, c := range cases {
		if got := c.h.SufficientData(); got != c.sufficient {
			t.Errorf("%s: SufficientData = %v", c.name, got)
		}
		if got := c.h.CommitmentTooHigh(); got != c.low {
			t.Errorf("%s: CommitmentTooHigh = %v", c.name, got)
		}
	}
}
