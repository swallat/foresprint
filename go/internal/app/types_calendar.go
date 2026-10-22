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
