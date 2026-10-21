package storage

import (
	"math"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/yamlx"
)

// The conversions mirror the helpers of storage.py one to one, including the texts of their
// errors, so that a file that Python refuses is refused with the same message.

func repr(v any) string { return yamlx.PyRepr(v) }

func cut60(s string) string {
	r := []rune(s)
	if len(r) > 60 {
		return string(r[:60])
	}
	return s
}

// truthy is Python's truth value of a loaded value.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case int64:
		return x != 0
	case *big.Int:
		return x.Sign() != 0
	case float64:
		return x != 0
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case *yamlx.Map:
		return x != nil && len(x.Entries) > 0
	}
	return true
}

// isEmptyText is `value is None or value == ""`.
func isEmptyText(v any) bool {
	s, ok := v.(string)
	return v == nil || (ok && s == "")
}

func get(m *yamlx.Map, key string) any {
	if m == nil {
		return nil
	}
	v, _ := m.Get(key)
	return v
}

func has(m *yamlx.Map, key string) bool {
	if m == nil {
		return false
	}
	_, ok := m.Get(key)
	return ok
}

// getOr is dict.get(key, default).
func getOr(m *yamlx.Map, key string, def any) any {
	if m == nil {
		return def
	}
	if v, ok := m.Get(key); ok {
		return v
	}
	return def
}

func asNumber(v any) (float64, bool, bool) { // value, isNumber, overflow
	switch x := v.(type) {
	case int64:
		return float64(x), true, false
	case *big.Int:
		f, _ := new(big.Float).SetInt(x).Float64()
		return f, true, math.IsInf(f, 0)
	case float64:
		return x, true, false
	}
	return 0, false, false
}

// floatOf is _float: a number or nothing; booleans and texts are refused.
func floatOf(v any, where string) (*float64, error) {
	if isEmptyText(v) {
		return nil, nil
	}
	f, ok, overflow := asNumber(v)
	if !ok {
		return nil, dataErr("{where}: number expected, found {value}", "where", where, "value", repr(v))
	}
	if overflow {
		f = math.Inf(1)
	}
	if math.IsInf(f, 0) || math.IsNaN(f) {
		return nil, dataErr("{where}: finite number expected, found {value}", "where", where, "value", repr(v))
	}
	return &f, nil
}

// floatOr0 is `_float(...) or 0.0`.
func floatOr0(v any, where string) (float64, error) {
	f, err := floatOf(v, where)
	if err != nil || f == nil {
		return 0, err
	}
	return *f, nil
}

var pyFloatSyntax = regexp.MustCompile(`^[+-]?(?:(?:\d(?:_?\d)*)(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$`)

// pyFloat is Python's float(str); ok is false where Python raises ValueError.
func pyFloat(s string) (float64, bool) {
	s = strings.TrimSpace(s)
	switch strings.ToLower(strings.TrimLeft(s, "+-")) {
	case "inf", "infinity", "nan":
		if len(s)-len(strings.TrimLeft(s, "+-")) > 1 {
			return 0, false
		}
		neg := strings.HasPrefix(s, "-")
		if strings.ToLower(strings.TrimLeft(s, "+-")) == "nan" {
			return math.NaN(), true
		}
		if neg {
			return math.Inf(-1), true
		}
		return math.Inf(1), true
	}
	if !pyFloatSyntax.MatchString(s) {
		return 0, false
	}
	f, err := strconv.ParseFloat(strings.ReplaceAll(s, "_", ""), 64)
	if err != nil && !math.IsInf(f, 0) {
		return 0, false
	}
	return f, true
}

// pyFloatConv is Python's float(value); a message is returned where Python raises.
func pyFloatConv(v any) (float64, string) {
	switch x := v.(type) {
	case bool:
		if x {
			return 1, ""
		}
		return 0, ""
	case string:
		if f, ok := pyFloat(x); ok {
			return f, ""
		}
		return 0, "could not convert string to float: " + repr(x)
	}
	if f, ok, overflow := asNumber(v); ok {
		if overflow {
			return 0, "int too large to convert to float"
		}
		return f, ""
	}
	return 0, "float() argument must be a string or a real number, not '" + yamlx.PyTypeName(v) + "'"
}

var pyIntSyntax = regexp.MustCompile(`^[+-]?\d(?:_?\d)*$`)

