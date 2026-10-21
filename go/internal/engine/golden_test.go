package engine_test

import (
	"encoding/json"
	"strconv"
	"testing"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/coretypes"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/golden"
)

type reference struct {
	Rounding []struct {
		Value       float64 `json:"value"`
		Digits      int     `json:"digits"`
		RoundDown   float64 `json:"round_down"`
		RoundHalfUp float64 `json:"round_half_up"`
	} `json:"rounding"`
	Series []struct {
		Name    string     `json:"name"`
		Values  []*float64 `json:"values"`
		Window  int        `json:"window"`
		Average []*float64 `json:"average"`
		Thin    bool       `json:"thin"`
		Gaps    int        `json:"gaps"`
		Trends  map[string]struct {
			Trend    []*float64 `json:"trend"`
			Fallback []bool     `json:"fallback"`
		} `json:"trends"`
	} `json:"series"`
	Klassisch string `json:"klassisch"`
	Compute   []struct {
		Window   int     `json:"window"`
		Mode     string  `json:"mode"`
		Rounding int     `json:"rounding"`
		Share    float64 `json:"share"`
		Results  any     `json:"results"`
	} `json:"compute"`
}

func load(t *testing.T) reference {
	t.Helper()
	var ref reference
	golden.Load(t, &ref, "engine", "cases.json")
	return ref
}

// Rounding is compared bit for bit: the tolerance of the golden comparison would hide a limit
// that falls on the other side.
func TestRoundingMatchesPython(t *testing.T) {
	for _, c := range load(t).Rounding {
		if got := engine.RoundDown(c.Value, c.Digits); got != c.RoundDown && !(got == 0 && c.RoundDown == 0) {
			t.Errorf("RoundDown(%v, %d) = %v, Python %v", c.Value, c.Digits, got, c.RoundDown)
		}
		if got := engine.RoundHalfUp(c.Value, c.Digits); got != c.RoundHalfUp && !(got == 0 && c.RoundHalfUp == 0) {
			t.Errorf("RoundHalfUp(%v, %d) = %v, Python %v", c.Value, c.Digits, got, c.RoundHalfUp)
		}
	}
}

func same(a, b []*float64) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if (a[i] == nil) != (b[i] == nil) || (a[i] != nil && *a[i] != *b[i] && !golden.Close(*a[i], *b[i])) {
			return false
		}
	}
	return true
}

func TestSeriesMatchPython(t *testing.T) {
	for _, c := range load(t).Series {
		values := engine.Series(c.Values)
		average := engine.RollingAverage(values, c.Window)
		if !same(average, c.Average) {
			t.Errorf("%s window %d: average %v, Python %v", c.Name, c.Window, average, c.Average)
		}
		if got := engine.ThinHistory(values, c.Window); got != c.Thin {
			t.Errorf("%s window %d: ThinHistory %v, Python %v", c.Name, c.Window, got, c.Thin)
		}
		if got := engine.GapsInWindow(values, c.Window); got != c.Gaps {
			t.Errorf("%s window %d: GapsInWindow %d, Python %d", c.Name, c.Window, got, c.Gaps)
		}
		for mode, want := range c.Trends {
			trend, err := engine.Trend(average, coretypes.TrendMode(mode))
			if err != nil {
				t.Fatal(err)
			}
			if !same(trend, want.Trend) {
				t.Errorf("%s window %d %s: trend %v, Python %v", c.Name, c.Window, mode, trend, want.Trend)
			}
		}
	}
}

func TestUnknownTrendModeMessage(t *testing.T) {
	var german map[string]string
	golden.Load(t, &german, "formulas-de", "calendar.json")
	err := &engine.UnknownTrendModeError{Mode: "quadratic"}
	if got := err.Message(coretest.German(t)); got != german["trend_mode"] {
		t.Errorf("message %q, Python %q", got, german["trend_mode"])
	}
}

func TestTrendModes(t *testing.T) {
	if mode, err := engine.ParseTrendMode("klassisch"); err != nil || mode != coretypes.Classic {
		t.Errorf("klassisch: %v, %v", mode, err)
	}
	if _, err := engine.ParseTrendMode("quadratic"); err == nil {
		t.Error("an unknown trend mode must fail")
	} else if got := err.Error(); got != "Unknown trend mode 'quadratic' (allowed: classic, linear, flat)" {
		t.Errorf("message %q", got)
	}
	if _, err := engine.Compute([]engine.SprintInput{{ID: "x"}}, coretypes.ForecastSettings{Window: 3, TrendMode: "quadratic"}); err == nil {
		t.Error("Compute must fail for an unknown trend mode")
	}
}

// The fallback marker of the trend (flat instead of the chosen mode) is part of the reference.
func TestFallbackMatchesPython(t *testing.T) {
	checked := 0
	for _, c := range load(t).Series {
		average := engine.RollingAverage(engine.Series(c.Values), c.Window)
		for mode, want := range c.Trends {
			got, err := engine.TrendFallback(average, coretypes.TrendMode(mode))
			if err != nil {
				t.Fatal(err)
			}
			for i := range want.Fallback {
				if got[i] != want.Fallback[i] {
					t.Errorf("%s window %d %s: fallback[%d] = %v, Python %v", c.Name, c.Window, mode, i, got[i], want.Fallback[i])
				}
			}
			checked++
		}
	}
	if checked == 0 {
		t.Fatal("nothing compared")
	}
}

func TestComputeMatchesPython(t *testing.T) {
	capacities := []*float64{f(30), f(35), f(28), f(32), nil, f(30), f(31), nil, nil, nil, nil, f(33), nil, nil}
	velocity := []*float64{f(20), f(25), f(18), f(22), f(24), nil, f(21), f(23), nil, nil, nil, nil, nil, nil}
	commitment := []*float64{f(22), f(24), f(20), f(23), f(24), f(25), f(22), f(24), f(26), nil, nil, nil, nil, nil}
	scope := []*float64{f(0.1), nil, f(0.2), f(0.05), f(0), nil, nil, nil, nil, nil, nil, nil, nil, nil}
	plannings := map[int]*coretypes.Planning{
		3: {Carryover: 5, Backlog: 10, Corrections: []float64{1.5, 2}},
		7: {Carryover: 0, Backlog: 12, Corrections: []float64{}},
	}
	recorded := engine.SourceRecorded
	for _, c := range load(t).Compute {
		inputs := make([]engine.SprintInput, len(capacities))
		for i, capacity := range capacities {
			in := engine.SprintInput{
				ID: "S" + strconv.Itoa(i+1), Capacity: capacity, Commitment: commitment[i], Velocity: velocity[i],
				ScopeCreep: scope[i], Planning: plannings[i],
			}
			if capacity != nil {
				in.CapacitySource = &recorded
			}
			inputs[i] = in
		}
		settings := coretypes.ForecastSettings{
			ReferenceCapacity: 40, Window: c.Window, RoadmapShare: c.Share, Rounding: c.Rounding,
			TrendMode: coretypes.TrendMode(c.Mode), Horizon: 3,
		}
		results, err := engine.Compute(inputs, settings)
		if err != nil {
			t.Fatal(err)
		}
		raw, _ := json.Marshal(c.Results)
		var want any
		_ = json.Unmarshal(raw, &want)
		t.Run(c.Mode, func(t *testing.T) { golden.Compare(t, coretest.JSON(t, want), coretest.JSON(t, results)) })
	}
}

func f(x float64) *float64 { return &x }
