package sources

import "strings"

// SprintValue is one entry of the sprint field of a ticket.
type SprintValue struct {
	Name  string
	State string
	ID    string
}

// Keys of "com.atlassian.greenhopper.service.sprint.Sprint@1a2b[id=12,rapidViewId=3,...]". Only
// these are recognised as separators, so that commas and brackets in a name are harmless.
var sprintKeys = []string{
	"id", "rapidViewId", "boardId", "originBoardId", "state", "name", "goal", "startDate",
	"endDate", "completeDate", "activatedDate", "sequence", "autoStartStop",
}

type sprintKeyMatch struct {
	key        string
	start, end int
}

// sprintKeyMatches finds "<key>=" where the key follows "[" or ",".
func sprintKeyMatches(body string) []sprintKeyMatch {
	var found []sprintKeyMatch
	for i := 1; i < len(body); {
		if body[i-1] != '[' && body[i-1] != ',' {
			i++
			continue
		}
		matched := false
		for _, key := range sprintKeys {
			if strings.HasPrefix(body[i:], key+"=") {
				end := i + len(key) + 1
				found = append(found, sprintKeyMatch{key, i, end})
				i = end
				matched = true
				break
			}
		}
		if !matched {
			i++
		}
	}
	return found
}

// ParseSprint reads a sprint entry in the Data Center toString form or as an object; ok is false
// when it is neither or has no name.
func ParseSprint(value any) (SprintValue, bool) {
	if obj, isObj := asObject(value); isObj {
		name, isStr := asString(obj["name"])
		if !isStr || pyStrip(name) == "" {
			return SprintValue{}, false
		}
		state := ""
		if pyTruthy(obj["state"]) {
			state = strings.ToUpper(pyStr(obj["state"]))
		}
		id := ""
		if v, present := obj["id"]; present {
			id = pyStr(v)
		}
		return SprintValue{Name: pyStrip(name), State: state, ID: id}, true
	}
	text, isStr := asString(value)
	if !isStr {
		return SprintValue{}, false
	}
	start := strings.IndexByte(text, '[')
	if start < 0 || !strings.HasSuffix(pyRStrip(text), "]") {
		return SprintValue{}, false
	}
	trimmed := pyRStrip(text)
	body := text[start:strings.LastIndexByte(trimmed, ']')] // starts with "[", no closing bracket
	matches := sprintKeyMatches(body)
	parts := map[string]string{}
	for i, m := range matches {
		end := len(body)
		if i+1 < len(matches) {
			end = matches[i+1].start - 1
		}
		if _, seen := parts[m.key]; !seen {
			if m.end <= end {
				parts[m.key] = body[m.end:end]
			} else {
				parts[m.key] = ""
			}
		}
	}
	name := pyStrip(parts["name"])
	if name == "" || name == "<null>" {
		return SprintValue{}, false
	}
	return SprintValue{
		Name:  name,
		State: strings.ToUpper(pyStrip(parts["state"])),
		ID:    pyStrip(parts["id"]),
	}, true
}

// ChooseSprint picks the sprint to use for a ticket: the ACTIVE one, else the first FUTURE, else
// the last listed (Jira lists the sprints of a ticket chronologically). It returns "" when there
// is none.
func ChooseSprint(values any) string {
	var list []any
	switch v := values.(type) {
	case string, map[string]any:
		list = []any{v}
	case []any:
		list = v
	default:
		return ""
	}
	var sprints []SprintValue
	for _, v := range list {
		if s, ok := ParseSprint(v); ok {
			sprints = append(sprints, s)
		}
	}
	if len(sprints) == 0 {
		return ""
	}
	for _, state := range []string{"ACTIVE", "FUTURE"} {
		for _, s := range sprints {
			if s.State == state {
				return s.Name
			}
		}
	}
	return sprints[len(sprints)-1].Name
}
