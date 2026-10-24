// Package engine is the calculation engine of the forecast: velocity, capacity and forecast
// calculation per sprint. It ports src/foresprint/engine.py.
//
// Metrics (per sprint):
//
//	Commitment, Velocity, capacity, Scope Creep   inputs
//	Normalized velocity = Velocity / capacity × reference capacity
//	Fulfillment         = Velocity / Commitment
//	Ø (rolling)         = average over Window sprints per metric
//	Trend               = projection of the average into the future
//	Forecast PLAN       = rounded down(norm. velocity trend / reference capacity × capacity)
//	Plannable / small items = Forecast PLAN × plannable share (RoadmapShare) / remainder
//	Planning delta      = Forecast PLAN − (carryover + backlog − corrections)
//
// Optional numbers are *float64 (nil is None in Python). Products are wrapped in float64(...)
// where a following addition must not be fused with them, so the results match Python on every
// processor (see go/README.md).
package engine

import (
	"math"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
)

// Series is a list of optional numbers, one per sprint.
type Series []*float64

const eps = 1e-9

func pow10(digits int) float64 {
	if digits >= 0 {
		return math.Pow10(digits)
	}
	return math.Pow(10, float64(digits))
}

// RoundDown truncates toward zero (with tolerance for floating-point errors).
func RoundDown(value float64, digits int) float64 {
	factor := pow10(digits)
	return math.Copysign(math.Floor(float64(math.Abs(value)*factor)+eps)/factor, value)
}

// RoundHalfUp rounds half up (.5 rounds up, tolerant of floating-point errors); no directional
// bias.
func RoundHalfUp(value float64, digits int) float64 {
	factor := pow10(digits)
	return math.Copysign(math.Floor(float64(math.Abs(value)*factor)+0.5+eps)/factor, value)
}

func div(a, b *float64) *float64 {
	if a == nil || b == nil || *b == 0 {
		return nil
	}
	return model.Ptr(*a / *b)
}

// MinThinHistory is the number of sprints with a value from which a new team already has an
// average and so a forecast, even if the window is not full yet.
const MinThinHistory = 3

func count(values Series) int {
	n := 0
	for _, v := range values {
		if v != nil {
			n++
		}
	}
	return n
}

// ThinHistory reports whether there are too few values for a full window, but enough for an
// initial forecast.
func ThinHistory(values Series, window int) bool {
	n := count(values)
	return MinThinHistory <= n && n < window
}

// RollingAverage is the rolling average over the last window sprints with a value.
//
// Rule for gaps: sprints without a value do not count, the window reaches back further
// accordingly (always exactly window values are averaged, never fewer). The average is only
// defined if the sprint itself has a value and enough values precede it.
//
// Exception for new teams: if there are fewer than window values in total but at least
// MinThinHistory, each sprint from the third value on averages over all values so far.
func RollingAverage(values Series, window int) Series {
	thin := ThinHistory(values, window)
	result := make(Series, 0, len(values))
	var present []float64
	for _, value := range values {
		if value == nil {
			result = append(result, nil)
			continue
		}
		present = append(present, *value)
		switch {
		case len(present) >= window:
			result = append(result, model.Ptr(pymath.Sum(present[max(len(present)-window, 0):])/float64(window)))
		case thin && len(present) >= MinThinHistory:
			result = append(result, model.Ptr(pymath.Sum(present)/float64(len(present))))
		default:
			result = append(result, nil)
		}
	}
	return result
}

// GapsInWindow is the number of sprints without a value that the window of the last average
// skips over.
func GapsInWindow(values Series, window int) int {
	last := -1
	for i, v := range values {
		if v != nil {
			last = i
		}
	}
	if last < 0 {
		return 0
	}
	seen := 0
	for i := last; i >= 0; i-- {
		if values[i] != nil {
			seen++
			if seen == window {
				gaps := 0
				for _, v := range values[i:last] {
					if v == nil {
						gaps++
					}
				}
				return gaps
			}
		}
	}
	return 0
}

