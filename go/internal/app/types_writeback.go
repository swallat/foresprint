package app

// WriteMove is one ticket that the write-back puts into another tracker sprint. From and To are
// sprint names of the tracker; an empty name is the backlog.
type WriteMove struct {
	Key   string `json:"key"`
	Title string `json:"title"`
	// Reason is "committed" (agreed, not yet in the tracker's sprint), "taken_out" (in the
	// tracker's sprint but taken out in the planning) or "undo".
	Reason string `json:"reason"`
	From   string `json:"from"`
	To     string `json:"to"`
	// FromKnown is false when the earlier place of the ticket is not known; an undo cannot go
	// back there.
	FromKnown bool `json:"fromKnown"`
}

// WritePreview is what the write-back would do. Nothing has been changed in the tracker when
// the page shows it.
type WritePreview struct {
	// Enabled is false when the team did not switch write-back on (Settings > Tickets and
	// tracker) or has no tracker; the page then offers nothing.
	Enabled bool `json:"enabled"`
	// Sprint is the sprint of the tracker the agreed tickets go into ("" = not found).
	Sprint string `json:"sprint"`
	// RemovedTarget is where taken-out tickets go: backlog, pro_forma or next.
	RemovedTarget string      `json:"removedTarget"`
	Moves         []WriteMove `json:"moves"`
	Problems      []string    `json:"problems"`
	// CanUndo is true when a write-back of this sprint went through in this session.
	CanUndo bool `json:"canUndo"`
}

// WriteResult says what a carried-out write-back did.
type WriteResult struct {
	Done   []WriteMove `json:"done"`
	Failed []WriteMove `json:"failed"`
	// Error is the text of the failure that stopped the write-back ("" = it went through).
	Error string `json:"error"`
	// CanUndo is true when something can be taken back.
	CanUndo bool `json:"canUndo"`
}
