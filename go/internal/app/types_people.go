package app

// MembershipDTO is one period in which a person is in the team; To "" = open. The first From is
// the entry, a To in the past is the leaving day.
type MembershipDTO struct {
	From string  `json:"from"` // YYYY-MM-DD
	To   string  `json:"to"`
	FTE  float64 `json:"fte"`
}

// PersonDTO is a person of the team. Country and Region are the person's own holiday calendar (empty = the team's);
// Workweek is not edited in the window, it travels along so that saving does not lose it.
type PersonDTO struct {
	ID          string          `json:"id"` // "" for a new person
	Name        string          `json:"name"`
	Kind        string          `json:"kind"` // "member", "guest", "external"
	Production  bool            `json:"production"`
	Memberships []MembershipDTO `json:"memberships"`
	Region      string          `json:"region,omitempty"`
	Country     string          `json:"country,omitempty"`
	Workweek    string          `json:"workweek,omitempty"`
	// Used: the person stands in a sprint that has begun, so they can be ended but not removed.
	// Read-only.
	Used bool `json:"used"`
}

// PeopleView is the people page: everybody ever in the team, current and former.
type PeopleView struct {
	Today string `json:"today"`
	// NewFrom is the day a person added now joins: the start of the first sprint while the
	// team is still in it, else today.
	NewFrom string `json:"newFrom"`
	// SprintDays is the length of a sprint in working days as set for the team.
	SprintDays int `json:"sprintDays"`
	// Production is true when the team uses production access.
	Production bool `json:"production"`
	// Country is the holiday country of the team, the default of a person without an own one.
	Country string      `json:"country"`
	People  []PersonDTO `json:"people"`
}

// AbsencePeriodDTO is a planned absence of one person from the first to the last day. Only the
// dates are kept, never a reason or a kind.
type AbsencePeriodDTO struct {
	Person    string `json:"person"`
	From      string `json:"from"`
	To        string `json:"to"`
	Confirmed bool   `json:"confirmed"`
}
