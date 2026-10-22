package storage

import (
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/yamlx"
)

// upper is str.upper() for the letters that differ from strings.ToUpper (ß gives SS).
func upper(s string) string {
	return strings.ToUpper(strings.NewReplacer("ß", "SS", "ﬁ", "FI", "ﬂ", "FL").Replace(s))
}

var isoTimestampRe = regexp.MustCompile(
	`^(\d{4})-?(\d{2})-?(\d{2})(?:[T ](\d{2})(?::?(\d{2})(?::?(\d{2})(?:[.,](\d{1,6})\d*)?)?)?)?\s*(Z|[+-]\d{2}(?::?\d{2}(?::?\d{2})?)?)?$`)

// parseISOTimestamp is datetime.fromisoformat (Python 3.11 and later) for the usual forms: a date,
// optionally with a time, fractional seconds and a UTC offset. Without an offset the result is in
// UTC (a "naive" time, see yamlx.Dump); with one it keeps the offset.
func parseISOTimestamp(s string) (time.Time, bool) {
	m := isoTimestampRe.FindStringSubmatch(s)
	if m == nil {
		return time.Time{}, false
	}
	date, ok := parseISODate(m[1] + "-" + m[2] + "-" + m[3])
	if !ok {
		return time.Time{}, false
	}
	atoi := func(x string) int { n, _ := strconv.Atoi(x); return n }
	hour, minute, second, micro := atoi(m[4]), atoi(m[5]), atoi(m[6]), 0
	if m[7] != "" {
		micro = atoi((m[7] + "000000")[:6])
	}
	if hour > 23 || minute > 59 || second > 59 {
		return time.Time{}, false
	}
	loc := time.UTC
	if z := m[8]; z != "" && z != "Z" {
		sign := 1
		if z[0] == '-' {
			sign = -1
		}
		digits := strings.ReplaceAll(z[1:], ":", "")
		secs := atoi(digits[:2]) * 3600
		if len(digits) >= 4 {
			secs += atoi(digits[2:4]) * 60
		}
		if len(digits) >= 6 {
			secs += atoi(digits[4:6])
		}
		if secs >= 24*3600 {
			return time.Time{}, false
		}
		loc = time.FixedZone("", sign*secs)
	} else if z == "Z" {
		loc = time.FixedZone("", 0) // aware (written with +00:00), unlike a time without zone
	}
	return time.Date(date.Year(), date.Month(), date.Day(), hour, minute, second, micro*1000, loc), true
}

// --- Projects ---------------------------------------------------------------------------

func schemaOf(d *yamlx.Map, where string) error {
	raw := get(d, "schema")
	if isEmptyText(raw) {
		return nil
	}
	n, ok := raw.(int64)
	if !ok {
		return dataErr("{where}: schema must be a whole number, found {value}", "where", where, "value", cut60(repr(raw)))
	}
	if n > Schema {
		return dataErr("{where}: The file was written by a newer program version (schema {found}, this version knows up to {known}). Please update foresprint.",
			"where", where, "found", strconv.FormatInt(n, 10), "known", strconv.Itoa(Schema))
	}
	return nil
}

// sprintRef is _sprint_ref: a sprint id as text; like sprint files, 2026.20 must be quoted.
func sprintRef(v any, where, name string) (*string, error) {
	if isEmptyText(v) {
		return nil, nil
	}
	if _, ok := v.(float64); ok {
		return nil, dataErr("{where}: please put {name} in quotation marks, e.g. {name}: \"2026.20\"", "where", where, "name", name)
	}
	s := pyStr(v)
	return &s, nil
}

// ProjectsFromDict is projects_from_dict.
func ProjectsFromDict(d *yamlx.Map, where string) ([]model.Project, error) {
	if err := schemaOf(d, where); err != nil {
		return nil, err
	}
	list, err := sequence(get(d, "projects"), where, "projects")
	if err != nil {
		return nil, err
	}
	var projects []model.Project
	for i, raw := range list {
		at := where + ": projects[" + idx(i) + "]"
		p, ok := asMap(raw)
		if !ok || !has(p, "id") {
			return nil, dataErr("{where}: field 'id' missing", "where", at)
		}
		pr := model.Project{ID: pyStr(get(p, "id"))}
		pr.Name = strOr(get(p, "name"), pr.ID)
		pr.Product = text(get(p, "product"))
		if truthy(get(p, "target")) {
			t, err := dateOf(get(p, "target"), at)
			if err != nil {
				return nil, err
			}
			pr.Target = &t
		}
		if pr.Priority, err = intOf(get(p, "priority"), at, "priority", 0); err != nil {
			return nil, err
		}
		if basis := get(p, "budget_basis"); truthy(basis) {
			b, err := choice(basis, budgetBases, model.BudgetPlan, at, "budget_basis")
			if err != nil {
				return nil, err
			}
			pr.BudgetBasis = &b
		}
		if pr.Match, err = ruleFrom(get(p, "match"), at+": match"); err != nil {
			return nil, err
		}
		pr.Note = text(get(p, "note"))
		if err = projectExtrasFrom(p, &pr, at); err != nil {
			return nil, err
		}
		projects = append(projects, pr)
	}
	return projects, nil
}

