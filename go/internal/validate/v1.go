package validate

import (
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/storage"
)

// This file holds the checks of what 1.0 adds to the data (flows.md, decisions 14 to 23).

var monthKey = regexp.MustCompile(`^\d{4}-(0[1-9]|1[0-2])$`)

// checkProjectV1 checks the 1.0 fields of a project: state and end, start and end, milestones
// and the contingent.
func checkProjectV1(data *storage.TeamData, pr model.Project, where string, r *reporter) {
	if pr.Closed() && pr.End == nil {
		r.warn(where, msg("closed project without an end date"))
	}
	if pr.Start != nil && pr.End != nil && pr.End.Before(*pr.Start) {
		r.error(where, msg("period ends ({end}) before it starts ({start})", "end", day(*pr.End), "start", day(*pr.Start)))
	}
	tickets := map[string]bool{}
	for _, tk := range data.Tickets {
		tickets[tk.Key] = true
	}
	ids := map[string]bool{}
	for _, m := range pr.Milestones {
		at := where + ": " + m.ID
		if ids[m.ID] {
			r.error(at, msg("milestone id is duplicated"))
		}
		ids[m.ID] = true
		if (pr.Start != nil && m.Date.Before(*pr.Start)) || (pr.End != nil && m.Date.After(*pr.End)) {
			r.warn(at, msg("milestone {date} lies outside the project period", "date", day(m.Date)))
		}
		if data.Team.Source() != model.SourceNone {
			for _, key := range m.Tickets {
				if !tickets[key] {
					r.warn(at, msg("milestone names the unknown ticket '{key}'", "key", key))
				}
			}
		}
	}
	c := pr.Contingent
	if isNeg(c.Total) {
		r.error(where, msg("contingent.total must not be negative"))
	}
	var months []float64
	for _, e := range c.PerMonth.Entries {
		switch {
		case !monthKey.MatchString(e.Key):
			r.error(where, msg("contingent.per_month: '{key}' is not a month (YYYY-MM)", "key", e.Key))
		case e.Value < 0:
			r.error(where, msg("contingent.per_month: {key} must not be negative", "key", e.Key))
		default:
			months = append(months, e.Value)
		}
	}
	if isNeg(c.Used) {
		r.error(where, msg("contingent.used must not be negative"))
	}
	for _, e := range c.UsedPerMonth.Entries {
		switch {
		case !monthKey.MatchString(e.Key):
			r.error(where, msg("contingent.used_per_month: '{key}' is not a month (YYYY-MM)", "key", e.Key))
		case e.Value < 0:
			r.error(where, msg("contingent.used_per_month: {key} must not be negative", "key", e.Key))
		}
	}
	if c.Used != nil && c.Total != nil && *c.Used > *c.Total+1e-9 {
		r.warn(where, msg("the booked consumption ({used} PD) exceeds the contingent ({total} PD)", "used", g(*c.Used), "total", g(*c.Total)))
	}
	if total := pymath.Sum(months); c.Total != nil && total > *c.Total+1e-9 {
		r.warn(where, msg("the monthly contingents ({sum} PD) exceed the total ({total} PD)", "sum", g(total), "total", g(*c.Total)))
	}
}

// checkV1 checks what 1.0 adds to a team besides the projects: absence periods, estimation
// changes, carry-overs, the decisions of the PO per ticket and the production shares.
func checkV1(data *storage.TeamData, today time.Time, r *reporter) {
	team := data.Team
	known := knownSprints(data, 52)
	people := map[string]bool{}
	for _, p := range data.People {
		people[p.ID] = true
	}

	for _, e := range data.AbsencePeriods.Entries {
		where := "abwesenheiten.yaml: " + e.Key
		if len(data.People) > 0 && !people[e.Key] {
			r.warn(where, msg("absence periods for unknown person '{id}'", "id", e.Key))
		}
		periods := slices.Clone(e.Value)
		slices.SortFunc(periods, func(a, b model.AbsencePeriod) int { return a.From.Compare(b.From) })
		last := 0
		for i := 1; i < len(periods); i++ {
			if !periods[i].From.After(periods[last].To) {
				r.warn(where, msg("the periods {a} and {b} overlap",
					"a", day(periods[last].From)+" – "+day(periods[last].To), "b", day(periods[i].From)+" – "+day(periods[i].To)))
			}
			if periods[i].To.After(periods[last].To) {
				last = i
			}
		}
	}

	for _, c := range team.Estimation.Changes {
		if _, ok := known[c.From]; !ok {
			r.warn("team.yaml", msg("estimation.changes: sprint '{id}' is not known", "id", c.From))
		}
	}

	ticketKeys := map[string]bool{}
	for _, tk := range data.Tickets {
		ticketKeys[tk.Key] = true
	}
	withTickets := team.Source() != model.SourceNone
	for i := range data.Sprints {
		s := data.Sprints[i]
		where := "sprints/" + s.ID + ".yaml"
		checkCarry(r, where, s.Carry, s.RestNext, data, known, ticketKeys, withTickets)
		for _, p := range s.Prognoses {
			checkCarry(r, where, p.Carry, p.RestNext, data, known, ticketKeys, withTickets)
		}
	}

	if !withTickets {
		return
	}
	checkPlanDecisions(data, today, r, ticketKeys)
}

