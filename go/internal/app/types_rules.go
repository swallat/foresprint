package app

// RuleOwner names who a rule belongs to, so that the preview can tell which other rules would
// also take a ticket and which tickets are assigned differently today.
type RuleOwner struct {
	Kind string `json:"kind"` // "product" or "project"
	ID   string `json:"id"`
}

// RulePreview is the answer to the rule editor while someone types: whether the text is a rule,
// and what it would match among the tickets of the team.
type RulePreview struct {
	Valid bool `json:"valid"`
	// Error is the readable problem (translated) and Pos its place in the text (0-based, -1 if
	// unknown); both only when Valid is false.
	Error string `json:"error,omitempty"`
	Pos   int    `json:"pos"`
	// Normalized is the rule written the way Foresprint writes it (spaces, quotes, case).
	Normalized string `json:"normalized,omitempty"`
	// Fields are the names a rule may use: the fixed ones and the configured extra fields.
	Fields []string `json:"fields"`
	// Matches counts the tickets the rule takes; Points is their estimate (tickets without one
	// count 0); Sample holds the first keys.
	Matches int      `json:"matches"`
	Points  float64  `json:"points"`
	Sample  []string `json:"sample"`
	// Clash counts matching tickets that another rule of the same kind takes as well; Moved
	// counts matching tickets that are assigned to something else today (projects only).
	Clash int `json:"clash"`
	Moved int `json:"moved"`
}
