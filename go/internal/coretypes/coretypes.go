// Package coretypes holds the data types that the calendar, capacity, forecast and analysis
// packages calculate with: a team's settings, its people and its sprints, with the field names
// of the Python model (src/foresprint/model.py).
//
// The complete model with storage and the YAML reader belongs to the step "Model and storage"
// of the port; the types here are the part the calculation needs and have the same shape, so
// that the calculation packages move to the complete model by changing the import. Optional
// numbers are *float64 (nil is None in Python), optional text is "" and an optional date is nil.
package coretypes

import (
	"time"

	"github.com/swallat/foresprint/internal/pymath"
)

// Date is a calendar date: UTC midnight, no time zone arithmetic anywhere.
type Date = time.Time

// NewDate returns the date year-month-day.
func NewDate(year int, month time.Month, day int) Date {
	return time.Date(year, month, day, 0, 0, 0, 0, time.UTC)
}

// ParseDate reads YYYY-MM-DD.
func ParseDate(s string) (Date, error) { return time.Parse("2006-01-02", s) }

// Float returns a pointer to x (an optional number that is set).
func Float(x float64) *float64 { return &x }

// Numbering of the sprint IDs.
type Numbering string

// The two numberings of the sprint IDs.
const (
	// Yearly is 2026.1, 2026.2, ...: the counter restarts with the start year of a sprint.
	Yearly Numbering = "yearly"
	// Sequential is 1, 2, 3, ...
	Sequential Numbering = "sequential"
)

// Unit of the estimates.
type Unit string

// The units a team estimates in.
const (
	PT Unit = "PT"
	SP Unit = "SP"
)

// TrendMode is how the rolling average is projected into the future.
type TrendMode string

// The trend modes. Older files name Classic in German ("klassisch"); ParseTrendMode reads that.
const (
	Classic TrendMode = "classic"
	Linear  TrendMode = "linear"
	Flat    TrendMode = "flat"
)

// ParseTrendMode converts a string to a TrendMode; an unknown value is an error (no silent
// linear), except the German name of classic.
func ParseTrendMode(s string) (TrendMode, bool) {
	switch TrendMode(s) {
	case Classic, Linear, Flat:
		return TrendMode(s), true
	}
	if s == "klassisch" {
		return Classic, true
	}
	return "", false
}

// AbsenceState says what the capacity of a sprint is calculated with.
type AbsenceState string

// The states of a sprint's absences.
const (
	// Unknown: capacity from calendar and people, absences estimated from history.
	Unknown AbsenceState = "unknown"
	// Expected: announced absences from the PO pre-planning (forecast, not confirmed).
	Expected AbsenceState = "expected"
	// Confirmed: absences confirmed, including "nobody is absent".
	Confirmed AbsenceState = "confirmed"
)

// ProductBasis is what the default distribution per product is taken from.
type ProductBasis string

// The product bases.
const (
	BasisPlan    ProductBasis = "plan"
	BasisRoadmap ProductBasis = "roadmap"
)

// SprintSettings is the section "sprint" of team.yaml.
type SprintSettings struct {
	LengthDays int
	Numbering  Numbering
	// FirstID and FirstStart are only needed as long as no sprint is recorded yet.
	FirstID    string
	FirstStart *Date
}

// ForecastSettings is the section "forecast" of team.yaml.
type ForecastSettings struct {
	ReferenceCapacity float64
	Window            int
	RoadmapShare      float64
	Rounding          int
	TrendMode         TrendMode
	Horizon           int
	ProductBasis      ProductBasis
}

// CapacitySettings is the section "capacity" of team.yaml.
type CapacitySettings struct {
	// OverheadShare is the share of the capacity for Scrum events, deducted as a flat amount.
	OverheadShare float64
	// OverheadDays is the same deduction in PD per full-time person and sprint; if set it
	// applies instead of the share.
	OverheadDays float64
	// Country (ISO 3166-1) and Region within it for holidays; "" = no region.
	Country string
	Region  string
	// Workweek is "auto" (the country's), "mon-fri", "sun-thu", "mon-sat" or a list of workdays.
	Workweek string
	Rounding int
	// AbsenceHistory is the number of sprints with confirmed absences the expected absence rate
	// is taken from; 0 = no estimate.
	AbsenceHistory int
}

// Team is a team's configuration.
type Team struct {
	Key      string
	Name     string
	Unit     Unit
	Sprint   SprintSettings
	Forecast ForecastSettings
	Capacity CapacitySettings
}

// NewTeam returns a team with the defaults of the Python model.
func NewTeam(key, name string) *Team {
	return &Team{
		Key:  key,
		Name: name,
		Unit: PT,
		Sprint: SprintSettings{
			LengthDays: 14,
			Numbering:  Yearly,
		},
		Forecast: ForecastSettings{
			ReferenceCapacity: 67,
			Window:            5,
			RoadmapShare:      0.8,
			Rounding:          1,
			TrendMode:         Flat,
			Horizon:           3,
			ProductBasis:      BasisPlan,
		},
		Capacity: CapacitySettings{
			Country:        "DE",
			Workweek:       "auto",
			Rounding:       1,
			AbsenceHistory: 4,
		},
	}
}