// pyIntConv is Python's int(value); a message is returned where Python raises.
func pyIntConv(v any) (int, string) {
	switch x := v.(type) {
	case bool:
		if x {
			return 1, ""
		}
		return 0, ""
	case int64:
		return int(x), ""
	case *big.Int:
		return 0, "Python int too large to convert to C int"
	case float64:
		switch {
		case math.IsNaN(x):
			return 0, "cannot convert float NaN to integer"
		case math.IsInf(x, 0):
			return 0, "cannot convert float infinity to integer"
		case math.Abs(x) >= 1<<62:
			return 0, "Python int too large to convert to C int"
		}
		return int(x), ""
	case string:
		s := strings.TrimSpace(x)
		if pyIntSyntax.MatchString(s) {
			n, err := strconv.Atoi(strings.ReplaceAll(s, "_", ""))
			if err == nil {
				return n, ""
			}
		}
		return 0, "invalid literal for int() with base 10: " + repr(x)
	}
	return 0, "int() argument must be a string, a bytes-like object or a real number, not '" + yamlx.PyTypeName(v) + "'"
}

// finiteOf is _finite: float(value), refused if it is nan or inf. The message is what Python's
// exception says (the caller puts the location before it).
func finiteOf(v any) (float64, string) {
	f, msg := pyFloatConv(v)
	if msg != "" {
		return 0, msg
	}
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return 0, tr("not a finite number: {value}", "value", pyStr(v))
	}
	return f, ""
}

// lenientFloat is _lenient_float: like float(value) (also numbers in quotes).
func lenientFloat(v any, where string) (*float64, error) {
	if v == nil {
		return nil, nil
	}
	f, msg := pyFloatConv(v)
	if msg != "" {
		return nil, dataErr("{where}: number expected, found {value}", "where", where, "value", cut60(repr(v)))
	}
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return nil, dataErr("{where}: finite number expected, found {value}", "where", where, "value", cut60(repr(v)))
	}
	return &f, nil
}

// mapping is _mapping: an object, or an empty one if missing or empty.
func mapping(v any, where, name string) (*yamlx.Map, error) {
	if !truthy(v) {
		return &yamlx.Map{}, nil
	}
	m, ok := v.(*yamlx.Map)
	if !ok {
		return nil, dataErr("{where}: '{name}' must be a mapping (lines of the form 'key: value'), found {value}",
			"where", where, "name", name, "value", cut60(repr(v)))
	}
	return m, nil
}

// sequence is _sequence: a list, or an empty one if missing or empty.
func sequence(v any, where, name string) ([]any, error) {
	if !truthy(v) {
		return nil, nil
	}
	s, ok := v.([]any)
	if !ok {
		return nil, dataErr("{where}: '{name}' must be a list (entries starting with '- '), found {value}",
			"where", where, "name", name, "value", cut60(repr(v)))
	}
	return s, nil
}

// code is _code: country or region as text. Unquoted, YAML reads NO (Norway) and ON (Ontario)
// as a boolean.
func code(v any, where, name string) (*string, error) {
	if isEmptyText(v) {
		return nil, nil
	}
	if _, ok := v.(bool); ok {
		return nil, dataErr("{where}: please put '{name}' in quotes, e.g. {name}: \"NO\" (unquoted, YAML reads it as a boolean)",
			"where", where, "name", name)
	}
	s, ok := v.(string)
	if !ok {
		return nil, dataErr("{where}: '{name}' must be text (e.g. DE or NW), found {value}",
			"where", where, "name", name, "value", cut60(repr(v)))
	}
	return &s, nil
}

// dateOf is _date.
func dateOf(v any, where string) (time.Time, error) {
	switch x := v.(type) {
	case time.Time:
		return model.Date(x.Year(), x.Month(), x.Day()), nil
	case yamlx.Date:
		return time.Time(x), nil
	}
	if d, ok := parseISODate(pyStr(v)); ok {
		return d, nil
	}
	return time.Time{}, dataErr("{where}: date in format YYYY-MM-DD expected, found {value}", "where", where, "value", repr(v))
}

var (
	isoDateRe = regexp.MustCompile(`^(\d{4})-(\d{2})-(\d{2})$|^(\d{4})(\d{2})(\d{2})$`)
	isoWeekRe = regexp.MustCompile(`^(\d{4})-W(\d{2})(?:-(\d))?$|^(\d{4})W(\d{2})(\d)?$`)
)

