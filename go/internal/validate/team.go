package validate

import (
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/yamlx"
)

func day(t time.Time) string { return t.Format("2006-01-02") }

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func g(v float64) string { return pymath.General(v) }

func pyFloat(v float64) string { return yamlx.PyFloatRepr(v) }

func isNeg(v *float64) bool { return v != nil && *v < 0 }

func keys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// reporter collects the findings of a check.
type reporter struct{ issues []Issue }

func (r *reporter) error(where, message string) {
	r.issues = append(r.issues, Issue{Level: Error, Where: where, Message: message})
}

func (r *reporter) warn(where, message string) {
	r.issues = append(r.issues, Issue{Level: Warning, Where: where, Message: message})
}

func hasCountry(code string) bool {
	for _, c := range calendar.Countries() {
		if c.Code == code {
			return true
		}
	}
	return false
}

func hasRegion(country, region string) bool {
	for _, r := range calendar.Subdivisions(country) {
		if r == region {
			return true
		}
	}
	return false
}

func contains(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

func checkProductShares(data *storage.TeamData, today time.Time, r *reporter) {
	type period struct {
		label      string
		start, end time.Time
	}
	var periods []period
	for _, s := range data.Sprints {
		periods = append(periods, period{msg("Sprint {id}", "id", s.ID), s.Start, s.End})
	}
	periods = append(periods, period{msg("today"), today, today.AddDate(0, 0, 1)})
	type key struct {
		total float64
		rest  bool
	}
	reported := map[key]bool{}
	for _, p := range periods {
		var shares []float64
		rest := false
		for _, prod := range data.Products {
			if !prod.ActiveBetween(p.start, p.end) {
				continue
			}
			if prod.Share != nil {
				shares = append(shares, *prod.Share)
			} else {
				rest = true
			}
		}
		total := pymath.Sum(shares)
		k := key{pymath.Round(total, 6), rest}
		if reported[k] {
			continue
		}
		switch {
		case total > 1+1e-9:
			reported[k] = true
			r.error("products.yaml", msg("Fixed shares add up to {total} % ({period}) – more than 100 %",
				"total", g(total*100), "period", p.label))
		case total > 1-1e-9 && rest:
			reported[k] = true
			r.warn("products.yaml", msg("Fixed shares add up to 100 % ({period}) – nothing is left for products without a fixed share",
				"period", p.label))
		}
	}
}

// knownSprints are the sprint files plus the following sprints from the calendar (earmarks name
// sprints that have no file yet), by id.
func knownSprints(data *storage.TeamData, ahead int) map[string]time.Time {
	ends := map[string]time.Time{}
	for _, s := range data.Sprints {
		ends[s.ID] = s.End
	}
	var last *model.Sprint
	if n := len(data.Sprints); n > 0 {
		last = &model.Sprint{ID: data.Sprints[n-1].ID, End: data.Sprints[n-1].End}
	}
	team := &data.Team
	chain := calendar.NewChain(team, data.Sprints)
	for i := 0; i < ahead; i++ {
		next, err := chain.After(last)
		if err != nil {
			break // no first sprint: reported elsewhere
		}
		ends[next.ID] = next.End
		last = &next
	}
	return ends
}

func checkTrackerSource(tr model.TrackerSettings, r *reporter) {
	if !contains(model.TrackerKinds, tr.Kind) {
		r.error("team.yaml", msg("tracker.kind: only {allowed}", "allowed", strings.Join(model.TrackerKinds, ", ")))
		return
	}
	if tr.Kind != "jira" {
		return
	}
	if str(tr.BaseURL) == "" {
		r.error("team.yaml", msg("tracker.base_url is missing (address of the Jira server, http or https)"))
	} else {
		switch model.BaseURLProblem(*tr.BaseURL) {
		case model.URLInvalid:
			r.error("team.yaml", msg("tracker.base_url must be an http or https address"))
		case model.URLCredentials:
			r.error("team.yaml", msg("tracker.base_url must not contain credentials"))
		case model.URLExtra:
			r.error("team.yaml", msg("tracker.base_url must not contain parameters (?…) or a fragment (#…)"))
		default:
			if strings.HasPrefix(strings.ToLower(pytext.Strip(*tr.BaseURL)), "http://") {
				r.warn("team.yaml", msg("tracker.base_url is unencrypted (http): the token could be read by others"))
			}
		}
	}
	if str(tr.Query) == "" {
		r.error("team.yaml", msg("tracker.query is missing (JQL query of the tickets)"))
	}
	if str(tr.Fields.Estimate) == "" {
		r.warn("team.yaml", msg("tracker.fields.estimate is missing: without an estimate nothing can be distributed"))
	}
}

func validFieldName(name string) bool {
	return model.RuleFieldName.MatchString(strings.TrimSuffix(name, "\n"))
}

// checkProjects checks projects.yaml; sources are the rule sources (nil without a tracker: no
// rules to check). It returns the project ids.
func checkProjects(data *storage.TeamData, today time.Time, r *reporter, sources []string, products map[string]model.Product) map[string]bool {
	team := data.Team
	projectIDs := map[string]bool{}
	for _, pr := range data.Projects {
		where := "projects.yaml: " + pr.ID
		if projectIDs[pr.ID] {
			r.error(where, msg("duplicate id"))
		}
		projectIDs[pr.ID] = true
		ids := pr.Products()
		switch {
		case team.Features.Products:
			if len(ids) == 0 {
				r.error(where, msg("product is missing (the product distribution is on)"))
			}
			for _, id := range ids {
				prod, known := products[id]
				switch {
				case !known:
					r.error(where, msg("unknown product '{id}'", "id", id))
				case prod.End != nil && prod.End.Before(today) && !pr.Closed():
					r.warn(where, msg("Product '{id}' ended on {end}", "id", id, "end", day(*prod.End)))
				}
			}
		case len(ids) > 0:
			r.error(where, msg("product must be empty (the product distribution is off)"))
		}
		switch {
		case pr.Closed():
		case pr.Target == nil:
			r.warn(where, msg("target is missing: the project is distributed last and has no deadline to miss"))
		case pr.Target.Before(today):
			r.warn(where, msg("target {date} lies in the past", "date", day(*pr.Target)))
		}
		checkProjectV1(data, pr, where, r)
		if sources == nil {
			continue // without a tracker there are no assignment rules
		}
		if pr.Match != nil {
			for _, problem := range RuleProblems(pr.Match, sources) {
				r.error(where, msg("match: {problem}", "problem", problem))
			}
		} else {
			assigned := false
			for _, tk := range data.Tickets {
				if tk.Project != nil && *tk.Project == pr.ID {
					assigned = true
					break
				}
			}
			if !assigned {
				r.warn(where, msg("neither a match rule nor assigned tickets"))
			}
		}
	}
	return projectIDs
}

func checkTickets(data *storage.TeamData, today time.Time, r *reporter) {
	team := data.Team
	tr := team.Tracker
	if team.TrackerRaw != nil {
		// An unreadable section kept while the feature was off: switching it on must not
		// produce a team that does not load.
		if _, err := storage.TrackerFromRaw(team.TrackerRaw, "team.yaml"); err != nil {
			r.error("team.yaml", strings.TrimPrefix(err.Error(), "team.yaml: "))
		}
	}
	if tr.DependencyGap != 0 && tr.DependencyGap != 1 {
		r.error("team.yaml", msg("tracker.dependency_gap must be 0 or 1"))
	}
	sources := model.RuleSourcesWith(tr.RuleFields)
	for _, e := range tr.RuleFields.Entries {
		name := e.Key
		switch {
		case !validFieldName(name) || contains(model.RuleSources, name) || contains(model.RuleReserved, name) ||
			strings.HasSuffix(name, "_contains"):
			r.error("team.yaml", msg("tracker.rule_fields: '{name}' is not allowed (lower-case words with digits and underscores, not one of {fixed}, not a keyword (and, or, not, in, any, all, none), not ending in _contains)",
				"name", name, "fixed", strings.Join(model.RuleSources, ", ")))
		case pytext.Strip(e.Value) == "":
			r.error("team.yaml", msg("tracker.rule_fields: the field name of '{name}' is empty", "name", name))
		}
	}
	order := tr.ProjectMatchOrder
	seen := map[string]bool{}
	bad := false
	for _, s := range order {
		if !contains(sources, s) {
			bad = true
		}
		seen[s] = true
	}
	if bad || len(seen) != len(order) {
		r.error("team.yaml", msg("tracker.project_match_order: only sources from {allowed}, each at most once",
			"allowed", strings.Join(sources, ", ")))
	}
	if !(tr.RoughFactor > 0) {
		r.error("team.yaml", msg("tracker.rough_factor must be > 0"))
	}
	if tr.RefinedAlsoIf != nil {
		for _, problem := range RuleProblems(tr.RefinedAlsoIf, sources) {
			r.error("team.yaml", msg("tracker.refined_also_if: {problem}", "problem", problem))
		}
	}
	if pytext.Strip(tr.LinkType) == "" {
		r.error("team.yaml", msg("tracker.link_type must not be empty"))
	}
	checkTrackerSource(tr, r)

	products := map[string]model.Product{}
	for _, p := range data.Products {
		products[p.ID] = p
	}
	for _, prod := range data.Products {
		if prod.Match != nil && team.Features.Products {
			for _, problem := range RuleProblems(prod.Match, sources) {
				r.error("products.yaml: "+prod.ID, msg("match: {problem}", "problem", problem))
			}
		}
	}
	projectIDs := checkProjects(data, today, r, sources, products)

	known := knownSprints(data, 52)
	ticketKeys := map[string]bool{}
	for _, tk := range data.Tickets {
		where := "tickets.yaml: " + tk.Key
		if ticketKeys[tk.Key] {
			r.error(where, msg("key is duplicated"))
		}
		ticketKeys[tk.Key] = true
		if isNeg(tk.Estimate) {
			r.error(where, msg("{name} must not be negative", "name", "estimate"))
		}
		if isNeg(tk.Remaining) {
			r.error(where, msg("{name} must not be negative", "name", "remaining"))
		}
		if tk.Project != nil && !projectIDs[*tk.Project] {
			r.error(where, msg("unknown project '{id}'", "id", *tk.Project))
		}
		if tk.InSprint != nil {
			if _, ok := known[*tk.InSprint]; !ok {
				r.warn(where, msg("in_sprint '{id}' is not a known sprint", "id", *tk.InSprint))
			}
		}
	}
	deps := make([]Dependency, len(data.Tickets))
	for i, tk := range data.Tickets {
		deps[i] = Dependency{Key: tk.Key, DependsOn: tk.DependsOn}
	}
	for _, cycle := range FindCycles(deps) {
		r.error("tickets.yaml", msg("Circular dependencies: {cycle}",
			"cycle", strings.Join(append(append([]string{}, cycle...), cycle[0]), " → ")))
	}

	earmarked := map[string]bool{}
	for _, e := range data.Preplan.Earmarks {
		where := "preplan.yaml: " + e.Ticket
		if earmarked[e.Ticket] {
			r.error(where, msg("several earmarks for the same ticket"))
		}
		earmarked[e.Ticket] = true
		if !ticketKeys[e.Ticket] {
			r.warn(where, msg("Earmark for an unknown ticket (not in the last import)"))
		}
		if end, ok := known[e.Sprint]; !ok {
			r.warn(where, msg("Sprint '{id}' is not known", "id", e.Sprint))
		} else if !end.After(today) {
			r.warn(where, msg("Earmark for the past sprint '{id}' (ignored; the next import drops it)", "id", e.Sprint))
		}
	}
	estimated := map[string]bool{}
	for _, m := range data.Preplan.Estimates {
		where := "preplan.yaml: " + m.Ticket
		if estimated[m.Ticket] {
			r.error(where, msg("several estimates for the same ticket"))
		}
		estimated[m.Ticket] = true
		if !ticketKeys[m.Ticket] {
			r.warn(where, msg("Estimate for an unknown ticket (not in the last import)"))
		}
		switch {
		case m.Estimate == nil:
			r.error(where, msg("estimate is missing"))
		case *m.Estimate < 0:
			r.error(where, msg("{name} must not be negative", "name", "estimate"))
		}
	}
}

// CheckTeam checks a team's data for errors and plausibility (check_team of validate.py).
// Entries of maps keyed by person or product are reported in sorted order.
func CheckTeam(data *storage.TeamData, today time.Time) []Issue {
	r := &reporter{}
	team := data.Team

	if team.AsOf != nil {
		r.warn("team.yaml", msg("as_of is set: {date} counts as today instead of the date of the computer (remove it for real use)",
			"date", team.AsOf.Format("2006-01-02")))
	}
	f := team.Forecast
	if !(f.ReferenceCapacity > 0) {
		r.error("team.yaml", msg("forecast.reference_capacity must be > 0"))
	}
	if f.StartRate < 0 {
		r.error("team.yaml", msg("forecast.start_rate must be ≥ 0"))
	}
	if f.Window < 1 {
		r.error("team.yaml", msg("forecast.window must be ≥ 1"))
	}
	if !(f.RoadmapShare >= 0 && f.RoadmapShare <= 1) {
		r.error("team.yaml", msg("forecast.roadmap_share must be between 0 and 1"))
	}
	if !(team.Capacity.OverheadShare >= 0 && team.Capacity.OverheadShare < 1) {
		r.error("team.yaml", msg("capacity.overhead_share must be between 0 and 1"))
	}
	country := team.Capacity.Country
	region := str(team.Capacity.Region)
	if !hasCountry(country) {
		r.error("team.yaml", msg("Country '{country}' is not supported", "country", country))
	} else if region != "" && !hasRegion(country, region) {
		r.error("team.yaml", msg("Region '{region}' does not belong to country {country}",
			"region", region, "country", country))
	}
	if _, _, err := calendar.WeekendFromWorkweek(team.Capacity.Workweek); err != nil {
		r.error("team.yaml", msg("Unknown work week '{value}'", "value", team.Capacity.Workweek))
	}
	if team.Capacity.AbsenceHistory < 0 {
		r.error("team.yaml", msg("capacity.absence_history must not be negative"))
	}
	if team.Capacity.OverheadDays < 0 {
		r.error("team.yaml", msg("capacity.overhead_days must not be negative"))
	}
	if team.Sprint.LengthDays < 1 {
		r.error("team.yaml", msg("sprint.length_days must be ≥ 1"))
	}
	if len(data.Sprints) == 0 && (team.Sprint.FirstID == nil || team.Sprint.FirstStart == nil) {
		r.error("team.yaml", msg("Without sprint files, sprint.first.id and sprint.first.start are required"))
	}
	// Calendar, absences and forecast form the follow-up IDs from the running sprint to beyond
	// the last one (without sprint files: from the first sprint). Completed sprints before that
	// do not matter; the last one always counts.
	type link struct {
		where, id string
		nextStart time.Time
	}
	var chain []link
	for _, s := range data.Sprints {
		if s.End.After(today) {
			chain = append(chain, link{"sprints/" + s.ID + ".yaml", s.ID, s.End})
		}
	}
	if n := len(data.Sprints); n > 0 && !data.Sprints[n-1].End.After(today) {
		last := data.Sprints[n-1]
		chain = append(chain, link{"sprints/" + last.ID + ".yaml", last.ID, last.End})
	}
	if len(data.Sprints) == 0 && str(team.Sprint.FirstID) != "" && team.Sprint.FirstStart != nil {
		days := team.Sprint.LengthDays
		if days < 1 {
			days = 1
		}
		chain = append(chain, link{"team.yaml", *team.Sprint.FirstID, team.Sprint.FirstStart.AddDate(0, 0, days)})
	}
	numbering := team.Sprint.Numbering
	for _, l := range chain {
		if !calendar.IDFitsNumbering(l.id, l.nextStart, numbering) {
			r.error(l.where, msg("ID does not match the numbering (expected {expected}) – the ID of the following sprint cannot be formed",
				"expected", calendar.ExpectedIDForm(i18n.Language(), numbering)))
		}
	}

	ids := map[string]bool{}
	for _, p := range data.People {
		where := "people.yaml: " + p.ID
		if ids[p.ID] {
			r.error(where, msg("duplicate id"))
		}
		ids[p.ID] = true
		if len(p.Memberships) == 0 {
			r.warn(where, msg("no memberships recorded"))
		}
		if p.Kind == model.KindExternal && len(p.Memberships) > 0 && p.Memberships[len(p.Memberships)-1].End == nil {
			r.warn(where, msg("external person without an end date"))
		}
		ordered := append([]model.Membership(nil), p.Memberships...)
		sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].Start.Before(ordered[j].Start) })
		for _, m := range ordered {
			if !(m.FTE >= 0 && m.FTE <= 1) {
				r.error(where, msg("fte {fte} must be between 0 and 1", "fte", pyFloat(m.FTE)))
			}
			if m.End != nil && m.End.Before(m.Start) {
				r.error(where, msg("membership ends ({end}) before it starts ({start})",
					"end", day(*m.End), "start", day(m.Start)))
			}
		}
		for i := 0; i+1 < len(ordered); i++ {
			a, b := ordered[i], ordered[i+1]
			if a.End == nil || !a.End.Before(b.Start) {
				r.error(where, msg("memberships overlap ({a} / {b})", "a", day(a.Start), "b", day(b.Start)))
			}
		}
	}

	for _, p := range data.People {
		where := "people.yaml: " + p.ID
		if _, _, err := calendar.WeekendFromWorkweek(str(p.Workweek)); err != nil {
			r.error(where, msg("Unknown work week '{value}'", "value", str(p.Workweek)))
		}
		own := str(p.Country)
		pregion := str(p.Region)
		if own != "" && !hasCountry(own) {
			r.error(where, msg("Country '{country}' is not supported", "country", own))
		} else if pregion != "" {
			c := own
			if c == "" {
				c = country
			}
			if !hasRegion(c, pregion) {
				r.error(where, msg("Region '{region}' does not belong to country {country}",
					"region", pregion, "country", c))
			}
		}
	}

	productIDs := map[string]bool{}
	for _, prod := range data.Products {
		where := "products.yaml: " + prod.ID
		if productIDs[prod.ID] {
			r.error(where, msg("duplicate id"))
		}
		productIDs[prod.ID] = true
		if prod.Share != nil && !(*prod.Share > 0 && *prod.Share <= 1) {
			r.error(where, msg("share must be between 0 and 1"))
		}
		if prod.Start != nil && prod.End != nil && prod.End.Before(*prod.Start) {
			r.error(where, msg("period ends ({end}) before it starts ({start})",
				"end", day(*prod.End), "start", day(*prod.Start)))
		}
	}
	products := map[string]model.Product{}
	for _, p := range data.Products {
		products[p.ID] = p
	}
	checkProductShares(data, today, r)

	people := map[string]model.Person{}
	for _, p := range data.People {
		people[p.ID] = p
	}
	var previous *model.Sprint
	for i := range data.Sprints {
		s := &data.Sprints[i]
		checkSprint(r, data, s, previous, people, products, today)
		previous = s
	}
	if team.Features.Tickets {
		checkTickets(data, today, r)
	} else if team.Features.Projects {
		checkProjects(data, today, r, nil, products)
	}
	checkV1(data, today, r)
	return r.issues
}

