// Package textfmt formats numbers and external text for the texts of the core: the number
// format of the language, capacities rounded half up, percentages, and Markdown code spans for
// names that come from files. It ports the helpers of src/foresprint/report.py and git.py that
// the calculation texts (formulas) need.
//
// The report and the Git messages are ported in other steps of the port; when those land, the
// functions here are the ones to share.
package textfmt

import (
	"regexp"
	"strings"
	"unicode"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pymath"
)

// Dash is the text for a missing value.
const Dash = "–"

// Fmt is a number with the thousands and decimal separators of the language (1.234,5 or
// 1,234.5); suffix is appended.
func Fmt(l string, value float64, digits int, suffix string) string {
	text := pymath.Fixed(value, digits, true)
	if l != i18n.Default {
		text = strings.NewReplacer(",", ".", ".", ",").Replace(text)
	}
	return text + suffix
}

// FmtPtr is Fmt for an optional number; nil gives Dash.
func FmtPtr(l string, value *float64, digits int) string {
	if value == nil {
		return Dash
	}
	return Fmt(l, *value, digits, "")
}

// FmtCapacity is a capacity for display, rounded half up (from .5 up) like Rounded and the
// frozen value. Formatting alone rounds an exact half to the even digit (25.25 → "25.2") and
// must not be used for capacities. digits is the team's capacity rounding.
func FmtCapacity(l string, value *float64, digits int) string {
	if value == nil {
		return Dash
	}
	return Fmt(l, engine.RoundHalfUp(*value, digits), digits, "")
}

// Pct is a share as a percentage ("80 %").
func Pct(l string, value float64) string { return Fmt(l, value*100, 0, " %") }

// isBidiControl reports the writing-direction control characters that BlankControls replaces:
// the Arabic letter mark, the direction marks, embeddings, overrides and isolates.
func isBidiControl(r rune) bool {
	switch {
	case r == 0x061c, r == 0x200e, r == 0x200f:
		return true
	case r >= 0x202a && r <= 0x202e:
		return true
	case r >= 0x2066 && r <= 0x2069:
		return true
	}
	return false
}

// BlankControls turns control characters, line breaks and writing-direction characters into
// spaces (external text for output without Markdown, e.g. the command line). The remaining
// format characters (zero-width joiners of emoji sequences) stay.
func BlankControls(text string) string {
	return strings.Map(func(r rune) rune {
		if isBidiControl(r) || unicode.Is(unicode.Cc, r) ||
			unicode.Is(unicode.Zl, r) || unicode.Is(unicode.Zp, r) {
			return ' '
		}
		return r
	}, text)
}

var backtickRun = regexp.MustCompile("`+")

// MdCode is text as a code span for Markdown. Names and addresses that come from outside never
// belong in the interface as plain text: emphasis would take effect there and web addresses
// would become links. Backticks in the text do not end the span; control characters, line
// breaks and writing-direction characters become spaces.
func MdCode(text string) string {
	text = BlankControls(text)
	if text == "" {
		return ""
	}
	longest := 0
	for _, run := range backtickRun.FindAllString(text, -1) {
		longest = max(longest, len(run))
	}
	fence := strings.Repeat("`", longest+1)
	pad := ""
	first, last := text[0], text[len(text)-1]
	if first == '`' || first == ' ' || last == '`' || last == ' ' {
		pad = " "
	}
	return fence + pad + text + pad + fence
}

// SprintText is a sprint ID for plain text without Markdown (table, command line): control
// characters and text direction characters become spaces, as with MdCode.
func SprintText(id string) string { return BlankControls(id) }

// AbsenceDerivedRemedy is what to do about an uncertain absence rate (without sprint IDs).
// window is the absence_history setting: how long the hint stays.
func AbsenceDerivedRemedy(l string, window int) string {
	return i18n.TIn(l,
		"If someone was absent in one of these sprints, enter the absences on the "+
			"\"{page}\" page and save them with \"Save absences\" (or with `foresprint "+
			"absences`). If nobody was absent, the rate is correct. In the \"Absence status\" "+
			"table these sprints count as confirmed because they have already been planned or "+
			"reviewed; but no absences are saved. The note stays until the sprints drop out of "+
			"the window of the last {window} sprints (setting `absence_history`) or absences "+
			"are entered.",
		"page", i18n.TIn(l, "Prepare the sprint: absences"), "window", window,
	)
}

// AbsenceDerivedNote is the hint that the expected absence rate is uncertain: sprints that count
// as confirmed only from other fields (older files without a stored state) and have no absences
// count as "0 % lost" and pull the rate down. The numbers stay unchanged. ok is false if no
// such sprint goes into the rate.
//
// The sprint IDs come from files and are shown in code notation (MdCode) so that they change
// nothing in Markdown (code=false for tables, plain text and the command line, there with
// SprintText). detailed adds what to do.
func AbsenceDerivedNote(l string, history *capacity.AbsenceHistory, detailed, code bool, window int) (string, bool) {
	if history == nil || len(history.Derived) == 0 {
		return "", false
	}
	count := len(history.Derived)
	ids := make([]string, count)
	for i, id := range history.Derived {
		if code {
			ids[i] = MdCode(id)
		} else {
			ids[i] = SprintText(id)
		}
	}
	sprints := strings.Join(ids, ", ")
	var note string
	if count == 1 {
		note = i18n.TIn(l,
			"Rate uncertain: {count} sprint in the expected absence rate ({sprints}) only "+
				"counts as confirmed because it has already been planned or reviewed; no "+
				"absences are saved, so the rate assumes \"0 % lost\". The estimated capacity "+
				"of future sprints may be too high.",
			"count", count, "sprints", sprints)
	} else {
		note = i18n.TIn(l,
			"Rate uncertain: {count} sprints in the expected absence rate ({sprints}) only "+
				"count as confirmed because they have already been planned or reviewed; no "+
				"absences are saved, so the rate assumes \"0 % lost\". The estimated capacity "+
				"of future sprints may be too high.",
			"count", count, "sprints", sprints)
	}
	if detailed {
		return note + " " + AbsenceDerivedRemedy(l, window), true
	}
	return note, true
}

// AbsenceDerivedHint is the short pointer for pages that show only the estimated capacity
// (without the list of sprints; that is on the absences page, in the calculation path, in the
// report).
func AbsenceDerivedHint(l string, history *capacity.AbsenceHistory) (string, bool) {
	if history == nil || len(history.Derived) == 0 {
		return "", false
	}
	page := i18n.TIn(l, "Prepare the sprint: absences")
	if len(history.Derived) == 1 {
		return i18n.TIn(l,
			"Rate uncertain: no absences are saved for {count} sprint in the rate. Details "+
				"on the \"{page}\" page.",
			"count", 1, "page", page), true
	}
	return i18n.TIn(l,
		"Rate uncertain: no absences are saved for {count} sprints in the rate. Details on "+
			"the \"{page}\" page.",
		"count", len(history.Derived), "page", page), true
}
