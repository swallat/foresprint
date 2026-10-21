// Package forecast connects the sprint calendar, the capacity calculator and the calculation
// engine into the forecast of a team. It ports src/foresprint/forecast.py.
package forecast

import (
	"fmt"
	"math"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/coretypes"
	"github.com/swallat/foresprint/internal/engine"
)

// TimelineEntry is a sprint with its result.
type TimelineEntry struct {
	Sprint coretypes.Sprint `json:"sprint"`
	// Recorded is false for sprints generated from the calendar only (no file).
	Recorded bool                `json:"recorded"`
	Result   engine.SprintResult `json:"result"`
	// CapacityDigits are the digits to which this team's capacity is displayed
	// (Team.Capacity.Rounding, like capacity.Breakdown.Rounded).
	CapacityDigits int `json:"capacity_digits"`
}

// Forecast is the calculated timeline of a team.
type Forecast struct {
	Data    *coretypes.TeamData
	Today   time.Time
	Entries []TimelineEntry
	// Absences is the absence history used to estimate unknown absences (nil = without a
	// people list).
	Absences *capacity.AbsenceHistory
}

// Current is the running sprint, nil if none runs today.
func (f *Forecast) Current() *TimelineEntry {
	for i := range f.Entries {
		s := f.Entries[i].Sprint
		if !s.Start.After(f.Today) && f.Today.Before(s.End) {
			return &f.Entries[i]
		}
	}
	return nil
}

// Upcoming is the current sprint and the following Horizon sprints.
func (f *Forecast) Upcoming() []*TimelineEntry {
	var future []*TimelineEntry
	for i := range f.Entries {
		if f.Entries[i].Sprint.End.After(f.Today) {
			future = append(future, &f.Entries[i])
		}
	}
	if n := f.Data.Team.Forecast.Horizon + 1; n >= 0 && len(future) > n {
		future = future[:n]
	}
	return future
}

// History is the completed sprints, oldest first.
func (f *Forecast) History() []*TimelineEntry {
	var past []*TimelineEntry
	for i := range f.Entries {
		if !f.Entries[i].Sprint.End.After(f.Today) {
			past = append(past, &f.Entries[i])
		}
	}
	return past
}

// HistoryLast is the last count completed sprints (none for count <= 0).
func (f *Forecast) HistoryLast(count int) []*TimelineEntry {
	past := f.History()
	if count <= 0 {
		return nil
	}
	if len(past) > count {
		past = past[len(past)-count:]
	}
	return past
}

// Entry is the entry of the sprint, nil if there is none.
func (f *Forecast) Entry(sprintID string) *TimelineEntry {
	for i := range f.Entries {
		if f.Entries[i].Sprint.ID == sprintID {
			return &f.Entries[i]
		}
	}
	return nil
}

// Purpose names what a default sprint is suggested for.
type Purpose string

// The purposes of DefaultEntry.
const (
	// PurposeCurrent is the running sprint.
	PurposeCurrent Purpose = "current"
	// PurposePlanning is the next Planning: the earliest running or future sprint without a
	// Commitment.
	PurposePlanning Purpose = "planning"
	// PurposeNext is the next sprint (absences).
	PurposeNext Purpose = "next"
	// PurposeReview is the Review: the latest completed sprint without a velocity, else the
	// running one.
	PurposeReview Purpose = "review"
)

// DefaultEntry is the suggestion for a purpose; nil if there is none.
func (f *Forecast) DefaultEntry(purpose Purpose) (*TimelineEntry, error) {
	switch purpose {
	case PurposeCurrent:
		return f.Current(), nil
	case PurposePlanning:
		for i := range f.Entries {
			e := &f.Entries[i]
			if e.Sprint.End.After(f.Today) && e.Sprint.Commitment == nil {
				return e, nil
			}
		}
		return nil, nil
	case PurposeNext:
		for i := range f.Entries {
			if f.Entries[i].Sprint.Start.After(f.Today) {
				return &f.Entries[i], nil
			}
		}
		return nil, nil
	case PurposeReview:
		past := f.History()
		for i := len(past) - 1; i >= 0; i-- {
			if past[i].Sprint.Velocity == nil {
				return past[i], nil
			}
		}
		return f.Current(), nil
	}
	return nil, fmt.Errorf("unknown purpose %q", purpose)
}

