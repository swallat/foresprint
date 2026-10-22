package model

import (
	"maps"
	"slices"
	"time"

	"github.com/swallat/foresprint/internal/pymath"
)

// AbsenceState is the state of a sprint's absences, which determines what the capacity is
// calculated with.
type AbsenceState string

// The absence states.
const (
	// AbsencesUnknown: nothing known; capacity from calendar and people, absences estimated
	// from history.
	AbsencesUnknown AbsenceState = "unknown"
	// AbsencesExpected: announced absences from the PO pre-planning (forecast, not confirmed).
	AbsencesExpected AbsenceState = "expected"
	// AbsencesConfirmed: absences confirmed, including "nobody is absent".
	AbsencesConfirmed AbsenceState = "confirmed"
)

// ProductValues are the values of a product in a sprint, in the team's estimation unit; nil =
// not specified.
type ProductValues struct {
	// Preplanned is provided for in the PO-side pre-planning (before Planning).
	Preplanned *float64
	// Planned is scheduled in the sprint Planning.
	Planned *float64
	// Done is actually done in the sprint (Review).
	Done *float64
	// ProductionPlanned and ProductionDone are the part that requires production access.
	ProductionPlanned *float64
	ProductionDone    *float64
}

// IsEmpty reports whether no value is set.
func (v ProductValues) IsEmpty() bool {
	return v.Preplanned == nil && v.Planned == nil && v.Done == nil &&
		v.ProductionPlanned == nil && v.ProductionDone == nil
}

// Planning is what the board shows at the sprint Planning.
type Planning struct {
	Carryover   float64
	Backlog     float64
	Corrections []float64
}

// Committed is the scheduled amount according to the board: carryover + backlog (equals the
// Commitment).
func (p Planning) Committed() float64 { return p.Carryover + p.Backlog }

// Total is the planning total for the delta: scheduled minus the parts already done.
func (p Planning) Total() float64 {
	return p.Committed() - pymath.Sum(p.Corrections)
}

// Prognosis is the team forecast for a still open sprint, recorded at a PO pre-planning. The
// pre-planning is done several times; every assumption stays traceable.
type Prognosis struct {
	// At is the time of the assumption (without time zone, as written).
	At time.Time
	// Comment says where the assumption comes from.
	Comment    *string
	Commitment *float64
	// NotDone is expected not done, AdditionalDone done in addition to the Commitment.
	NotDone        *float64
	AdditionalDone *float64
	// ExpectedDone is Commitment - NotDone + AdditionalDone.
	ExpectedDone *float64
	// Target, Plan and Preplanned are the forecast PLAN of the target sprint with this
	// assumption and the pre-planning provided for it.
	Target     *string
	Plan       *float64
	Preplanned OrderedMap[float64]
	// Label names the assumption ("A", "B"); several are kept side by side.
	Label *string
	// Finish are the keys of the running sprint's tickets marked "will finish"; Carry the rest
	// of the ones carried over, each with its target.
	Finish []string
	Carry  []CarryItem
	// RestNext is, without tickets, the part of NotDone that continues in the next sprint.
	RestNext *float64
}

