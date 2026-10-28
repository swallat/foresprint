package app

// Types of the sprint calendar (api_calendar.go). The JSON names are the ones of
// frontend/src/lib/types.team.ts.

// HolidayDTO is a public holiday inside a sprint.
type HolidayDTO struct {
	Date string `json:"date"` // YYYY-MM-DD
	Name string `json:"name"`
}

// Calendar row states.
const (
	CalFinished = "finished"
	CalRunning  = "running"
	CalOpen     = "open"    // starts later, has a file
	CalPlanned  = "planned" // starts later, no file yet
)

// CalendarRow is one sprint of the calendar. Locked sprints (finished) cannot be changed.
type CalendarRow struct {
	ID       string       `json:"id"`
	Start    string       `json:"start"`
	Last     string       `json:"last"` // last day (the stored end is the day after)
	Workdays int          `json:"workdays"`
	Holidays []HolidayDTO `json:"holidays"`
	State    string       `json:"state"`
	Locked   bool         `json:"locked"`
	Saved    bool         `json:"saved"` // has a sprint file
}

// NamingRuleDTO is a sprint naming pattern valid from a sprint on ("" = from the first).
type NamingRuleDTO struct {
	From    string `json:"from"`
	Pattern string `json:"pattern"`
}

// CalendarView is the sprint calendar page.
type CalendarView struct {
	Today        string          `json:"today"`
	Country      string          `json:"country"`
	Region       string          `json:"region"`
	Rows         []CalendarRow   `json:"rows"`
	Naming       []NamingRuleDTO `json:"naming"`
	Pattern      string          `json:"pattern"` // the pattern that names the next sprint ("" = none)
	Placeholders []string        `json:"placeholders"`
	ProForma     []string        `json:"proForma"`
}

// LastDay is a changed last day of a sprint.
type LastDay struct {
	ID   string `json:"id"`
	Last string `json:"last"` // YYYY-MM-DD
}

// CalendarResult is the calendar after a change. Moved is the number of following sprints that
// moved; Undo is the token for API.Undo (0 = not undoable).
type CalendarResult struct {
	View  CalendarView `json:"view"`
	Moved int          `json:"moved"`
	Undo  int          `json:"undo"`
}

// NamePreview is one line of the naming preview: the sprint, its start, the ID until now and
// the new name. Changes is false for sprints that keep their name.
type NamePreview struct {
	Index   int    `json:"index"`
	Start   string `json:"start"`
	Old     string `json:"old"`
	New     string `json:"new"`
	Locked  bool   `json:"locked"`
	Saved   bool   `json:"saved"`
	Changes bool   `json:"changes"`
}

// NamingPreview is what applying a pattern would do. Duplicate is the first name that comes up
// twice ("" = none); NoNumber is true if the pattern has no {NN}, {N}, {LFD} or {KW}; Problem is
// the text of an unknown placeholder.
type NamingPreview struct {
	Rows      []NamePreview `json:"rows"`
	Duplicate string        `json:"duplicate"`
	NoNumber  bool          `json:"noNumber"`
	Problem   string        `json:"problem"`
	Count     int           `json:"count"` // sprints that would be renamed
}

// CalendarChange is one change of the calendar: Kind "last" (new last day in Date), "start" (new
// start in Date) or "remove" (the sprint ID falls away, its days go to the sprint before).
// Mode says what happens to the later sprints: "shift" (they move along) or "keep" (they keep
// their dates; covered ones fall away). Naming says what happens to sprints with a file whose
// name no longer fits the count: "keep" their name or "renumber" them.
type CalendarChange struct {
	Kind   string `json:"kind"`
	ID     string `json:"id"`
	Date   string `json:"date"`
	Mode   string `json:"mode"`
	Naming string `json:"naming"`
}

// ChangeNote says what happens to one sprint: Kind is "moved" (Days, signed), "longer" or
// "shorter" (Days), "starts-later" or "starts-earlier" (Days), "gone" or "renamed" (From).
type ChangeNote struct {
	Kind string `json:"kind"`
	Days int    `json:"days"`
	From string `json:"from"`
}

// ChangeRow is one sprint in the preview of a change.
type ChangeRow struct {
	ID       string       `json:"id"`
	Old      string       `json:"old"`
	OldStart string       `json:"oldStart"`
	OldLast  string       `json:"oldLast"`
	Start    string       `json:"start"`
	Last     string       `json:"last"`
	Workdays int          `json:"workdays"`
	Gone     bool         `json:"gone"`
	Saved    bool         `json:"saved"`
	Notes    []ChangeNote `json:"notes"`
}

// CalendarPreview shows what a change does before it is written. Lost are the sprints with a
// file that fall away, Free those without one. Via is the sprint whose last day is the one that
// really changes (for a new start or a removal), Forced says that the later sprints have to move
// along. NamingChoice is true when the naming question matters for this change. Problem is set
// when the change is not possible.
type CalendarPreview struct {
	Rows         []ChangeRow `json:"rows"`
	Lost         []string    `json:"lost"`
	Free         []string    `json:"free"`
	Target       string      `json:"target"`
	Via          string      `json:"via"`
	Forced       bool        `json:"forced"`
	Mode         string      `json:"mode"`
	NamingChoice bool        `json:"namingChoice"`
	Problem      string      `json:"problem"`
}