// SprintRef is a sprint of the timeline and whether it is recorded.
type SprintRef struct {
	Sprint   coretypes.Sprint
	Recorded bool
}

// Timeline is the recorded sprints plus the generated follow-up sprints up to Horizon sprints
// after today.
func Timeline(data *coretypes.TeamData, today time.Time) ([]SprintRef, error) {
	line := make([]SprintRef, 0, len(data.Sprints)+data.Team.Forecast.Horizon)
	for _, s := range data.Sprints {
		line = append(line, SprintRef{s, true})
	}
	horizon := data.Team.Forecast.Horizon
	var last *coretypes.Sprint
	if len(data.Sprints) > 0 {
		last = &data.Sprints[len(data.Sprints)-1]
	}
	for {
		future := 0
		for _, r := range line {
			if r.Sprint.Start.After(today) {
				future++
			}
		}
		if future >= horizon {
			return line, nil
		}
		next, err := calendar.FollowingSprint(data.Team, last)
		if err != nil {
			return nil, err
		}
		last = &next
		line = append(line, SprintRef{next, false})
	}
}

// FindSprint is the sprint from storage or, if it has no file yet, generated from the calendar
// (up to maxAhead sprints beyond the last recorded one); nil = unknown.
func FindSprint(data *coretypes.TeamData, sprintID string, maxAhead int) (*coretypes.Sprint, error) {
	if s := data.Sprint(sprintID); s != nil {
		return s, nil
	}
	var last *coretypes.Sprint
	if len(data.Sprints) > 0 {
		last = &data.Sprints[len(data.Sprints)-1]
	}
	for i := 0; i < maxAhead; i++ {
		next, err := calendar.FollowingSprint(data.Team, last)
		if err != nil {
			return nil, err
		}
		last = &next
		if next.ID == sprintID {
			return last, nil
		}
	}
	return nil, nil
}

// DefaultMaxAhead is the number of sprints FindSprint looks ahead in the Python core.
const (
	DefaultFindAhead   = 200
	DefaultLookupAhead = 52
)

// LookupSprint is the sprint by ID: recorded, in the forecast, or generated from the calendar up
// to maxAhead sprints beyond the last recorded one; nil = unknown.
func (f *Forecast) LookupSprint(sprintID string, maxAhead int) (*coretypes.Sprint, error) {
	if s := f.Data.Sprint(sprintID); s != nil {
		return s, nil
	}
	if e := f.Entry(sprintID); e != nil {
		return &e.Sprint, nil
	}
	return FindSprint(f.Data, sprintID, maxAhead)
}

// ApplyPlanning applies the Planning inputs to the sprint.
//
// The control calculation (carryover, backlog, corrections) is optional; empty or 0 means "not
// recorded". An empty Commitment is prefilled with carryover + backlog. It reports whether it
// was prefilled.
func ApplyPlanning(sprint *coretypes.Sprint, commitment *float64, planning *coretypes.Planning) bool {
	if planning != nil && planning.Carryover == 0 && planning.Backlog == 0 && len(planning.Corrections) == 0 {
		planning = nil
	}
	sprint.Planning = planning
	planned := 0.0
	if planning != nil {
		planned = planning.Committed()
	}
	prefilled := commitment == nil && planned > 0
	if prefilled {
		sprint.Commitment = coretypes.Float(planned)
	} else {
		sprint.Commitment = commitment
	}
	return prefilled
}

// FreezePlan remembers the Forecast PLAN at Planning time, the basis of the default distribution
// per product. An already frozen value is kept unless refreeze; completed sprints stay unchanged.
func FreezePlan(sprint *coretypes.Sprint, entry *TimelineEntry, today time.Time, refreeze bool) {
	if entry == nil || !sprint.End.After(today) || entry.Result.Plan == nil {
		return
	}
	if sprint.ForecastPlan != nil && !refreeze {
		return
	}
	sprint.ForecastPlan = coretypes.Float(*entry.Result.Plan)
}

