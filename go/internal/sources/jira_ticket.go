package sources

import (
	"encoding/json"
	"math"
	"math/big"
	"strconv"
)

// FieldTexts returns the texts of a field value for the rule facts: a text, a number, an option
// (value or name), a user (displayName) or a list of these.
func FieldTexts(value any) []string {
	switch v := value.(type) {
	case nil, bool:
		return []string{}
	case string:
		if s := pyStrip(v); s != "" {
			return []string{s}
		}
		return []string{}
	case json.Number:
		return []string{jsonNumberText(v)}
	case map[string]any:
		for _, key := range []string{"value", "name", "displayName"} {
			if s, ok := asString(v[key]); ok && pyStrip(s) != "" {
				return []string{pyStrip(s)}
			}
		}
		return []string{}
	case []any:
		var out []string
		for _, item := range v {
			out = append(out, FieldTexts(item)...)
		}
		return dedupe(append([]string{}, out...))
	}
	return []string{}
}

// jsonNumberText is str(int(v)) for a whole number and str(v) otherwise.
func jsonNumberText(n json.Number) string {
	if isJSONInt(n) {
		return numberString(n)
	}
	f, err := strconv.ParseFloat(string(n), 64)
	if err != nil && !math.IsInf(f, 0) {
		return string(n)
	}
	if f == math.Trunc(f) && !math.IsInf(f, 0) {
		return new(big.Float).SetFloat64(f).Text('f', 0)
	}
	return pyFloatRepr(f)
}

// numberField reads a number field of a ticket: nil for no value, an error for anything that is
// not a non-negative finite number.
func (j *JiraSource) numberField(value any, key, label string) (*float64, error) {
	if value == nil {
		return nil, nil //nolint:nilnil // nil means "no value"
	}
	if s, ok := value.(string); ok && s == "" {
		return nil, nil //nolint:nilnil // nil means "no value"
	}
	if obj, ok := asObject(value); ok { // a select list: {"value": "5"}
		value = obj["value"]
	}
	number, valid := 0.0, false
	switch v := value.(type) {
	case string:
		number, valid = pyFloat(v)
	case json.Number:
		f, err := strconv.ParseFloat(string(v), 64)
		number, valid = f, err == nil && !math.IsInf(f, 0) && !math.IsNaN(f)
	}
	valid = valid && number >= 0
	if !valid {
		name := j.settings.Fields.get(label)
		if name == "" {
			name = label
		}
		return nil, errorf("Ticket {key}: the field “{field}” does not contain a valid "+
			"non-negative number", "key", key, "field", name)
	}
	number += 0.0 // -0 is stored as 0
	return &number, nil
}

func named(value any) string {
	obj, ok := asObject(value)
	if !ok {
		return ""
	}
	name, _ := asString(obj["name"])
	return name
}

// keyOf is the key of an issue reference (an object with "key", or the key itself).
func keyOf(value any) string {
	if obj, ok := asObject(value); ok {
		value = obj["key"]
	}
	key, _ := asString(value)
	return key
}

