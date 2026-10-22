package app

// ProductCell is one sprint of one product in "Products over time"; nil is "no value".
type ProductCell struct {
	Standard   *float64 `json:"standard"`
	Preplanned *float64 `json:"preplanned"`
	Planned    *float64 `json:"planned"`
	Done       *float64 `json:"done"`
}

// ProductLine is one product over the sprints (same order as ProductsOverTime.Sprints).
type ProductLine struct {
	ID    string        `json:"id"`
	Name  string        `json:"name"`
	Cells []ProductCell `json:"cells"`
	// Balance: Done minus Standard over the sprints with a Done value; Missing counts the
	// sprints without one (they are not counted).
	Sprints    int     `json:"sprints"`
	Standard   float64 `json:"standard"`
	Done       float64 `json:"done"`
	Difference float64 `json:"difference"`
	Missing    int     `json:"missing"`
}

// ProductsOverTime is the product table over several sprints (Forecast > Products over time).
type ProductsOverTime struct {
	// Enabled is false for a team with a single product: the tab does not appear.
	Enabled bool          `json:"enabled"`
	Sprints []string      `json:"sprints"`
	Current string        `json:"current"`
	Lines   []ProductLine `json:"lines"`
}

// ReportFile says where an export was written.
type ReportFile struct {
	Path string `json:"path"`
	// Cancelled is true if the user closed the folder dialog.
	Cancelled bool `json:"cancelled"`
}

// ImportChange is one value an Excel import would change.
type ImportChange struct {
	File string `json:"file"`
	Path string `json:"path"`
	Old  string `json:"old"`
	New  string `json:"new"`
}

// ImportPreview is what importing a workbook would do; nothing has been written.
type ImportPreview struct {
	Path string `json:"path"`
	// Hash identifies the content that was previewed; Apply refuses a changed file.
	Hash    string         `json:"hash"`
	Changes []ImportChange `json:"changes"`
	// More counts the changes beyond the first Limit that are not listed.
	More      int      `json:"more"`
	Untouched []string `json:"untouched"`
	// NoTeam is true for an older export that names no team (it is not checked).
	NoTeam bool `json:"noTeam"`
	// Cancelled is true if the user closed the file dialog.
	Cancelled bool `json:"cancelled"`
}
