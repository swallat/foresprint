package app

// Types of the projects page (api_projects.go). Dates are YYYY-MM-DD, months YYYY-MM. Amounts
// of the contingent are person days (PT); points are converted with the team rate and are
// estimates (decision 2).

// ProductRef names a product for chips and filters.
type ProductRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// MilestoneView is a milestone with the traffic light that follows from its tickets.
type MilestoneView struct {
	ID      string   `json:"id"`
	Name    string   `json:"name"`
	Date    string   `json:"date"`
	Tickets []string `json:"tickets"`
	// Done and Total count the tickets of the milestone that are finished, and all that exist.
	Done  int `json:"done"`
	Total int `json:"total"`
	// Light is "ok", "warn", "bad" or "none" (no tickets: no light is calculated).
	Light string `json:"light"`
}

// MonthRow is one row of the contingent per month.
type MonthRow struct {
	Month  string   `json:"month"`
	Booked float64  `json:"booked"`
	Done   *float64 `json:"done"`
	// Planned is an estimate; nil when the team rate is not known yet.
	Planned *float64 `json:"planned"`
}

// ProjectSprintRow is one row of the report for the project lead.
type ProjectSprintRow struct {
	Sprint  string   `json:"sprint"`
	State   string   `json:"state"`
	Booked  float64  `json:"booked"`
	Planned *float64 `json:"planned"`
	Done    *float64 `json:"done"`
}

// ProjectView is a project for the portfolio and the detail page.
type ProjectView struct {
	ID       string   `json:"id"`
	Name     string   `json:"name"`
	Products []string `json:"products"`
	Start    string   `json:"start"`
	End      string   `json:"end"`
	Note     string   `json:"note"`
	Rule     string   `json:"rule"`
	Light    string   `json:"light"` // "ok", "warn", "bad" or "none"
	Reason   string   `json:"reason"`
	Priority int      `json:"priority"`
	Booked   *float64 `json:"booked"`  // contingent in PT, nil = none booked
	Done     *float64 `json:"done"`    // finished work in PT (estimate), nil = unknown
	Planned  *float64 `json:"planned"` // planned work in PT (estimate), nil = unknown
	// DonePoints and PlannedPoints are the sums in the team's unit that the PT values come from.
	DonePoints    float64         `json:"donePoints"`
	PlannedPoints float64         `json:"plannedPoints"`
	Months        []MonthRow      `json:"months"`
	OpenScope     *float64        `json:"openScope"`
	Open          int             `json:"open"` // open tickets
	Milestones    []MilestoneView `json:"milestones"`
	// State is "", "finished" or "cancelled"; ClosedAt is the end date of a closed project.
	State string `json:"state"`
	// History is true when ending the project closes it instead of deleting it.
	History bool `json:"history"`
}

// DemandCell is the demand of one project on one product in the sprint of the conflict view.
type DemandCell struct {
	Project string  `json:"project"`
	Points  float64 `json:"points"`
}

// ConflictRow is one product of the conflict view.
type ConflictRow struct {
	Product string       `json:"product"`
	Budget  float64      `json:"budget"`
	Demand  []DemandCell `json:"demand"`
	Rest    float64      `json:"rest"`
	// Light is "ok", "warn" (nearly full) or "bad" (no room left).
	Light string `json:"light"`
}

// ProjectsView is the portfolio.
type ProjectsView struct {
	Today string `json:"today"`
	// Enabled is false when the team keeps no projects (features projects and tickets off).
	Enabled bool `json:"enabled"`
	// Source is "tracker", "packages" or "none".
	Source string `json:"source"`
	// Unit is the estimation unit of the team ("PT" or "SP").
	Unit string `json:"unit"`
	// Rate is points per person day; nil while it cannot be measured. RateEstimated says that
	// converted values are estimates.
	Rate     *float64      `json:"rate"`
	Products []ProductRef  `json:"products"`
	Projects []ProjectView `json:"projects"`
	Closed   []ProjectView `json:"closed"`
	Sprints  []SprintInfo  `json:"sprints"`
	// SprintDays is the usual length of a sprint; sprints after the calendar follow it.
	SprintDays     int           `json:"sprintDays"`
	ConflictSprint string        `json:"conflictSprint"`
	Conflict       []ConflictRow `json:"conflict"`
	// Problem is set when the distribution could not be calculated (no lights then).
	Problem string `json:"problem"`
}

// ProjectDetail is one project with its report.
type ProjectDetail struct {
	ProjectsView
	Project ProjectView        `json:"project"`
	Report  []ProjectSprintRow `json:"report"`
	Tickets []TicketLine       `json:"tickets"`
}

// TicketLine is a ticket of the project.
type TicketLine struct {
	Key      string   `json:"key"`
	Title    string   `json:"title"`
	Status   string   `json:"status"`
	Sprint   string   `json:"sprint"` // planned sprint ("" = not earmarked)
	Estimate *float64 `json:"estimate"`
	Done     bool     `json:"done"`
}

// MilestoneInput is a milestone as the form sends it.
type MilestoneInput struct {
	ID      string   `json:"id"`
	Name    string   `json:"name"`
	Date    string   `json:"date"`
	Tickets []string `json:"tickets"`
}

// ProjectInput is the form of a project; an empty ID creates a new one.
type ProjectInput struct {
	ID         string             `json:"id"`
	Name       string             `json:"name"`
	Products   []string           `json:"products"`
	Start      string             `json:"start"`
	End        string             `json:"end"`
	Note       string             `json:"note"`
	Rule       string             `json:"rule"`
	Booked     *float64           `json:"booked"`
	Months     map[string]float64 `json:"months"`
	OpenScope  *float64           `json:"openScope"`
	Milestones []MilestoneInput   `json:"milestones"`
}

// CloseInput says how a project ends.
type CloseInput struct {
	ID string `json:"id"`
	// How is "finished" or "cancelled".
	How string `json:"how"`
	At  string `json:"at"`
	// MoveTo is the project the open tickets go to; "" = daily business.
	MoveTo string `json:"moveTo"`
}
