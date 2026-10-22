package storage

import (
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/yamlx"
)

// The readers and writers of what 1.0 adds. Everything is optional: a field is written only
// when it has a value, so a file from 0.8 is read and written back unchanged.

// AbsencesHeader is the comment at the top of abwesenheiten.yaml.
const AbsencesHeader = "# Planned absences as periods per person. Only dates are stored, never a reason.\n"

// PackagesHeader is the comment at the top of arbeitspakete.yaml.
const PackagesHeader = "# Work packages kept in Foresprint (instead of tickets from a tracker).\n"

// --- Absence periods ------------------------------------------------------------------

// AbsencesFromDict reads abwesenheiten.yaml: periods per person id.
func AbsencesFromDict(d *yamlx.Map, where string) (model.Absences, error) {
	var out model.Absences
	if err := schemaOf(d, where); err != nil {
		return out, err
	}
	people, err := mapping(get(d, "absences"), where, "absences")
	if err != nil {
		return out, err
	}
	for _, e := range people.Entries {
		pid := pyStr(e.Key)
		list, err := sequence(e.Value, where+": absences."+pid, "periods")
		if err != nil {
			return out, err
		}
		periods := make([]model.AbsencePeriod, 0, len(list))
		for i, item := range list {
			at := where + ": absences." + pid + "[" + idx(i) + "]"
			m, ok := asMap(item)
			if !ok || !truthy(get(m, "from")) || !truthy(get(m, "to")) {
				return out, dataErr("{where}: fields 'from' and 'to' are required", "where", at)
			}
			p := model.AbsencePeriod{Confirmed: truthy(getOr(m, "confirmed", false))}
			if p.From, err = dateOf(get(m, "from"), at); err != nil {
				return out, err
			}
			if p.To, err = dateOf(get(m, "to"), at); err != nil {
				return out, err
			}
			if p.To.Before(p.From) {
				return out, dataErr("{where}: 'to' lies before 'from'", "where", at)
			}
			periods = append(periods, p)
		}
		out.Set(pid, periods)
	}
	return out, nil
}

// AbsencesToDict writes the periods; the periods of a person are sorted by start.
func AbsencesToDict(a model.Absences) *yamlx.Map {
	people := &yamlx.Map{}
	for _, e := range a.Entries {
		if len(e.Value) == 0 {
			continue
		}
		list := make([]any, 0, len(e.Value))
		for _, p := range sortedPeriods(e.Value) {
			entry := omap("from", yamlx.Date(p.From), "to", yamlx.Date(p.To))
			if p.Confirmed {
				put(entry, "confirmed", true)
			}
			list = append(list, entry)
		}
		put(people, e.Key, list)
	}
	return omap("schema", int64(Schema), "absences", people)
}