// UnknownTrendModeError is the error for a trend mode that does not exist.
type UnknownTrendModeError struct{ Mode string }

// Message is the text for the user.
func (e *UnknownTrendModeError) Message(l string) string {
	return i18n.TIn(l, "Unknown trend mode {mode} (allowed: {allowed})",
		"mode", "'"+e.Mode+"'", "allowed", "classic, linear, flat")
}

func (e *UnknownTrendModeError) Error() string { return e.Message(i18n.Default) }

// ParseTrendMode checks a trend mode; an unknown value is an error (no silent linear). The
// German name of classic is accepted.
func ParseTrendMode(mode model.TrendMode) (model.TrendMode, error) {
	switch mode {
	case model.TrendClassic, model.TrendLinear, model.TrendFlat:
		return mode, nil
	case "klassisch":
		return model.TrendClassic, nil
	}
	return "", &UnknownTrendModeError{Mode: string(mode)}
}

// trendOf projects the rolling average into the future where it is missing, and says per
// position whether it fell back to flat instead of the chosen mode (too little history).
func trendOf(average Series, mode model.TrendMode) (Series, []bool, error) {
	mode, err := ParseTrendMode(mode)
	if err != nil {
		return nil, nil, err
	}
	result := make(Series, len(average))
	fallback := make([]bool, len(average))
	avg := func(j int) *float64 {
		if j >= 0 {
			return average[j]
		}
		return nil
	}
	tr := func(j int) *float64 {
		if j >= 0 {
			return result[j]
		}
		return nil
	}
	known := func(j int) *float64 {
		if a := avg(j); a != nil {
			return a
		}
		return tr(j)
	}
	for i := range average {
		if average[i] != nil {
			continue
		}
		var value *float64
		if mode == model.TrendFlat {
			value = known(i - 1)
		} else {
			a1, a2 := avg(i-1), avg(i-2)
			switch {
			case mode == model.TrendClassic && a1 != nil:
				// =(Ø[i-1] − Ø[i-2]) + Ø[i-1]
				if a2 != nil {
					value = model.Ptr(*a1 + (*a1 - *a2))
				}
			case mode == model.TrendClassic && i >= 2 && tr(i-2) == nil:
				// =Ø[i-2] / Ø[i-3] × Trend[i-1]
				ratio := div(avg(i-2), avg(i-3))
				if t1 := tr(i - 1); ratio != nil && t1 != nil {
					value = model.Ptr(*ratio * *t1)
				}
			default:
				k1, k2 := known(i-1), known(i-2)
				if k1 != nil && k2 != nil {
					value = model.Ptr(*k1 + (*k1 - *k2))
				}
			}
			if value == nil {
				if value = known(i - 1); value != nil {
					fallback[i] = true // thin history: carry the last average forward
				} else if i > 0 && fallback[i-1] {
					fallback[i] = true
				}
			} else if i > 0 && fallback[i-1] {
				fallback[i] = true // builds on a value that was already "flat"
			}
		}
		// Quantities, capacity and shares are never negative; a projection below zero (noise)
		// is clamped to zero.
		if value != nil {
			result[i] = model.Ptr(maxZero(*value))
		}
	}
	return result, fallback, nil
}

// TrendFallback says per position whether the trend fell back to flat instead of the chosen
// mode because of too little history.
func TrendFallback(average Series, mode model.TrendMode) ([]bool, error) {
	_, fallback, err := trendOf(average, mode)
	return fallback, err
}

// Trend projects the rolling average forward where it is missing (future). If the history is
// not enough for classic or linear (e.g. exactly window sprints), flat applies. The result is
// never negative.
func Trend(average Series, mode model.TrendMode) (Series, error) {
	t, _, err := trendOf(average, mode)
	return t, err
}

// CapacitySource says where a sprint's capacity comes from. The values are the English source
// texts (a catalog translates them).
type CapacitySource string