// ProjectsToDict is projects_to_dict.
func ProjectsToDict(projects []model.Project) *yamlx.Map {
	out := make([]any, 0, len(projects))
	for _, p := range projects {
		entry := omap("id", p.ID, "name", p.Name)
		if p.Product != nil && *p.Product != "" {
			put(entry, "product", *p.Product)
		}
		put(entry, "target", dateOrNil(p.Target))
		put(entry, "priority", int64(p.Priority))
		if p.BudgetBasis != nil {
			put(entry, "budget_basis", string(*p.BudgetBasis))
		}
		if p.Match != nil {
			put(entry, "match", ruleTo(p.Match))
		}
		if p.Note != nil && *p.Note != "" {
			put(entry, "note", *p.Note)
		}
		projectExtrasTo(entry, p)
		out = append(out, entry)
	}
	return omap("schema", int64(Schema), "projects", out)
}

// --- Tickets ---------------------------------------------------------------------------

var estimateSources = []model.EstimateSource{model.EstimateRefined, model.EstimateRough, model.EstimateManual, model.EstimateNone}

// TicketsFile is the content of tickets.yaml.
type TicketsFile struct {
	Tickets  []model.Ticket
	Imported *time.Time
	Source   *string
}

// TicketsFromDict is tickets_from_dict: the tickets of the last import plus its time stamp and
// source (both optional).
func TicketsFromDict(d *yamlx.Map, where string) (TicketsFile, error) {
	var out TicketsFile
	if err := schemaOf(d, where); err != nil {
		return out, err
	}
	var err error
	if out.Imported, err = timestampOf(get(d, "imported"), where, "imported"); err != nil {
		return out, err
	}
	out.Source = text(get(d, "source"))
	list, err := sequence(get(d, "tickets"), where, "tickets")
	if err != nil {
		return out, err
	}
	for i, item := range list {
		at := where + ": tickets[" + idx(i) + "]"
		raw, ok := asMap(item)
		if !ok || !truthy(get(raw, "key")) {
			return out, dataErr("{where}: field 'key' is missing", "where", at)
		}
		tk := model.Ticket{Key: pyStr(get(raw, "key")), Title: strOr(get(raw, "title"), "")}
		tk.Status = text(get(raw, "status"))
		tk.IssueType = text(get(raw, "issue_type"))
		tk.Priority = text(get(raw, "priority"))
		fm, err := mapping(get(raw, "fields"), at, "fields")
		if err != nil {
			return out, err
		}
		for _, e := range fm.Entries {
			vals, err := texts(e.Value, at, "fields."+pyStr(e.Key))
			if err != nil {
				return out, err
			}
			tk.Extra.Set(pyStr(e.Key), vals)
		}
		if tk.Estimate, err = floatOf(get(raw, "estimate"), at+": estimate"); err != nil {
			return out, err
		}
		if tk.Remaining, err = floatOf(get(raw, "remaining"), at+": remaining"); err != nil {
			return out, err
		}
		if tk.EstimateSource, err = choice(get(raw, "estimate_source"), estimateSources, model.EstimateNone, at, "estimate_source"); err != nil {
			return out, err
		}
		tk.RefinedUnclear = truthy(getOr(raw, "refined_unclear", false))
		if tk.InSprint, err = sprintRef(get(raw, "in_sprint"), at, "in_sprint"); err != nil {
			return out, err
		}
		tk.SprintName = text(get(raw, "sprint_name"))
		tk.Rank = text(get(raw, "rank"))
		tk.Epic = text(get(raw, "epic"))
		if tk.Labels, err = texts(get(raw, "labels"), at, "labels"); err != nil {
			return out, err
		}
		if tk.Components, err = texts(get(raw, "components"), at, "components"); err != nil {
			return out, err
		}
		if tk.DependsOn, err = texts(get(raw, "depends_on"), at, "depends_on"); err != nil {
			return out, err
		}
		tk.Project = text(get(raw, "project"))
		if tk.ProjectCandidates, err = texts(get(raw, "project_candidates"), at, "project_candidates"); err != nil {
			return out, err
		}
		tk.Done = truthy(getOr(raw, "done", false))
		if err = packageFieldsFrom(raw, &tk, at); err != nil {
			return out, err
		}
		out.Tickets = append(out.Tickets, tk)
	}
	return out, nil
}