// Sprint is one sprint (sprints/<id>.yaml).
type Sprint struct {
	ID    string
	Start time.Time
	End   time.Time
	// Absences are the plannable absences per person (working days).
	Absences map[string]float64
	// Capacity in person days, recorded or frozen at the Review.
	Capacity   *float64
	Commitment *float64
	Velocity   *float64
	ScopeCreep *float64
	Planning   *Planning
	// ForecastPlan is the forecast PLAN at the time of Planning (frozen), the basis of the
	// default distribution.
	ForecastPlan *float64
	// Products are the values per product id.
	Products map[string]ProductValues
	Note     *string
	// ProductionPlanned and ProductionDone are the amount with production access if the team
	// does not use a product distribution.
	ProductionPlanned *float64
	ProductionDone    *float64
	// NotDone was not finished, AdditionalDone was done in addition to the Commitment
	// (Velocity = Commitment - NotDone + AdditionalDone).
	NotDone        *float64
	AdditionalDone *float64
	// AbsenceState is the explicitly stored state. Nil = not stored (older files): then it is
	// derived from the existing fields, see AbsenceStatus.
	AbsenceState *AbsenceState
	// ExpectedAbsences are the announced absences per person from the PO pre-planning
	// (forecast, not yet confirmed).
	ExpectedAbsences map[string]float64
	// Prognoses are the team forecasts from the PO pre-plannings, older first.
	Prognoses []Prognosis
	// Name is a name given by hand; otherwise the naming pattern of the team gives one.
	Name *string
	// CommittedTickets is the ticket list frozen at Planning (the commitment); nil = not frozen.
	CommittedTickets []string
	// Carry and RestNext are the definitive rest entered in the Review; they replace the
	// assumption (see Prognosis).
	Carry    []CarryItem
	RestNext *float64
	// Projects are the values per project id, for teams without tickets: the split of the
	// product amounts over the projects.
	Projects map[string]ProductValues
}

// legacyKnown: in older files without a stored state, absences counted as known if the sprint
// was already planned or evaluated. A file with only, e.g., the PO pre-planning does not
// confirm them.
func (s Sprint) legacyKnown() bool {
	return s.Planning != nil || s.Commitment != nil || s.Velocity != nil || s.ForecastPlan != nil
}

// AbsenceStatus is the state of the absences: confirmed, announced or unknown.
//
// Entered absences are confirmed. Otherwise the stored state applies; if it is missing (older
// files), it is derived from the existing fields. Announced absences only take effect as long
// as nothing is confirmed.
func (s Sprint) AbsenceStatus() AbsenceState {
	if len(s.Absences) > 0 || (s.AbsenceState != nil && *s.AbsenceState == AbsencesConfirmed) {
		return AbsencesConfirmed
	}
	if s.AbsenceState == nil && s.legacyKnown() {
		return AbsencesConfirmed
	}
	if len(s.ExpectedAbsences) > 0 {
		return AbsencesExpected
	}
	return AbsencesUnknown
}

// AbsencesConfirmed reports whether the absences are confirmed.
func (s Sprint) AbsencesConfirmed() bool { return s.AbsenceStatus() == AbsencesConfirmed }

// SetAbsencesConfirmed confirms the absences, or revokes the confirmation (state unknown).
func (s *Sprint) SetAbsencesConfirmed(confirmed bool) {
	switch {
	case confirmed:
		s.AbsenceState = Ptr(AbsencesConfirmed)
	case s.AbsenceState != nil && *s.AbsenceState == AbsencesConfirmed:
		s.AbsenceState = Ptr(AbsencesUnknown)
	}
}

// ExplicitStateNeeded reports whether the state has to be stored: not if the older derivation
// from the fields would give the same result, so existing files stay unchanged when saving.
func (s Sprint) ExplicitStateNeeded() bool {
	if s.AbsenceState == nil {
		return false
	}
	derived := s
	derived.AbsenceState = nil
	return s.AbsenceStatus() != derived.AbsenceStatus()
}

// Clone returns a copy of the sprint whose maps and planning can be changed without affecting
// the original. Pointers to single values are shared; those are replaced, not changed.
func (s Sprint) Clone() Sprint {
	c := s
	c.Absences = maps.Clone(s.Absences)
	c.ExpectedAbsences = maps.Clone(s.ExpectedAbsences)
	c.Products = maps.Clone(s.Products)
	c.Projects = maps.Clone(s.Projects)
	c.CommittedTickets = slices.Clone(s.CommittedTickets)
	c.Carry = slices.Clone(s.Carry)
	c.Prognoses = slices.Clone(s.Prognoses)
	for i := range c.Prognoses {
		c.Prognoses[i].Finish = slices.Clone(c.Prognoses[i].Finish)
		c.Prognoses[i].Carry = slices.Clone(c.Prognoses[i].Carry)
	}
	if s.Planning != nil {
		p := *s.Planning
		p.Corrections = slices.Clone(s.Planning.Corrections)
		c.Planning = &p
	}
	return c
}
