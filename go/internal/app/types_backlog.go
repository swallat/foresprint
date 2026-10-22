package app

// Types of the Backlog area (api_backlog.go). Keep them in step with
// frontend/src/lib/types.backlog.ts.

// Named is a product or project in a filter or a selector.
type Named struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	// Closed: a finished product or project (shown only where it still has tickets).
	Closed bool `json:"closed,omitempty"`
}

// BacklogTicket is one row of the backlog list or a lane.
type BacklogTicket struct {
	Key      string `json:"key"`
	Title    string `json:"title"`
	Status   string `json:"status"`
	Type     string `json:"type"`
	Priority string `json:"priority"`
	Assignee string `json:"assignee"`
	// URL is the link into the tracker; empty for work packages and CSV sources.
	URL string `json:"url"`
	// Size is the number the planning calculates with (the tracker's value or the PO's own
	// estimate); nil = no estimate. SizeSource is refined, rough, manual or none.
	Size       *float64 `json:"size"`
	SizeSource string   `json:"sizeSource"`
	// Refined is the refined state; RefinedUnclear says it could not be told for sure.
	Refined        bool `json:"refined"`
	RefinedUnclear bool `json:"refinedUnclear"`
	// Product and Project are ids; "" = none (a project of "" is daily business).
	Product string `json:"product"`
	Project string `json:"project"`
	// ProductSet and ProjectSet: the PO decided it for this ticket, against or without a rule.
	ProductSet bool `json:"productSet"`
	ProjectSet bool `json:"projectSet"`
	// RuleHint is "none" (no product rule matches), "several" (rules contradict each other) or
	// "project" (a product rule says another product than the project); RuleProducts names them.
	RuleHint     string   `json:"ruleHint,omitempty"`
	RuleProducts []string `json:"ruleProducts,omitempty"`
	// Earmark is the sprint the PO put the ticket into ("" = none); TrackerSprint is the
	// sprint according to the tracker (id, or the name when it is unknown here).
	Earmark string `json:"earmark"`
	// EarmarkNote is the PO's note on the earmark.
	EarmarkNote string `json:"earmarkNote,omitempty"`
	// Fixed: the tracker has the ticket in a sprint; the PO cannot move it here.
	Fixed         bool   `json:"fixed,omitempty"`
	TrackerSprint string `json:"trackerSprint"`
	// Production is the share (0-100) that needs production access; nil = not set.
	Production *float64 `json:"production"`
	Epic       string   `json:"epic"`
	Labels     []string `json:"labels"`
	DependsOn  []string `json:"dependsOn"`
	// Blocked: a ticket this one depends on is earmarked for a later sprint or not at all.
	Blocked bool `json:"blocked"`
}

// BacklogLane is one coming sprint with what is earmarked for it.
type BacklogLane struct {
	Sprint string `json:"sprint"`
	Start  string `json:"start"`
	End    string `json:"end"`
	// Plan is the Forecast PLAN of the sprint in the team's unit; nil if it cannot be told.
	Plan *float64 `json:"plan"`
	// Absences is "confirmed", "announced" or "unknown".
	Absences string          `json:"absences"`
	Tickets  []BacklogTicket `json:"tickets"`
}

// ProFormaSprint is a tracker sprint that is no real sprint (for example "Refinement").
type ProFormaSprint struct {
	Name    string          `json:"name"`
	Tickets []BacklogTicket `json:"tickets"`
}

