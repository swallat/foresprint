package validate

import (
	"strings"
	"unicode"
)

// blankControls turns control characters, line breaks and writing-direction characters into
// spaces (blank_controls of git.py).
func blankControls(s string) string {
	return strings.Map(func(r rune) rune {
		switch r {
		case '؜', '‎', '‏', '‪', '‫', '‬', '‭', '‮',
			'⁦', '⁧', '⁨', '⁩':
			return ' '
		}
		if unicode.Is(unicode.Cc, r) || unicode.Is(unicode.Zl, r) || unicode.Is(unicode.Zp, r) {
			return ' '
		}
		return r
	}, s)
}
