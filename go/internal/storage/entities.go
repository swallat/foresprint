package storage

import (
	"sort"
	"strconv"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/yamlx"
)

// Headers of the files.
const (
	PeopleHeader = "# People. Memberships with period and FTE share (1.0 = full time in the team).\n" +
		"# Never delete people; end the membership with `to:` instead – otherwise history changes.\n"
	ProductsHeader = "# Products of the team. Period (from/to) = when the team works on the product; po optional.\n" +
		"# Never delete products; end them with `to:` instead – otherwise past evaluations change.\n" +
		"# match (optional): rule for tickets of the product without a project (same language as the\n" +
		"# projects' match).\n"
	SprintHeader   = "# Sprint {id}. Explanations of all fields: `foresprint help fields`\n"
	ProjectsHeader = "# Projects of the ticket pre-planning: target date, product, priority and assignment rule.\n" +
		"# A ticket belongs to the project whose `match` rule it fulfils (docs/design/ticket-planning.md).\n"
	TicketsHeader = "# Tickets as last imported from the tracker. Written by the import – do not edit by hand.\n"
	PreplanHeader = "# Pre-planning of the PO: earmarks (ticket → future sprint) and own estimates for tickets.\n"
)

// Schema is the version of the three ticket files. Missing = 1; a greater version was written by
// a newer program version and is refused instead of being read half.
const Schema = 1

func idx(i int) string { return strconv.Itoa(i) }

// objectAt is `isinstance(p, dict)` with a message for the entry.
func asMap(v any) (*yamlx.Map, bool) {
	m, ok := v.(*yamlx.Map)
	return m, ok
}

// --- People ----------------------------------------------------------------------------

// PeopleFromDict is people_from_dict.
func PeopleFromDict(d *yamlx.Map, where string) ([]model.Person, error) {
	list, err := sequence(get(d, "people"), where, "people")
	if err != nil {
		return nil, err
	}
	var people []model.Person
	for i, raw := range list {
		at := where + ": people[" + idx(i) + "]"
		p, ok := asMap(raw)
		if !ok || !has(p, "id") {
			return nil, dataErr("{where}: field 'id' missing", "where", at)
		}
		mlist, err := sequence(get(p, "memberships"), at, "memberships")
		if err != nil {
			return nil, err
		}
		var memberships []model.Membership
		for j, mraw := range mlist {
			m, err := mapping(mraw, at, "memberships["+idx(j)+"]")
			if err != nil {
				return nil, err
			}
			start, err := dateOf(get(m, "from"), at)
			if err != nil {
				return nil, err
			}
			ms := model.Membership{Start: start}
			if truthy(get(m, "to")) {
				end, err := dateOf(get(m, "to"), at)
				if err != nil {
					return nil, err
				}
				ms.End = &end
			}
			fte, err := floatOr0(getOr(m, "fte", 1.0), at)
			if err != nil {
				return nil, err
			}
			ms.FTE = fte
			memberships = append(memberships, ms)
		}
		person := model.Person{ID: pyStr(get(p, "id"))}
		person.Name = strOr(get(p, "name"), person.ID)
		if person.Region, err = code(get(p, "region"), at, "region"); err != nil {
			return nil, err
		}
		country, err := code(get(p, "country"), at, "country")
		if err != nil {
			return nil, err
		}
		if country != nil && *country != "" {
			up := upper(*country)
			person.Country = &up
		}
		if truthy(get(p, "workweek")) {
			w := pyStr(get(p, "workweek"))
			person.Workweek = &w
		}
		person.Memberships = memberships
		person.ProductionAccess = truthy(getOr(p, "production_access", false))
		people = append(people, person)
	}
	return people, nil
}

// PeopleToDict is people_to_dict.
func PeopleToDict(people []model.Person) *yamlx.Map {
	out := make([]any, 0, len(people))
	for _, p := range people {
		entry := omap("id", p.ID, "name", p.Name)
		if p.Country != nil && *p.Country != "" {
			put(entry, "country", *p.Country)
		}
		if p.Workweek != nil && *p.Workweek != "" {
			put(entry, "workweek", *p.Workweek)
		}
		if p.Region != nil && *p.Region != "" {
			put(entry, "region", *p.Region)
		}
		if p.ProductionAccess {
			put(entry, "production_access", true)
		}
		ms := make([]any, len(p.Memberships))
		for i, m := range p.Memberships {
			ms[i] = omap("from", yamlx.Date(m.Start), "to", dateOrNil(m.End), "fte", clean(m.FTE))
		}
		put(entry, "memberships", ms)
		out = append(out, entry)
	}
	return omap("people", out)
}