// BacklogView is everything the Backlog page shows.
type BacklogView struct {
	// Source is "tracker", "packages" or "none".
	Source string `json:"source"`
	// Tracker is the name of the tracker ("Jira"), empty for work packages.
	Tracker  string           `json:"tracker"`
	Unit     string           `json:"unit"`
	Products []Named          `json:"products"`
	Projects []Named          `json:"projects"`
	Tickets  []BacklogTicket  `json:"tickets"`
	Lanes    []BacklogLane    `json:"lanes"`
	ProForma []ProFormaSprint `json:"proForma"`
	// Imported is the time of the last tracker fetch (RFC 3339), empty if never.
	Imported string `json:"imported"`
	// Multi: the team works with several products.
	Multi bool `json:"multi"`
	// Production: the team uses the production share.
	Production bool `json:"production"`
	// Cycles lists dependency cycles; their tickets are in the list, but cannot be distributed.
	Cycles [][]string `json:"cycles"`
	// Drift is the difference between the list frozen for the running sprint and the tracker's
	// sprint at the last fetch; nil without a tracker, a running frozen sprint or a difference.
	Drift *BacklogDrift `json:"drift,omitempty"`
	// Adjust lists the tickets the PO placed in (or out of) a pro-forma sprint here that the
	// tracker still has differently: they are to be adjusted in the tracker.
	Adjust []BacklogAdjust `json:"adjust"`
	// OwnOrder: the PO's own order among tracker tickets is in use (ResetOrder takes it away).
	OwnOrder bool `json:"ownOrder"`
}

// BacklogAdjust is one ticket whose pro-forma sprint differs between the tool and the tracker.
type BacklogAdjust struct {
	Key   string `json:"key"`
	Title string `json:"title"`
	URL   string `json:"url"`
	// From is the pro-forma sprint in the tracker, To the one the PO chose; "" = none (backlog).
	From string `json:"from"`
	To   string `json:"to"`
}

// BacklogDrift says which tickets came into or left the tracker's sprint after the freeze.
type BacklogDrift struct {
	Sprint   string   `json:"sprint"`
	PulledIn []string `json:"pulledIn"`
	Dropped  []string `json:"dropped"`
	Unknown  []string `json:"unknown"`
}

// Subtask is a part of a work package.
type Subtask struct {
	Title string `json:"title"`
	Done  bool   `json:"done"`
}

// Comment is a note on a work package.
type Comment struct {
	Author string `json:"author"`
	At     string `json:"at"`
	Text   string `json:"text"`
}

// Dependency is a ticket another one depends on.
type Dependency struct {
	Key   string `json:"key"`
	Title string `json:"title"`
	// Earmark is the sprint the other ticket is earmarked for ("" = none).
	Earmark string `json:"earmark"`
}

// TicketDetail is one ticket with everything the panel and the presentation view show.
type TicketDetail struct {
	BacklogTicket
	Description  string       `json:"description"`
	Acceptance   string       `json:"acceptance"`
	Subtasks     []Subtask    `json:"subtasks"`
	Comments     []Comment    `json:"comments"`
	Dependencies []Dependency `json:"dependencies"`
	// Components, Remaining and Estimate are the tracker's own values.
	Components []string `json:"components"`
	Estimate   *float64 `json:"estimate"`
	Remaining  *float64 `json:"remaining"`
	// Note is the PO's note on the earmark.
	Note string `json:"note"`
	// Editable: a work package, whose fields are all edited here; tracker tickets are read only.
	Editable bool `json:"editable"`
	// Sprints are the sprints a ticket can be earmarked for (the coming ones).
	Sprints []string `json:"sprints"`
	// Statuses and Types are the values the form offers for a work package.
	Statuses   []string `json:"statuses"`
	Types      []string `json:"types"`
	Priorities []string `json:"priorities"`
	// People are the names offered for "assignee".
	People []string `json:"people"`
}

// WorkPackageInput is the form of a work package; Key "" creates a new one.
type WorkPackageInput struct {
	Key         string    `json:"key"`
	Title       string    `json:"title"`
	Status      string    `json:"status"`
	Type        string    `json:"type"`
	Priority    string    `json:"priority"`
	Assignee    string    `json:"assignee"`
	Product     string    `json:"product"`
	Project     string    `json:"project"`
	Estimate    *float64  `json:"estimate"`
	Refined     bool      `json:"refined"`
	Labels      []string  `json:"labels"`
	Description string    `json:"description"`
	Acceptance  string    `json:"acceptance"`
	Subtasks    []Subtask `json:"subtasks"`
	DependsOn   []string  `json:"dependsOn"`
	Comments    []Comment `json:"comments"`
	Done        bool      `json:"done"`
}