// The sources of a capacity.
const (
	SourceRecorded CapacitySource = "recorded"
	SourcePeople   CapacitySource = "people list"
	SourceTrend    CapacitySource = "Trend"
	// SourceCalendar: people list and calendar; absences unknown and no history, hence no
	// deduction.
	SourceCalendar  CapacitySource = "Calendar, absences unknown"
	SourceEstimated CapacitySource = "expected absences"
	SourceExpected  CapacitySource = "announced absences"
)

// Unsure reports whether the source has neither known absences nor a history: the capacity is
// only an estimate.
func (s CapacitySource) Unsure() bool { return s == SourceTrend || s == SourceCalendar }

// PlanSource says whether a plan is a recorded actual or a projection.
type PlanSource string

// The sources of a plan.
const (
	PlanActual   PlanSource = "IST"
	PlanForecast PlanSource = "Projection"
	// PlanStart is the capacity times the team's start rate, used while there is no history.
	PlanStart PlanSource = "Start"
)

// SprintInput is what the engine calculates a sprint from.
type SprintInput struct {
	ID             string          `json:"id"`
	Capacity       *float64        `json:"capacity"`
	CapacitySource *CapacitySource `json:"capacity_source"`
	Commitment     *float64        `json:"commitment"`
	Velocity       *float64        `json:"velocity"`
	ScopeCreep     *float64        `json:"scope_creep"`
	Planning       *model.Planning `json:"planning"`
}

// Metric is a value with its rolling average and trend.
type Metric struct {
	Value   *float64 `json:"value"`
	Average *float64 `json:"average"`
	Trend   *float64 `json:"trend"`
}

// SprintResult is the result for one sprint.
type SprintResult struct {
	Input              SprintInput `json:"input"`
	Commitment         Metric      `json:"commitment"`
	Velocity           Metric      `json:"velocity"`
	Capacity           Metric      `json:"capacity"`
	NormalizedVelocity Metric      `json:"normalized_velocity"`
	Fulfillment        Metric      `json:"fulfillment"`
	ScopeCreep         Metric      `json:"scope_creep"`
	// PlanCapacity is the capacity the Forecast PLAN was calculated with (recorded, from people
	// and calendar, or trend).
	PlanCapacity       *float64        `json:"plan_capacity"`
	PlanCapacitySource *CapacitySource `json:"plan_capacity_source"`
	Plan               *float64        `json:"plan"`
	PlanSource         *PlanSource     `json:"plan_source"`
	// Samples is the number of all values so far behind the normalized velocity trend;
	// TrendFallback says that flat was used instead of the chosen trend mode because of thin
	// history.
	Samples       int      `json:"samples"`
	TrendFallback bool     `json:"trend_fallback"`
	Roadmap       *float64 `json:"roadmap"`
	SmallStuff    *float64 `json:"small_stuff"`
	PlanningTotal *float64 `json:"planning_total"`
	PlanningDelta *float64 `json:"planning_delta"`
}

// ID is the sprint's ID.
func (r SprintResult) ID() string { return r.Input.ID }

func metricSeries(values Series, s model.ForecastSettings) ([]Metric, []bool, error) {
	averages := RollingAverage(values, s.Window)
	var trends Series
	var fallback []bool
	if ThinHistory(values, s.Window) {
		// Thin history: only the average, no projection of an increase.
		t, _, err := trendOf(averages, model.TrendFlat)
		if err != nil {
			return nil, nil, err
		}
		trends = t
		mode, err := ParseTrendMode(s.TrendMode)
		if err != nil {
			return nil, nil, err
		}
		fallback = make([]bool, len(values))
		for i := range fallback {
			fallback[i] = mode != model.TrendFlat
		}
	} else {
		t, f, err := trendOf(averages, s.TrendMode)
		if err != nil {
			return nil, nil, err
		}
		trends, fallback = t, f
	}
	metrics := make([]Metric, len(values))
	for i := range values {
		metrics[i] = Metric{Value: values[i], Average: averages[i], Trend: trends[i]}
	}
	return metrics, fallback, nil
}

