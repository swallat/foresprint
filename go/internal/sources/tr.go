package sources

import (
	"fmt"
	"strings"
)

// T fills the named placeholders ({name}) of a user text with the key/value pairs. Texts are
// English source texts; the translation catalog is applied by the caller's T replacement:
// assign Translate to look a text up before the placeholders are filled.
func T(text string, kv ...any) string {
	if Translate != nil {
		text = Translate(text)
	}
	if len(kv) == 0 {
		return text
	}
	pairs := make([]string, 0, len(kv))
	for i := 0; i+1 < len(kv); i += 2 {
		pairs = append(pairs, "{"+fmt.Sprint(kv[i])+"}", fmt.Sprint(kv[i+1]))
	}
	return strings.NewReplacer(pairs...).Replace(text)
}

// Translate returns the translation of an English source text (nil = English). The catalog of
// the program sets it; this package has no texts of its own besides the English ones.
var Translate func(text string) string
