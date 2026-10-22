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