// TicketsToDict is tickets_to_dict.
func TicketsToDict(f TicketsFile) *yamlx.Map {
	out := omap("schema", int64(Schema))
	if f.Imported != nil {
		put(out, "imported", f.Imported.Truncate(time.Second))
	}
	if f.Source != nil && *f.Source != "" {
		put(out, "source", *f.Source)
	}
	entries := make([]any, 0, len(f.Tickets))
	for _, tk := range f.Tickets {
		entry := omap("key", tk.Key, "title", tk.Title, "status", strPtr(tk.Status),
			"issue_type", strPtr(tk.IssueType), "estimate", cleanPtr(tk.Estimate))
		if tk.Priority != nil && *tk.Priority != "" {
			put(entry, "priority", *tk.Priority)
		}
		if tk.Remaining != nil {
			put(entry, "remaining", clean(*tk.Remaining))
		}
		put(entry, "estimate_source", string(tk.EstimateSource))
		if tk.RefinedUnclear {
			put(entry, "refined_unclear", true)
		}
		if tk.InSprint != nil {
			put(entry, "in_sprint", *tk.InSprint)
		}
		if tk.SprintName != nil {
			put(entry, "sprint_name", *tk.SprintName)
		}
		put(entry, "rank", strPtr(tk.Rank))
		put(entry, "epic", strPtr(tk.Epic))
		put(entry, "labels", strs(tk.Labels))
		put(entry, "components", strs(tk.Components))
		if tk.Extra.Len() > 0 {
			fields := &yamlx.Map{}
			for _, e := range tk.Extra.Entries {
				put(fields, e.Key, strs(e.Value))
			}
			put(entry, "fields", fields)
		}
		put(entry, "depends_on", strs(tk.DependsOn))
		if tk.Project != nil {
			put(entry, "project", *tk.Project)
		}
		if len(tk.ProjectCandidates) > 0 {
			put(entry, "project_candidates", strs(tk.ProjectCandidates))
		}
		if tk.Done {
			put(entry, "done", true)
		}
		packageFieldsTo(entry, tk)
		entries = append(entries, entry)
	}
	put(out, "tickets", entries)
	return out
}

// --- Preplan ---------------------------------------------------------------------------

// PreplanFromDict is preplan_from_dict.
func PreplanFromDict(d *yamlx.Map, where string) (model.Preplan, error) {
	var pp model.Preplan
	if err := schemaOf(d, where); err != nil {
		return pp, err
	}
	earmarks, err := sequence(get(d, "earmarks"), where, "earmarks")
	if err != nil {
		return pp, err
	}
	for i, item := range earmarks {
		at := where + ": earmarks[" + idx(i) + "]"
		raw, ok := asMap(item)
		if !ok || !truthy(get(raw, "ticket")) {
			return pp, dataErr("{where}: field 'ticket' is missing", "where", at)
		}
		sprint, err := sprintRef(get(raw, "sprint"), at, "sprint")
		if err != nil {
			return pp, err
		}
		if sprint == nil {
			return pp, dataErr("{where}: field 'sprint' is missing", "where", at)
		}
		pp.Earmarks = append(pp.Earmarks, model.Earmark{Ticket: pyStr(get(raw, "ticket")), Sprint: *sprint, Note: text(get(raw, "note"))})
	}
	estimates, err := sequence(get(d, "estimates"), where, "estimates")
	if err != nil {
		return pp, err
	}
	for i, item := range estimates {
		at := where + ": estimates[" + idx(i) + "]"
		raw, ok := asMap(item)
		if !ok || !truthy(get(raw, "ticket")) {
			return pp, dataErr("{where}: field 'ticket' is missing", "where", at)
		}
		est, err := floatOf(get(raw, "estimate"), at+": estimate")
		if err != nil {
			return pp, err
		}
		pp.Estimates = append(pp.Estimates, model.ManualEstimate{Ticket: pyStr(get(raw, "ticket")), Estimate: est, Note: text(get(raw, "note"))})
	}
	if err := preplanExtrasFrom(d, &pp, where); err != nil {
		return pp, err
	}
	return pp, nil
}

// PreplanToDict is preplan_to_dict.
func PreplanToDict(pp model.Preplan) *yamlx.Map {
	earmarks := make([]any, 0, len(pp.Earmarks))
	for _, e := range pp.Earmarks {
		entry := omap("ticket", e.Ticket, "sprint", e.Sprint)
		if e.Note != nil && *e.Note != "" {
			put(entry, "note", *e.Note)
		}
		earmarks = append(earmarks, entry)
	}
	estimates := make([]any, 0, len(pp.Estimates))
	for _, m := range pp.Estimates {
		entry := omap("ticket", m.Ticket, "estimate", cleanPtr(m.Estimate))
		if m.Note != nil && *m.Note != "" {
			put(entry, "note", *m.Note)
		}
		estimates = append(estimates, entry)
	}
	out := omap("schema", int64(Schema), "earmarks", earmarks, "estimates", estimates)
	preplanExtrasTo(out, pp)
	return out
}