func sortedPeriods(list []model.AbsencePeriod) []model.AbsencePeriod {
	out := append([]model.AbsencePeriod(nil), list...)
	for i := 1; i < len(out); i++ { // insertion sort: stable, lists are short
		for j := i; j > 0 && out[j].From.Before(out[j-1].From); j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}

// --- Team -----------------------------------------------------------------------------

var (
	personKinds   = []model.PersonKind{model.KindMember, model.KindGuest, model.KindExternal}
	projectStates = []model.ProjectState{model.ProjectFinished, model.ProjectCancelled}
	removedTarget = []string{"backlog", "pro_forma", "next"}
)

func namingFrom(raw any, where string) ([]model.NamingRule, error) {
	list, err := sequence(raw, where, "naming")
	if err != nil {
		return nil, err
	}
	var out []model.NamingRule
	for i, item := range list {
		at := where + ": naming[" + idx(i) + "]"
		m, ok := asMap(item)
		if !ok || !truthy(get(m, "pattern")) {
			return nil, dataErr("{where}: field 'pattern' is missing", "where", at)
		}
		pattern := pyStr(get(m, "pattern"))
		if bad := model.NamingProblem(pattern); bad != "" {
			return nil, dataErr("{where}: unknown placeholder {name}", "where", at, "name", bad)
		}
		from, err := sprintRef(get(m, "from"), at, "from")
		if err != nil {
			return nil, err
		}
		out = append(out, model.NamingRule{From: from, Pattern: pattern})
	}
	return out, nil
}

func namingTo(rules []model.NamingRule) []any {
	out := make([]any, len(rules))
	for i, r := range rules {
		entry := &yamlx.Map{}
		if r.From != nil {
			put(entry, "from", *r.From)
		}
		put(entry, "pattern", r.Pattern)
		out[i] = entry
	}
	return out
}

func estimationFrom(raw any, where string) (model.EstimationSettings, error) {
	var e model.EstimationSettings
	m, err := mapping(raw, where, "estimation")
	if err != nil {
		return e, err
	}
	if e.Factor, err = floatOf(get(m, "factor"), where+": estimation.factor"); err != nil {
		return e, err
	}
	if e.Factor != nil && *e.Factor <= 0 {
		return e, dataErr("{where}: estimation.factor must be greater than 0", "where", where)
	}
	list, err := sequence(get(m, "changes"), where, "estimation.changes")
	if err != nil {
		return e, err
	}
	for i, item := range list {
		at := where + ": estimation.changes[" + idx(i) + "]"
		c, ok := asMap(item)
		if !ok {
			return e, dataErr("{where}: mapping with from/unit expected", "where", at)
		}
		from, err := sprintRef(get(c, "from"), at, "from")
		if err != nil {
			return e, err
		}
		if from == nil {
			return e, dataErr("{where}: field 'from' is missing", "where", at)
		}
		ch := model.UnitChange{From: *from}
		if ch.Unit, err = choice(get(c, "unit"), units, model.UnitPT, at, "unit"); err != nil {
			return e, err
		}
		if ch.Factor, err = floatOf(get(c, "factor"), at+": factor"); err != nil {
			return e, err
		}
		if ch.Factor != nil && *ch.Factor <= 0 {
			return e, dataErr("{where}: factor must be greater than 0", "where", at)
		}
		e.Changes = append(e.Changes, ch)
	}
	return e, nil
}

func estimationTo(e model.EstimationSettings) *yamlx.Map {
	out := &yamlx.Map{}
	if e.Factor != nil {
		put(out, "factor", clean(*e.Factor))
	}
	if len(e.Changes) > 0 {
		list := make([]any, len(e.Changes))
		for i, c := range e.Changes {
			entry := omap("from", c.From, "unit", string(c.Unit))
			if c.Factor != nil {
				put(entry, "factor", clean(*c.Factor))
			}
			list[i] = entry
		}
		put(out, "changes", list)
	}
	return out
}

// --- Tracker additions ----------------------------------------------------------------

func trackerFieldsFrom(fields *yamlx.Map) model.TrackerFields {
	return model.TrackerFields{
		Estimate: text(get(fields, "estimate")), Remaining: text(get(fields, "remaining")), Epic: text(get(fields, "epic")),
		Status: text(get(fields, "status")), Acceptance: text(get(fields, "acceptance")),
		Product: text(get(fields, "product")), Project: text(get(fields, "project")),
		Refined: text(get(fields, "refined")), Production: text(get(fields, "production")),
	}
}

func trackerFieldNames(f model.TrackerFields) []struct {
	name  string
	value *string
} {
	return []struct {
		name  string
		value *string
	}{{"estimate", f.Estimate}, {"remaining", f.Remaining}, {"epic", f.Epic}, {"status", f.Status},
		{"acceptance", f.Acceptance}, {"product", f.Product}, {"project", f.Project},
		{"refined", f.Refined}, {"production", f.Production}}
}

func trackerExtrasFrom(d *yamlx.Map, tr *model.TrackerSettings, at string) error {
	var err error
	tr.ProductionLabel = text(get(d, "production_label"))
	rules, err := sequence(get(d, "production_rules"), at, "production_rules")
	if err != nil {
		return err
	}
	for i, item := range rules {
		where := at + ".production_rules[" + idx(i) + "]"
		m, ok := asMap(item)
		if !ok || !truthy(get(m, "match")) {
			return dataErr("{where}: field 'match' is missing", "where", where)
		}
		r := model.ProductionRule{}
		if r.Match, err = ruleFrom(get(m, "match"), where+": match"); err != nil {
			return err
		}
		share, err := floatOf(get(m, "share"), where+": share")
		if err != nil {
			return err
		}
		if share == nil || *share < 0 || *share > 100 {
			return dataErr("{where}: 'share' must be between 0 and 100", "where", where)
		}
		r.Percent = *share
		tr.ProductionRules = append(tr.ProductionRules, r)
	}
	tr.WriteSprint = truthy(getOr(d, "write_sprint", false))
	if tr.RemovedTarget, err = choice(get(d, "removed_target"), removedTarget, "", at, "removed_target"); err != nil {
		return err
	}
	if t := text(get(d, "package_prefix")); t != nil {
		tr.PackagePrefix = *t
	}
	if v := get(d, "board_id"); !isEmptyText(v) {
		n, err := intOf(v, at, "board_id", 0)
		if err != nil {
			return err
		}
		if n < 1 {
			return dataErr("{where}: 'board_id' must be a positive whole number", "where", at)
		}
		tr.BoardID = &n
	}
	return nil
}

func trackerExtrasTo(out *yamlx.Map, tr model.TrackerSettings) {
	if tr.ProductionLabel != nil && *tr.ProductionLabel != "" {
		put(out, "production_label", *tr.ProductionLabel)
	}
	if len(tr.ProductionRules) > 0 {
		list := make([]any, len(tr.ProductionRules))
		for i, r := range tr.ProductionRules {
			entry := &yamlx.Map{}
			if r.Match != nil {
				put(entry, "match", ruleTo(r.Match))
			}
			put(entry, "share", clean(r.Percent))
			list[i] = entry
		}
		put(out, "production_rules", list)
	}
	if tr.WriteSprint {
		put(out, "write_sprint", true)
	}
	if tr.RemovedTarget != "" {
		put(out, "removed_target", tr.RemovedTarget)
	}
	if tr.PackagePrefix != "" {
		put(out, "package_prefix", tr.PackagePrefix)
	}
	if tr.BoardID != nil {
		put(out, "board_id", *tr.BoardID)
	}
}

// --- Projects -------------------------------------------------------------------------

func projectExtrasFrom(p *yamlx.Map, pr *model.Project, at string) error {
	var err error
	if list, err := texts(get(p, "products"), at, "products"); err != nil {
		return err
	} else if len(list) > 0 {
		first := list[0]
		pr.Product = &first
		pr.AlsoProducts = list[1:]
	}
	if truthy(get(p, "start")) {
		t, err := dateOf(get(p, "start"), at)
		if err != nil {
			return err
		}
		pr.Start = &t
	}
	if truthy(get(p, "end")) {
		t, err := dateOf(get(p, "end"), at)
		if err != nil {
			return err
		}
		pr.End = &t
	}
	if truthy(get(p, "closed")) {
		t, err := dateOf(get(p, "closed"), at)
		if err != nil {
			return err
		}
		pr.ClosedAt = &t
	}
	if pr.State, err = choice(get(p, "state"), projectStates, model.ProjectOpen, at, "state"); err != nil {
		return err
	}
	if pr.OpenScope, err = floatOf(get(p, "open_scope"), at+": open_scope"); err != nil {
		return err
	}
	ms, err := sequence(get(p, "milestones"), at, "milestones")
	if err != nil {
		return err
	}
	for i, item := range ms {
		where := at + ": milestones[" + idx(i) + "]"
		m, ok := asMap(item)
		if !ok || !truthy(get(m, "date")) {
			return dataErr("{where}: field 'date' is missing", "where", where)
		}
		ml := model.Milestone{ID: strOr(get(m, "id"), "m"+idx(i+1)), Name: strOr(get(m, "name"), "")}
		if ml.Date, err = dateOf(get(m, "date"), where); err != nil {
			return err
		}
		if ml.Light, err = choice(get(m, "light"), model.MilestoneLights, "", where, "light"); err != nil {
			return err
		}
		if ml.Tickets, err = texts(get(m, "tickets"), where, "tickets"); err != nil {
			return err
		}
		pr.Milestones = append(pr.Milestones, ml)
	}
	c, err := mapping(get(p, "contingent"), at, "contingent")
	if err != nil {
		return err
	}
	if pr.Contingent.Total, err = floatOf(get(c, "total"), at+": contingent.total"); err != nil {
		return err
	}
	months, err := mapping(get(c, "per_month"), at, "contingent.per_month")
	if err != nil {
		return err
	}
	for _, e := range months.Entries {
		v, err := floatOr0(e.Value, at)
		if err != nil {
			return err
		}
		pr.Contingent.PerMonth.Set(pyStr(e.Key), v)
	}
	if pr.Contingent.Used, err = floatOf(get(c, "used"), at+": contingent.used"); err != nil {
		return err
	}
	usedMonths, err := mapping(get(c, "used_per_month"), at, "contingent.used_per_month")
	if err != nil {
		return err
	}
	for _, e := range usedMonths.Entries {
		v, err := floatOr0(e.Value, at)
		if err != nil {
			return err
		}
		pr.Contingent.UsedPerMonth.Set(pyStr(e.Key), v)
	}
	pr.Contact = text(get(p, "contact"))
	return nil
}

func projectExtrasTo(entry *yamlx.Map, p model.Project) {
	if len(p.AlsoProducts) > 0 {
		put(entry, "products", strs(p.Products()))
		delete1(entry, "product")
	}
	if p.Start != nil {
		put(entry, "start", dateOrNil(p.Start))
	}
	if p.End != nil {
		put(entry, "end", dateOrNil(p.End))
	}
	if p.State != model.ProjectOpen {
		put(entry, "state", string(p.State))
		if p.ClosedAt != nil {
			put(entry, "closed", dateOrNil(p.ClosedAt))
		}
	}
	if p.OpenScope != nil {
		put(entry, "open_scope", clean(*p.OpenScope))
	}
	if len(p.Milestones) > 0 {
		list := make([]any, len(p.Milestones))
		for i, m := range p.Milestones {
			e := omap("id", m.ID, "name", m.Name, "date", yamlx.Date(m.Date))
			if len(m.Tickets) > 0 {
				put(e, "tickets", strs(m.Tickets))
			}
			if m.Light != "" {
				put(e, "light", m.Light)
			}
			list[i] = e
		}
		put(entry, "milestones", list)
	}
	if p.Contact != nil && *p.Contact != "" {
		put(entry, "contact", *p.Contact)
	}
	if p.Contingent.Total != nil || p.Contingent.PerMonth.Len() > 0 || p.Contingent.Used != nil || p.Contingent.UsedPerMonth.Len() > 0 {
		c := &yamlx.Map{}
		if p.Contingent.Total != nil {
			put(c, "total", clean(*p.Contingent.Total))
		}
		if p.Contingent.PerMonth.Len() > 0 {
			months := &yamlx.Map{}
			for _, e := range p.Contingent.PerMonth.Entries {
				put(months, e.Key, clean(e.Value))
			}
			put(c, "per_month", months)
		}
		if p.Contingent.Used != nil {
			put(c, "used", clean(*p.Contingent.Used))
		}
		if p.Contingent.UsedPerMonth.Len() > 0 {
			months := &yamlx.Map{}
			for _, e := range p.Contingent.UsedPerMonth.Entries {
				put(months, e.Key, clean(e.Value))
			}
			put(c, "used_per_month", months)
		}
		put(entry, "contingent", c)
	}
}

// delete1 removes a key from an ordered mapping.
func delete1(m *yamlx.Map, key string) {
	for i, e := range m.Entries {
		if pyStr(e.Key) == key {
			m.Entries = append(m.Entries[:i], m.Entries[i+1:]...)
			return
		}
	}
}

// --- Work package fields --------------------------------------------------------------

func packageFieldsFrom(raw *yamlx.Map, tk *model.Ticket, at string) error {
	tk.Description = text(get(raw, "description"))
	tk.Acceptance = text(get(raw, "acceptance"))
	tk.Assignee = text(get(raw, "assignee"))
	tk.Product = text(get(raw, "product"))
	subs, err := sequence(get(raw, "subtasks"), at, "subtasks")
	if err != nil {
		return err
	}
	for _, item := range subs {
		m, ok := asMap(item)
		if !ok {
			tk.Subtasks = append(tk.Subtasks, model.Subtask{Title: pyStr(item)})
			continue
		}
		tk.Subtasks = append(tk.Subtasks, model.Subtask{Title: strOr(get(m, "title"), ""), Done: truthy(getOr(m, "done", false))})
	}
	cms, err := sequence(get(raw, "comments"), at, "comments")
	if err != nil {
		return err
	}
	for i, item := range cms {
		m, ok := asMap(item)
		if !ok {
			return dataErr("{where}: mapping with author/text expected", "where", at+": comments["+idx(i)+"]")
		}
		c := model.Comment{Author: strOr(get(m, "author"), ""), Text: strOr(get(m, "text"), "")}
		if c.At, err = timestampOf(get(m, "at"), at, "at"); err != nil {
			return err
		}
		tk.Comments = append(tk.Comments, c)
	}
	return nil
}

func packageFieldsTo(entry *yamlx.Map, tk model.Ticket) {
	for _, f := range []struct {
		key string
		val *string
	}{{"description", tk.Description}, {"acceptance", tk.Acceptance}, {"assignee", tk.Assignee}, {"product", tk.Product}} {
		if f.val != nil && *f.val != "" {
			put(entry, f.key, *f.val)
		}
	}
	if len(tk.Subtasks) > 0 {
		list := make([]any, len(tk.Subtasks))
		for i, s := range tk.Subtasks {
			e := omap("title", s.Title)
			if s.Done {
				put(e, "done", true)
			}
			list[i] = e
		}
		put(entry, "subtasks", list)
	}
	if len(tk.Comments) > 0 {
		list := make([]any, len(tk.Comments))
		for i, c := range tk.Comments {
			e := omap("author", c.Author)
			if c.At != nil {
				put(e, "at", c.At.Truncate(time.Second))
			}
			put(e, "text", c.Text)
			list[i] = e
		}
		put(entry, "comments", list)
	}
}

// --- Preplan additions ----------------------------------------------------------------

func preplanExtrasFrom(d *yamlx.Map, pp *model.Preplan, where string) error {
	prod, err := sequence(get(d, "production"), where, "production")
	if err != nil {
		return err
	}
	for i, item := range prod {
		at := where + ": production[" + idx(i) + "]"
		m, ok := asMap(item)
		if !ok || !truthy(get(m, "ticket")) {
			return dataErr("{where}: field 'ticket' is missing", "where", at)
		}
		share, err := floatOf(get(m, "share"), at+": share")
		if err != nil {
			return err
		}
		if share == nil || *share < 0 || *share > 100 {
			return dataErr("{where}: 'share' must be between 0 and 100", "where", at)
		}
		pp.Production = append(pp.Production, model.ProductionShare{Ticket: pyStr(get(m, "ticket")), Percent: *share, Note: text(get(m, "note"))})
	}
	ov, err := sequence(get(d, "overrides"), where, "overrides")
	if err != nil {
		return err
	}
	for i, item := range ov {
		at := where + ": overrides[" + idx(i) + "]"
		m, ok := asMap(item)
		if !ok || !truthy(get(m, "ticket")) {
			return dataErr("{where}: field 'ticket' is missing", "where", at)
		}
		pp.Overrides = append(pp.Overrides, model.TicketOverride{
			Ticket: pyStr(get(m, "ticket")), Product: text(get(m, "product")), Project: text(get(m, "project")),
			Daily: truthy(getOr(m, "daily", false)),
		})
	}
	pf, err := sequence(get(d, "proforma"), where, "proforma")
	if err != nil {
		return err
	}
	for i, item := range pf {
		at := where + ": proforma[" + idx(i) + "]"
		m, ok := asMap(item)
		if !ok || !truthy(get(m, "ticket")) {
			return dataErr("{where}: field 'ticket' is missing", "where", at)
		}
		name := ""
		if n := text(get(m, "name")); n != nil {
			name = *n
		}
		pp.ProForma = append(pp.ProForma, model.ProFormaPlacement{Ticket: pyStr(get(m, "ticket")), Name: name})
	}
	return nil
}

func preplanExtrasTo(out *yamlx.Map, pp model.Preplan) {
	if len(pp.Production) > 0 {
		list := make([]any, len(pp.Production))
		for i, s := range pp.Production {
			e := omap("ticket", s.Ticket, "share", clean(s.Percent))
			if s.Note != nil && *s.Note != "" {
				put(e, "note", *s.Note)
			}
			list[i] = e
		}
		put(out, "production", list)
	}
	if len(pp.Overrides) > 0 {
		list := make([]any, len(pp.Overrides))
		for i, o := range pp.Overrides {
			e := omap("ticket", o.Ticket)
			if o.Product != nil && *o.Product != "" {
				put(e, "product", *o.Product)
			}
			if o.Project != nil && *o.Project != "" {
				put(e, "project", *o.Project)
			}
			if o.Daily {
				put(e, "daily", true)
			}
			list[i] = e
		}
		put(out, "overrides", list)
	}
	if len(pp.ProForma) > 0 {
		list := make([]any, len(pp.ProForma))
		for i, f := range pp.ProForma {
			list[i] = omap("ticket", f.Ticket, "name", f.Name)
		}
		put(out, "proforma", list)
	}
}

// --- Sprint additions -----------------------------------------------------------------

func carryFrom(raw any, where string) ([]model.CarryItem, error) {
	list, err := sequence(raw, where, "carry")
	if err != nil {
		return nil, err
	}
	var out []model.CarryItem
	for i, item := range list {
		at := where + ": carry[" + idx(i) + "]"
		m, ok := asMap(item)
		if !ok {
			return nil, dataErr("{where}: mapping with ticket/rest/target expected", "where", at)
		}
		c := model.CarryItem{Ticket: text(get(m, "ticket"))}
		if c.Rest, err = floatOr0(get(m, "rest"), at); err != nil {
			return nil, err
		}
		if t := text(get(m, "target")); t != nil {
			c.Target = *t
		}
		out = append(out, c)
	}
	return out, nil
}

func carryTo(items []model.CarryItem) []any {
	out := make([]any, len(items))
	for i, c := range items {
		e := &yamlx.Map{}
		if c.Ticket != nil && *c.Ticket != "" {
			put(e, "ticket", *c.Ticket)
		}
		put(e, "rest", clean(c.Rest))
		if c.Target != "" {
			put(e, "target", c.Target)
		}
		out[i] = e
	}
	return out
}

func valuesFrom(raw any, where, name string) (map[string]model.ProductValues, error) {
	out := map[string]model.ProductValues{}
	m, err := mapping(raw, where, name)
	if err != nil {
		return nil, err
	}
	for _, e := range m.Entries {
		id := pyStr(e.Key)
		at := where + ": " + name + "." + id
		values, ok := asMap(e.Value)
		if !ok {
			return nil, dataErr("{where}: mapping with preplanned/planned/done expected", "where", at)
		}
		var pv model.ProductValues
		for _, f := range []struct {
			key string
			dst **float64
		}{{"preplanned", &pv.Preplanned}, {"planned", &pv.Planned}, {"done", &pv.Done},
			{"production_planned", &pv.ProductionPlanned}, {"production_done", &pv.ProductionDone}} {
			if *f.dst, err = floatOf(get(values, f.key), at); err != nil {
				return nil, err
			}
		}
		out[id] = pv
	}
	return out, nil
}

func valuesTo(values map[string]model.ProductValues) *yamlx.Map {
	out := &yamlx.Map{}
	for _, id := range sortedKeys(values) {
		pv := values[id]
		if pv.IsEmpty() {
			continue
		}
		vals := &yamlx.Map{}
		for _, f := range []struct {
			key string
			val *float64
		}{{"preplanned", pv.Preplanned}, {"planned", pv.Planned}, {"done", pv.Done},
			{"production_planned", pv.ProductionPlanned}, {"production_done", pv.ProductionDone}} {
			if f.val != nil {
				put(vals, f.key, clean(*f.val))
			}
		}
		put(out, id, vals)
	}
	return out
}

func sprintExtrasFrom(d *yamlx.Map, s *model.Sprint, where string) error {
	var err error
	s.Name = text(get(d, "name"))
	if s.CommittedTickets, err = texts(get(d, "committed_tickets"), where, "committed_tickets"); err != nil {
		return err
	}
	if s.Carry, err = carryFrom(get(d, "carry"), where); err != nil {
		return err
	}
	if s.RestNext, err = floatOf(get(d, "rest_next"), where+": rest_next"); err != nil {
		return err
	}
	projects, err := valuesFrom(get(d, "projects"), where, "projects")
	if err != nil {
		return err
	}
	if len(projects) > 0 {
		s.Projects = projects
	}
	if s.Preplanned, err = floatOf(get(d, "preplanned"), where+": preplanned"); err != nil {
		return err
	}
	if s.Removed, err = texts(get(d, "removed_tickets"), where, "removed_tickets"); err != nil {
		return err
	}
	matrix, err := mapping(get(d, "matrix"), where, "matrix")
	if err != nil {
		return err
	}
	for _, e := range matrix.Entries {
		product := pyStr(e.Key)
		row, ok := asMap(e.Value)
		if !ok {
			return dataErr("{where}: mapping of project amounts expected", "where", where+": matrix."+product)
		}
		for _, c := range row.Entries {
			v, err := floatOr0(c.Value, where+": matrix."+product)
			if err != nil {
				return err
			}
			if s.Matrix == nil {
				s.Matrix = map[string]map[string]float64{}
			}
			if s.Matrix[product] == nil {
				s.Matrix[product] = map[string]float64{}
			}
			s.Matrix[product][pyStr(c.Key)] = v
		}
	}
	return nil
}

func sprintExtrasTo(d *yamlx.Map, s model.Sprint) {
	if s.Name != nil && *s.Name != "" {
		put(d, "name", *s.Name)
	}
	if vals := valuesTo(s.Projects); len(vals.Entries) > 0 {
		put(d, "projects", vals)
	}
	if s.Preplanned != nil {
		put(d, "preplanned", clean(*s.Preplanned))
	}
	if len(s.Matrix) > 0 {
		matrix := &yamlx.Map{}
		for _, product := range sortedKeys(s.Matrix) {
			row := &yamlx.Map{}
			for _, project := range sortedKeys(s.Matrix[product]) {
				put(row, project, clean(s.Matrix[product][project]))
			}
			if len(row.Entries) > 0 {
				put(matrix, product, row)
			}
		}
		if len(matrix.Entries) > 0 {
			put(d, "matrix", matrix)
		}
	}
	if s.CommittedTickets != nil {
		put(d, "committed_tickets", strs(s.CommittedTickets))
	}
	if len(s.Removed) > 0 {
		put(d, "removed_tickets", strs(s.Removed))
	}
	if len(s.Carry) > 0 {
		put(d, "carry", carryTo(s.Carry))
	}
	if s.RestNext != nil {
		put(d, "rest_next", clean(*s.RestNext))
	}
}

func prognosisExtrasFrom(p *yamlx.Map, pr *model.Prognosis, at string) error {
	var err error
	pr.Label = text(get(p, "label"))
	if pr.Finish, err = texts(get(p, "finish"), at, "finish"); err != nil {
		return err
	}
	if pr.Carry, err = carryFrom(get(p, "carry"), at); err != nil {
		return err
	}
	pr.RestNext, err = floatOf(get(p, "rest_next"), at+": rest_next")
	return err
}

func prognosisExtrasTo(entry *yamlx.Map, p model.Prognosis) {
	if p.Label != nil && *p.Label != "" {
		put(entry, "label", *p.Label)
	}
	if len(p.Finish) > 0 {
		put(entry, "finish", strs(p.Finish))
	}
	if len(p.Carry) > 0 {
		put(entry, "carry", carryTo(p.Carry))
	}
	if p.RestNext != nil {
		put(entry, "rest_next", clean(*p.RestNext))
	}
}

func productOwnersFrom(raw any, where string) ([]model.ProductOwner, error) {
	list, err := sequence(raw, where, "product_owners")
	if err != nil {
		return nil, err
	}
	var out []model.ProductOwner
	seen := map[string]bool{}
	for i, item := range list {
		at := where + ": product_owners[" + idx(i) + "]"
		m, ok := asMap(item)
		if !ok || !truthy(get(m, "id")) || !truthy(get(m, "name")) {
			return nil, dataErr("{where}: fields 'id' and 'name' are required", "where", at)
		}
		po := model.ProductOwner{ID: pyStr(get(m, "id")), Name: pyStr(get(m, "name"))}
		if seen[po.ID] {
			return nil, dataErr("{where}: the id {id} is used twice", "where", at, "id", po.ID)
		}
		seen[po.ID] = true
		if truthy(get(m, "person")) {
			person := pyStr(get(m, "person"))
			po.Person = &person
		}
		out = append(out, po)
	}
	return out, nil
}

func productOwnersTo(pos []model.ProductOwner) []any {
	out := make([]any, len(pos))
	for i, po := range pos {
		entry := omap("id", po.ID, "name", po.Name)
		if po.Person != nil && *po.Person != "" {
			put(entry, "person", *po.Person)
		}
		out[i] = entry
	}
	return out
}
