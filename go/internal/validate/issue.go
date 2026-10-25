// Package validate checks the data of a team for errors and plausibility (port of validate.py):
// the findings of check_team, the silent assumptions in the YAML text, the rules of the
// assignment language and the circular dependencies of tickets.
package validate

import (
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
)

// Level of a finding.
type Level string

// The two levels; the values are the English texts the references use.
const (
	Error   Level = "Error"
	Warning Level = "Notice"
)

// Issue is one finding: where it is (file, optionally "file: id") and what is wrong.
type Issue struct {
	Level   Level
	Where   string
	Message string
}

// Translate turns an English message into the language of the user. Wire it to the text
// catalog; placeholders are {name}, filled from pairs of name and value.
var Translate = func(text string) string { return i18n.T(text) }

func msg(text string, pairs ...string) string {
	text = Translate(text)
	if len(pairs) == 0 {
		return text
	}
	var b strings.Builder
	for i := 0; i < len(text); {
		if text[i] == '{' {
			if end := strings.IndexByte(text[i:], '}'); end > 0 {
				if v, ok := lookup(pairs, text[i+1:i+end]); ok {
					b.WriteString(v)
					i += end + 1
					continue
				}
			}
		}
		b.WriteByte(text[i])
		i++
	}
	return b.String()
}

func lookup(pairs []string, name string) (string, bool) {
	for i := 0; i+1 < len(pairs); i += 2 {
		if pairs[i] == name {
			return pairs[i+1], true
		}
	}
	return "", false
}
