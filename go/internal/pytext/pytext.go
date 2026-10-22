// Package pytext has the few text functions whose Python behaviour differs from Go's: str.split(),
// str.strip(), str.splitlines() and the notion of white space (str.isspace).
package pytext

import (
	"golang.org/x/text/cases"

	"strings"
	"unicode"
	"unicode/utf8"
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

// isLineBreak reports the characters at which str.splitlines() splits.
func isLineBreak(r rune) bool {
	switch r {
	case '\n', '\r', '\v', '\f', 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029:
		return true
	}
	return false
}

// SplitLines is str.splitlines(keepends): like Splitlines, but with keepends the line ends stay
// at the end of each line.
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

// Casefold is str.casefold(): full Unicode case folding (ß → ss, ς → σ, ﬁ → fi, İ → i̇).
func Casefold(s string) string { return cases.Fold().String(s) }
