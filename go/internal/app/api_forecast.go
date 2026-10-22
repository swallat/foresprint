package app

import (
	"errors"
	"time"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
)

// simulationRuns and simulationSeed make "when is it done?" repeatable: the same data gives the
// same answer.
const (
	simulationRuns = 10000
	simulationSeed = 42
)

func (a *API) forecastOf(team string) (*storage.TeamData, *forecast.Forecast, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return nil, nil, err
	}
	fc, err := forecast.Build(data, today())
	if err != nil {
		return nil, nil, err
	}
	return data, fc, nil
}

func today() time.Time {
	y, m, d := time.Now().Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

func row(fc *forecast.Forecast, e *forecast.TimelineEntry, band bool) ForecastRow {
	r := e.Result
	s := e.Sprint
	state := "future"
	switch {
	case !s.End.After(fc.Today):
		state = "past"
	case !s.Start.After(fc.Today):
		state = "current"
	}
	out := ForecastRow{
		ID:                 s.ID,
		Start:              s.Start.Format("2006-01-02"),
		End:                s.End.Format("2006-01-02"),
		State:              state,
		Recorded:           e.Recorded,
		Capacity:           r.Capacity.Value,
		Commitment:         r.Commitment.Value,
		Velocity:           r.Velocity.Value,
		NormalizedVelocity: r.NormalizedVelocity.Value,
		Average:            r.NormalizedVelocity.Average,
		Trend:              r.NormalizedVelocity.Trend,
		Fulfillment:        r.Fulfillment.Value,
		Plan:               r.Plan,
		Plannable:          r.Roadmap,
		Small:              r.SmallStuff,
	}
	if state != "past" {
		out.Capacity = r.PlanCapacity
		if r.PlanCapacitySource != nil {
			out.CapacitySource = string(*r.PlanCapacitySource)
			out.Unsure = r.PlanCapacitySource.Unsure()
		}
	} else if r.Input.CapacitySource != nil {
		out.CapacitySource = string(*r.Input.CapacitySource)
	}
	if r.PlanSource != nil {
		out.PlanSource = "projection"
		if *r.PlanSource == engine.PlanActual {
			out.PlanSource = "actual"
		}
	}
	if band {
		if b, ok := analysis.BandOf(fc, e); ok {
			out.Low, out.High = &b.Low, &b.High
		}
	}
	return out
}

// Forecast returns the history and the coming sprints of a team with the plan, the range and
// the settings the calculation used.
func (a *API) Forecast(team string) (ForecastView, error) {
	data, fc, err := a.forecastOf(team)
	if err != nil {
		return ForecastView{}, err
	}
	s := data.Team.Forecast
	v := ForecastView{
		Team:              team,
		Today:             fc.Today.Format("2006-01-02"),
		ReferenceCapacity: s.ReferenceCapacity,
		Window:            s.Window,
		RoadmapShare:      s.RoadmapShare,
		TrendMode:         string(s.TrendMode),
		Horizon:           s.Horizon,
		Rounding:          s.Rounding,
		Samples:           analysis.SampleCount(fc),
		FewSamples:        analysis.FewSamples(fc),
		Past:              []ForecastRow{},
		Upcoming:          []ForecastRow{},
	}
	for _, e := range fc.History() {
		v.Past = append(v.Past, row(fc, e, false))
	}
	for _, e := range fc.Upcoming() {
		v.Upcoming = append(v.Upcoming, row(fc, e, true))
	}
	for _, r := range v.Upcoming {
		if r.Trend != nil && s.ReferenceCapacity > 0 {
			rate := *r.Trend / s.ReferenceCapacity
			v.Rate = &rate
			break
		}
	}
	return v, nil
}

// ForecastWhatIf calculates the coming sprints again with fewer person days (extraAbsenceDays
// per sprint, in addition to the known absences) and a changed share of the capacity that turns
// into points (focusPercent, 100 = as measured). Nothing is saved.
func (a *API) ForecastWhatIf(team string, extraAbsenceDays, focusPercent float64) ([]WhatIfRow, error) {
	if extraAbsenceDays < 0 || focusPercent < 0 {
		return nil, errors.New(i18n.T("Absence days and focus must not be negative."))
	}
	data, fc, err := a.forecastOf(team)
	if err != nil {
		return nil, err
	}
	s := data.Team.Forecast
	out := []WhatIfRow{}
	for _, e := range fc.Upcoming() {
		r := e.Result
		if r.Plan == nil || r.PlanCapacity == nil || r.NormalizedVelocity.Trend == nil {
			continue
		}
		capacity := max(0, *r.PlanCapacity-extraAbsenceDays)
		forecastValue := engine.RoundDown(analysis.PlanAt(s, *r.NormalizedVelocity.Trend, capacity)*focusPercent/100, s.Rounding)
		out = append(out, WhatIfRow{ID: e.Sprint.ID, Capacity: capacity, Forecast: forecastValue, Base: *r.Plan, Delta: forecastValue - *r.Plan})
	}
	return out, nil
}

// ForecastWhenDone simulates in which coming sprint a remaining quantity of points is done.
// sharePercent is the share of the forecast that is available for it (0 to 100).
func (a *API) ForecastWhenDone(team string, remaining, sharePercent float64) (WhenDoneView, error) {
	if remaining < 0 || sharePercent < 0 || sharePercent > 100 {
		return WhenDoneView{}, errors.New(i18n.T("Remaining work must not be negative and the share must be between 0 and 100."))
	}
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return WhenDoneView{}, err
	}
	c, err := analysis.Simulate(data, today(), remaining, sharePercent/100, analysis.DefaultMaxSprints, simulationRuns, simulationSeed)
	if err != nil {
		return WhenDoneView{}, err
	}
	if c == nil {
		return WhenDoneView{Remaining: remaining, Share: sharePercent, Sprints: []string{}, Cumulative: []float64{}, TrendCapacity: []string{}}, nil
	}
	v := WhenDoneView{
		Remaining: c.Remaining, Share: sharePercent, Runs: c.Runs, Samples: c.Samples,
		Sprints: c.Sprints, Cumulative: c.Cumulative, PerSprint: c.PerSprint,
		TrendCapacity: c.TrendCapacitySprints, Available: true,
	}
	if c.P50 != nil {
		v.P50 = *c.P50
	}
	if c.P85 != nil {
		v.P85 = *c.P85
	}
	return v, nil
}
