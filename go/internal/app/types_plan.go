package app

// Types of the Pre-plan and Plan pages (api_plan.go). All amounts are in the team's estimation
// unit (Unit) unless a field name says PD. A nil pointer means "no value", never 0.

// PlanSprint is everything the Pre-plan and Plan pages show about one sprint.
type PlanSprint struct {
	Team   string `json:"team"`
	Sprint string `json:"sprint"`
	Start  string `json:"start"` // YYYY-MM-DD
	End    string `json:"end"`   // YYYY-MM-DD
	Days   int    `json:"days"`
	// Stage is "past", "current", "planned" (plan frozen) or "open".
	Stage string `json:"stage"`
	// Unit is the estimation unit of the team ("SP" or "PT").
	Unit string `json:"unit"`
	// Source is where the work comes from: "tracker", "packages" or "none" (no tickets).
	Source      string `json:"source"`
	TrackerName string `json:"trackerName"`
	// WriteBack is true when the team switched on writing the sprint back to the tracker; the
	// page then offers the preview (PlanWritePreview).
	WriteBack bool `json:"writeBack"`
	// WriteUndo is true when a write-back of this sprint went through in this session and can be
	// taken back.
	WriteUndo bool `json:"writeUndo"`
	// MultiProduct, MultiPO and Production switch the optional columns on (the products feature,
	// more than one PO, the production access feature).
	MultiProduct bool `json:"multiProduct"`
	MultiPO      bool `json:"multiPO"`
	Production   bool `json:"production"`
	// Absences is "confirmed", "announced" or "unknown".
	Absences    string   `json:"absences"`
	AbsenceDays float64  `json:"absenceDays"`
	Capacity    *float64 `json:"capacity"`
	// Plan is the Forecast PLAN (with the assumption if one is passed and touched); PlanOriginal
	// the one without. Low and High are the range, Rate the unit per person day (nil if it
	// cannot be measured yet).
	Plan         *float64 `json:"plan"`
	PlanOriginal *float64 `json:"planOriginal"`
	// PlanSource is "start" if the PLAN comes from the start rate (no history yet), else "".
	// StartRate is the start rate of the team, 0 if none.
	PlanSource string   `json:"planSource"`
	StartRate  float64  `json:"startRate"`
	Low        *float64 `json:"low"`
	High       *float64 `json:"high"`
	Rate       *float64 `json:"rate"`
	// RateKnown: the other unit (PD for points) can be shown; false for a team planning in PD.
	OtherUnit string `json:"otherUnit"`
	// Share is the plannable share; Split the PLAN split into carry-over, plannable and small
	// stuff. CarryIn is the rest that continues in this sprint, CarryLater the rest that
	// continues in a later sprint or goes back.
	Share      float64    `json:"share"`
	Split      *PlanSplit `json:"split"`
	CarryLater float64    `json:"carryLater"`
	// Planned is the sum that is pre-planned (amounts) or planned (tickets), Committed the
	// commitment of a frozen plan.
	Preplanned float64 `json:"preplanned"`
	Earmarked  float64 `json:"earmarked"`
	// Removed are tickets the team took out of the sprint although the tracker still has them
	// in it (kept until the plan is frozen).
	Removed []string `json:"removed"`
	// SprintPre is the pre-planned amount of the whole sprint (teams without the products
	// feature), nil if none is set.
	SprintPre *float64 `json:"sprintPre"`
	Committed *float64 `json:"committed"`

	Products   []PlanProduct `json:"products"`
	Tickets    []PlanTicket  `json:"tickets"`
	Candidates []PlanTicket  `json:"candidates"`
	Projects   []PlanProject `json:"projects"`
	// Matrix is the pre-planned amount per product and project; nil when the team has no
	// products or no open project.
	Matrix *PlanMatrix     `json:"matrix"`
	Prod   *PlanProduction `json:"prod"`
	// Frozen is set when the plan is frozen.
	Frozen *PlanFrozen `json:"frozen"`
	// Assumptions are the saved assumptions about the running sprint (what-if) that target
	// this sprint; the newest of each label.
	Assumptions []Assumption `json:"assumptions"`
	// Running is the running sprint the what-if is about, "" if none runs before this sprint.
	Running string `json:"running"`
	// Notes are hints that belong to the view (for example an unreadable rate).
	Notes []string `json:"notes"`
}