func (j *JiraSource) ticket(issue any, resolved *ResolvedFields) (RawTicket, error) {
	obj, ok := asObject(issue)
	if !ok {
		return RawTicket{}, j.shapeError()
	}
	key, ok := asString(obj["key"])
	if !ok {
		return RawTicket{}, j.shapeError()
	}
	data, ok := asObject(obj["fields"])
	if !ok {
		return RawTicket{}, j.shapeError()
	}
	field := func(id string) any {
		if id == "" {
			return nil
		}
		return data[id]
	}
	first := func(ids []string) any {
		for _, id := range ids {
			if v, present := data[id]; present && v != nil && v != "" {
				if l, isList := asList(v); isList && len(l) == 0 {
					continue
				}
				return v
			}
		}
		return nil
	}
	ticket := RawTicket{
		Key:       key,
		Status:    named(data["status"]),
		IssueType: named(data["issuetype"]),
		Priority:  named(data["priority"]),
		Extra:     map[string][]string{},
		Resolved:  data["resolution"] != nil || statusDone(data["status"]),
	}
	if pyTruthy(data["summary"]) {
		ticket.Title = collapse(pyStr(data["summary"]))
	}
	for _, e := range resolved.Extra {
		if values := FieldTexts(data[e.ID]); len(values) > 0 {
			ticket.Extra[e.Name] = values
		}
	}
	var err error
	if ticket.Estimate, err = j.numberField(field(resolved.Estimate), key, "estimate"); err != nil {
		return RawTicket{}, err
	}
	if ticket.Remaining, err = j.numberField(field(resolved.Remaining), key, "remaining"); err != nil {
		return RawTicket{}, err
	}
	ticket.SprintName = ChooseSprint(first(resolved.Sprint))
	j.rememberSprints(first(resolved.Sprint))
	if rank, ok := asString(first(resolved.Rank)); ok {
		ticket.Rank = rank
	}
	ticket.Epic = epicOf(data, resolved)
	if labels, ok := asList(data["labels"]); ok {
		for _, l := range labels {
			if s, ok := asString(l); ok {
				ticket.Labels = append(ticket.Labels, s)
			}
		}
		ticket.Labels = dedupe(ticket.Labels)
	}
	if components, ok := asList(data["components"]); ok {
		for _, c := range components {
			if name := named(c); name != "" {
				ticket.Components = append(ticket.Components, name)
			}
		}
		ticket.Components = dedupe(ticket.Components)
	}
	ticket.Subtask, ticket.Parent = subtaskOf(data)
	ticket.BlockedBy = j.blockedBy(data["issuelinks"])
	return ticket, nil
}

// subtaskOf says whether the issue type is a sub-task type, and the key of the parent.
func subtaskOf(data map[string]any) (bool, string) {
	kind, ok := asObject(data["issuetype"])
	if !ok {
		return false, ""
	}
	if sub, _ := kind["subtask"].(bool); !sub {
		return false, ""
	}
	return true, keyOf(data["parent"])
}

func epicOf(data map[string]any, resolved *ResolvedFields) string {
	parent := data["parent"]
	if resolved.Epic == parentField {
		return keyOf(parent) // configured: the parent is the epic
	}
	ids := append([]string{resolved.Epic}, resolved.EpicLink...)
	for _, id := range ids {
		if id == "" {
			continue
		}
		if found := keyOf(data[id]); found != "" {
			return found
		}
	}
	if p, ok := asObject(parent); ok {
		fields, _ := asObject(p["fields"])
		if name := named(fields["issuetype"]); name != "" {
			folded := casefold(pyStrip(name))
			for _, epic := range epicTypeNames {
				if folded == epic {
					return keyOf(p)
				}
			}
		}
	}
	return ""
}

// blockedBy returns the keys on the inward side of the configured link type ("is blocked by").
func (j *JiraSource) blockedBy(links any) []string {
	wanted := casefold(pyStrip(j.settings.LinkType))
	var keys []string
	list, _ := asList(links)
	for _, l := range list {
		link, ok := asObject(l)
		if !ok {
			continue
		}
		name, isStr := asString(mapGet(link["type"], "name"))
		inward, isObj := asObject(link["inwardIssue"])
		if !isStr || !isObj {
			continue
		}
		key, isKey := asString(inward["key"])
		if isKey && casefold(pyStrip(name)) == wanted {
			keys = append(keys, key)
		}
	}
	return dedupe(keys)
}

func mapGet(value any, key string) any {
	obj, ok := asObject(value)
	if !ok {
		return nil
	}
	return obj[key]
}

// statusDone reports whether the status belongs to Jira's status category "done", whatever the
// status is called ("Closed", "Fertig", ...): workflows do not always set a resolution.
func statusDone(status any) bool {
	obj, ok := asObject(status)
	if !ok {
		return false
	}
	category, ok := asObject(obj["statusCategory"])
	if !ok {
		return false
	}
	key, _ := asString(category["key"])
	return key == "done"
}
