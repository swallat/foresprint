// Package analysis has the supplementary analyses of the forecast. They do not change any
// existing values. It ports src/foresprint/analysis.py.
//
//   - Range: forecast with the lowest, middle and highest normalized velocity of the last
//     sprints instead of the trend.
//   - Focus factor: velocity / capacity (independent of the reference capacity).
//   - Buffer recommendation: average scope creep of the last sprints compared to the
//     small-items share.
//   - Completion: Monte Carlo simulation of the sprint in which a remaining quantity is done.
package analysis

import (
	"math"
	"time"

	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/pyrand"
	"github.com/swallat/foresprint/internal/storage"
)

// MinSamples is the number of sprints with a velocity below which the range and the frequencies
// are only rough hints.
const MinSamples = 5

// recent is the last window values that are set.
func recent(values []*float64, window int) []float64 {
	var present []float64
	for _, v := range values {
		if v != nil {
			present = append(present, *v)
		}
	}
	if window > 0 && len(present) > window {
		present = present[len(present)-window:]
	}
	return present
}

// PlanBasis are the sprints whose velocity the engine uses for the plan: the completed ones and
// the current sprint (once its review value is recorded, it has a normalized velocity).
//
// The guarantee "the plan lies within the range" holds up to and including the current sprint.
// The engine also averages in a future sprint (start after today) with a recorded value; that
// one deliberately does not belong here, so the plan can then lie outside the range (known,
// open edge case).
func PlanBasis(fc *forecast.Forecast) []*forecast.TimelineEntry {
	var out []*forecast.TimelineEntry
	for i := range fc.Entries {
		if fc.Phase(fc.Entries[i].Sprint) != model.PhaseOpen {
			out = append(out, &fc.Entries[i])
		}
	}
	return out
}

// NormalizedHistory is the normalized velocity of the last Window sprints with a value:
// completed sprints and the current one, once its review value (velocity) is recorded.
func NormalizedHistory(fc *forecast.Forecast) []float64 {
	var values []*float64
	for _, e := range PlanBasis(fc) {
		values = append(values, e.Result.NormalizedVelocity.Value)
	}
	return recent(values, fc.Data.Team.Forecast.Window)
}

// SampleCount is the number of sprints with a normalized velocity that the forecast actually
// draws from: at most Window (sample for the range and the simulation).
func SampleCount(fc *forecast.Forecast) int { return len(NormalizedHistory(fc)) }

// AvailableCount is the number of all available sprints with a normalized velocity (uncapped,
// the same set of values as PlanBasis). It decides whether a forecast exists yet
// (MinThinHistory); SampleCount, in contrast, is the sample of the calculation capped at Window.
func AvailableCount(fc *forecast.Forecast) int {
	n := 0
	for _, e := range PlanBasis(fc) {
		if e.Result.NormalizedVelocity.Value != nil {
			n++
		}
	}
	return n
}

// FewSamples reports whether there are fewer samples than MinSamples.
func FewSamples(fc *forecast.Forecast) bool { return SampleCount(fc) < MinSamples }

// --- Range ---------------------------------------------------------------------------------

// PlanAt is the Forecast PLAN for a normalized velocity and a capacity: scaled to the capacity
// and rounded down to the team's precision (the calculation behind Band).
func PlanAt(settings model.ForecastSettings, nvel, capacity float64) float64 {
	return engine.RoundDown(nvel/settings.ReferenceCapacity*capacity, settings.Rounding)
}

// Band is the forecast range of a sprint.
type Band struct {
	Low     float64 `json:"low"`
	Mid     float64 `json:"mid"`
	High    float64 `json:"high"`
	Samples int     `json:"samples"`
}

// BandOf is the forecast range for a future sprint, from the spread of the last sprints; ok is
// false if there are fewer than two samples or no capacity.
func BandOf(fc *forecast.Forecast, entry *forecast.TimelineEntry) (Band, bool) {
	values := NormalizedHistory(fc)
	capacity := entry.Result.PlanCapacity
	if len(values) < 2 || capacity == nil {
		return Band{}, false
	}
	settings := fc.Data.Team.Forecast
	lo, hi := values[0], values[0]
	for _, v := range values {
		lo, hi = min(lo, v), max(hi, v)
	}
	return Band{
		Low:     PlanAt(settings, lo, *capacity),
		Mid:     PlanAt(settings, pymath.Median(values), *capacity),
		High:    PlanAt(settings, hi, *capacity),
		Samples: len(values),
	}, true
}