// parseISODate is date.fromisoformat: YYYY-MM-DD, YYYYMMDD and ISO week dates.
func parseISODate(s string) (time.Time, bool) {
	if m := isoDateRe.FindStringSubmatch(s); m != nil {
		if m[1] == "" {
			m = append([]string{m[0]}, m[4:7]...)
		}
		y, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		d, _ := strconv.Atoi(m[3])
		if y < 1 || mo < 1 || mo > 12 || d < 1 {
			return time.Time{}, false
		}
		t := model.Date(y, time.Month(mo), d)
		if t.Day() != d || int(t.Month()) != mo {
			return time.Time{}, false
		}
		return t, true
	}
	if m := isoWeekRe.FindStringSubmatch(s); m != nil {
		if m[1] == "" {
			m = append([]string{m[0]}, m[4:7]...)
		}
		y, _ := strconv.Atoi(m[1])
		w, _ := strconv.Atoi(m[2])
		wd := 1
		if m[3] != "" {
			wd, _ = strconv.Atoi(m[3])
		}
		if y < 1 || w < 1 || w > 53 || wd < 1 || wd > 7 {
			return time.Time{}, false
		}
		// Monday of week 1 is the Monday of the week that holds January 4th.
		jan4 := model.Date(y, time.January, 4)
		offset := (int(jan4.Weekday()) + 6) % 7
		monday := jan4.AddDate(0, 0, -offset)
		t := monday.AddDate(0, 0, (w-1)*7+wd-1)
		if w == 53 {
			if _, isoWeek := t.ISOWeek(); isoWeek != 53 {
				return time.Time{}, false
			}
		}
		return t, true
	}
	return time.Time{}, false
}

// clean is _clean: a whole number as an integer, otherwise rounded to six decimals.
func clean(v float64) any {
	if v == math.Trunc(v) {
		if math.Abs(v) < 1<<62 {
			return int64(v)
		}
		n, _ := new(big.Float).SetFloat64(v).Int(nil)
		return n
	}
	r, _ := strconv.ParseFloat(strconv.FormatFloat(v, 'f', 6, 64), 64)
	return r
}

// cleanPtr is _clean of an optional value.
func cleanPtr(v *float64) any {
	if v == nil {
		return nil
	}
	return clean(*v)
}

// intOf is _int: a whole number; missing or empty = def. Booleans and fractions are refused.
func intOf(v any, where, name string, def int) (int, error) {
	if isEmptyText(v) {
		return def, nil
	}
	f, ok, _ := asNumber(v)
	if !ok || math.IsNaN(f) || math.IsInf(f, 0) || f != math.Trunc(f) {
		return 0, dataErr("{where}: '{name}' must be a whole number, found {value}",
			"where", where, "name", name, "value", cut60(repr(v)))
	}
	if n, ok := v.(int64); ok {
		return int(n), nil
	}
	if math.Abs(f) >= 1<<62 { // beyond what Go holds (Python has no limit): refuse, never wrap around
		return 0, dataErr("{where}: '{name}' must be a whole number, found {value}",
			"where", where, "name", name, "value", cut60(repr(v)))
	}
	return int(f), nil
}

// text is _text: a free text; missing or empty = nil.
func text(v any) *string {
	if isEmptyText(v) {
		return nil
	}
	s := pyStr(v)
	return &s
}

// texts is _texts: a list of texts; a single scalar counts as a list of one.
func texts(v any, where, name string) ([]string, error) {
	if isEmptyText(v) {
		return nil, nil
	}
	if m, ok := v.(*yamlx.Map); ok {
		if _, err := sequence(m, where, name); err != nil { // raises: an object is not a list
			return nil, err
		}
	}
	list, ok := v.([]any)
	if !ok {
		list = []any{v}
	}
	out := make([]string, len(list))
	for i, it := range list {
		out[i] = pyStr(it)
	}
	return out, nil
}

func strOr(v any, def string) string {
	if truthy(v) {
		return pyStr(v)
	}
	return def
}

// pyStr is Python's str() of a loaded value (the repr for lists and mappings).
func pyStr(v any) string {
	switch v.(type) {
	case []any, *yamlx.Map:
		return yamlx.PyRepr(v)
	}
	return yamlx.PyStr(v)
}
