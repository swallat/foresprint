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
	// AbsencesOpen (1.0): the sprint is not frozen; cells are confirmed (Absences) or announced
	// (ExpectedAbsences) one by one. Only stored when the sprint has a confirmed cell.
	AbsencesOpen AbsenceState = "open"
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
	// Preplanned is the pre-planned amount of the whole sprint for a team without the products
	// feature (with products it is the sum of the products' Preplanned).
	Preplanned *float64
	// Matrix is the pre-planned amount per product and project, product id first; optional, it
	// refines Projects (per project) for teams that plan by product and project.
	Matrix map[string]map[string]float64
	// Removed are tickets the team took out of the sprint in the planning that the tracker still
	// has in it ("adjust in the tracker"); kept until the plan is frozen.
	Removed []string
}

// legacyKnown: in older files without a stored state, absences counted as known if the sprint
// was already planned or evaluated. A file with only, e.g., the PO pre-planning does not
// confirm them.
func (s Sprint) legacyKnown() bool {
	return s.Planning != nil || s.Commitment != nil || s.Velocity != nil || s.ForecastPlan != nil
}

// AbsenceStatus is the state of the absences of the whole sprint: confirmed ("frozen": every
// cell is confirmed and an empty cell means 0 days), announced or unknown.
//
// Entered absences are confirmed (files from 0.8 have no cell states). Otherwise the stored
// state applies; if it is missing (older files), it is derived from the existing fields. The
// stored state AbsencesOpen (1.0) keeps a sprint open although some of its cells are confirmed:
// Absences then holds the confirmed cells and ExpectedAbsences the announced ones. Announced
// absences only take effect as long as nothing is confirmed for the whole sprint.
func (s Sprint) AbsenceStatus() AbsenceState {
	if s.AbsenceState != nil && *s.AbsenceState == AbsencesOpen {
		if len(s.Absences) > 0 || len(s.ExpectedAbsences) > 0 {
			return AbsencesExpected
		}
		return AbsencesUnknown
	}
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

// CellState is the state of one person's absence in this sprint: confirmed (closed lock),
// announced (open lock) or unknown (nothing entered). In a frozen sprint every cell is
// confirmed.
func (s Sprint) CellState(person string) AbsenceState {
	if s.AbsenceStatus() == AbsencesConfirmed {
		return AbsencesConfirmed
	}
	if _, ok := s.Absences[person]; ok {
		return AbsencesConfirmed
	}
	if _, ok := s.ExpectedAbsences[person]; ok {
		return AbsencesExpected
	}
	return AbsencesUnknown
}

// CellDays is the absence days of one person as the cell shows them: the confirmed days, else
// the announced ones.
func (s Sprint) CellDays(person string) float64 {
	if d, ok := s.Absences[person]; ok {
		return d
	}
	if s.AbsenceStatus() == AbsencesConfirmed {
		return 0
	}
	return s.ExpectedAbsences[person]
}

// SetCell sets the absence days of one person: state AbsencesConfirmed or AbsencesExpected
// (announced); 0 days removes the entry. In a frozen sprint the cell stays confirmed. An open
// sprint stores the state "open", so confirmed cells next to announced ones are not read as a
// frozen sprint.
func (s *Sprint) SetCell(person string, days float64, state AbsenceState) {
	frozen := s.AbsenceStatus() == AbsencesConfirmed
	delete(s.Absences, person)
	delete(s.ExpectedAbsences, person)
	if days != 0 {
		toConfirmed := frozen || state == AbsencesConfirmed
		target := &s.ExpectedAbsences
		if toConfirmed {
			target = &s.Absences
		}
		if *target == nil {
			*target = map[string]float64{}
		}
		(*target)[person] = days
	}
	if frozen {
		s.AbsenceState = Ptr(AbsencesConfirmed) // also when the last cell was removed
	} else {
		s.settleOpenState()
	}
}

// settleOpenState stores the state of an open sprint: open while a cell is confirmed (the 1.0
// state), announced while there are only announced cells (the 0.8 state), otherwise unknown.
func (s *Sprint) settleOpenState() {
	switch {
	case len(s.Absences) > 0:
		s.AbsenceState = Ptr(AbsencesOpen)
	case len(s.ExpectedAbsences) > 0:
		s.AbsenceState = Ptr(AbsencesExpected)
	default:
		s.AbsenceState = Ptr(AbsencesUnknown)
	}
}

// Freeze confirms the whole allocation: all entries count as confirmed and every empty cell as
// 0 days ("nobody is absent" needs no extra step). Confirmed days win over announced ones.
func (s *Sprint) Freeze() {
	merged := map[string]float64{}
	for k, v := range s.ExpectedAbsences {
		merged[k] = v
	}
	for k, v := range s.Absences {
		merged[k] = v
	}
	s.Absences = merged
	s.ExpectedAbsences = nil
	s.AbsenceState = Ptr(AbsencesConfirmed)
}

// Unfreeze opens a frozen sprint again: all entries count as announced.
func (s *Sprint) Unfreeze() {
	announced := map[string]float64{}
	for k, v := range s.ExpectedAbsences {
		announced[k] = v
	}
	for k, v := range s.Absences {
		announced[k] = v
	}
	s.ExpectedAbsences = announced
	s.Absences = nil
	s.settleOpenState()
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
	c.Removed = slices.Clone(s.Removed)
	if s.Matrix != nil {
		c.Matrix = make(map[string]map[string]float64, len(s.Matrix))
		for k, v := range s.Matrix {
			c.Matrix[k] = maps.Clone(v)
		}
	}
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
