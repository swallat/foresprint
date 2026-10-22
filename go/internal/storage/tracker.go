package storage

import (
	"strings"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/yamlx"
)

// Parts of a key name that mark a secret; such a key in the tracker section is an error ...
var secretWords = []string{"token", "password", "passwort", "secret", "credential"}

// ... and so are these names when they are the whole key (a part of a longer name is no hint).
var secretNames = []string{"key", "api_key", "apikey", "pat", "auth", "authorization", "bearer"}

// Sections whose keys are free text of the user (sprint names), not setting names.
var freeKeys = []string{"sprint_names"}

func inList(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// SecretKey returns the first key anywhere in the (nested) tracker section whose name marks a
// secret, else "" and false. Only names are looked at, values are never read.
func SecretKey(section any) (string, bool) {
	switch s := section.(type) {
	case []any:
		for _, item := range s {
			if k, ok := SecretKey(item); ok {
				return k, true
			}
		}
	case *yamlx.Map:
		for _, e := range s.Entries {
			name := pyStr(e.Key)
			plain := strings.ReplaceAll(casefold(strings.TrimSpace(name)), "-", "_")
			if inList(secretNames, plain) {
				return name, true
			}
			for _, w := range secretWords {
				if strings.Contains(plain, w) {
					return name, true
				}
			}
			if !inList(freeKeys, plain) {
				if k, ok := SecretKey(e.Value); ok {
					return k, true
				}
			}
		}
	}
	return "", false
}

func orderedTexts(v any, where, name string) (model.OrderedMap[string], error) {
	var out model.OrderedMap[string]
	m, err := mapping(v, where, name)
	if err != nil {
		return out, err
	}
	for _, e := range m.Entries {
		k, err := textValue(e.Key, where, name)
		if err != nil {
			return out, err
		}
		val, err := textValue(e.Value, where, name)
		if err != nil {
			return out, err
		}
		out.Set(k, val)
	}
	return out, nil
}

func trackerFrom(d *yamlx.Map, where string) (model.TrackerSettings, error) {
	at := where + ": tracker"
	// The value is never read, let alone shown: it would end up in the data repository.
	if name, ok := SecretKey(d); ok {
		return model.TrackerSettings{}, dataErr("{where}: '{name}' does not belong in the file – tokens and passwords belong in the environment variable FORESPRINT_JIRA_TOKEN or in the keychain",
			"where", at, "name", name)
	}
	tr := model.NewTrackerSettings()
	fields, err := mapping(get(d, "fields"), at, "fields")
	if err != nil {
		return tr, err
	}
	order, err := texts(get(d, "project_match_order"), at, "project_match_order")
	if err != nil {
		return tr, err
	}
	rough, err := floatOf(get(d, "rough_factor"), at+": rough_factor")
	if err != nil {
		return tr, err
	}
	tr.Kind = strOr(get(d, "kind"), "csv")
	tr.BaseURL = text(get(d, "base_url"))
	tr.Query = text(get(d, "query"))
	tr.Fields = trackerFieldsFrom(fields)
	if tr.PlanningUses, err = choice(get(d, "planning_uses"), planningUses, model.UsesRemaining, at, "planning_uses"); err != nil {
		return tr, err
	}
	tr.RefinedLabel = text(get(d, "refined_label"))
	if tr.RefinedAlsoIf, err = ruleFrom(get(d, "refined_also_if"), at+".refined_also_if"); err != nil {
		return tr, err
	}
	if len(order) > 0 {
		tr.ProjectMatchOrder = order
	}
	if has(d, "priority_order") {
		if tr.PriorityOrder, err = texts(get(d, "priority_order"), at, "priority_order"); err != nil {
			return tr, err
		}
	}
	if tr.DependencyGap, err = intOf(get(d, "dependency_gap"), at, "dependency_gap", 1); err != nil {
		return tr, err
	}
	if tr.BudgetBasis, err = choice(get(d, "budget_basis"), budgetBases, model.BudgetRoadmapShare, at, "budget_basis"); err != nil {
		return tr, err
	}
	if rough != nil {
		tr.RoughFactor = *rough
	}
	tr.WriteLabels = truthy(getOr(d, "write_labels", false))
	if tr.SprintNames, err = orderedTexts(get(d, "sprint_names"), at, "sprint_names"); err != nil {
		return tr, err
	}
	// Absent = default; an explicitly empty value stays empty so that the check reports it.
	if has(d, "link_type") {
		tr.LinkType = ""
		if t := text(get(d, "link_type")); t != nil {
			tr.LinkType = *t
		}
	}
	if tr.RuleFields, err = orderedTexts(get(d, "rule_fields"), at, "rule_fields"); err != nil {
		return tr, err
	}
	if err = trackerExtrasFrom(d, &tr, at); err != nil {
		return tr, err
	}
	return tr, nil
}

// TrackerFromRaw reads a raw tracker section (as kept in Team.TrackerRaw); an unusable one is an
// error.
func TrackerFromRaw(raw any, where string) (model.TrackerSettings, error) {
	m, err := mapping(raw, where, "tracker")
	if err != nil {
		return model.TrackerSettings{}, err
	}
	return trackerFrom(m, where)
}

func orderedStrings(m model.OrderedMap[string]) *yamlx.Map {
	out := &yamlx.Map{}
	for _, e := range m.Entries {
		put(out, e.Key, e.Value)
	}
	return out
}

func trackerTo(tr model.TrackerSettings) *yamlx.Map {
	out := omap("kind", tr.Kind)
	if tr.BaseURL != nil && *tr.BaseURL != "" {
		put(out, "base_url", *tr.BaseURL)
	}
	if tr.Query != nil && *tr.Query != "" {
		put(out, "query", *tr.Query)
	}
	fields := &yamlx.Map{}
	for _, f := range trackerFieldNames(tr.Fields) {
		if f.value != nil && *f.value != "" {
			put(fields, f.name, *f.value)
		}
	}
	if len(fields.Entries) > 0 {
		put(out, "fields", fields)
	}
	put(out, "planning_uses", string(tr.PlanningUses))
	if tr.RefinedLabel != nil && *tr.RefinedLabel != "" {
		put(out, "refined_label", *tr.RefinedLabel)
	}
	if tr.RefinedAlsoIf != nil {
		put(out, "refined_also_if", ruleTo(tr.RefinedAlsoIf))
	}
	put(out, "project_match_order", strs(tr.ProjectMatchOrder))
	if !sameList(tr.PriorityOrder, model.DefaultPriorityOrder) {
		put(out, "priority_order", strs(tr.PriorityOrder))
	}
	put(out, "dependency_gap", int64(tr.DependencyGap))
	put(out, "budget_basis", string(tr.BudgetBasis))
	put(out, "rough_factor", clean(tr.RoughFactor))
	put(out, "write_labels", tr.WriteLabels)
	if tr.SprintNames.Len() > 0 {
		put(out, "sprint_names", orderedStrings(tr.SprintNames))
	}
	if tr.LinkType != "Blocks" {
		put(out, "link_type", tr.LinkType)
	}
	if tr.RuleFields.Len() > 0 {
		put(out, "rule_fields", orderedStrings(tr.RuleFields))
	}
	trackerExtrasTo(out, tr)
	return out
}

func sameList(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// casefold is str.casefold().
func casefold(s string) string { return pytext.Casefold(s) }
