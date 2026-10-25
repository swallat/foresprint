package sources

import (
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
)

// Moving tickets between sprints is the one write besides labels (decision 10 of the design,
// "Write sprint back to the tracker"). It is off until EnableSprintWrite is called, which the
// program does only for a team that switched write-back on and only on the explicit action of
// the user. Only two requests are allowed, both of the Agile API: add issues to a sprint and
// move issues to the backlog. Foresprint never creates, starts or closes a sprint, and never
// touches order, estimate, status or texts.
var (
	sprintIssuePath  = regexp.MustCompile(`^/rest/agile/1\.0/sprint/[0-9]+/issue$`)
	backlogIssuePath = "/rest/agile/1.0/backlog/issue"
	issueKeyPattern  = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]*-[0-9]+$`)
)

// MaxMoveBatch is how many issues one request moves (the limit of the Jira API).
const MaxMoveBatch = 50

// isSprintWrite says whether a POST is exactly "move these issues to a sprint or the backlog":
// the body has the single key "issues", a non-empty list of issue keys.
func isSprintWrite(path string, body any) bool {
	obj, ok := asObject(body)
	if !ok || len(obj) != 1 || (!sprintIssuePath.MatchString(path) && path != backlogIssuePath) {
		return false
	}
	list, ok := asList(obj["issues"])
	if !ok || len(list) == 0 || len(list) > MaxMoveBatch {
		return false
	}
	for _, v := range list {
		key, isStr := asString(v)
		if !isStr || !issueKeyPattern.MatchString(key) {
			return false
		}
	}
	return true
}

// EnableSprintWrite allows MoveToSprint and MoveToBacklog on this source.
func (j *JiraSource) EnableSprintWrite() { j.sprintWrite = true }

// rememberSprints keeps the sprints of a ticket's sprint field so that the Jira id of a sprint
// is known for the write-back.
func (j *JiraSource) rememberSprints(values any) {
	var list []any
	switch v := values.(type) {
	case string, map[string]any:
		list = []any{v}
	case []any:
		list = v
	}
	for _, v := range list {
		s, ok := ParseSprint(v)
		if !ok || s.ID == "" {
			continue
		}
		if j.seen == nil {
			j.seen = map[string]SprintValue{}
		}
		j.seen[s.ID] = s
	}
}

// KnownSprints are the sprints met while fetching, ordered by Jira id.
func (j *JiraSource) KnownSprints() []SprintValue {
	out := make([]SprintValue, 0, len(j.seen))
	for _, s := range j.seen {
		out = append(out, s)
	}
	sortSprints(out)
	return out
}

func sortSprints(list []SprintValue) {
	less := func(a, b SprintValue) bool {
		ai, aerr := strconv.Atoi(a.ID)
		bi, berr := strconv.Atoi(b.ID)
		if aerr == nil && berr == nil && ai != bi {
			return ai < bi
		}
		return a.ID < b.ID
	}
	for i := 1; i < len(list); i++ {
		for k := i; k > 0 && less(list[k], list[k-1]); k-- {
			list[k], list[k-1] = list[k-1], list[k]
		}
	}
}

// MoveToSprint puts the issues into the Jira sprint with this id (open or future sprints only;
// Jira refuses closed ones).
func (j *JiraSource) MoveToSprint(sprintID int, keys []string) error {
	return j.moveIssues(fmt.Sprintf("/rest/agile/1.0/sprint/%d/issue", sprintID), keys)
}

// MoveToBacklog takes the issues out of their sprint.
func (j *JiraSource) MoveToBacklog(keys []string) error {
	return j.moveIssues(backlogIssuePath, keys)
}

func (j *JiraSource) moveIssues(path string, keys []string) error {
	if !j.sprintWrite {
		return errorf("Writing sprints back to the tracker is not switched on.")
	}
	for start := 0; start < len(keys); start += MaxMoveBatch {
		end := min(start+MaxMoveBatch, len(keys))
		issues := make([]any, 0, end-start)
		for _, k := range keys[start:end] {
			issues = append(issues, k)
		}
		if _, err := j.request(http.MethodPost, path, nil, map[string]any{"issues": issues}); err != nil {
			return err
		}
	}
	return nil
}

// ListBoardSprints reads the open and future sprints of a board (GET only), so that a sprint
// without any ticket yet can be the target of a write-back.
func (j *JiraSource) ListBoardSprints(boardID int) ([]SprintValue, error) {
	var out []SprintValue
	for start := 0; ; {
		params := url.Values{"state": {"active,future"}, "startAt": {strconv.Itoa(start)}, "maxResults": {"50"}}
		answer, err := j.request(http.MethodGet, fmt.Sprintf("/rest/agile/1.0/board/%d/sprint", boardID), params, nil)
		if err != nil {
			return nil, err
		}
		page, ok := asObject(answer)
		if !ok {
			return nil, j.shapeError()
		}
		values, _ := asList(page["values"])
		for _, v := range values {
			if s, ok := ParseSprint(v); ok && s.ID != "" {
				out = append(out, s)
			}
		}
		if last, _ := page["isLast"].(bool); last || len(values) == 0 {
			sortSprints(out)
			return out, nil
		}
		start += len(values)
	}
}
