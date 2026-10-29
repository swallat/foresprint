package analysis_test

import (
	"encoding/json"
	"testing"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/golden"
)

// The analysis of every golden case (history, bands, focus factor, buffer hint, horizon) equals
// the one of the Python core.
func TestHorizonMatchesPython(t *testing.T) {
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			var want any
			if !c.LoadExpected(t, &want, "horizon.json") {
				t.Skip("no reference")
			}
			data := coretest.Load(t, c)
			today := coretest.Today(t, c)
			fc, err := analysis.HorizonForecast(data, today, analysis.DefaultMaxSprints)
			if err != nil {
				t.Fatal(err)
			}
			bands := map[string]any{}
			focus := map[string]any{}
			for i := range fc.Entries {
				e := &fc.Entries[i]
				if e.Sprint.Start.After(today) {
					if b, ok := analysis.BandOf(fc, e); ok {
						bands[e.Sprint.ID] = b
					} else {
						bands[e.Sprint.ID] = nil
					}
				}
				focus[e.Sprint.ID] = analysis.FocusFactor(e)
			}
			horizon := []map[string]any{}
			for _, h := range analysis.HorizonEntries(fc, analysis.DefaultMaxSprints) {
				horizon = append(horizon, map[string]any{"sprint": h.Entry.Sprint.ID, "capacity": h.Capacity, "trend": h.Trend})
			}
			got := map[string]any{
				"normalized_history":   orEmpty(analysis.NormalizedHistory(fc)),
				"sample_count":         analysis.SampleCount(fc),
				"average_focus_factor": analysis.AverageFocusFactor(fc),
				"buffer_hint":          analysis.Buffer(fc),
				"bands":                bands,
				"focus":                focus,
				"horizon":              horizon,
			}
			golden.Compare(t, want, coretest.JSON(t, got))
		})
	}
}

func orEmpty(v []float64) []float64 {
	if v == nil {
		return []float64{}
	}
	return v
}

type simulation struct {
	Params struct {
		Remaining float64 `json:"remaining"`
		Share     float64 `json:"share"`
		Runs      int     `json:"runs"`
		Seed      int64   `json:"seed"`
	} `json:"params"`
	Result any `json:"result"`
}

// The Monte Carlo simulation draws the same numbers as Python's random.Random for the same
// seed, so every probability and every sprint of 50 % and 85 % is the same.
func TestSimulateMatchesPython(t *testing.T) {
	for _, c := range golden.Cases(t) {
		var sims []simulation
		if !c.LoadExpected(t, &sims, "completion.json") {
			continue
		}
		data := coretest.Load(t, c)
		for _, s := range sims {
			result, err := analysis.Simulate(data, coretest.Today(t, c), s.Params.Remaining, s.Params.Share,
				analysis.DefaultMaxSprints, s.Params.Runs, s.Params.Seed)
			if err != nil {
				t.Fatal(err)
			}
			raw, _ := json.Marshal(s.Result)
			var want any
			_ = json.Unmarshal(raw, &want)
			var got any
			if result != nil {
				got = coretest.JSON(t, result)
			}
			if want == nil {
				if result != nil {
					t.Errorf("%s %+v: Python has no result", c.Name, s.Params)
				}
				continue
			}
			t.Run(c.Name, func(t *testing.T) { golden.Compare(t, coretest.JSON(t, want), got) })
		}
	}
}

// The range shown next to a Forecast PLAN holds the plan and grows with the distance.
func TestBandAroundPlanHoldsThePlan(t *testing.T) {
	for _, c := range golden.Cases(t) {
		data := coretest.Load(t, c)
		fc, err := analysis.HorizonForecast(data, coretest.Today(t, c), analysis.DefaultMaxSprints)
		if err != nil {
			continue
		}
		for i := range fc.Entries {
			e := &fc.Entries[i]
			b, ok := analysis.BandAroundPlan(fc, e)
			if !ok {
				continue
			}
			if p := *e.Result.Plan; p < b.Low || p > b.High || b.Mid != p {
				t.Errorf("%s %s: plan %v outside %v-%v", c.Name, e.Sprint.ID, p, b.Low, b.High)
			}
		}
	}
}