// PlanSplit is planning.Split in the shape of the window.
type PlanSplit struct {
	Plan       float64 `json:"plan"`
	CarryIn    float64 `json:"carryIn"`
	Plannable  float64 `json:"plannable"`
	SmallStuff float64 `json:"smallStuff"`
	Overbooked bool    `json:"overbooked"`
}

// PlanProduct is one row of the product table: the stages as columns.
type PlanProduct struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	PO     string `json:"po"`
	POName string `json:"poName"`
	// Default is the standard amount, Pre the pre-planned amount (editable), Earmark the sum of
	// the earmarked tickets, Planned and ProdPlanned the frozen plan, Done the review.
	Default     *float64 `json:"default"`
	Pre         *float64 `json:"pre"`
	Earmark     float64  `json:"earmark"`
	Planned     *float64 `json:"planned"`
	ProdPlanned *float64 `json:"prodPlanned"`
	Done        *float64 `json:"done"`
	Active      bool     `json:"active"`
	// Budget is what the plan compares the tickets with: Pre if set, else Default.
	Budget float64 `json:"budget"`
}

// PlanTicket is a ticket (or work package) in one of the lanes.
type PlanTicket struct {
	Key      string   `json:"key"`
	Title    string   `json:"title"`
	Status   string   `json:"status"`
	URL      string   `json:"url"`
	Estimate *float64 `json:"estimate"`
	// Size is the number the plan calculates with (estimate, remaining or a manual estimate).
	Size    *float64 `json:"size"`
	Product string   `json:"product"`
	Project string   `json:"project"`
	// Refined is false for rough or unclear estimates and tickets without an estimate.
	Refined bool `json:"refined"`
	// Sprint is the sprint the ticket is earmarked for, InTracker its sprint in the tracker.
	Sprint    string `json:"sprint"`
	InTracker string `json:"inTracker"`
	// ProdPct is the production share 0 to 100, ProdSource where it comes from: "manual",
	// "label", "rule" or "none".
	ProdPct    float64 `json:"prodPct"`
	ProdSource string  `json:"prodSource"`
	// Remaining is the remaining effort of a ticket that is already worked on.
	Remaining *float64 `json:"remaining"`
}

// PlanProject is a project with work in the sprint, against its contingent.
type PlanProject struct {
	ID      string   `json:"id"`
	Name    string   `json:"name"`
	Tickets int      `json:"tickets"`
	Amount  float64  `json:"amount"`   // in the unit
	NeedPD  *float64 `json:"needPD"`   // estimate via the rate
	Booked  *float64 `json:"bookedPD"` // contingent for the whole project, in PD
	// UsedPD is what the contingent already consumed (from the project, nil if not recorded).
	UsedPD *float64 `json:"usedPD"`
	// Manual is the split of an amount without tickets: editable.
	Manual bool `json:"manual"`
}

// PlanProduction compares the production time of the sprint with the production part of the
// planned work.
type PlanProduction struct {
	People     []PlanProdPerson `json:"people"`
	Time       float64          `json:"time"` // before the cap, PD
	CapPercent float64          `json:"capPercent"`
	Available  float64          `json:"available"` // PD
	// Scaled: Available is Basis × Share × cap (needs a Forecast PLAN); otherwise it is Time × cap.
	Scaled bool `json:"scaled"`
	// Share is the part of the capacity that has production access (0 to 1).
	Share float64 `json:"share"`
	// Basis is the plannable amount in PD.
	Basis        float64  `json:"basis"`
	Demand       float64  `json:"demand"` // PD
	DemandSet    bool     `json:"demandSet"`
	DemandAmount float64  `json:"demandAmount"` // in the unit
	Load         *float64 `json:"load"`
	Status       string   `json:"status"` // "ok", "tight" or "over"
	// Manual is the value entered without tickets (PD), nil if none.
	Manual *float64 `json:"manual"`
}

