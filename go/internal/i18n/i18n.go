// Package i18n translates the texts of the program. Source texts are English; a language is a
// JSON file in data/ (see scripts/gen_locales.py) that maps them to the translation. A text
// without entry is shown in English. File contents (YAML) are English whatever the language.
//
// Another language is another file in data/: nothing in the program changes. A language may
// have extra files "<code>.<name>.json" (same format) for texts that only exist in the Go core;
// they are merged into the catalog of the language and win over "<code>.json". The texts of
// the window are in "<code>.ui.json"; UITexts serves that set to the frontend.
package i18n

import (
	"embed"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"sync"
)

// LangEnv is the environment variable that overrides the saved language.
const LangEnv = "FORESPRINT_LANG"

// Default is the language of the source texts.
const Default = "en"

//go:embed data/*.json
var files embed.FS

// Catalog is one language.
type Catalog struct {
	Code  string            `json:"code"`
	Name  string            `json:"name"`
	Texts map[string]string `json:"texts"`
}

var (
	loadOnce sync.Once
	catalogs map[string]*Catalog
	// ui holds the texts of the window per language, from the files "<code>.ui.json".
	ui map[string]map[string]string

	mu       sync.Mutex
	override string
	saved    = func() string { return "" }
)

func load() {
	catalogs = map[string]*Catalog{}
	ui = map[string]map[string]string{}
	var extras []Catalog
	entries, err := files.ReadDir("data")
	if err != nil {
		panic("i18n: " + err.Error())
	}
	for _, entry := range entries {
		raw, err := files.ReadFile("data/" + entry.Name())
		if err != nil {
			panic("i18n: " + err.Error())
		}
		var catalog Catalog
		if err := json.Unmarshal(raw, &catalog); err != nil {
			panic("i18n: " + entry.Name() + ": " + err.Error())
		}
		if strings.HasSuffix(entry.Name(), ".ui.json") { // texts of the window, served as a set
			ui[catalog.Code] = catalog.Texts
		}
		if strings.Count(entry.Name(), ".") > 1 { // extra file: merged below
			extras = append(extras, catalog)
			continue
		}
		catalogs[catalog.Code] = &catalog
	}
	for _, extra := range extras {
		base := catalogs[extra.Code]
		if base == nil {
			panic("i18n: extra texts for the unknown language " + extra.Code)
		}
		for k, v := range extra.Texts {
			base.Texts[k] = v
		}
	}
}

// UITexts returns the texts of the window for a language: English source text to translation.
// Only texts that have a translation are in the set; the window shows the source text for the
// rest. The set comes from the file "<code>.ui.json" and is empty for English.
func UITexts(code string) map[string]string {
	loadOnce.Do(load)
	out := make(map[string]string, len(ui[code]))
	for k, v := range ui[code] {
		out[k] = v
	}
	return out
}

// Register adds translations of one language (English source text to translated text) from
// code, for packages that keep a few texts next to their code. Entries win over the files.
// Call it from an init function, before texts are translated. Prefer a data file (see the
// package comment).
func Register(code string, entries map[string]string) {
	loadOnce.Do(load)
	mu.Lock()
	defer mu.Unlock()
	c := catalogs[code]
	if c == nil {
		return
	}
	for k, v := range entries {
		c.Texts[k] = v
	}
}

// Languages returns the available language codes with their names, sorted by code.
func Languages() []Catalog {
	loadOnce.Do(load)
	out := make([]Catalog, 0, len(catalogs))
	for _, c := range catalogs {
		out = append(out, Catalog{Code: c.Code, Name: c.Name})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Code < out[j].Code })
	return out
}

// Name is the name of a language in that language ("" for an unknown code).
func Name(code string) string {
	loadOnce.Do(load)
	if c := catalogs[code]; c != nil {
		return c.Name
	}
	return ""
}

// Normalize reduces a locale such as "de_DE.UTF-8" to a known language code ("" if unknown).
func Normalize(raw string) string {
	loadOnce.Do(load)
	code := strings.ToLower(strings.TrimSpace(raw))
	if len(code) > 2 {
		code = code[:2]
	}
	if _, ok := catalogs[code]; ok {
		return code
	}
	return ""
}

// SetSaved registers where the saved language setting is read from (the user settings).
func SetSaved(f func() string) {
	mu.Lock()
	defer mu.Unlock()
	saved = f
}

// SetLanguage fixes the language for this process; "" or an unknown code goes back to
// environment and setting.
func SetLanguage(code string) {
	mu.Lock()
	defer mu.Unlock()
	override = Normalize(code)
}

// Language is the language in use: SetLanguage > FORESPRINT_LANG > saved setting > English.
func Language() string {
	mu.Lock()
	o, f := override, saved
	mu.Unlock()
	if o != "" {
		return o
	}
	for _, raw := range []string{os.Getenv(LangEnv), f()} {
		if code := Normalize(raw); code != "" {
			return code
		}
	}
	return Default
}

// T translates an English source text and fills in {name} placeholders from values
// (alternating names and values: T("Saved: {names}", "names", x)).
func T(text string, values ...any) string {
	return TIn(Language(), text, values...)
}

// TIn is T for a given language.
func TIn(lang, text string, values ...any) string {
	return translate(lang, text, false, values)
}

// P is T for the command line: rich markup in the template is removed before the values are
// filled in, so brackets in values (a team name "[x]") stay as they are.
func P(text string, values ...any) string {
	return translate(Language(), text, true, values)
}

func translate(lang, text string, plain bool, values []any) string {
	loadOnce.Do(load)
	template := text
	if c := catalogs[lang]; c != nil {
		if translated, ok := c.Texts[text]; ok {
			template = translated
		}
	}
	if plain {
		template = Plain(template)
	}
	if len(values) == 0 {
		return template // like Python: without values the text is not a format string
	}
	return Format(template, values...)
}

// Format fills in {name} and {name!r} placeholders; "{{" and "}}" are braces. A placeholder
// without value stays as it is.
func Format(template string, values ...any) string {
	args := map[string]any{}
	for i := 0; i+1 < len(values); i += 2 {
		if name, ok := values[i].(string); ok {
			args[name] = values[i+1]
		}
	}
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
			field := template[i+1 : i+end]
			name, repr := field, false
			if n, ok := strings.CutSuffix(field, "!r"); ok {
				name, repr = n, true
			}
			if v, ok := args[name]; ok {
				b.WriteString(render(v, repr))
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

// render writes a value like Python's str() (or repr() for !r) for strings and numbers.
func render(v any, repr bool) string {
	if s, ok := v.(string); ok && repr {
		return pyRepr(s)
	}
	if e, ok := v.(error); ok {
		return e.Error()
	}
	return fmt.Sprint(v)
}

// pyRepr quotes a string like Python's repr(): single quotes, unless the text has a single
// and no double quote.
func pyRepr(s string) string {
	quote := byte('\'')
	if strings.ContainsRune(s, '\'') && !strings.ContainsRune(s, '"') {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case r == rune(quote):
			b.WriteString(`\` + string(r))
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}
