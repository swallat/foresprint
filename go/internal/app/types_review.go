package app

// Types of the Review and the minutes (api_review.go). The JSON names are the ones of
// frontend/src/lib/types.review.ts.

// ReviewTicket is a ticket of the commitment in the Review of a team with tickets.
type ReviewTicket struct {
	Key      string  `json:"key"`
	Title    string  `json:"title"`
	Estimate float64 `json:"estimate"`
	// Status is the tracker status; Added marks a ticket pulled into the sprint after the freeze:
	// done, it counts as done in addition, not done, it does not count as not done.
	Status string `json:"status"`
	Added  bool   `json:"added"`
	Done   bool   `json:"done"`
	// Rest is what is left of a ticket that is not done; Target says where it continues:
	// "" = the next sprint, a sprint id, "backlog".
	Rest   float64 `json:"rest"`
	Target string  `json:"target"`
}

// ReviewProduct is one product row of the Review.
type ReviewProduct struct {
	ID       string  `json:"id"`
	Name     string  `json:"name"`
	Planned  float64 `json:"planned"`
	Done     float64 `json:"done"`
	ProdDone float64 `json:"prodDone"`
}

// ReviewTarget is a place where the rest of a ticket can continue.
type ReviewTarget struct {
	ID   string `json:"id"` // "" = next sprint, a sprint id, "backlog"
	Name string `json:"name"`
}

// SprintReview is what the page Sprint > Review shows and edits.
type SprintReview struct {
	Sprint AbsenceColumn `json:"sprint"`
	Unit   string        `json:"unit"`
	// Started is false for a sprint that has not begun; its numbers are placeholders.
	Started bool `json:"started"`
	// Reviewed is true once the Review was closed (the velocity is recorded).
	Reviewed bool `json:"reviewed"`
	// Reopenable is true for the latest reviewed sprint.
	Reopenable bool `json:"reopenable"`
	Tickets    bool `json:"tickets"` // the team commits to tickets
	// Frozen is true when the planning froze a ticket list; without one the commitment stays as recorded.
	Frozen     bool    `json:"frozen"`
	Commitment float64 `json:"commitment"`
	// CommitmentSet is false for a sprint without a recorded commitment: the page asks for it.
	CommitmentSet  bool    `json:"commitmentSet"`
	NotDone        float64 `json:"notDone"`
	AdditionalDone float64 `json:"additionalDone"`
	// Pulled are the done tickets pulled in after the freeze; their estimates prefill AdditionalDone
	// of an open Review. NoEstimate are those among them without an estimate.
	Pulled       []string        `json:"pulled"`
	NoEstimate   []string        `json:"noEstimate"`
	RestNext     float64         `json:"restNext"` // without tickets: rest that continues in the next sprint
	Velocity     float64         `json:"velocity"`
	List         []ReviewTicket  `json:"list"`
	Targets      []ReviewTarget  `json:"targets"`
	PlannedDays  float64         `json:"plannedDays"`
	FrozenDays   float64         `json:"frozenDays"`
	Rate         *float64        `json:"rate"`   // velocity per person day, nil without days
	Factor       *float64        `json:"factor"` // the fixed factor valid for the sprint, nil = measured rate
	Products     []ReviewProduct `json:"products"`
	ProductsOn   bool            `json:"productsOn"`
	ProductionOn bool            `json:"productionOn"`
	// Production is the done amount with production access for a team without products.
	Production float64 `json:"production"`
	Tag        string  `json:"tag"`
	// Prefill is the label of the what-if assumption the ticket table is prefilled from; empty =
	// from the tracker status only.
	Prefill string `json:"prefill"`
}

// ReviewInput is what Close takes from the page.
type ReviewInput struct {
	NotDone        float64 `json:"notDone"`
	AdditionalDone float64 `json:"additionalDone"`
	RestNext       float64 `json:"restNext"`
	// Commitment is taken only where the sprint has none recorded.
	Commitment *float64        `json:"commitment"`
	List       []ReviewTicket  `json:"list"`
	FrozenDays float64         `json:"frozenDays"`
	Products   []ReviewProduct `json:"products"`
	Production float64         `json:"production"`
	// Tag names the state with the Review at the next Save; empty = no tag.
	Tag string `json:"tag"`
}

// ReviewClosed answers Close and Reopen.
type ReviewClosed struct {
	Review SprintReview `json:"review"`
	// Minutes is the file written (or marked obsolete), relative to the team folder.
	Minutes string `json:"minutes"`
	// Tag is the tag that the next Save sets; empty = none.
	Tag string `json:"tag"`
}

// MinutesRow is one minutes file.
type MinutesRow struct {
	Sprint   string `json:"sprint"`
	Kind     string `json:"kind"` // vorplanung, planning, review
	At       string `json:"at"`   // 2006-01-02 15:04
	File     string `json:"file"` // relative to the team folder
	Obsolete bool   `json:"obsolete"`
}

// MinutesText is the Markdown of one minutes file.
type MinutesText struct {
	Text string `json:"text"`
	// Path is the full path of the file.
	Path string `json:"path"`
}
