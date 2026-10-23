package app

// ForecastRow is one sprint of the forecast page: a completed one (history) or a coming one.
type ForecastRow struct {
	ID    string `json:"id"`
	Start string `json:"start"` // YYYY-MM-DD
	End   string `json:"end"`   // YYYY-MM-DD
	// State is "past", "current" or "future", by today's date.
	State    string `json:"state"`
	Recorded bool   `json:"recorded"`
	// Capacity is the capacity of the sprint in person days (recorded for past sprints, the one
	// the plan was calculated with for the others); CapacitySource says where it comes from.
	Capacity       *float64 `json:"capacity"`
	CapacitySource string   `json:"capacitySource"`
	// Unsure is true if the capacity is a trend or a calendar value with unknown absences.
	Unsure     bool     `json:"unsure"`
	Commitment *float64 `json:"commitment"`
	Velocity   *float64 `json:"velocity"`
	// NormalizedVelocity is the velocity scaled to the reference capacity; Average is its
	// rolling mean over the window, Trend the trend used for the plan.
	NormalizedVelocity *float64 `json:"normalizedVelocity"`
	Average            *float64 `json:"average"`
	Trend              *float64 `json:"trend"`
	Fulfillment        *float64 `json:"fulfillment"`
	// Plan is the Forecast PLAN; PlanSource is "actual" (recorded commitment) or "projection".
	Plan       *float64 `json:"plan"`
	PlanSource string   `json:"planSource"`
	Low        *float64 `json:"low"`
	High       *float64 `json:"high"`
	// Plannable is the share of the plan for roadmap work; Small is the rest.
	Plannable *float64 `json:"plannable"`
	Small     *float64 `json:"small"`
	// CarryIn is the rest of earlier sprints that continues in this sprint and is taken off
	// the plan before the share applies; CarryAssumed says it is only an assumption of a
	// running sprint, Overbooked that it exceeds the plan.
	CarryIn      float64 `json:"carryIn"`
	CarryAssumed bool    `json:"carryAssumed"`
	Overbooked   bool    `json:"overbooked"`
}

// ForecastView is the data of the forecast page for one team.
type ForecastView struct {
	Team  string `json:"team"`
	Today string `json:"today"`
	// Settings used by the calculation (Settings > Forecast).
	ReferenceCapacity float64 `json:"referenceCapacity"`
	Window            int     `json:"window"`
	RoadmapShare      float64 `json:"roadmapShare"`
	TrendMode         string  `json:"trendMode"`
	Horizon           int     `json:"horizon"`
	Rounding          int     `json:"rounding"`
	// Samples is the number of sprints behind the range; FewSamples says that is thin.
	// Products is the number of products; "Products over time" appears for more than one.
	Products   int  `json:"products"`
	Samples    int  `json:"samples"`
	FewSamples bool `json:"fewSamples"`
	// Rate is the team rate (normalized velocity trend per reference capacity day, i.e.
	// points per person day) of the next sprint, nil if there is no forecast yet.
	Rate *float64 `json:"rate"`
	// RateFixed says Rate is the fixed factor of the team (decision 19), not a measured rate.
	RateFixed bool `json:"rateFixed"`
	// Running is the running sprint and Next the one after it ("" if none); RunningCommitment is
	// the commitment of the running sprint. The what-if expects a velocity for the running one.
	Running           string   `json:"running"`
	Next              string   `json:"next"`
	RunningCommitment *float64 `json:"runningCommitment"`
	// Past are the completed sprints, oldest first; Upcoming the current and the following ones.
	Past     []ForecastRow `json:"past"`
	Upcoming []ForecastRow `json:"upcoming"`
}

// ForecastAssumption is what the Forecast page tries: the sprint (empty = all coming ones),
// additional days off per sprint, the focus in percent, the velocity expected for the running
// sprint (nil = leave it) and the label under which it is saved as a prognosis.
type ForecastAssumption struct {
	Sprint           string   `json:"sprint"`
	ExtraAbsenceDays float64  `json:"extraAbsenceDays"`
	FocusPercent     float64  `json:"focusPercent"`
	ExpectedVelocity *float64 `json:"expectedVelocity"`
	Label            string   `json:"label"`
}

// WhatIfRow is a coming sprint under changed assumptions.
type WhatIfRow struct {
	ID       string  `json:"id"`
	Capacity float64 `json:"capacity"`
	Forecast float64 `json:"forecast"`
	Base     float64 `json:"base"`
	Delta    float64 `json:"delta"`
}

// WhenDoneView is the answer to "when is it done?".
type WhenDoneView struct {
	Remaining float64 `json:"remaining"`
	Share     float64 `json:"share"`
	Runs      int     `json:"runs"`
	Samples   int     `json:"samples"`
	// P50 and P85 are the sprint in which the work is done in half / 85 % of the runs; "" if
	// not within the period.
	P50        string    `json:"p50"`
	P85        string    `json:"p85"`
	Sprints    []string  `json:"sprints"`
	Cumulative []float64 `json:"cumulative"`
	PerSprint  float64   `json:"perSprint"`
	// TrendCapacity lists sprints beyond the people list, calculated with the average capacity.
	TrendCapacity []string `json:"trendCapacity"`
	// Available is false if there is too little history or nothing to do.
	Available bool `json:"available"`
	// Earliest is the first sprint in which the work is done in at least 15 % of the runs.
	Earliest string `json:"earliest"`
	// Starts and Ends are the first and last day of each sprint of Sprints.
	Starts []string `json:"starts"`
	Ends   []string `json:"ends"`
	// ProjectName, ProjectEnd and Light are set when the question was asked for a project: Light
	// is "ok", "warn", "bad" or "none" (no project end).
	ProjectName string `json:"projectName"`
	ProjectEnd  string `json:"projectEnd"`
	Light       string `json:"light"`
}

// WhenProject is an open project the analysis can be asked for.
type WhenProject struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	// End is the project end (or target date) as YYYY-MM-DD, "" if none.
	End string `json:"end"`
	// OpenScope is the open scope in the unit of the team, nil if unknown.
	OpenScope *float64 `json:"openScope"`
	Open      int      `json:"open"` // open tickets
}
