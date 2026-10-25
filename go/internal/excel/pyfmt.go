package excel

import (
	"strconv"
	"strings"
	"unicode"
)

// pyG formats a number like Python's format(x, "g").
func pyG(x float64) string { return strconv.FormatFloat(x, 'g', 6, 64) }

// pyRepr is repr() of a string.
func pyRepr(s string) string {
	quote := byte('\'')
	if strings.ContainsRune(s, '\'') && !strings.ContainsRune(s, '"') {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == rune(quote) || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case !unicode.IsPrint(r):
			switch {
			case r < 0x100:
				b.WriteString(`\x` + strconv.FormatInt(int64(r)+0x100, 16)[1:])
			case r < 0x10000:
				b.WriteString(`\u` + strconv.FormatInt(int64(r)+0x10000, 16)[1:])
			default:
				b.WriteString(`\U` + strconv.FormatInt(int64(r)+0x100000000, 16)[1:])
			}
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}