// BandAroundPlan is the range of the Forecast PLAN of the entry: the plan with the spread of the
// last sprints around it. The spread is how far the lowest and the highest normalized velocity
// lie from their median (BandOf); that distance is laid around the plan: the plan stands where
// the median stood, and the range does not depend on where the trend has gone.
func BandAroundPlan(fc *forecast.Forecast, entry *forecast.TimelineEntry) (Band, bool) {
	b, ok := BandOf(fc, entry)
	if !ok || entry.Result.Plan == nil {
		return b, ok
	}
	plan, digits := *entry.Result.Plan, fc.Data.Team.Forecast.Rounding
	below, above := b.Mid-b.Low, b.High-b.Mid
	b.Low = engine.RoundHalfUp(math.Max(plan-below, 0), digits)
	b.Mid = plan
	b.High = engine.RoundHalfUp(plan+above, digits)
	return b, true
}

// --- Focus factor --------------------------------------------------------------------------

// FocusFactor is velocity / capacity of an entry; nil if either is missing or the capacity is 0.
func FocusFactor(e *forecast.TimelineEntry) *float64 {
	r := e.Result
	if r.Velocity.Value == nil || r.Capacity.Value == nil || *r.Capacity.Value == 0 {
		return nil
	}
	return model.Ptr(*r.Velocity.Value / *r.Capacity.Value)
}

// AverageFocusFactor is the mean focus factor of the last Window completed sprints; nil without
// values.
func AverageFocusFactor(fc *forecast.Forecast) *float64 {
	var factors []*float64
	for _, e := range fc.History() {
		factors = append(factors, FocusFactor(e))
	}
	values := recent(factors, fc.Data.Team.Forecast.Window)
	if len(values) == 0 {
		return nil
	}
	return model.Ptr(pymath.FMean(values))
}

// --- Buffer --------------------------------------------------------------------------------

// BufferHint compares the added-later share with the small-items share.
type BufferHint struct {
	// AverageScopeCreep is relative to the commitment of the respective sprint (as recorded).
	AverageScopeCreep *float64 `json:"average_scope_creep"`
	Samples           int      `json:"samples"`
	// AverageLateShare is the same converted to the base of the small-items share: the Forecast
	// PLAN.
	AverageLateShare *float64 `json:"average_late_share"`
	// ConfiguredSmallStuff is 1 − plannable share, relative to the Forecast PLAN.
	ConfiguredSmallStuff float64 `json:"configured_small_stuff"`
}

// SufficientData reports whether there are enough samples to judge.
func (b BufferHint) SufficientData() bool { return b.Samples >= 3 }

// BufferTooSmall reports whether the late share exceeds the configured small-items share.
func (b BufferHint) BufferTooSmall() bool {
	return b.SufficientData() && b.AverageLateShare != nil && *b.AverageLateShare > b.ConfiguredSmallStuff
}

// lateShare is the quantity added later, as a share of the sprint's Forecast PLAN (frozen at
// Planning, otherwise as calculated), the same base as the small-items share. Scope creep
// itself is relative to the commitment.
func lateShare(e *forecast.TimelineEntry) *float64 {
	s := e.Sprint
	if s.ScopeCreep == nil {
		return nil
	}
	plan := s.ForecastPlan
	if plan == nil {
		plan = e.Result.Plan
	}
	if s.Commitment == nil || plan == nil || *plan == 0 {
		return s.ScopeCreep // cannot be converted without a commitment or plan
	}
	return model.Ptr(*s.ScopeCreep * *s.Commitment / *plan)
}

// Buffer is the buffer recommendation of the forecast.
func Buffer(fc *forecast.Forecast) BufferHint {
	window := fc.Data.Team.Forecast.Window
	var creep, late []*float64
	for _, e := range fc.History() {
		creep = append(creep, e.Sprint.ScopeCreep)
		late = append(late, lateShare(e))
	}
	values := recent(creep, window)
	lates := recent(late, window)
	hint := BufferHint{
		Samples:              len(values),
		ConfiguredSmallStuff: 1 - fc.Data.Team.Forecast.RoadmapShare,
	}
	if len(values) > 0 {
		hint.AverageScopeCreep = model.Ptr(pymath.FMean(values))
	}
	if len(lates) > 0 {
		hint.AverageLateShare = model.Ptr(pymath.FMean(lates))
	}
	return hint
}

// --- Completion (Monte Carlo) --------------------------------------------------------------

// Completion is the result of the Monte Carlo simulation.
type Completion struct {
	Remaining float64 `json:"remaining"`
	// Share is the share of the forecast available for the remaining quantity.
	Share float64 `json:"share"`
	Runs  int     `json:"runs"`
	// P50 and P85 are the sprint IDs in which the remaining quantity is done in 50 % or 85 % of
	// the simulation runs (model-dependent frequency, not a commitment); nil = not within the
	// period.
	P50     *string  `json:"p50"`
	P85     *string  `json:"p85"`
	Sprints []string `json:"sprints"`
	// Samples is the number of sprints the simulation draws from.
	Samples int `json:"samples"`
	// Cumulative is the probability of being done by the end of sprint i.
	Cumulative           []float64 `json:"cumulative"`
	TrendCapacitySprints []string  `json:"trend_capacity_sprints"`
	// PerSprint is the expected quantity per sprint for the remaining quantity (median velocity
	// × median capacity × share).
	PerSprint float64 `json:"per_sprint"`
}

