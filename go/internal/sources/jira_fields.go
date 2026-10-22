package sources

import (
	"sort"
	"strings"
)

// resolvedFields are the field ids of the instance. Estimate, Remaining and Epic come from the
// display names in the settings; sprint, rank and epic link from the schema of the field.
type resolvedFields struct {
	Estimate  string
	Remaining string
	// Epic is a customfield id, or "parent" when the configured epic field is the parent link.
	Epic     string
	EpicLink []string
	Sprint   []string
	Rank     []string
	// Extra holds the field ids of the rule fields, in the order of the settings.
	Extra []extraField
}

type extraField struct{ Name, ID string }

// ResolvedFields is the result of ResolveFields, for the setup page and the tests.
type ResolvedFields = resolvedFields

// requested is the fields= list of a search: only what is needed.
func (r *resolvedFields) requested() []string {
	wanted := append([]string{}, baseFields...)
	for _, name := range []string{r.Estimate, r.Remaining, r.Epic} {
		if name != "" {
			wanted = append(wanted, name)
		}
	}
	wanted = append(wanted, r.EpicLink...)
	wanted = append(wanted, r.Sprint...)
	wanted = append(wanted, r.Rank...)
	for _, e := range r.Extra {
		wanted = append(wanted, e.ID)
	}
	return dedupe(wanted)
}

// fieldString is str(f.get(key, "")) of a field description.
func fieldString(f map[string]any, key string) string {
	v, present := f[key]
	if !present {
		return ""
	}
	return pyStr(v)
}

// resolveName returns the field id of the field with this display name (or this id). It fails
// for an unknown or an ambiguous name; the ids of the candidates are in the message.
func resolveName(name string, fields []map[string]any, setting, host, section string) (string, error) {
	trimmed := pyStrip(name)
	var found []map[string]any
	for _, f := range fields {
		if pyStrip(fieldString(f, "name")) == trimmed {
			found = append(found, f)
		}
	}
	if len(found) == 0 {
		wanted := casefold(trimmed)
		for _, f := range fields {
			if casefold(pyStrip(fieldString(f, "name"))) == wanted {
				found = append(found, f)
			}
		}
	}
	if len(found) == 0 {
		for _, f := range fields {
			if fieldString(f, "id") == trimmed {
				return pyStr(f["id"]), nil
			}
		}
	}
	if len(found) == 1 {
		return pyStr(found[0]["id"]), nil
	}
	if len(found) > 1 {
		ids := make([]string, len(found))
		for i, f := range found {
			ids[i] = pyStr(f["id"])
		}
		sort.Strings(ids)
		return "", errorf("The field “{name}” (tracker.{section}.{setting}) is ambiguous in {host}: "+
			"{ids}. Please enter the field ID instead of the name in team.yaml.",
			"name", name, "section", section, "setting", setting, "host", host,
			"ids", strings.Join(ids, ", "))
	}
	var names []string
	for _, f := range fields {
		if pyTruthy(f["name"]) {
			names = append(names, fieldString(f, "name"))
		}
	}
	hint := ""
	if close := closeMatches(name, names, 3, 0.6); len(close) > 0 {
		hint = " " + T("Similar names: {names}", "names", strings.Join(close, ", "))
	}
	return "", errorf("The field “{name}” (tracker.{section}.{setting}) does not exist in {host}.{hint}",
		"name", name, "section", section, "setting", setting, "host", host, "hint", hint)
}

// idsBySchema returns the ids of the fields with this custom schema, sorted.
func idsBySchema(fields []map[string]any, schema string) []string {
	found := []string{}
	for _, f := range fields {
		info, ok := asObject(f["schema"])
		if !ok {
			continue
		}
		if custom, _ := asString(info["custom"]); custom == schema && pyTruthy(f["id"]) {
			found = append(found, pyStr(f["id"]))
		}
	}
	sort.Strings(found)
	return found
}

