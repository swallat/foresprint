package sources

import (
	"encoding/json"
	"math"
	"math/big"
	"strconv"
	"strings"
	"unicode"

	"golang.org/x/text/cases"
)

// Helpers that reproduce what the Python sources rely on (str.strip, str.split, float(), repr of a
// float), so that the same input gives the same result.

// pyIsSpace is Python's str.isspace for one character: Unicode white space plus the separators
// U+001C to U+001F.
func pyIsSpace(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}

// pyStrip is str.strip().
func pyStrip(s string) string { return strings.TrimFunc(s, pyIsSpace) }

// pyRStrip is str.rstrip().
func pyRStrip(s string) string { return strings.TrimRightFunc(s, pyIsSpace) }

// pyFields is str.split() without argument.
func pyFields(s string) []string { return strings.FieldsFunc(s, pyIsSpace) }

// collapse is " ".join(s.split()).
func collapse(s string) string { return strings.Join(pyFields(s), " ") }

var folder = cases.Fold()

// casefold is str.casefold().
func casefold(s string) string { return folder.String(s) }

// digitValue returns the value of a decimal digit of any script (what Python's float() accepts),
// or -1.
func digitValue(r rune) int {
	if r >= '0' && r <= '9' {
		return int(r - '0')
	}
	if r < 0x80 || !unicode.Is(unicode.Nd, r) {
		return -1
	}
	start := r
	for unicode.Is(unicode.Nd, start-1) {
		start--
	}
	return int(r-start) % 10
}

// pyFloat is float(text) for a finite result: it returns false for text Python rejects and for
// the values inf and nan, which every caller of the sources treats as an error as well.
func pyFloat(text string) (float64, bool) {
	text = pyStrip(text)
	if text == "" {
		return 0, false
	}
	var b strings.Builder
	runes := []rune(text)
	for i, r := range runes {
		if r == '_' {
			// An underscore is allowed between two digits only.
			if i == 0 || i == len(runes)-1 || digitValue(runes[i-1]) < 0 || digitValue(runes[i+1]) < 0 {
				return 0, false
			}
			continue
		}
		if d := digitValue(r); d >= 0 {
			b.WriteByte(byte('0' + d))
			continue
		}
		if r >= 0x80 {
			return 0, false
		}
		b.WriteRune(r)
	}
	s := b.String()
	if strings.ContainsAny(s, "xXpP") { // Go reads hexadecimal floats, Python does not
		return 0, false
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil || math.IsInf(v, 0) || math.IsNaN(v) {
		return 0, false
	}
	return v, true
}

// pyFloatRepr is repr(float): the shortest text that reads back as the same number, in fixed
// notation for exponents from -4 up to 15 and in scientific notation otherwise.
func pyFloatRepr(v float64) string {
	if v == math.Trunc(v) && math.Abs(v) < 1e16 {
		return strconv.FormatFloat(v, 'f', 1, 64)
	}
	exp := strconv.FormatFloat(v, 'e', -1, 64)
	at := strings.IndexByte(exp, 'e')
	e, _ := strconv.Atoi(exp[at+1:])
	if e >= -4 && e < 16 {
		return strconv.FormatFloat(v, 'f', -1, 64)
	}
	return exp
}

// isJSONInt reports whether a decoded JSON number is an integer in the sense of Python's json
// module (no fraction, no exponent).
func isJSONInt(n json.Number) bool {
	return !strings.ContainsAny(string(n), ".eE")
}

// numberString is str() of a decoded JSON number.
func numberString(n json.Number) string {
	if isJSONInt(n) {
		if i, ok := new(big.Int).SetString(string(n), 10); ok {
			return i.String()
		}
		return string(n)
	}
	f, err := strconv.ParseFloat(string(n), 64)
	if err != nil {
		return string(n)
	}
	return pyFloatRepr(f)
}

// pyTruthy is Python's truthiness of a decoded JSON value.
func pyTruthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, _ := strconv.ParseFloat(string(x), 64)
		return f != 0
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

// pyStr is str() of a decoded JSON value, as far as the sources print values.
func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return x
	case json.Number:
		return numberString(x)
	}
	return ""
}

// asString returns v when it is a JSON string.
func asString(v any) (string, bool) {
	s, ok := v.(string)
	return s, ok
}

// asObject returns v when it is a JSON object.
func asObject(v any) (map[string]any, bool) {
	m, ok := v.(map[string]any)
	return m, ok
}

// asList returns v when it is a JSON array.
func asList(v any) ([]any, bool) {
	l, ok := v.([]any)
	return l, ok
}

// asInt returns v when it is a JSON integer (not a boolean, not a float).
func asInt(v any) (int64, bool) {
	n, ok := v.(json.Number)
	if !ok || !isJSONInt(n) {
		return 0, false
	}
	i, err := strconv.ParseInt(string(n), 10, 64)
	return i, err == nil
}

// dedupe is list(dict.fromkeys(items)).
func dedupe(items []string) []string {
	seen := make(map[string]bool, len(items))
	out := make([]string, 0, len(items))
	for _, s := range items {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	return out
}

// IsSpace is Python's str.isspace for one character, for callers that must treat text the way the
// Python code did.
func IsSpace(r rune) bool { return pyIsSpace(r) }
