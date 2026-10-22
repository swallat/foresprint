package calendar

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/model"
)

// Chain generates the sprints that follow the recorded ones. Without naming rules in the team
// it behaves exactly like FollowingSprint (the ID counts on from the previous ID). With a naming
// rule (decision 18) the ID is the name from the pattern, and the number in the year and the
// running number come from the order of the sprints, not from the previous ID: the previous ID
// is only read to continue a number (by the pattern, or in the numeric form of the numbering).
type Chain struct {
	team *model.Team
	list []model.Sprint
}

// NewChain starts a chain after the recorded sprints (oldest first).
func NewChain(team *model.Team, saved []model.Sprint) *Chain {
	return &Chain{team: team, list: append([]model.Sprint(nil), saved...)}
}

// Last is the latest sprint of the chain (nil if there is none).
func (c *Chain) Last() *model.Sprint {
	if len(c.list) == 0 {
		return nil
	}
	return &c.list[len(c.list)-1]
}

// Next creates the sprint after the last one of the chain and appends it.
func (c *Chain) Next() (model.Sprint, error) {
	return c.After(c.Last())
}

// After creates the sprint that follows previous (nil: the first sprint of the team). When
// previous is the last sprint of the chain, the new sprint is appended to it.
func (c *Chain) After(previous *model.Sprint) (model.Sprint, error) {
	prefix := c.list
	if previous != nil {
		prefix = nil
		for i := range c.list {
			if c.list[i].ID == previous.ID {
				prefix = c.list[:i+1]
				break
			}
		}
		if prefix == nil {
			prefix = append(append([]model.Sprint(nil), c.list...), *previous)
		}
	}
	next, err := c.follow(previous, prefix)
	if err != nil {
		return model.Sprint{}, err
	}
	if len(prefix) == len(c.list) {
		c.list = append(c.list, next)
	}
	return next, nil
}

func (c *Chain) follow(previous *model.Sprint, prefix []model.Sprint) (model.Sprint, error) {
	if previous == nil || len(c.team.Sprint.Naming) == 0 {
		return FollowingSprint(c.team, previous)
	}
	length := time.Duration(c.team.Sprint.LengthDays) * 24 * time.Hour
	start := previous.End
	// The ID the numbering would give: needed for a rule that begins at a sprint not yet there.
	legacy, legacyErr := NextID(previous.ID, start, c.team.Sprint.Numbering)
	rule := activeRule(c.team.Sprint.Naming, prefix, legacy, legacyErr == nil)
	if rule == nil {
		if legacyErr != nil {
			return model.Sprint{}, legacyErr
		}
		return newSprint(legacy, start, start.Add(length)), nil
	}
	number, seq := numbersAfter(patternsOf(c.team.Sprint.Naming, rule), prefix, c.team.Sprint.Numbering, start.Year())
	id, err := model.FormatSprintName(rule.Pattern, model.SprintNameInput{Start: start, Number: number, Sequence: seq})
	if err != nil {
		return model.Sprint{}, err
	}
	return newSprint(id, start, start.Add(length)), nil
}

// activeRule is the last rule that has begun by the new sprint: it has no From, its From sprint
// is already in the chain, or its From is the ID the numbering gives the new sprint.
func activeRule(rules []model.NamingRule, prefix []model.Sprint, legacy string, legacyOK bool) *model.NamingRule {
	var found *model.NamingRule
	for i := range rules {
		r := &rules[i]
		if r.From == nil {
			found = r
			continue
		}
		if legacyOK && *r.From == legacy {
			found = r
			continue
		}
		for _, s := range prefix {
			if s.ID == *r.From {
				found = r
				break
			}
		}
	}
	return found
}

var tokenRE = regexp.MustCompile(`\{([^{}]*)\}`)

