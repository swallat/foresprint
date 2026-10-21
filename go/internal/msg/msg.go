// Package msg fills in the user texts of the core. Source texts are English with {name}
// placeholders (Python's str.format); a catalog maps the English text to its translation. The
// catalogs (German) belong to the texts of the program; this package only has the mechanism the
// calculation core needs for the texts it builds (explanations, formulas).
package msg

import (
	"fmt"
	"strconv"
	"strings"
)

// Values are the named values of a text.
type Values map[string]any

// Lang is the language of the texts: English (the source texts) or a translation by catalog.
type Lang struct {
	// Code is "en" or "de" (or another language code).
	Code string
	// Catalog maps an English source text to its translation; texts it lacks stay English.
	Catalog map[string]string
}

// English is the language of the source texts.
var English = Lang{Code: "en"}

// IsEnglish reports whether the texts are the English source texts.
func (l Lang) IsEnglish() bool { return l.Code == "" || l.Code == "en" }

// T translates text and fills in the values, like t(text, **values) of the Python core.
func (l Lang) T(text string, values Values) string {
	if !l.IsEnglish() {
		if translated, ok := l.Catalog[text]; ok {
			text = translated
		}
	}
	if values == nil {
		return text
	}
	return Format(text, values)
}

// Format is str.format with named fields only: {name} is replaced, {{ and }} are single braces.
// A field without a value is left as it is.
func Format(template string, values Values) string {
	var b strings.Builder
	for i := 0; i < len(template); i++ {
		c := template[i]
		switch {
		case c == '{' && i+1 < len(template) && template[i+1] == '{':
			b.WriteByte('{')
			i++
		case c == '}' && i+1 < len(template) && template[i+1] == '}':
			b.WriteByte('}')
			i++
		case c == '{':
			end := strings.IndexByte(template[i:], '}')
			if end < 0 {
				b.WriteString(template[i:])
				return b.String()
			}
			name := template[i+1 : i+end]
			if v, ok := values[name]; ok {
				b.WriteString(str(v))
			} else {
				b.WriteString(template[i : i+end+1])
			}
			i += end
		default:
			b.WriteByte(c)
		}
	}
	return b.String()
}

func str(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case int:
		return strconv.Itoa(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		return strconv.FormatFloat(x, 'g', -1, 64)
	default:
		return fmt.Sprint(v)
	}
}
