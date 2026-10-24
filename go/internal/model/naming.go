package model

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// SprintNameInput is what a naming pattern is filled with for one sprint.
type SprintNameInput struct {
	// Start is the first day of the sprint (year, quarter, month and ISO week come from it).
	Start time.Time
	// Number is the number of the sprint within its year, starting at 1 each year.
	Number int
	// Sequence is the running number over all sprints, starting at 1.
	Sequence int
}

// NamingPlaceholders are the placeholders of a sprint naming pattern.
var NamingPlaceholders = []string{"JJJJ", "JJ", "NN", "N", "LFD", "Q", "MM", "KW"}

var placeholder = regexp.MustCompile(`\{([^{}]*)\}`)

// NamingProblem returns the first unknown placeholder of the pattern, or "" if all are known.
// An empty pattern has the problem "" too (it means: name = id).
func NamingProblem(pattern string) string {
	for _, m := range placeholder.FindAllStringSubmatch(pattern, -1) {
		if !contains(NamingPlaceholders, m[1]) {
			return m[0]
		}
	}
	if strings.Count(pattern, "{") != strings.Count(pattern, "}") {
		return "{}"
	}
	return ""
}

// FormatSprintName fills a naming pattern: {JJJJ} year, {JJ} short year, {NN} number within the
// year (two digits), {N} the same without padding, {LFD} running number over all sprints, {Q}
// quarter, {MM} month and {KW} ISO week of the sprint start (two digits each). An unknown
// placeholder is an error.
func FormatSprintName(pattern string, in SprintNameInput) (string, error) {
	if bad := NamingProblem(pattern); bad != "" {
		return "", fmt.Errorf("unknown placeholder %s in sprint naming pattern", bad)
	}
	_, week := in.Start.ISOWeek()
	values := map[string]string{
		"JJJJ": strconv.Itoa(in.Start.Year()),
		"JJ":   fmt.Sprintf("%02d", in.Start.Year()%100),
		"NN":   fmt.Sprintf("%02d", in.Number),
		"N":    strconv.Itoa(in.Number),
		"LFD":  strconv.Itoa(in.Sequence),
		"Q":    strconv.Itoa((int(in.Start.Month())-1)/3 + 1),
		"MM":   fmt.Sprintf("%02d", int(in.Start.Month())),
		"KW":   fmt.Sprintf("%02d", week),
	}
	return placeholder.ReplaceAllStringFunc(pattern, func(m string) string {
		return values[m[1:len(m)-1]]
	}), nil
}

// SprintDisplayName is the name shown for the sprint with the given id: the name given by hand,
// else the naming pattern that applies from this sprint on (the newest rule whose From is this
// sprint or an earlier one; From nil = from the first), else the id. sprints must be ordered
// from the oldest to the newest; the number within the year counts the sprints that start in
// the same year, the running number all sprints.
func SprintDisplayName(team *Team, sprints []Sprint, id string) string {
	index := -1
	for i, s := range sprints {
		if s.ID == id {
			index = i
			break
		}
	}
	if index < 0 {
		return id
	}
	s := sprints[index]
	if s.Name != nil && *s.Name != "" {
		return *s.Name
	}
	pattern, best := "", -1
	for _, rule := range team.Sprint.Naming {
		from := 0
		if rule.From != nil {
			from = -1
			for i, c := range sprints {
				if c.ID == *rule.From {
					from = i
					break
				}
			}
		}
		if from < 0 || from > index || from < best {
			continue
		}
		best, pattern = from, rule.Pattern
	}
	if pattern == "" {
		return id
	}
	number := 0
	for _, c := range sprints[:index+1] {
		if c.Start.Year() == s.Start.Year() {
			number++
		}
	}
	// A team that starts mid-year keeps counting from the number of its first sprint
	// (first ID "2026.16": the first sprint is number 16, not 1).
	seq := index + 1
	if first := sprints[0]; first.Start.Year() == s.Start.Year() {
		if k, ok := leadingCounter(first); ok && team.Sprint.Numbering != NumberingSequential {
			number += k - 1
		}
	}
	if team.Sprint.Numbering == NumberingSequential {
		if k, err := strconv.Atoi(sprints[0].ID); err == nil && k > 0 {
			seq += k - 1
		}
	}
	name, err := FormatSprintName(pattern, SprintNameInput{Start: s.Start, Number: number, Sequence: seq})
	if err != nil {
		return id
	}
	return name
}

// leadingCounter is k of a yearly ID "YYYY.k" of the sprint's start year.
func leadingCounter(s Sprint) (int, bool) {
	year, counter, ok := strings.Cut(s.ID, ".")
	if !ok || year != strconv.Itoa(s.Start.Year()) {
		return 0, false
	}
	k, err := strconv.Atoi(counter)
	return k, err == nil && k > 0
}