// ResolveFields resolves the display names of the settings and finds the sprint, rank and epic
// link fields by their schema (GET /rest/api/2/field). The answer is kept for later calls.
func (j *JiraSource) ResolveFields() (*ResolvedFields, error) {
	if j.fields != nil {
		return j.fields, nil
	}
	fields, err := j.ListFields()
	if err != nil {
		return nil, err
	}
	resolved := &ResolvedFields{
		Sprint:   idsBySchema(fields, sprintSchema),
		Rank:     idsBySchema(fields, rankSchema),
		EpicLink: idsBySchema(fields, epicLinkSchema),
	}
	for _, setting := range []string{"estimate", "remaining", "epic"} {
		name := j.settings.Fields.get(setting)
		if name == "" {
			continue
		}
		id, err := resolveName(name, fields, setting, j.host, "fields")
		if err != nil {
			return nil, err
		}
		switch setting {
		case "estimate":
			resolved.Estimate = id
		case "remaining":
			resolved.Remaining = id
		default:
			resolved.Epic = id
		}
	}
	for _, rf := range j.settings.RuleFields {
		id, err := resolveName(rf.Display, fields, rf.Name, j.host, "rule_fields")
		if err != nil {
			return nil, err
		}
		resolved.Extra = append(resolved.Extra, extraField{rf.Name, id})
	}
	j.fields = resolved
	return resolved, nil
}

// FieldCandidate is a field of the instance that could serve as one of the tracker fields.
type FieldCandidate struct {
	ID   string
	Name string
	// Value is the text for team.yaml: the display name, or the id when another field has that name.
	Value string
	// Score is a hint from the name (higher = more likely); 0 = no hint, only the type fits.
	Score int
}

// FieldSuggestions are the candidates per setting, best first (the first is only a suggestion
// when its score is above 0).
type FieldSuggestions struct {
	Estimate  []FieldCandidate
	Remaining []FieldCandidate
	Epic      []FieldCandidate
}

// Fragments of (localized) field names that point at the kind of number a field holds.
var (
	pointHints     = []string{"story point", "storypoint", "story-punkt", "storypunkt", "punkte", "points"}
	estimateHints  = []string{"original", "initial", "ursprüng", "estimate", "schätz", "refine"}
	remainingHints = []string{"remaining", "rest", "verbleib"}
)

func containsAny(text string, hints []string) bool {
	for _, h := range hints {
		if strings.Contains(text, h) {
			return true
		}
	}
	return false
}

func scoreName(name string, hints []string) int {
	lowered := casefold(name)
	score := 0
	if containsAny(lowered, pointHints) {
		score++
	}
	if containsAny(lowered, hints) {
		score += 2
	}
	return score
}

// SuggestFields proposes candidates for the tracker fields from the answer of /rest/api/2/field:
// number fields for the estimate and the remaining work (ordered by hints in the name), the epic
// link fields and the parent link for the epic.
func SuggestFields(fields []map[string]any) FieldSuggestions {
	names := make([]string, len(fields))
	for i, f := range fields {
		names[i] = pyStrip(fieldString(f, "name"))
	}
	count := func(name string) int {
		n := 0
		for _, x := range names {
			if x == name {
				n++
			}
		}
		return n
	}
	candidate := func(f map[string]any, hints []string) (FieldCandidate, bool) {
		id, name := "", ""
		if pyTruthy(f["id"]) {
			id = pyStr(f["id"])
		}
		if pyTruthy(f["name"]) {
			name = pyStrip(pyStr(f["name"]))
		}
		if id == "" || name == "" {
			return FieldCandidate{}, false
		}
		value := id
		if count(name) == 1 {
			value = name
		}
		return FieldCandidate{ID: id, Name: name, Value: value, Score: scoreName(name, hints)}, true
	}
	ordered := func(found []FieldCandidate) []FieldCandidate {
		sort.SliceStable(found, func(i, j int) bool {
			a, b := found[i], found[j]
			if a.Score != b.Score {
				return a.Score > b.Score
			}
			if x, y := casefold(a.Name), casefold(b.Name); x != y {
				return x < y
			}
			return a.ID < b.ID
		})
		return found
	}
	var numbers, links []map[string]any
	for _, f := range fields {
		info, ok := asObject(f["schema"])
		if !ok {
			continue
		}
		if kind, _ := asString(info["type"]); kind == "number" && pyTruthy(info["custom"]) {
			numbers = append(numbers, f)
		}
		if custom, _ := asString(info["custom"]); custom == epicLinkSchema {
			links = append(links, f)
		}
	}
	collect := func(source []map[string]any, hints []string) []FieldCandidate {
		found := []FieldCandidate{}
		for _, f := range source {
			if c, ok := candidate(f, hints); ok {
				found = append(found, c)
			}
		}
		return ordered(found)
	}
	result := FieldSuggestions{
		Estimate:  collect(numbers, estimateHints),
		Remaining: collect(numbers, remainingHints),
		Epic:      collect(links, nil),
	}
	for _, f := range fields {
		if id, _ := asString(f["id"]); id == parentField {
			result.Epic = append(result.Epic, FieldCandidate{ID: parentField, Name: parentField, Value: parentField})
			break
		}
	}
	return result
}