// Membership is a period of a person in the team with an FTE share.
type Membership struct {
	Start Date    `json:"start"`
	End   *Date   `json:"end"` // nil = open end
	FTE   float64 `json:"fte"`
}

// Covers reports whether the membership includes the day (both ends inclusive).
func (m Membership) Covers(day Date) bool {
	return !m.Start.After(day) && (m.End == nil || !m.End.Before(day))
}

// Person is a member of the team.
type Person struct {
	ID          string       `json:"id"`
	Name        string       `json:"name"`
	Region      string       `json:"region"`
	Memberships []Membership `json:"memberships"`
	// ProductionAccess: may work on tickets that require production access.
	ProductionAccess bool `json:"production_access"`
	// Country is the person's own country if different; "" = the team's.
	Country string `json:"country"`
	// Workweek is the person's own workweek; "" = that of the country or the team.
	Workweek string `json:"workweek"`
}

// FTEOn is the person's FTE share on the day: that of the first membership that covers it, 0 if
// none does.
func (p Person) FTEOn(day Date) float64 {
	for _, m := range p.Memberships {
		if m.Covers(day) {
			return m.FTE
		}
	}
	return 0
}

// Planning is the control calculation of the sprint planning.
type Planning struct {
	Carryover   float64   `json:"carryover"`
	Backlog     float64   `json:"backlog"`
	Corrections []float64 `json:"corrections"`
}

// Committed is the scheduled amount according to the board: carryover plus backlog.
func (p Planning) Committed() float64 { return p.Carryover + p.Backlog }

// Total is the planning total for the delta: scheduled minus the parts already done.
func (p Planning) Total() float64 {
	return p.Committed() - pymath.Sum(p.Corrections)
}

// Sprint is one sprint, recorded or generated from the calendar. Only the fields the
// calculation needs are here; the complete model also has products, notes, prognoses and so on.
type Sprint struct {
	ID    string `json:"id"`
	Start Date   `json:"start"`
	End   Date   `json:"end"`
	// Absences are the plannable absences per person (working days).
	Absences map[string]float64 `json:"absences"`
	// Capacity in PD, recorded or frozen at the review; nil = not recorded.
	Capacity     *float64  `json:"capacity"`
	Commitment   *float64  `json:"commitment"`
	Velocity     *float64  `json:"velocity"`
	ScopeCreep   *float64  `json:"scope_creep"`
	Planning     *Planning `json:"planning"`
	ForecastPlan *float64  `json:"forecast_plan"`
	// AbsenceState is the stored state; nil = not stored (older files), derived by
	// AbsenceStatus.
	AbsenceState *AbsenceState `json:"absence_state"`
	// ExpectedAbsences are the announced absences from the PO pre-planning.
	ExpectedAbsences map[string]float64 `json:"expected_absences"`
}

// Clone returns a copy that shares nothing mutable with s.
func (s Sprint) Clone() Sprint {
	c := s
	c.Absences = cloneDays(s.Absences)
	c.ExpectedAbsences = cloneDays(s.ExpectedAbsences)
	if s.Planning != nil {
		p := *s.Planning
		p.Corrections = append([]float64(nil), s.Planning.Corrections...)
		c.Planning = &p
	}
	return c
}

func cloneDays(m map[string]float64) map[string]float64 {
	if m == nil {
		return nil
	}
	out := make(map[string]float64, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// LegacyKnown reports, for older files without a stored state the absences count as known if the sprint
// was already planned or evaluated. A file with only the PO pre-planning does not confirm them.
func LegacyKnown(s Sprint) bool {
	return s.Planning != nil || s.Commitment != nil || s.Velocity != nil || s.ForecastPlan != nil
}

// AbsenceStatus is the state of the absences: confirmed, announced or unknown. Entered absences
// are confirmed. Otherwise the stored state applies; if it is missing (older files) it is
// derived from the existing fields. Announced absences only take effect as long as nothing is
// confirmed.
func AbsenceStatus(s Sprint) AbsenceState {
	if len(s.Absences) > 0 || (s.AbsenceState != nil && *s.AbsenceState == Confirmed) {
		return Confirmed
	}
	if s.AbsenceState == nil && LegacyKnown(s) {
		return Confirmed
	}
	if len(s.ExpectedAbsences) > 0 {
		return Expected
	}
	return Unknown
}

// TeamData is what the calculation reads of a team: settings, people and recorded sprints,
// oldest first.
type TeamData struct {
	Team    *Team
	People  []Person
	Sprints []Sprint
}

// Sprint returns the recorded sprint with the ID.
func (d *TeamData) Sprint(id string) *Sprint {
	for i := range d.Sprints {
		if d.Sprints[i].ID == id {
			return &d.Sprints[i]
		}
	}
	return nil
}