// RefreezeOffer is (frozen, current) if the Forecast PLAN has changed since freezing.
func RefreezeOffer(sprint *coretypes.Sprint, entry *TimelineEntry) (frozen, current float64, ok bool) {
	if entry == nil || sprint.ForecastPlan == nil || entry.Result.Plan == nil {
		return 0, 0, false
	}
	if math.Abs(*sprint.ForecastPlan-*entry.Result.Plan) < 1e-9 {
		return 0, 0, false
	}
	return *sprint.ForecastPlan, *entry.Result.Plan, true
}

// AbsencesKnown reports whether the absences count as confirmed: if some are entered, if "nobody is absent" was
// explicitly confirmed (Absences page), or, for older files without a stored state, if the
// sprint was already planned or evaluated. Announced absences from the PO pre-planning confirm
// nothing.
func AbsencesKnown(sprint coretypes.Sprint) bool {
	return coretypes.AbsenceStatus(sprint) == coretypes.Confirmed
}

// ResolveCapacity is the capacity of a sprint and its source (nil, nil if it cannot be
// determined).
//
// With a people list it is always calculated from calendar and people (holidays, sprint length,
// FTE); only unknown absences are estimated. The capacity trend applies only to teams without a
// people list.
func ResolveCapacity(data *coretypes.TeamData, sprint coretypes.Sprint, history *capacity.AbsenceHistory) (*float64, *engine.CapacitySource) {
	src := func(s engine.CapacitySource) *engine.CapacitySource { return &s }
	if sprint.Capacity != nil {
		return sprint.Capacity, src(engine.SourceRecorded)
	}
	if len(data.People) == 0 {
		return nil, nil
	}
	switch coretypes.AbsenceStatus(sprint) {
	case coretypes.Confirmed:
		return coretypes.Float(capacity.Sprint(data.Team, data.People, sprint, 0).Capacity), src(engine.SourcePeople)
	case coretypes.Expected:
		return coretypes.Float(capacity.WithExpectedAbsences(data.Team, data.People, sprint)), src(engine.SourceExpected)
	}
	var rate *float64
	if history != nil {
		rate = history.Rate
	}
	r := 0.0
	if rate != nil {
		r = *rate
	}
	c := coretypes.Float(capacity.Estimated(data.Team, data.People, sprint, r))
	if rate != nil {
		return c, src(engine.SourceEstimated)
	}
	return c, src(engine.SourceCalendar)
}

// Build calculates the forecast of a team. A zero today means today's date.
func Build(data *coretypes.TeamData, today time.Time) (*Forecast, error) {
	if today.IsZero() {
		y, m, d := time.Now().Date()
		today = coretypes.NewDate(y, m, d)
	}
	line, err := Timeline(data, today)
	if err != nil {
		return nil, err
	}
	var history *capacity.AbsenceHistory
	if len(data.People) > 0 {
		var past []coretypes.Sprint
		for _, r := range line {
			if r.Recorded && !r.Sprint.End.After(today) {
				past = append(past, r.Sprint)
			}
		}
		h := capacity.History(data.Team, data.People, past, data.Team.Capacity.AbsenceHistory)
		history = &h
	}
	inputs := make([]engine.SprintInput, len(line))
	for i, r := range line {
		c, source := ResolveCapacity(data, r.Sprint, history)
		inputs[i] = engine.SprintInput{
			ID:             r.Sprint.ID,
			Capacity:       c,
			CapacitySource: source,
			Commitment:     r.Sprint.Commitment,
			Velocity:       r.Sprint.Velocity,
			ScopeCreep:     r.Sprint.ScopeCreep,
			Planning:       r.Sprint.Planning,
		}
	}
	results, err := engine.Compute(inputs, data.Team.Forecast)
	if err != nil {
		return nil, err
	}
	entries := make([]TimelineEntry, len(line))
	for i, r := range line {
		entries[i] = TimelineEntry{
			Sprint:         r.Sprint,
			Recorded:       r.Recorded,
			Result:         results[i],
			CapacityDigits: data.Team.Capacity.Rounding,
		}
	}
	return &Forecast{Data: data, Today: today, Entries: entries, Absences: history}, nil
}
