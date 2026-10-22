package app

// Types of the sprint workspace (api_sprints.go). The JSON names are the ones of
// frontend/src/lib/types.sprints.ts.

// Absence states of a sprint column.
const (
	AbsenceUnknown   = "unknown"   // nothing entered
	AbsenceAnnounced = "announced" // entered, not yet confirmed (open lock)
	AbsenceConfirmed = "confirmed" // frozen (closed lock); empty cells count as 0 days
)

// States of one cell: confirmed (closed lock), announced (open lock), empty (nothing entered).
const (
	CellConfirmed = "confirmed"
	CellAnnounced = "announced"
	CellEmpty     = "empty"
)

// AbsenceColumn is one sprint of the absence grid with its totals.
type AbsenceColumn struct {
	ID       string   `json:"id"`
	Name     string   `json:"name"`
	Start    string   `json:"start"`
	End      string   `json:"end"`
	State    string   `json:"state"`
	Workdays int      `json:"workdays"` // working days of the team in the sprint
	Entries  int      `json:"entries"`  // people with absence days
	Absent   float64  `json:"absent"`   // sum of absence days
	Capacity float64  `json:"capacity"` // person days with these absences
	Plan     *float64 `json:"plan"`     // Forecast PLAN, nil if there is none (past sprint, no history)
	Past     bool     `json:"past"`
}

// AbsenceCell is the absence of one person in one sprint.
type AbsenceCell struct {
	Days   float64 `json:"days"`
	State  string  `json:"state"`  // CellConfirmed, CellAnnounced or CellEmpty
	Max    float64 `json:"max"`    // working days of the person in the sprint (holidays deducted)
	Active bool    `json:"active"` // the person is in the team during the sprint
}

// AbsenceRow is one person with a cell per column.
type AbsenceRow struct {
	Person string        `json:"person"`
	Name   string        `json:"name"`
	FTE    float64       `json:"fte"`
	Cells  []AbsenceCell `json:"cells"`
}

// AbsenceGrid is the absences of several consecutive sprints.
type AbsenceGrid struct {
	Columns []AbsenceColumn `json:"columns"`
	Rows    []AbsenceRow    `json:"rows"`
}

// Readiness item states.
const (
	ReadyDone = "done"
	ReadyOpen = "open"
	ReadyNA   = "na" // does not apply to this team
)

// ReadyItem is one line of "Ready for planning?". The window words it (Text is built from Kind,
// Count and Names), so that the texts stay with the UI.
type ReadyItem struct {
	Kind  string   `json:"kind"` // "absences", "refinement", "preplan"
	State string   `json:"state"`
	Count int      `json:"count"`
	Names []string `json:"names"`
}

// SprintPrepare is what the page Prepare shows besides the grid: the preview of the selected
// sprint and the readiness checklist.
type SprintPrepare struct {
	Sprint       AbsenceColumn `json:"sprint"`
	CapacityBase float64       `json:"capacityBase"` // person days without any absence
	PlanBase     *float64      `json:"planBase"`     // Forecast PLAN without absences
	Preplanned   float64       `json:"preplanned"`   // sum of the pre-planned amounts
	Unit         string        `json:"unit"`         // "SP" or "PT"
	Ready        []ReadyItem   `json:"ready"`
}

// Sprint states of the overview.
const (
	SprintPast    = "past"
	SprintCurrent = "current"
	SprintPlanned = "planned" // the plan is frozen
	SprintFuture  = "future"
)

// Next steps of a sprint in the overview; the window words them.
const (
	NextNone     = "none"     // finished
	NextReview   = "review"   // running: prepare the review
	NextFrozen   = "frozen"   // the plan is frozen
	NextAbsences = "absences" // confirm the absences
	NextPreplan  = "preplan"  // enter the pre-planned amounts
	NextPlan     = "plan"
)

// SprintRow is one sprint of the overview.
type SprintRow struct {
	ID         string   `json:"id"`
	Name       string   `json:"name"`
	Start      string   `json:"start"`
	End        string   `json:"end"` // last day
	State      string   `json:"state"`
	Absences   string   `json:"absences"` // AbsenceUnknown, AbsenceAnnounced or AbsenceConfirmed
	Capacity   *float64 `json:"capacity"`
	Plan       *float64 `json:"plan"`
	Commitment *float64 `json:"commitment"`
	Velocity   *float64 `json:"velocity"`
	Normalized *float64 `json:"normalized"` // velocity at the reference capacity
	Rate       *float64 `json:"rate"`       // velocity per person day
	Next       string   `json:"next"`
}

// SprintOverview is the table of all sprints.
type SprintOverview struct {
	Rows         []SprintRow `json:"rows"`
	Reference    float64     `json:"reference"` // reference capacity of the normalized velocity
	Unit         string      `json:"unit"`
	CurrentIndex int         `json:"currentIndex"` // row of the running or next sprint, -1 if none
}