// Compute calculates the metrics, trends and forecast of every sprint. It fails only for an
// unknown trend mode.
func Compute(inputs []SprintInput, settings model.ForecastSettings) ([]SprintResult, error) {
	ref := settings.ReferenceCapacity
	n := len(inputs)
	capacity := make(Series, n)
	velocity := make(Series, n)
	commitment := make(Series, n)
	scope := make(Series, n)
	normalized := make(Series, n)
	fulfillment := make(Series, n)
	for i, s := range inputs {
		capacity[i], velocity[i], commitment[i], scope[i] = s.Capacity, s.Velocity, s.Commitment, s.ScopeCreep
		if s.Velocity != nil && s.Capacity != nil && *s.Capacity != 0 {
			normalized[i] = model.Ptr(*s.Velocity / *s.Capacity * ref)
		}
		fulfillment[i] = div(s.Velocity, s.Commitment)
	}

	mCommit, _, err := metricSeries(commitment, settings)
	if err != nil {
		return nil, err
	}
	mVel, _, _ := metricSeries(velocity, settings)
	mCap, _, _ := metricSeries(capacity, settings)
	mNorm, normFallback, _ := metricSeries(normalized, settings)
	mFul, _, _ := metricSeries(fulfillment, settings)
	mScope, _, _ := metricSeries(scope, settings)

	results := make([]SprintResult, n)
	for i, s := range inputs {
		var planCap *float64
		var planCapSource *CapacitySource
		if s.Capacity != nil {
			planCap, planCapSource = s.Capacity, s.CapacitySource
		} else {
			planCap = mCap[i].Trend
			if planCap != nil {
				src := SourceTrend
				planCapSource = &src
			}
		}

		var plan *float64
		var planSource *PlanSource
		nTrend := mNorm[i].Trend
		switch {
		case nTrend != nil && planCap != nil:
			p := RoundDown((*nTrend/ref)*(*planCap), settings.Rounding)
			p = maxZero(p)
			plan = &p
			src := PlanForecast
			planSource = &src
		case s.Commitment != nil:
			// The fallback to Commitment is also rounded down.
			p := RoundDown(*s.Commitment, settings.Rounding)
			plan = &p
			src := PlanActual
			planSource = &src
		case settings.StartRate > 0 && planCap != nil:
			// No history yet: the team's own start rate stands in for the trend.
			p := maxZero(RoundDown(*planCap*settings.StartRate, settings.Rounding))
			plan = &p
			src := PlanStart
			planSource = &src
		}

		var roadmap, small *float64
		if plan != nil {
			r := float64(*plan * settings.RoadmapShare)
			roadmap = &r
			small = model.Ptr(*plan - r)
		}
		var planningTotal *float64
		if s.Planning != nil {
			planningTotal = model.Ptr(s.Planning.Total())
		}
		var delta *float64
		if plan != nil && planningTotal != nil {
			delta = model.Ptr(*plan - *planningTotal)
		}
		samples := 0
		for _, v := range normalized[:i] {
			if v != nil {
				samples++
			}
		}
		results[i] = SprintResult{
			Input:              s,
			Commitment:         mCommit[i],
			Velocity:           mVel[i],
			Capacity:           mCap[i],
			NormalizedVelocity: mNorm[i],
			Fulfillment:        mFul[i],
			ScopeCreep:         mScope[i],
			PlanCapacity:       planCap,
			PlanCapacitySource: planCapSource,
			Plan:               plan,
			PlanSource:         planSource,
			Samples:            samples,
			TrendFallback:      normFallback[i] && planSource != nil && *planSource == PlanForecast,
			Roadmap:            roadmap,
			SmallStuff:         small,
			PlanningTotal:      planningTotal,
			PlanningDelta:      delta,
		}
	}
	return results, nil
}

// maxZero is Python's max(x, 0.0): it keeps -0.0, where math.Max turns it into +0.
func maxZero(x float64) float64 {
	if x < 0 {
		return 0
	}
	return x
}