// patternRegexp matches names made by the pattern; it returns the order of the captured
// placeholders ("NN", "N" or "LFD").
func patternRegexp(pattern string) (*regexp.Regexp, []string) {
	var expr strings.Builder
	var order []string
	expr.WriteString("^")
	last := 0
	for _, loc := range tokenRE.FindAllStringSubmatchIndex(pattern, -1) {
		expr.WriteString(regexp.QuoteMeta(pattern[last:loc[0]]))
		last = loc[1]
		switch name := pattern[loc[2]:loc[3]]; name {
		case "NN", "N", "LFD":
			expr.WriteString(`(\d+)`)
			order = append(order, name)
		case "JJJJ":
			expr.WriteString(`\d{4}`)
		case "JJ", "MM", "KW":
			expr.WriteString(`\d{2}`)
		case "Q":
			expr.WriteString(`\d`)
		}
	}
	expr.WriteString(regexp.QuoteMeta(pattern[last:]))
	expr.WriteString("$")
	re, err := regexp.Compile(expr.String())
	if err != nil {
		return nil, nil
	}
	return re, order
}

// patternsOf are the patterns to read the previous ID with: the active one first, then the
// others (the previous sprint may be named by an earlier rule).
func patternsOf(rules []model.NamingRule, active *model.NamingRule) []string {
	out := []string{active.Pattern}
	for i := len(rules) - 1; i >= 0; i-- {
		if rules[i].Pattern != active.Pattern {
			out = append(out, rules[i].Pattern)
		}
	}
	return out
}

// numbersAfter are the number in the year and the running number of the sprint after the last
// of prefix, which starts in startYear.
func numbersAfter(patterns []string, prefix []model.Sprint, numbering model.Numbering, startYear int) (number, seq int) {
	prev := prefix[len(prefix)-1]
	prevNumber, prevSeq := 0, 0
	haveNumber, haveSeq := false, false
	for _, pattern := range patterns {
		re, order := patternRegexp(pattern)
		if re == nil {
			continue
		}
		m := re.FindStringSubmatch(prev.ID)
		if m == nil {
			continue
		}
		for i, name := range order {
			n, err := strconv.Atoi(m[i+1])
			if err != nil {
				continue
			}
			if name == "LFD" {
				prevSeq, haveSeq = n, true
			} else {
				prevNumber, haveNumber = n, true
			}
		}
		break
	}
	if !haveNumber && numbering != model.NumberingSequential {
		if year, counter, ok := strings.Cut(prev.ID, "."); ok && year == strconv.Itoa(prev.Start.Year()) {
			if n, err := strconv.Atoi(counter); err == nil {
				prevNumber, haveNumber = n, true
			}
		}
	}
	if !haveSeq && numbering == model.NumberingSequential {
		if n, err := strconv.Atoi(prev.ID); err == nil {
			prevSeq, haveSeq = n, true
		}
	}
	if !haveNumber {
		for _, s := range prefix {
			if s.Start.Year() == prev.Start.Year() {
				prevNumber++
			}
		}
	}
	if !haveSeq {
		prevSeq = len(prefix)
	}
	if prev.Start.Year() == startYear {
		number = prevNumber + 1
	} else {
		number = 1
	}
	return number, prevSeq + 1
}

// NameAll names the sprints of the list (oldest first) with the pattern: the number in the year
// restarts with each calendar year, the running number counts all sprints. first and firstSeq are
// the numbers of the first sprint (1 and 1 if you have nothing better).
func NameAll(pattern string, sprints []model.Sprint, first, firstSeq int) ([]string, error) {
	names := make([]string, len(sprints))
	number, year := first-1, 0
	for i, s := range sprints {
		if y := s.Start.Year(); i == 0 {
			year = y
			number = first
		} else if y != year {
			year, number = y, 1
		} else {
			number++
		}
		name, err := model.FormatSprintName(pattern, model.SprintNameInput{Start: s.Start, Number: number, Sequence: firstSeq + i})
		if err != nil {
			return nil, fmt.Errorf("sprint %s: %w", s.ID, err)
		}
		names[i] = name
	}
	return names, nil
}
