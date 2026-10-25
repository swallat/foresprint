package preplan

import (
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/ticketimport"
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

// ProductionShareOf is the production share (0 to 100) of a ticket and where it comes from
// (hand, field, label, rule, none; see ticketimport.ProductionOf). Without the production
// feature: 0.
func ProductionShareOf(ticket model.Ticket, data *storage.TeamData) (float64, ticketimport.ProductionSource) {
	if !data.Team.Features.Production {
		return 0, ticketimport.ProductionNone
	}
	p := ticketimport.ProductionOf(ticket, data.Team.Tracker, data.Preplan)
	return p.Percent, p.Source
}

// effectiveProjectID is the project id the distribution groups a ticket by: the override, else
// the id the rules found (kept even when unknown, as the checks report it); nil for daily
// business and for tickets of closed projects.
func effectiveProjectID(ticket model.Ticket, data *storage.TeamData) *string {
	id := ticket.Project
	if o := data.Preplan.OverrideFor(ticket.Key); o != nil {
		switch {
		case o.Daily:
			return nil
		case o.Project != nil && *o.Project != "":
			id = o.Project
		}
	}
	if p := findProject(data, id); p != nil && p.Closed() {
		return nil
	}
	return id
}
