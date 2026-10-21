// Package i18n translates the texts of the interface. Source texts are English, as in the Python
// core (`t("Saved: {names}", names=...)`); German and other languages come from catalogs that
// map the English text to its translation. A text that has no entry stays English.
//
// Placeholders are written `{name}` and filled from the key/value pairs after the text. The
// catalogs themselves are registered by the package that owns them (see Register).
package i18n

import (
	"fmt"
	"strings"
	"sync"
)

// Default is the language of the source texts.
const Default = "en"

var (
	mu       sync.RWMutex
	language = Default
	catalogs = map[string]map[string]string{}
)

// SetLanguage selects the language for the process ("en", "de", ...). An empty code selects
// the default.
func SetLanguage(code string) {
	if code == "" {
		code = Default
	}
	mu.Lock()
	language = code
	mu.Unlock()
}

// Language returns the language in use.
func Language() string {
	mu.RLock()
	defer mu.RUnlock()
	return language
}

// Register adds the translations of one language (English source text to translated text).
// Later entries replace earlier ones.
func Register(code string, entries map[string]string) {
	mu.Lock()
	defer mu.Unlock()
	cat := catalogs[code]
	if cat == nil {
		cat = make(map[string]string, len(entries))
		catalogs[code] = cat
	}
	for k, v := range entries {
		cat[k] = v
	}
}

// T translates text and fills the placeholders. values are alternating names and values:
// T("Saved {n} files", "n", 3).
func T(text string, values ...any) string {
	mu.RLock()
	template := text
	if language != Default {
		if translated, ok := catalogs[language][text]; ok {
			template = translated
		}
	}
	mu.RUnlock()
	if len(values) == 0 {
		return template
	}
	pairs := make([]string, 0, len(values))
	for i := 0; i+1 < len(values); i += 2 {
		pairs = append(pairs, "{"+fmt.Sprint(values[i])+"}", fmt.Sprint(values[i+1]))
	}
	return strings.NewReplacer(pairs...).Replace(template)
}