func dateOrNil(d *time.Time) any {
	if d == nil {
		return nil
	}
	return yamlx.Date(*d)
}

// --- Products --------------------------------------------------------------------------

// ProductsFromDict is products_from_dict.
func ProductsFromDict(d *yamlx.Map, where string) ([]model.Product, error) {
	list, err := sequence(get(d, "products"), where, "products")
	if err != nil {
		return nil, err
	}
	var products []model.Product
	for i, raw := range list {
		at := where + ": products[" + idx(i) + "]"
		p, ok := asMap(raw)
		if !ok || !has(p, "id") {
			return nil, dataErr("{where}: field 'id' missing", "where", at)
		}
		prod := model.Product{ID: pyStr(get(p, "id"))}
		prod.Name = strOr(get(p, "name"), prod.ID)
		if truthy(get(p, "po")) {
			po := pyStr(get(p, "po"))
			prod.PO = &po
		}
		if truthy(get(p, "from")) {
			start, err := dateOf(get(p, "from"), at)
			if err != nil {
				return nil, err
			}
			prod.Start = &start
		}
		if truthy(get(p, "to")) {
			end, err := dateOf(get(p, "to"), at)
			if err != nil {
				return nil, err
			}
			prod.End = &end
		}
		if prod.Share, err = lenientFloat(get(p, "share"), at+": share"); err != nil {
			return nil, err
		}
		if prod.Match, err = ruleFrom(get(p, "match"), at+": match"); err != nil {
			return nil, err
		}
		products = append(products, prod)
	}
	return products, nil
}

// ProductsToDict is products_to_dict.
func ProductsToDict(products []model.Product) *yamlx.Map {
	out := make([]any, 0, len(products))
	for _, p := range products {
		entry := omap("id", p.ID, "name", p.Name)
		if p.PO != nil && *p.PO != "" {
			put(entry, "po", *p.PO)
		}
		if p.Share != nil {
			put(entry, "share", clean(*p.Share))
		}
		if p.Match != nil {
			put(entry, "match", ruleTo(p.Match))
		}
		put(entry, "from", dateOrNil(p.Start))
		put(entry, "to", dateOrNil(p.End))
		out = append(out, entry)
	}
	return omap("products", out)
}

// --- Sprints ---------------------------------------------------------------------------

func timestampOf(v any, where, name string) (*time.Time, error) {
	if isEmptyText(v) {
		return nil, nil
	}
	switch x := v.(type) {
	case time.Time:
		return &x, nil
	case yamlx.Date:
		t := time.Time(x)
		return &t, nil
	}
	if t, ok := parseISOTimestamp(pyStr(v)); ok {
		return &t, nil
	}
	return nil, dataErr("{where}: invalid time '{value}'", "where", where+": "+name, "value", pyStr(v))
}

func prognosesFrom(raw any, where string) ([]model.Prognosis, error) {
	list, err := sequence(raw, where, "prognoses")
	if err != nil {
		return nil, err
	}
	var result []model.Prognosis
	for i, item := range list {
		at := where + ": prognoses[" + idx(i) + "]"
		p, ok := asMap(item)
		if !ok || get(p, "at") == nil {
			return nil, dataErr("{where}: field 'at' missing", "where", at)
		}
		stamp := get(p, "at")
		var when time.Time
		switch x := stamp.(type) {
		case time.Time:
			when = x
		default:
			t, ok := parseISOTimestamp(pyStr(stamp))
			if !ok {
				return nil, dataErr("{where}: invalid time '{value}'", "where", at, "value", pyStr(stamp))
			}
			when = t
		}
		pr := model.Prognosis{At: when}
		if truthy(get(p, "comment")) {
			c := pyStr(get(p, "comment"))
			pr.Comment = &c
		}
		for _, f := range []struct {
			key string
			dst **float64
		}{{"forecast_ist", &pr.Commitment}, {"not_done", &pr.NotDone}, {"additional_done", &pr.AdditionalDone},
			{"expected_done", &pr.ExpectedDone}} {
			if *f.dst, err = floatOf(get(p, f.key), at); err != nil {
				return nil, err
			}
		}
		if get(p, "target") != nil {
			t := pyStr(get(p, "target"))
			pr.Target = &t
		}
		if pr.Plan, err = floatOf(get(p, "plan"), at); err != nil {
			return nil, err
		}
		pre, err := mapping(get(p, "preplanned"), at, "preplanned")
		if err != nil {
			return nil, err
		}
		for _, e := range pre.Entries {
			v, err := floatOr0(e.Value, at)
			if err != nil {
				return nil, err
			}
			pr.Preplanned.Set(pyStr(e.Key), v)
		}
		result = append(result, pr)
	}
	return result, nil
}

