package forecast_test

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/model"
)

type apiRef struct {
	Current   *string            `json:"current"`
	Upcoming  []string           `json:"upcoming"`
	History   []string           `json:"history"`
	History0  []string           `json:"history_0"`
	History3  []string           `json:"history_3"`
	Defaults  map[string]*string `json:"defaults"`
	Find      map[string]*string `json:"find"`
	Lookup    map[string]*string `json:"lookup"`
	Known     map[string]bool    `json:"absences_known"`
	Available int                `json:"available_count"`
	Few       bool               `json:"few_samples"`
	Samples   int                `json:"sample_count"`
	Buffer    struct {
		Sufficient bool `json:"sufficient_data"`
		TooSmall   bool `json:"buffer_too_small"`
	} `json:"buffer"`
	Freeze []struct {
		Sprint   string   `json:"sprint"`
		Preset   *float64 `json:"preset"`
		Refreeze bool     `json:"refreeze"`
		Result   *float64 `json:"result"`
	} `json:"freeze"`
	Refreeze []struct {
		Sprint string    `json:"sprint"`
		Preset *float64  `json:"preset"`
		Offer  []float64 `json:"offer"`
	} `json:"refreeze"`
	HorizonEntries int `json:"horizon_forecast_entries"`
}

func ids(entries []*forecast.TimelineEntry) []string {
	out := []string{}
	for _, e := range entries {
		out = append(out, e.Sprint.ID)
	}
	return out
}

func idOf(e *forecast.TimelineEntry) *string {
	if e == nil {
		return nil
	}
	return &e.Sprint.ID
}

func sameIDs(t *testing.T, what string, got, want []string) {
	t.Helper()
	diffs, err := golden.Diff(coretest.JSON(t, want), coretest.JSON(t, got))
	if err != nil {
		t.Fatal(err)
	}
	if len(diffs) > 0 {
		t.Errorf("%s: %v", what, diffs)
	}
}

func eqPtr(a, b *string) bool { return (a == nil) == (b == nil) && (a == nil || *a == *b) }

// The lookups around the forecast equal the Python ones for every golden case.
func TestLookupsMatchPython(t *testing.T) {
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			var ref apiRef
			golden.Load(t, &ref, "forecast_api", c.Name+".json")
			data := coretest.Load(t, c)
			today := coretest.Today(t, c)
			fc, err := forecast.Build(data, today)
			if err != nil {
				t.Fatal(err)
			}
			if got := idOf(fc.Current()); !eqPtr(got, ref.Current) {
				t.Errorf("Current %v, Python %v", got, ref.Current)
			}
			sameIDs(t, "upcoming", ids(fc.Upcoming()), ref.Upcoming)
			sameIDs(t, "history", ids(fc.History()), ref.History)
			sameIDs(t, "history 0", ids(fc.HistoryLast(0)), ref.History0)
			sameIDs(t, "history 3", ids(fc.HistoryLast(3)), ref.History3)
			for purpose, want := range ref.Defaults {
				e, err := fc.DefaultEntry(forecast.Purpose(purpose))
				if err != nil {
					t.Fatal(err)
				}
				if got := idOf(e); !eqPtr(got, want) {
					t.Errorf("DefaultEntry(%s) %v, Python %v", purpose, got, want)
				}
			}
			if _, err := fc.DefaultEntry("bogus"); err == nil {
				t.Error("an unknown purpose must fail")
			}
			for id, want := range ref.Find {
				s, err := forecast.FindSprint(data, id, 8)
				if err != nil {
					t.Fatal(err)
				}
				var got *string
				if s != nil {
					got = &s.ID
				}
				if !eqPtr(got, want) {
					t.Errorf("FindSprint(%s) %v, Python %v", id, got, want)
				}
			}
			for id, want := range ref.Lookup {
				s, err := fc.LookupSprint(id, 8)
				if err != nil {
					t.Fatal(err)
				}
				var got *string
				if s != nil {
					got = &s.ID
				}
				if !eqPtr(got, want) {
					t.Errorf("LookupSprint(%s) %v, Python %v", id, got, want)
				}
			}
			for _, e := range fc.Entries {
				if got := forecast.AbsencesKnown(e.Sprint); got != ref.Known[e.Sprint.ID] {
					t.Errorf("AbsencesKnown(%s) %v, Python %v", e.Sprint.ID, got, ref.Known[e.Sprint.ID])
				}
			}
			if got := analysis.AvailableCount(fc); got != ref.Available {
				t.Errorf("AvailableCount %d, Python %d", got, ref.Available)
			}
			if got := analysis.FewSamples(fc); got != ref.Few {
				t.Errorf("FewSamples %v, Python %v", got, ref.Few)
			}
			if got := analysis.SampleCount(fc); got != ref.Samples {
				t.Errorf("SampleCount %d, Python %d", got, ref.Samples)
			}
			buffer := analysis.Buffer(fc)
			if buffer.SufficientData() != ref.Buffer.Sufficient || buffer.BufferTooSmall() != ref.Buffer.TooSmall {
				t.Errorf("Buffer %v %v, Python %v", buffer.SufficientData(), buffer.BufferTooSmall(), ref.Buffer)
			}
			long, err := analysis.HorizonForecast(data, today, 6)
			if err != nil {
				t.Fatal(err)
			}
			if len(long.Entries) != ref.HorizonEntries {
				t.Errorf("horizon forecast has %d entries, Python %d", len(long.Entries), ref.HorizonEntries)
			}
			if data.Team.Forecast.Horizon == 6 {
				t.Error("the horizon forecast must not change the team")
			}

			i := 0
			for _, e := range fc.Entries {
				for _, preset := range []*float64{nil, model.Ptr(9.9)} {
					for _, refreeze := range []bool{false, true} {
						want := ref.Freeze[i]
						i++
						s := e.Sprint.Clone()
						s.ForecastPlan = preset
						forecast.FreezePlan(&s, &e, today, refreeze)
						if want.Sprint != s.ID || !eqF(s.ForecastPlan, want.Result) {
							t.Errorf("FreezePlan(%s, %v, %v) = %v, Python %v", s.ID, preset, refreeze, s.ForecastPlan, want.Result)
						}
					}
				}
			}
			j := 0
			for _, e := range fc.Entries {
				for _, preset := range []*float64{nil, model.Ptr(9.9)} {
					want := ref.Refreeze[j]
					j++
					s := e.Sprint.Clone()
					s.ForecastPlan = preset
					frozen, current, ok := forecast.RefreezeOffer(&s, &e)
					if ok != (want.Offer != nil) || (ok && (frozen != want.Offer[0] || current != want.Offer[1])) {
						t.Errorf("RefreezeOffer(%s, %v) = %v %v %v, Python %v", s.ID, preset, frozen, current, ok, want.Offer)
					}
				}
			}
		})
	}
}