func checkSprint(r *reporter, data *storage.TeamData, s, previous *model.Sprint,
	people map[string]model.Person, products map[string]model.Product, today time.Time) {
	where := "sprints/" + s.ID + ".yaml"
	if !s.End.After(s.Start) {
		r.error(where, msg("end must be after start"))
	}
	if previous != nil && s.Start.Before(previous.End) {
		r.error(where, msg("overlaps sprint {id}", "id", previous.ID))
	}
	if previous != nil && s.Start.After(previous.End) {
		r.warn(where, msg("gap after sprint {id} ({end} → {start})",
			"id", previous.ID, "end", day(previous.End), "start", day(s.Start)))
	}

	for _, pid := range keys(s.ExpectedAbsences) {
		absent := s.ExpectedAbsences[pid]
		if _, ok := people[pid]; !ok {
			r.error(where, msg("Announced absences for unknown person '{id}'", "id", pid))
		} else if absent < 0 {
			r.error(where, msg("expected_absences.{id} must not be negative", "id", pid))
		}
	}

	workdays := len(calendar.TeamWorkdays(&data.Team, s.Start, s.End))
	for _, pid := range keys(s.Absences) {
		absent := s.Absences[pid]
		person, ok := people[pid]
		if !ok {
			r.error(where, msg("absences for unknown person '{id}'", "id", pid))
		} else if !person.ActiveBetween(s.Start, s.End) {
			r.warn(where, msg("'{id}' is not in the team during this sprint", "id", pid))
		}
		if absent < 0 {
			r.error(where, msg("absences for '{id}' are negative", "id", pid))
		} else if absent > float64(workdays) {
			r.error(where, msg("'{id}': {absent} days absent, the sprint only has {days} working days",
				"id", pid, "absent", g(absent), "days", strconv.Itoa(workdays)))
		}
	}

	productIDs := keys(s.Products)
	for _, pid := range productIDs {
		values := s.Products[pid]
		product, ok := products[pid]
		if !ok {
			r.error(where, msg("values for unknown product '{id}'", "id", pid))
		} else if !product.ActiveBetween(s.Start, s.End) && !values.IsEmpty() {
			r.warn(where, msg("according to the product list, product '{id}' is not handled in this sprint", "id", pid))
		}
		for _, n := range []struct {
			name  string
			value *float64
		}{
			{"preplanned", values.Preplanned}, {"planned", values.Planned}, {"done", values.Done},
			{"production_planned", values.ProductionPlanned}, {"production_done", values.ProductionDone},
		} {
			if isNeg(n.value) {
				r.error(where, msg("products.{id}.{name} must not be negative", "id", pid, "name", n.name))
			}
		}
	}
	for _, pid := range productIDs {
		values := s.Products[pid]
		for _, pair := range [][2]*float64{
			{values.Planned, values.ProductionPlanned}, {values.Done, values.ProductionDone},
		} {
			whole, part := pair[0], pair[1]
			total := 0.0
			if whole != nil {
				total = *whole
			}
			if part != nil && *part > total+0.05 {
				r.warn(where, msg("Product '{id}': production access ({part}) is larger than the total ({whole})",
					"id", pid, "part", g(*part), "whole", g(total)))
			}
		}
	}
	var planned, done []float64
	for _, pid := range productIDs {
		if v := s.Products[pid].Planned; v != nil {
			planned = append(planned, *v)
		}
		if v := s.Products[pid].Done; v != nil {
			done = append(done, *v)
		}
	}
	if len(planned) > 0 && s.Commitment != nil && pymath.Sum(planned) > *s.Commitment+0.05 {
		r.warn(where, msg("planned per product ({planned}) exceeds the commitment ({commitment})",
			"planned", g(pymath.Sum(planned)), "commitment", g(*s.Commitment)))
	}
	if len(done) > 0 && s.Velocity != nil && pymath.Sum(done) > *s.Velocity+0.05 {
		r.warn(where, msg("done per product ({done}) exceeds the velocity ({velocity})",
			"done", g(pymath.Sum(done)), "velocity", g(*s.Velocity)))
	}

	for _, n := range []struct {
		name  string
		value *float64
	}{
		{"not_done", s.NotDone}, {"additional_done", s.AdditionalDone},
		{"production_planned", s.ProductionPlanned}, {"production_done", s.ProductionDone},
	} {
		if isNeg(n.value) {
			r.error(where, msg("{name} must not be negative", "name", n.name))
		}
	}
	if s.ProductionPlanned != nil && s.Commitment != nil && *s.ProductionPlanned > *s.Commitment+0.05 {
		r.warn(where, msg("Planned with production access ({part}) exceeds the commitment ({whole})",
			"part", g(*s.ProductionPlanned), "whole", g(*s.Commitment)))
	}
	if s.Velocity != nil && s.Commitment != nil && (s.NotDone != nil || s.AdditionalDone != nil) {
		notDone, extra := 0.0, 0.0
		if s.NotDone != nil {
			notDone = *s.NotDone
		}
		if s.AdditionalDone != nil {
			extra = *s.AdditionalDone
		}
		expected := *s.Commitment - notDone + extra
		if abs(expected-*s.Velocity) > 0.05 {
			r.warn(where, msg("Commitment ({commitment}) − not finished ({open}) + additionally done ({extra}) gives {expected}, but the velocity is {velocity}",
				"commitment", g(*s.Commitment), "open", g(notDone), "extra", g(extra),
				"expected", g(expected), "velocity", g(*s.Velocity)))
		}
	}
	for _, n := range []struct {
		name  string
		value *float64
	}{
		{"capacity", s.Capacity},
		{"forecast_ist", s.Commitment}, // the file key keeps its name
		{"velocity", s.Velocity},
		{"forecast_plan", s.ForecastPlan},
	} {
		if isNeg(n.value) {
			r.error(where, msg("{name} must not be negative", "name", n.name))
		}
	}
	if s.ScopeCreep != nil && !(*s.ScopeCreep >= 0 && *s.ScopeCreep <= 1) {
		r.warn(where, msg("scope_creep {value} is outside 0–1 (a share, not a percentage?)", "value", g(*s.ScopeCreep)))
	}
	if s.Capacity != nil && *s.Capacity == 0 {
		r.warn(where, msg("capacity 0 – normalized velocity cannot be calculated"))
	}
	if s.Velocity != nil && s.Commitment != nil && *s.Commitment != 0 && *s.Velocity > 2*(*s.Commitment) {
		r.warn(where, msg("velocity is more than twice the commitment – typo?"))
	}

	if s.Planning != nil && s.End.After(today) {
		committed := s.Planning.Committed()
		if s.Commitment != nil && committed != 0 && abs(*s.Commitment-committed) > 0.05 {
			r.warn(where, msg("commitment {commitment} differs from carry-over + backlog ({planned}) – typo or missing ticket?",
				"commitment", g(*s.Commitment), "planned", g(committed)))
		}
		if pymath.Sum(s.Planning.Corrections) > committed {
			r.warn(where, msg("corrections exceed carry-over + backlog"))
		}
	}

	if !s.End.After(today) {
		if s.Velocity == nil {
			r.warn(where, msg("sprint has ended, velocity missing (record the review)"))
		}
		if s.Capacity == nil {
			r.warn(where, msg("sprint has ended, capacity not frozen (otherwise calculated from the current people list)"))
		}
	}
}