// PlanProdPerson is one person with production access.
type PlanProdPerson struct {
	Name     string  `json:"name"`
	Capacity float64 `json:"capacity"`
	Absence  float64 `json:"absence"`
}

// PlanFrozen describes a frozen plan.
type PlanFrozen struct {
	Tickets    int      `json:"tickets"`
	Commitment *float64 `json:"commitment"`
}

// CarryInput is the rest of one ticket in an assumption: where it continues is Target ("" = the
// sprint the assumption is about, a sprint id, "backlog" or "proforma:<name>").
type CarryInput struct {
	Ticket string  `json:"ticket"`
	Rest   float64 `json:"rest"`
	Target string  `json:"target"`
}

// Assumption is an assumption about how the running sprint ends. With tickets, Carry lists the
// tickets that do not finish (their estimates count as not done, only the rest is carried);
// without tickets NotDone, Extra and RestNext are numbers.
type Assumption struct {
	Label      string       `json:"label"`
	Commitment *float64     `json:"commitment"`
	Carry      []CarryInput `json:"carry"`
	NotDone    *float64     `json:"notDone"`
	Extra      *float64     `json:"extra"`
	RestNext   *float64     `json:"restNext"`
	// FocusPercent and ExtraAbsenceDays come from the Forecast page (nil = as measured / none).
	FocusPercent     *float64 `json:"focusPercent"`
	ExtraAbsenceDays *float64 `json:"extraAbsenceDays"`
}

// WhatIf is the result of an assumption.
type WhatIf struct {
	Running string `json:"running"`
	Touched bool   `json:"touched"`
	// Commitment of the running sprint, NotDone and Extra as they count, Velocity expected.
	Commitment   float64  `json:"commitment"`
	NotDone      float64  `json:"notDone"`
	Extra        float64  `json:"extra"`
	Velocity     float64  `json:"velocity"`
	Plan         *float64 `json:"plan"`
	PlanOriginal *float64 `json:"planOriginal"`
	Low          *float64 `json:"low"`
	High         *float64 `json:"high"`
	Rest         float64  `json:"rest"`
	Later        float64  `json:"later"`
	Plannable    float64  `json:"plannable"`
	SmallStuff   float64  `json:"smallStuff"`
}

// RunningTicket is a ticket of the running sprint for the what-if table.
type RunningTicket struct {
	PlanTicket
	// Done: the ticket is finished. Added: pulled into the sprint after the plan was frozen.
	Done  bool `json:"done"`
	Added bool `json:"added"`
}

// RunningHint explains an empty what-if table: Unresolved open tickets sit in tracker sprints
// that Foresprint cannot map to one of its sprints (Names: the first few).
type RunningHint struct {
	Unresolved int      `json:"unresolved"`
	Names      []string `json:"names"`
}

// FreezeInput is what the team agreed in the planning. With tickets, Tickets is the agreed list
// (the commitment follows from it); without tickets Amounts (per product, unit of the team) and
// Commitment are entered. Removed lists tickets that the tracker still has in the sprint but
// the team took out: the minutes list them under "adjust in the tracker".
type FreezeInput struct {
	Tickets    []string           `json:"tickets"`
	Commitment *float64           `json:"commitment"`
	Amounts    map[string]float64 `json:"amounts"`
	Removed    []string           `json:"removed"`
}

// PlanMatrix is the table product x project of the pre-planning. Only cells with an amount are
// listed; Projects are the columns (every open project), the rows are the products of the view.
type PlanMatrix struct {
	Projects []PlanRef  `json:"projects"`
	Cells    []PlanCell `json:"cells"`
}

// PlanRef names a project.
type PlanRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// PlanCell is the amount of one product in one project.
type PlanCell struct {
	Product string  `json:"product"`
	Project string  `json:"project"`
	Value   float64 `json:"value"`
}