func prognosesTo(prognoses []model.Prognosis) []any {
	out := make([]any, 0, len(prognoses))
	for _, p := range prognoses {
		entry := omap("at", p.At.Truncate(time.Second))
		if p.Comment != nil && *p.Comment != "" {
			put(entry, "comment", *p.Comment)
		}
		for _, f := range []struct {
			key string
			val *float64
		}{{"forecast_ist", p.Commitment}, {"not_done", p.NotDone}, {"additional_done", p.AdditionalDone},
			{"expected_done", p.ExpectedDone}} {
			if f.val != nil {
				put(entry, f.key, clean(*f.val))
			}
		}
		if p.Target != nil {
			put(entry, "target", *p.Target)
		}
		if p.Plan != nil {
			put(entry, "plan", clean(*p.Plan))
		}
		if p.Preplanned.Len() > 0 {
			pre := &yamlx.Map{}
			for _, e := range p.Preplanned.Entries {
				put(pre, e.Key, clean(e.Value))
			}
			put(entry, "preplanned", pre)
		}
		out = append(out, entry)
	}
	return out
}

// absenceStateOf is _absence_state: the stored state of the absences; older files only know
// absences_confirmed.
func absenceStateOf(d *yamlx.Map, where string) (*model.AbsenceState, error) {
	if raw := get(d, "absence_state"); raw != nil {
		if s, ok := raw.(string); ok {
			for _, a := range absenceStates {
				if string(a) == s {
					return &a, nil
				}
			}
		}
		names := ""
		for i, a := range absenceStates {
			if i > 0 {
				names += ", "
			}
			names += string(a)
		}
		return nil, dataErr("{where}: absence_state '{value}' unknown (allowed: {allowed})",
			"where", where, "value", pyStr(raw), "allowed", names)
	}
	if truthy(get(d, "absences_confirmed")) {
		return model.Ptr(model.AbsencesConfirmed), nil
	}
	return nil, nil
}

// floatMap reads a mapping of person → days.
func floatMap(raw any, where, name string, label func(string) string) (map[string]float64, error) {
	m, err := mapping(raw, where, name)
	if err != nil {
		return nil, err
	}
	out := map[string]float64{}
	for _, e := range m.Entries {
		pid := pyStr(e.Key)
		v, err := floatOr0(e.Value, label(pid))
		if err != nil {
			return nil, err
		}
		out[pid] = v
	}
	return out, nil
}