func abs(v float64) float64 {
	if v < 0 {
		return -v
	}
	return v
}

// CheckTeamFiles reports the silent assumptions in a team's files (folder base): duplicate keys
// and empty number fields, each as a notice with file name, line and key path. The files of
// the ticket pre-planning only with tickets.
func CheckTeamFiles(base string, tickets bool) []Issue {
	return CheckFiles(base, model.Features{Tickets: tickets})
}

// CheckFiles is CheckTeamFiles for the features of the team: with projects but without tickets
// projects.yaml is checked as well.
func CheckFiles(base string, features model.Features) []Issue {
	var files []string
	for _, name := range storage.TeamFiles {
		if features.Tickets || !contains(storage.TicketFiles, name) || (features.Projects && name == "projects.yaml") {
			files = append(files, name)
		}
	}
	if matches, err := filepath.Glob(filepath.Join(base, "sprints", "*.yaml")); err == nil {
		sort.Strings(matches)
		for _, m := range matches {
			if rel, err := filepath.Rel(base, m); err == nil {
				files = append(files, filepath.ToSlash(rel))
			}
		}
	}
	var issues []Issue
	for _, name := range files {
		b, err := os.ReadFile(filepath.Join(base, filepath.FromSlash(name)))
		if err != nil || !utf8.Valid(b) {
			continue // loading reports missing or unreadable files
		}
		issues = append(issues, CheckYAMLText(universalNewlines(string(b)), name)...)
	}
	return issues
}

// universalNewlines reads text like Python's text mode: CRLF and CR become LF.
func universalNewlines(s string) string {
	return strings.ReplaceAll(strings.ReplaceAll(s, "\r\n", "\n"), "\r", "\n")
}

// CheckFolder is the complete data check of one team folder (root/team): the load error as the
// only finding when the team does not load, otherwise CheckTeam and CheckTeamFiles. It is what
// a sync runs on a data folder after a merge.
func CheckFolder(root, team string, today time.Time) []Issue {
	data, err := storage.NewRepository(root).Load(team)
	if err != nil {
		return []Issue{{Level: Error, Where: team, Message: err.Error()}}
	}
	return append(CheckTeam(data, today), CheckFiles(filepath.Join(root, team), data.Team.Features)...)
}