func checkCarry(r *reporter, where string, items []model.CarryItem, restNext *float64, data *storage.TeamData,
	known map[string]time.Time, tickets map[string]bool, withTickets bool) {
	if isNeg(restNext) {
		r.error(where, msg("{name} must not be negative", "name", "rest_next"))
	}
	for _, c := range items {
		at := where
		if c.Ticket != nil {
			at += ": " + *c.Ticket
			if withTickets && !tickets[*c.Ticket] {
				r.warn(at, msg("carry-over of an unknown ticket (not in the last import)"))
			}
		}
		if c.Rest < 0 {
			r.error(at, msg("{name} must not be negative", "name", "rest"))
		}
		switch {
		case c.Target == "" || c.Target == model.CarryBacklog:
		case strings.HasPrefix(c.Target, model.CarryProForma):
			if name := strings.TrimPrefix(c.Target, model.CarryProForma); !slices.Contains(data.Team.Sprint.ProForma, name) {
				r.warn(at, msg("carry-over target '{name}' is not a pro-forma sprint of the team", "name", name))
			}
		default:
			if _, ok := known[c.Target]; !ok {
				r.warn(at, msg("carry-over target '{id}' is not a known sprint", "id", c.Target))
			}
		}
	}
}

// checkPlanDecisions checks the production shares and the per-ticket decisions of the PO in
// preplan.yaml and the tickets that belong to an ended product or a closed project.
func checkPlanDecisions(data *storage.TeamData, today time.Time, r *reporter, tickets map[string]bool) {
	team := data.Team
	products := map[string]model.Product{}
	for _, p := range data.Products {
		products[p.ID] = p
	}
	projects := map[string]model.Project{}
	for _, p := range data.Projects {
		projects[p.ID] = p
	}
	seen := map[string]bool{}
	anyShare := false
	for _, ps := range data.Preplan.Production {
		where := "preplan.yaml: " + ps.Ticket
		if seen[ps.Ticket] {
			r.error(where, msg("several production shares for the same ticket"))
		}
		seen[ps.Ticket] = true
		if !tickets[ps.Ticket] {
			r.warn(where, msg("Production share for an unknown ticket (not in the last import)"))
		}
		if ps.Percent < 0 || ps.Percent > 100 {
			r.error(where, msg("'share' must be between 0 and 100"))
		}
		anyShare = anyShare || ps.Percent > 0
	}
	tr := team.Tracker
	if anyShare || len(tr.ProductionRules) > 0 || str(tr.ProductionLabel) != "" {
		access := false
		for _, p := range data.People {
			access = access || p.ProductionAccess
		}
		switch {
		case !team.Features.Production:
			r.warn("team.yaml", msg("Production shares are set, but the production feature is off"))
		case !access:
			r.warn("people.yaml", msg("Production shares are set, but nobody has production access"))
		}
	}
	if tr.RemovedTarget != "" && !slices.Contains(model.RemovedTargets, tr.RemovedTarget) {
		r.error("team.yaml", msg("tracker.removed_target must be one of {allowed}", "allowed", strings.Join(model.RemovedTargets, ", ")))
	}

	seen = map[string]bool{}
	for _, o := range data.Preplan.Overrides {
		where := "preplan.yaml: " + o.Ticket
		if seen[o.Ticket] {
			r.error(where, msg("several decisions for the same ticket"))
		}
		seen[o.Ticket] = true
		if !tickets[o.Ticket] {
			r.warn(where, msg("Decision for an unknown ticket (not in the last import)"))
		}
		if o.Product != nil {
			if prod, ok := products[*o.Product]; !ok {
				r.error(where, msg("unknown product '{id}'", "id", *o.Product))
			} else if prod.End != nil && prod.End.Before(today) {
				r.warn(where, msg("Product '{id}' ended on {end}", "id", *o.Product, "end", day(*prod.End)))
			}
		}
		if o.Project != nil {
			if pr, ok := projects[*o.Project]; !ok {
				r.error(where, msg("unknown project '{id}'", "id", *o.Project))
			} else if pr.Closed() {
				r.warn(where, msg("Project '{id}' is closed", "id", *o.Project))
			}
		}
		if o.Daily && o.Project != nil {
			r.error(where, msg("daily business and a project exclude each other"))
		}
	}

	open := map[string]int{}
	for _, tk := range data.Tickets {
		if tk.Done {
			continue
		}
		id := tk.Project
		if o := data.Preplan.OverrideFor(tk.Key); o != nil {
			if o.Daily {
				continue
			}
			if o.Project != nil && *o.Project != "" {
				id = o.Project
			}
		}
		if id != nil {
			if pr, ok := projects[*id]; ok && pr.Closed() {
				open[*id]++
			}
		}
	}
	for _, pr := range data.Projects {
		if n := open[pr.ID]; n > 0 {
			r.warn("projects.yaml: "+pr.ID, msg("{count} open tickets still belong to the closed project", "count", strconv.Itoa(n)))
		}
	}
}
