package app

// ProductDTO is a product of the team. PO is the PO reference as stored: the id of a PO of the
// team, or in a file from 0.8 the plain name.
type ProductDTO struct {
	ID   string `json:"id"` // "" for a new product
	Name string `json:"name"`
	PO   string `json:"po"`
	// Share is the agreed share of the sprint (0 to 1); nil = the remainder is split evenly.
	Share *float64 `json:"share"`
	// Rule is the assignment rule in text form ("" = none).
	Rule string `json:"rule"`
	From string `json:"from"` // YYYY-MM-DD, "" = open
	To   string `json:"to"`
	// Tickets and Points count what the rule (or, for work packages, the product field) takes.
	Tickets int     `json:"tickets"`
	Points  float64 `json:"points"`
	// Ended: the product has a last day that lies before today.
	Ended bool `json:"ended"`
	// Used: the product has history (sprint values, tickets, an end), so it is ended, not deleted.
	Used bool `json:"used"`
}

// OwnerDTO is a PO of the team. A PO who works in the team is a person as well; Person is that
// person's id and FTE their current share.
type OwnerDTO struct {
	ID       string  `json:"id"`
	Name     string  `json:"name"`
	Person   string  `json:"person"`
	Products int     `json:"products"`
	InTeam   bool    `json:"inTeam"`
	FTE      float64 `json:"fte"`
}

// ProductsView is the products page.
type ProductsView struct {
	// Source is where the work comes from: "tracker", "packages" or "none" (decision 15).
	Source string `json:"source"`
	Today  string `json:"today"`
	// Multi is true when the team has more than one product (or uses the feature).
	Multi bool `json:"multi"`
	// Legacy is true while the POs are plain names (a file from 0.8).
	Legacy   bool         `json:"legacy"`
	Products []ProductDTO `json:"products"`
	Owners   []OwnerDTO   `json:"owners"`
	// Defaults is the default share per sprint for the running and the next sprints.
	Defaults []ProductsDefault `json:"defaults"`
}

// ProductsDefault is the default amount of one sprint: Forecast PLAN (times the plannable share
// when the team plans on the roadmap basis) times the share of each product, rounded to whole
// points like the plan page.
type ProductsDefault struct {
	Sprint string `json:"sprint"`
	// Running: the sprint runs today (the next one to plan is the first row that does not).
	Running bool `json:"running"`
	// Roadmap: the team plans on the roadmap basis, so RoadmapShare applies (even when it is 0).
	Roadmap bool `json:"roadmap"`
	// Plan is the Forecast PLAN of the sprint; nil = no forecast yet.
	Plan *float64 `json:"plan"`
	// Available is what is distributed: Plan, or Plan times RoadmapShare on the roadmap basis.
	Available *float64 `json:"available"`
	// RoadmapShare is set only on the roadmap basis (0 to 1), otherwise 0.
	RoadmapShare float64 `json:"roadmapShare"`
	// Fixed is the sum of the fixed amounts, Rest the number of active products without a fixed
	// share, which split Available − Fixed (not below 0) evenly.
	Fixed float64 `json:"fixed"`
	Rest  int     `json:"rest"`
	// Values is the default amount per active product id.
	Values map[string]float64 `json:"values"`
}

// EndResult is the answer to ending a product.
type EndResult struct {
	View ProductsView `json:"view"`
	// Moved counts the open tickets or work packages that went to another product.
	Moved int `json:"moved"`
	// Undo is the token for Undo.
	Undo int `json:"undo"`
}

// Step is the answer to a change that Undo can take back.
type Step struct {
	View ProductsView `json:"view"`
	Undo int          `json:"undo"`
}
