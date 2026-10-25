package yamlx

import (
	"fmt"
	"math/big"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// PyRepr is Python's repr() of a loaded value (used in messages and by PyStr).
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
		return PyFloatRepr(x)
	case string:
		return pyStrRepr(x)
	case Date:
		t := time.Time(x)
		return fmt.Sprintf("datetime.date(%d, %d, %d)", t.Year(), int(t.Month()), t.Day())
	case time.Time:
		return datetimeRepr(x)
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

// PyTypeName is the name of the Python type of a loaded value as Python shows it in a
// TypeError (type(x).__name__; "datetime.date" for dates, like the C type reports itself).
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

// datetimeRepr is repr(datetime): seconds and microseconds only when set, then the zone.
func datetimeRepr(t time.Time) string {
	parts := []int{t.Year(), int(t.Month()), t.Day(), t.Hour(), t.Minute()}
	us := t.Nanosecond() / 1000
	if t.Second() != 0 || us != 0 {
		parts = append(parts, t.Second())
	}
	if us != 0 {
		parts = append(parts, us)
	}
	texts := make([]string, len(parts))
	for i, p := range parts {
		texts[i] = strconv.Itoa(p)
	}
	out := "datetime.datetime(" + strings.Join(texts, ", ")
	if t.Location() != time.UTC {
		_, off := t.Zone()
		if off == 0 {
			out += ", tzinfo=datetime.timezone.utc"
		} else {
			out += ", tzinfo=datetime.timezone(datetime.timedelta(" + timedeltaArgs(off) + "))"
		}
	}
	return out + ")"
}

// timedeltaArgs is the argument list of repr(timedelta) for an offset in seconds.
func timedeltaArgs(sec int) string {
	days := 0
	for sec < 0 {
		sec += 86400
		days--
	}
	var args []string
	if days != 0 {
		args = append(args, "days="+strconv.Itoa(days))
	}
	if sec != 0 {
		args = append(args, "seconds="+strconv.Itoa(sec))
	}
	return strings.Join(args, ", ")
}