func eqF(a, b *float64) bool { return (a == nil) == (b == nil) && (a == nil || *a == *b) }

type miscRef struct {
	ApplyPlanning []struct {
		Commitment *float64        `json:"commitment"`
		Planning   *model.Planning `json:"planning"`
		Prefilled  bool            `json:"prefilled"`
		SprintC    *float64        `json:"sprint_commitment"`
		SprintP    *model.Planning `json:"sprint_planning"`
	} `json:"apply_planning"`
	Errors map[string]*string `json:"errors"`
}

func TestApplyPlanningAndErrorsMatchPython(t *testing.T) {
	var ref miscRef
	golden.Load(t, &ref, "forecast_api", "misc.json")
	for _, c := range ref.ApplyPlanning {
		s := model.Sprint{ID: "x"}
		var planning *model.Planning
		if c.Planning != nil {
			p := *c.Planning
			p.Corrections = append([]float64{}, c.Planning.Corrections...)
			planning = &p
		}
		prefilled := forecast.ApplyPlanning(&s, c.Commitment, planning)
		if prefilled != c.Prefilled || !eqF(s.Commitment, c.SprintC) {
			t.Errorf("ApplyPlanning(%v, %v) = %v, %v; Python %v, %v", c.Commitment, c.Planning, prefilled, s.Commitment, c.Prefilled, c.SprintC)
		}
		golden.Compare(t, coretest.JSON(t, c.SprintP), coretest.JSON(t, s.Planning))
	}

	team := model.NewTeam("no-first", "x")
	_, err := calendar.FollowingSprint(&team, nil)
	if err == nil || err.Error() != *ref.Errors["no_first_sprint"] {
		t.Errorf("no first sprint: %v, Python %q", err, *ref.Errors["no_first_sprint"])
	}
	d := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	for key, in := range map[string]struct {
		id        string
		numbering model.Numbering
	}{
		"sequential_22b": {"22b", model.NumberingSequential}, "sequential_x": {"x", model.NumberingSequential},
		"yearly_counter": {"2026.x", model.NumberingYearly},
	} {
		_, err := calendar.NextID(in.id, d, in.numbering)
		want := ref.Errors[key]
		if want == nil || err == nil || err.Error() != *want {
			t.Errorf("%s: %v, Python %v", key, err, want)
		}
	}
	if got := calendar.ExpectedIDForm("en", model.NumberingYearly); got != *ref.Errors["yearly_form"] {
		t.Errorf("%q", got)
	}
	if got := calendar.ExpectedIDForm("en", model.NumberingSequential); got != *ref.Errors["sequential_form"] {
		t.Errorf("%q", got)
	}
}
