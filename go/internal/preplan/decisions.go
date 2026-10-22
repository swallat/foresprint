package preplan

import (
	"strconv"
	"strings"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// ProductionSource says where a ticket's production share comes from (decision 20).
type ProductionSource string

// Where a production share comes from, in the order they are tried.
const (
	SourceHand  ProductionSource = "hand"
	SourceField ProductionSource = "field"
	SourceLabel ProductionSource = "label"
	SourceRule  ProductionSource = "rule"
	SourceNone  ProductionSource = "none"
)

// ProjectOf is the project a ticket belongs to: the PO's override wins (daily business = none),
// then the project the rules found. A closed or unknown project counts as none, so its tickets
// are daily business and take no part in the project's planning (decision 22).
func ProjectOf(ticket model.Ticket, data *storage.TeamData) *model.Project {
	id := ticket.Project
	if o := data.Preplan.OverrideFor(ticket.Key); o != nil {
		switch {
		case o.Daily:
			return nil
		case o.Project != nil && *o.Project != "":
			id = o.Project
		}
	}
	p := findProject(data, id)
	if p == nil || p.Closed() {
		return nil
	}
	return p
}

// ProductionShareOf is the production share (0 to 100) of a ticket and where it comes from:
// by hand in preplan.yaml, then the mapped tracker field, the production label (100 %), the
// first matching production rule, otherwise 0. Without the production feature: 0.
func ProductionShareOf(ticket model.Ticket, data *storage.TeamData) (float64, ProductionSource) {
	if !data.Team.Features.Production {
		return 0, SourceNone
	}
	if s := data.Preplan.ProductionFor(ticket.Key); s != nil {
		return clampPercent(s.Percent), SourceHand
	}
	tr := data.Team.Tracker
	if tr.Fields.Production != nil {
		if vals, ok := ticket.Extra.Get("production"); ok && len(vals) > 0 {
			if v, err := strconv.ParseFloat(strings.TrimSuffix(strings.TrimSpace(vals[0]), "%"), 64); err == nil {
				return clampPercent(v), SourceField
			}
		}
	}
	if tr.ProductionLabel != nil && *tr.ProductionLabel != "" {
		want := casefold(*tr.ProductionLabel)
		for _, l := range ticket.Labels {
			if casefold(l) == want {
				return 100, SourceLabel
			}
		}
	}
	facts := ticket.Facts()
	for _, r := range tr.ProductionRules {
		if r.Match != nil && r.Match.Matches(facts) {
			return clampPercent(r.Percent), SourceRule
		}
	}
	return 0, SourceNone
}

func clampPercent(v float64) float64 {
	switch {
	case v < 0:
		return 0
	case v > 100:
		return 100
	}
	return v
}

// effectiveProjectID is the id of ProjectOf, nil for daily business.
func effectiveProjectID(ticket model.Ticket, data *storage.TeamData) *string {
	if p := ProjectOf(ticket, data); p != nil {
		id := p.ID
		return &id
	}
	return nil
}
