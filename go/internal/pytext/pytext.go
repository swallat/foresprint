// Package pytext has the few text functions whose Python behaviour differs from Go's: str.split(),
// str.strip(), str.splitlines() and the notion of white space (str.isspace).
package pytext

import (
	"strings"
	"unicode"
)

// IsSpace is str.isspace() for one character (and \s of Python's re): Go's unicode.IsSpace
// lacks the information separators 0x1c to 0x1f.
func IsSpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

// Fields is s.split() without arguments: runs of white space separate the words.
func Fields(s string) []string { return strings.FieldsFunc(s, IsSpace) }

// Strip is s.strip() without arguments.
func Strip(s string) string { return strings.TrimFunc(s, IsSpace) }

// Splitlines is s.splitlines(): lines end at \n, \r, \r\n, \v, \f, 0x1c to 0x1e, 0x85, U+2028
// and U+2029; the line ends are not kept and a final one does not start an empty line.
func Splitlines(s string) []string {
	var lines []string
	start := 0
	rs := []rune(s)
	for i := 0; i < len(rs); i++ {
		switch rs[i] {
		case '\n', '\v', '\f', 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029:
		case '\r':
			lines = append(lines, string(rs[start:i]))
			if i+1 < len(rs) && rs[i+1] == '\n' {
				i++
			}
			start = i + 1
			continue
		default:
			continue
		}
		lines = append(lines, string(rs[start:i]))
		start = i + 1
	}
	if start < len(rs) {
		lines = append(lines, string(rs[start:]))
	}
	return lines
}
