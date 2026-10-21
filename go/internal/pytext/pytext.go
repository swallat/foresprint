// Package pytext has the few text functions of Python's str type whose behavior differs from
// the Go standard library in ways that show in the output of the core.
package pytext

import (
	"strings"
	"unicode/utf8"
)

// isLineBreak reports the characters at which str.splitlines() splits.
func isLineBreak(r rune) bool {
	switch r {
	case '\n', '\r', '\v', '\f', 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029:
		return true
	}
	return false
}

// SplitLines is str.splitlines(keepends): it splits at \n, \r, \r\n, \v, \f, \x1c-\x1e, \x85,
// U+2028 and U+2029. A final line break does not create an empty last line.
func SplitLines(s string, keepends bool) []string {
	var lines []string
	start := 0
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		if !isLineBreak(r) {
			i += size
			continue
		}
		end := i + size
		if r == '\r' && end < len(s) && s[end] == '\n' {
			end++
		}
		if keepends {
			lines = append(lines, s[start:end])
		} else {
			lines = append(lines, s[start:i])
		}
		i, start = end, end
	}
	if start < len(s) {
		lines = append(lines, s[start:])
	}
	return lines
}

// Strip is str.strip() without arguments.
func Strip(s string) string { return strings.TrimSpace(s) }
