package yamlmerge

import (
	"math"
	"strconv"
	"strings"
	"time"
)

// The YAML value tree the merge works on. It has the shapes PyYAML's safe loader produces:
// nil, bool, int64, float64, string, Date, DateTime, []any (a list) and *Map (a mapping that
// keeps its key order).

// Date is a calendar date without a time.
type Date struct {
	Year  int
	Month time.Month
	Day   int
}

// String is the ISO form (2026-01-31).
func (d Date) String() string {
	return time.Date(d.Year, d.Month, d.Day, 0, 0, 0, 0, time.UTC).Format("2006-01-02")
}

// DateTime is a point in time. Aware says whether the file gave a time zone; Time then carries
// it. Without a zone the wall clock time is kept in UTC and Aware is false.
type DateTime struct {
	Time  time.Time
	Aware bool
}

// Pair is one entry of a Map.
type Pair struct {
	Key   any
	Value any
}

// Map is a mapping with the key order of the file. Keys are normally strings.
type Map struct {
	pairs []Pair
	index map[string]int
}

// NewMap returns an empty mapping.
func NewMap() *Map { return &Map{index: map[string]int{}} }

// Len is the number of entries.
func (m *Map) Len() int { return len(m.pairs) }

// Pairs returns the entries in order. The slice must not be changed.
func (m *Map) Pairs() []Pair { return m.pairs }

// Keys returns the keys in order.
func (m *Map) Keys() []any {
	keys := make([]any, len(m.pairs))
	for i, p := range m.pairs {
		keys[i] = p.Key
	}
	return keys
}

// Get returns the value of key.
func (m *Map) Get(key any) (any, bool) {
	if m == nil {
		return nil, false
	}
	i, ok := m.index[keyID(key)]
	if !ok {
		return nil, false
	}
	return m.pairs[i].Value, true
}

// Has says whether key is present.
func (m *Map) Has(key any) bool {
	_, ok := m.Get(key)
	return ok
}

// Set adds the entry or replaces the value of an existing key (which keeps its position).
func (m *Map) Set(key, value any) {
	id := keyID(key)
	if i, ok := m.index[id]; ok {
		m.pairs[i].Value = value
		return
	}
	m.index[id] = len(m.pairs)
	m.pairs = append(m.pairs, Pair{key, value})
}

// keyID identifies a key the way Python's dictionary does: an integer and the float of the same
// value are the same key; other types stay apart.
func keyID(key any) string {
	switch k := key.(type) {
	case nil:
		return "z"
	case string:
		return "s" + k
	case bool:
		if k {
			return "b1"
		}
		return "b0"
	case int64:
		return "n" + strconv.FormatInt(k, 10)
	case float64:
		if k == math.Trunc(k) && math.Abs(k) < 1<<62 {
			return "n" + strconv.FormatInt(int64(k), 10)
		}
		return "f" + strconv.FormatFloat(k, 'g', -1, 64)
	case Date:
		return "d" + k.String()
	case DateTime:
		return "t" + k.Time.UTC().Format(time.RFC3339Nano) + strconv.FormatBool(k.Aware)
	default:
		return "?" + Str(key)
	}
}

// Str is Python's str() of a scalar: how a key or an id appears in a path.
func Str(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		return PyFloat(x)
	case Date:
		return x.String()
	case DateTime:
		return pyDateTime(x)
	default:
		return ""
	}
}

func pyDateTime(d DateTime) string {
	text := d.Time.Format("2006-01-02 15:04:05")
	if micro := d.Time.Nanosecond() / 1000; micro != 0 {
		text += "." + strconv.Itoa(1_000_000 + micro)[1:]
	}
	if d.Aware {
		_, offset := d.Time.Zone()
		sign := '+'
		if offset < 0 {
			sign, offset = '-', -offset
		}
		text += string(sign) + twoDigits(offset/3600) + ":" + twoDigits(offset%3600/60)
	}
	return text
}

func twoDigits(n int) string {
	if n < 10 {
		return "0" + strconv.Itoa(n)
	}
	return strconv.Itoa(n)
}

// PyFloat formats a float like Python's repr().
func PyFloat(f float64) string {
	switch {
	case math.IsNaN(f):
		return "nan"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	case f == 0:
		if math.Signbit(f) {
			return "-0.0"
		}
		return "0.0"
	}
	e := strconv.FormatFloat(f, 'e', -1, 64) // d.ddde±xx
	mant, exp, _ := strings.Cut(e, "e")
	exponent, _ := strconv.Atoi(exp)
	neg := strings.HasPrefix(mant, "-")
	digits := strings.Replace(strings.TrimPrefix(mant, "-"), ".", "", 1)
	var out string
	switch {
	case exponent >= 16 || exponent < -4:
		out = digits[:1]
		if len(digits) > 1 {
			out += "." + digits[1:]
		}
		sign := "+"
		if exponent < 0 {
			sign, exponent = "-", -exponent
		}
		out += "e" + sign + twoDigits(exponent)
	case exponent < 0:
		out = "0." + strings.Repeat("0", -exponent-1) + digits
	case exponent+1 >= len(digits):
		out = digits + strings.Repeat("0", exponent+1-len(digits)) + ".0"
	default:
		out = digits[:exponent+1] + "." + digits[exponent+1:]
	}
	if neg {
		out = "-" + out
	}
	return out
}
