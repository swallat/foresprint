// Package report holds the Markdown report and the number formats shared by the report, the
// minutes and the command line (port of report.py).
package report

import (
	"math"
	"strconv"
	"strings"
)

// English tells whether texts and numbers are in English (1,234.5) or German (1.234,5). The text
// catalog replaces it.
var English = func() bool { return true }

// Fmt formats a number with the thousands and decimal separators of the language; nil is "–".
func Fmt(value *float64, digits int, suffix string) string {
	if value == nil {
		return "–"
	}
	return FmtValue(*value, digits) + suffix
}

// FmtValue is Fmt for a number that exists.
func FmtValue(v float64, digits int) string {
	var text string
	switch {
	case math.IsNaN(v):
		text = "nan"
	case math.IsInf(v, 1):
		text = "inf"
	case math.IsInf(v, -1):
		text = "-inf"
	default:
		text = group(strconv.FormatFloat(v, 'f', digits, 64))
	}
	if !English() {
		text = strings.NewReplacer(",", ".", ".", ",").Replace(text)
	}
	return text
}

// group inserts the thousands separators of Python's "{:,}" into a fixed-point number.
func group(s string) string {
	sign := ""
	if strings.HasPrefix(s, "-") {
		sign, s = "-", s[1:]
	}
	whole, frac, hasFrac := strings.Cut(s, ".")
	var b strings.Builder
	for i, c := range whole {
		if i > 0 && (len(whole)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(c)
	}
	out := sign + b.String()
	if hasFrac {
		out += "." + frac
	}
	return out
}

// Pct formats a share as a percentage ("12 %"); nil is "–".
func Pct(value *float64) string {
	if value == nil {
		return "–"
	}
	v := *value * 100
	return Fmt(&v, 0, " %")
}
