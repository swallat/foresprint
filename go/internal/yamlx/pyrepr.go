package yamlx

import (
	"fmt"
	"math/big"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// PyRepr is Python's repr() of a loaded value.
func PyRepr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case int:
		return strconv.Itoa(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case *big.Int:
		return x.String()
	case float64:
		return pyFloatRepr2(x)
	case string:
		return pyStrRepr(x)
	case Date:
		t := time.Time(x)
		return fmt.Sprintf("datetime.date(%d, %d, %d)", t.Year(), int(t.Month()), t.Day())
	case time.Time:
		return "datetime.datetime(" + timestampText(x) + ")"
	case []any:
		parts := make([]string, len(x))
		for i, it := range x {
			parts[i] = PyRepr(it)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case *Map:
		parts := make([]string, 0, len(x.Entries))
		for _, e := range x.Entries {
			parts = append(parts, PyRepr(e.Key)+": "+PyRepr(e.Value))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return fmt.Sprint(v)
}

// PyTypeName is the name of the Python type of a loaded value as a TypeError shows it
// ("datetime.date" for dates, like the C type reports itself).
func PyTypeName(v any) string {
	switch v.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case int, int64, *big.Int:
		return "int"
	case float64:
		return "float"
	case string:
		return "str"
	case Date:
		return "datetime.date"
	case time.Time:
		return "datetime.datetime"
	case []any:
		return "list"
	case *Map:
		return "dict"
	}
	return "object"
}

// pyFloatRepr2 is repr(float) including inf and nan.
func pyFloatRepr2(f float64) string {
	switch t := floatText(f); t {
	case ".inf":
		return "inf"
	case "-.inf":
		return "-inf"
	case ".nan":
		return "nan"
	}
	return pyFloatRepr(f)
}

// pyStrRepr is repr(str): single quotes unless the text has a single and no double quote.
func pyStrRepr(s string) string {
	quote := '\''
	if strings.ContainsRune(s, '\'') && !strings.ContainsRune(s, '"') {
		quote = '"'
	}
	var b strings.Builder
	b.WriteRune(quote)
	for _, r := range s {
		switch {
		case r == quote || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7F:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r < 0x7F || unicode.IsPrint(r):
			b.WriteRune(r)
		case r <= 0xFF:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r <= 0xFFFF:
			fmt.Fprintf(&b, `\u%04x`, r)
		default:
			fmt.Fprintf(&b, `\U%08x`, r)
		}
	}
	b.WriteRune(quote)
	return b.String()
}