// HorizonEntry is a future sprint of a long forecast with the capacity to calculate with.
type HorizonEntry struct {
	Entry    *forecast.TimelineEntry
	Capacity float64
	// Trend is true if the sprint lies beyond the people list (capacity source trend or none):
	// it counts with the average capacity of the last sprints instead of the (over many sprints
	// unstable) capacity trend.
	Trend bool
}

// Sprint is the entry's sprint.
func (h HorizonEntry) Sprint() model.Sprint { return h.Entry.Sprint }

// DefaultMaxSprints is the length of the long forecast.
const DefaultMaxSprints = 26

// HorizonForecast is the forecast with maxSprints sprints after today (the team's horizon is
// usually much shorter); data stays unchanged.
func HorizonForecast(data *storage.TeamData, today time.Time, maxSprints int) (*forecast.Forecast, error) {
	longer := *data
	longer.Team.Forecast.Horizon = maxSprints
	return forecast.Build(&longer, today)
}

// HorizonEntries are the future sprints of fc (start after today) with the capacity to calculate
// with: as forecast while the people list reaches, beyond it the average capacity of the last
// Window sprints.
func HorizonEntries(fc *forecast.Forecast, maxSprints int) []HorizonEntry {
	window := fc.Data.Team.Forecast.Window
	var caps []*float64
	for _, e := range fc.History() {
		caps = append(caps, e.Result.Capacity.Value)
	}
	values := recent(caps, window)
	if len(values) == 0 {
		values = []float64{0}
	}
	avg := pymath.FMean(values)
	var out []HorizonEntry
	for i := range fc.Entries {
		e := &fc.Entries[i]
		if fc.Phase(e.Sprint) != model.PhaseOpen {
			continue
		}
		if len(out) == maxSprints {
			break
		}
		switch src := e.Result.PlanCapacitySource; {
		case src != nil && (*src == engine.SourceRecorded || *src == engine.SourcePeople ||
			*src == engine.SourceEstimated || *src == engine.SourceCalendar || *src == engine.SourceExpected):
			c := 0.0
			if e.Result.PlanCapacity != nil {
				c = *e.Result.PlanCapacity
			}
			out = append(out, HorizonEntry{e, c, false})
		default:
			out = append(out, HorizonEntry{e, avg, true})
		}
	}
	return out
}

// Simulate simulates, starting with the next sprint, when remaining is done; nil if there are
// fewer than two samples or nothing to do.
//
// share is the share of the forecast available for the remaining quantity per sprint, e.g.
// plannable share × project share (0.8 × 0.5 = 0.4).
//
// For each sprint a normalized velocity of the last sprints is drawn at random and converted
// with the sprint's capacity. For sprints without a people list (capacity only as a trend), the
// average capacity of the last sprints is used instead of the trend (which is unstable over
// many sprints). The draws are those of Python's random.Random(seed).
func Simulate(data *storage.TeamData, today time.Time, remaining, share float64, maxSprints, runs int, seed int64) (*Completion, error) {
	fc, err := HorizonForecast(data, today, maxSprints)
	if err != nil {
		return nil, err
	}
	history := NormalizedHistory(fc)
	if len(history) < 2 || remaining <= 0 || share <= 0 {
		return nil, nil
	}
	horizon := HorizonEntries(fc, maxSprints)
	capacities := make([]float64, len(horizon))
	ids := make([]string, len(horizon))
	trendIDs := []string{}
	for i, h := range horizon {
		capacities[i] = h.Capacity
		ids[i] = h.Entry.Sprint.ID
		if h.Trend {
			trendIDs = append(trendIDs, h.Entry.Sprint.ID)
		}
	}

	ref := data.Team.Forecast.ReferenceCapacity
	rng := pyrand.New(seed)
	finishedIn := make([]int, len(horizon))
	for run := 0; run < runs; run++ {
		done := 0.0
		for i, c := range capacities {
			done += float64(float64(float64(history[rng.Choice(len(history))]/ref)*c) * share)
			if done >= remaining {
				finishedIn[i]++
				break
			}
		}
	}

	cumulative := make([]float64, len(horizon))
	total := 0
	for i, n := range finishedIn {
		total += n
		cumulative[i] = float64(total) / float64(runs)
	}
	firstReaching := func(p float64) *string {
		for i, c := range cumulative {
			if c >= p {
				return &ids[i]
			}
		}
		return nil
	}
	return &Completion{
		Remaining:            remaining,
		Share:                share,
		Runs:                 runs,
		P50:                  firstReaching(0.5),
		P85:                  firstReaching(0.85),
		Sprints:              ids,
		Samples:              len(history),
		Cumulative:           cumulative,
		TrendCapacitySprints: trendIDs,
		PerSprint:            float64(float64(pymath.Median(history)/ref*pymath.Median(capacities)) * share),
	}, nil
}