// SprintFromDict is sprint_from_dict.
func SprintFromDict(d *yamlx.Map, where string) (model.Sprint, error) {
	for _, key := range []string{"id", "start", "end"} {
		if get(d, key) == nil {
			return model.Sprint{}, dataErr("{where}: field '{key}' missing", "where", where, "key", key)
		}
	}
	if _, ok := get(d, "id").(float64); ok {
		return model.Sprint{}, dataErr("{where}: please quote the id, e.g. id: \"2026.20\"", "where", where)
	}
	var planning *model.Planning
	pm, err := mapping(get(d, "planning"), where, "planning")
	if err != nil {
		return model.Sprint{}, err
	}
	if len(pm.Entries) > 0 {
		pl := model.Planning{}
		if pl.Carryover, err = floatOr0(get(pm, "carryover"), where); err != nil {
			return model.Sprint{}, err
		}
		if pl.Backlog, err = floatOr0(get(pm, "backlog"), where); err != nil {
			return model.Sprint{}, err
		}
		corr, err := sequence(get(pm, "corrections"), where, "corrections")
		if err != nil {
			return model.Sprint{}, err
		}
		for _, c := range corr {
			v, err := floatOr0(c, where)
			if err != nil {
				return model.Sprint{}, err
			}
			pl.Corrections = append(pl.Corrections, v)
		}
		planning = &pl
	}
	products := map[string]model.ProductValues{}
	pmap, err := mapping(get(d, "products"), where, "products")
	if err != nil {
		return model.Sprint{}, err
	}
	for _, e := range pmap.Entries {
		pid := pyStr(e.Key)
		at := where + ": products." + pid
		values, ok := asMap(e.Value)
		if !ok {
			return model.Sprint{}, dataErr("{where}: mapping with preplanned/planned/done expected", "where", at)
		}
		var pv model.ProductValues
		for _, f := range []struct {
			key string
			dst **float64
		}{{"preplanned", &pv.Preplanned}, {"planned", &pv.Planned}, {"done", &pv.Done},
			{"production_planned", &pv.ProductionPlanned}, {"production_done", &pv.ProductionDone}} {
			if *f.dst, err = floatOf(get(values, f.key), at); err != nil {
				return model.Sprint{}, err
			}
		}
		products[pid] = pv
	}
	absences, err := floatMap(get(d, "absences"), where, "absences", func(pid string) string { return where + ": absences." + pid })
	if err != nil {
		return model.Sprint{}, err
	}
	s := model.Sprint{ID: pyStr(get(d, "id")), Absences: absences, Planning: planning, Products: products}
	if s.Start, err = dateOf(get(d, "start"), where); err != nil {
		return model.Sprint{}, err
	}
	if s.End, err = dateOf(get(d, "end"), where); err != nil {
		return model.Sprint{}, err
	}
	for _, f := range []struct {
		key string
		dst **float64
	}{{"capacity", &s.Capacity}, {"forecast_ist", &s.Commitment}, {"velocity", &s.Velocity},
		{"scope_creep", &s.ScopeCreep}, {"forecast_plan", &s.ForecastPlan}} {
		if *f.dst, err = floatOf(get(d, f.key), where+": "+f.key); err != nil {
			return model.Sprint{}, err
		}
	}
	if note := get(d, "note"); note != nil {
		if str, ok := note.(string); ok {
			s.Note = &str
		} else {
			str := pyStr(note)
			s.Note = &str
		}
	}
	for _, f := range []struct {
		key string
		dst **float64
	}{{"production_planned", &s.ProductionPlanned}, {"production_done", &s.ProductionDone}} {
		if *f.dst, err = floatOf(get(d, f.key), where+": "+f.key); err != nil {
			return model.Sprint{}, err
		}
	}
	if s.AbsenceState, err = absenceStateOf(d, where); err != nil {
		return model.Sprint{}, err
	}
	if s.ExpectedAbsences, err = floatMap(get(d, "expected_absences"), where, "expected_absences",
		func(pid string) string { return where + ": expected_absences." + pid }); err != nil {
		return model.Sprint{}, err
	}
	for _, f := range []struct {
		key string
		dst **float64
	}{{"not_done", &s.NotDone}, {"additional_done", &s.AdditionalDone}} {
		if *f.dst, err = floatOf(get(d, f.key), where+": "+f.key); err != nil {
			return model.Sprint{}, err
		}
	}
	if s.Prognoses, err = prognosesFrom(get(d, "prognoses"), where); err != nil {
		return model.Sprint{}, err
	}
	return s, nil
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func sortedFloats(m map[string]float64) *yamlx.Map {
	out := &yamlx.Map{}
	for _, k := range sortedKeys(m) {
		put(out, k, clean(m[k]))
	}
	return out
}

// SprintToDict is sprint_to_dict.
func SprintToDict(s model.Sprint) *yamlx.Map {
	d := omap("id", s.ID, "start", yamlx.Date(s.Start), "end", yamlx.Date(s.End), "absences", sortedFloats(s.Absences))
	if s.ExplicitStateNeeded() {
		put(d, "absence_state", string(*s.AbsenceState))
		// Older program versions only know this field.
		if *s.AbsenceState == model.AbsencesConfirmed {
			put(d, "absences_confirmed", true)
		}
	}
	put(d, "capacity", cleanPtr(s.Capacity))
	put(d, "forecast_ist", cleanPtr(s.Commitment))
	put(d, "velocity", cleanPtr(s.Velocity))
	put(d, "scope_creep", cleanPtr(s.ScopeCreep))
	if s.Planning != nil {
		corr := make([]any, len(s.Planning.Corrections))
		for i, c := range s.Planning.Corrections {
			corr[i] = clean(c)
		}
		put(d, "planning", omap("carryover", clean(s.Planning.Carryover), "backlog", clean(s.Planning.Backlog), "corrections", corr))
	}
	if s.ForecastPlan != nil {
		put(d, "forecast_plan", clean(*s.ForecastPlan))
	}
	products := &yamlx.Map{}
	for _, pid := range sortedKeys(s.Products) {
		pv := s.Products[pid]
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
		put(products, pid, vals)
	}
	if len(products.Entries) > 0 {
		put(d, "products", products)
	}
	if len(s.ExpectedAbsences) > 0 {
		put(d, "expected_absences", sortedFloats(s.ExpectedAbsences))
	}
	for _, f := range []struct {
		key string
		val *float64
	}{{"production_planned", s.ProductionPlanned}, {"production_done", s.ProductionDone},
		{"not_done", s.NotDone}, {"additional_done", s.AdditionalDone}} {
		if f.val != nil {
			put(d, f.key, clean(*f.val))
		}
	}
	if len(s.Prognoses) > 0 {
		put(d, "prognoses", prognosesTo(s.Prognoses))
	}
	if s.Note != nil && *s.Note != "" {
		put(d, "note", *s.Note)
	}
	return d
}
