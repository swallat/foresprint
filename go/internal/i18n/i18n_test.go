package i18n

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"

	"errors"
	"regexp"
	"sort"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
)

func TestTranslate(t *testing.T) {
	if got := TIn("de", "Feature areas"); got != "Funktionsbereiche" {
		t.Errorf("de = %q", got)
	}
	if got := TIn("en", "Feature areas"); got != "Feature areas" {
		t.Errorf("en = %q", got)
	}
	if got := TIn("de", "no such text {x}", "x", 3); got != "no such text 3" {
		t.Errorf("fallback = %q", got)
	}
	if got := TIn("de", "Minutes: {kind} ({count})", "kind", "Review", "count", 2); got != "Protokolle: Review (2)" {
		t.Errorf("de format = %q", got)
	}
}

func TestFormat(t *testing.T) {
	cases := []struct{ in, want string }{
		{"a {{b}} {x}", "a {b} 7"},
		{"{missing} {x}", "{missing} 7"},
		{"{name!r}", "'it'"},
		{"{err}", "boom"},
		{"open {", "open {"},
	}
	for _, c := range cases {
		got := Format(c.in, "x", 7, "name", "it", "err", errors.New("boom"))
		if got != c.want {
			t.Errorf("Format(%q) = %q, want %q", c.in, got, c.want)
		}
	}
	if got := Format("{s!r}", "s", `it's`); got != `"it's"` {
		t.Errorf("repr = %s", got)
	}
}

func TestLanguageOrder(t *testing.T) {
	t.Setenv(LangEnv, "")
	SetSaved(func() string { return "de" })
	t.Cleanup(func() { SetSaved(func() string { return "" }); SetLanguage("") })
	if Language() != "de" {
		t.Errorf("saved: %s", Language())
	}
	t.Setenv(LangEnv, "en_US.UTF-8")
	if Language() != "en" {
		t.Errorf("env over saved: %s", Language())
	}
	SetLanguage("de")
	if Language() != "de" {
		t.Errorf("override: %s", Language())
	}
	SetLanguage("xx")
	t.Setenv(LangEnv, "zz")
	SetSaved(func() string { return "" })
	if Language() != Default {
		t.Errorf("default: %s", Language())
	}
}

func TestLanguages(t *testing.T) {
	var codes []string
	for _, l := range Languages() {
		codes = append(codes, l.Code)
	}
	if !sort.StringsAreSorted(codes) || len(codes) < 2 || Name("de") != "Deutsch" || Name("en") != "English" {
		t.Errorf("languages = %v", codes)
	}
}

// Every placeholder of a source text must appear in its translation and the other way round.
func TestPlaceholdersMatch(t *testing.T) {
	loadOnce.Do(load)
	re := regexp.MustCompile(`\{[A-Za-z_]\w*(!r)?\}`)
	for code, c := range catalogs {
		for src, dst := range c.Texts {
			a, b := map[string]int{}, map[string]int{}
			for _, m := range re.FindAllString(src, -1) {
				a[m]++
			}
			for _, m := range re.FindAllString(dst, -1) {
				b[m]++
			}
			for k, n := range a {
				if b[k] != n {
					t.Errorf("%s: placeholder %s differs in %q", code, k, src)
				}
			}
			for k := range b {
				if a[k] == 0 {
					t.Errorf("%s: extra placeholder %s in %q", code, k, dst)
				}
			}
		}
	}
}

func TestPlainKeepsValues(t *testing.T) {
	if got := TIn("en", "[bold]{x}[/bold]", "x", "[red]"); got != "[bold][red][/bold]" {
		t.Errorf("T = %q", got)
	}
	SetLanguage("en")
	t.Cleanup(func() { SetLanguage("") })
	if got := P("[bold]{x}[/bold]", "x", "[red]"); got != "[red]" {
		t.Errorf("P = %q", got)
	}
}

func TestPlain(t *testing.T) {
	cases := map[string]string{
		"[bold]x[/bold] y":       "x y",
		`\[red] literal`:         "[red] literal",
		"[green]ok[/]":           "ok",
		"list [1, 2] stays":      "list [1, 2] stays",
		"[bold red]a[/bold red]": "a",
	}
	for in, want := range cases {
		if got := Plain(in); got != want {
			t.Errorf("Plain(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestGolden(t *testing.T) {
	var ref struct {
		Count  int               `json:"count"`
		Digest map[string]string `json:"digest"`
		Sample []struct{ Text, De, En string }
	}
	golden.Load(t, &ref, "i18n", "catalog.json")
	raw, err := files.ReadFile("data/de.json") // the texts of the Python core, not the extras
	if err != nil {
		t.Fatal(err)
	}
	var german Catalog
	if err := json.Unmarshal(raw, &german); err != nil {
		t.Fatal(err)
	}
	keys := make([]string, 0, len(german.Texts))
	for k := range german.Texts {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	if len(keys) != ref.Count {
		t.Fatalf("catalog has %d texts, reference %d", len(keys), ref.Count)
	}
	placeholder := regexp.MustCompile(`\{(\w+)(!r)?\}`)
	fill := func(lang, text string) string {
		var values []any
		for _, m := range placeholder.FindAllStringSubmatch(text, -1) {
			values = append(values, m[1], "<"+m[1]+">")
		}
		return TIn(lang, text, values...)
	}
	for _, lang := range []string{"de", "en"} {
		texts := make([]string, len(keys))
		for i, k := range keys {
			texts[i] = fill(lang, k)
		}
		sum := sha256.Sum256([]byte(strings.Join(texts, "\n")))
		if got := hex.EncodeToString(sum[:]); got != ref.Digest[lang] {
			t.Errorf("%s: digest of all texts differs from the Python reference", lang)
		}
	}
	for _, s := range ref.Sample {
		if got := fill("de", s.Text); got != s.De {
			t.Errorf("de %q = %q, want %q", s.Text, got, s.De)
		}
		if got := fill("en", s.Text); got != s.En {
			t.Errorf("en %q = %q, want %q", s.Text, got, s.En)
		}
	}
}

func TestRegister(t *testing.T) {
	Register("de", map[string]string{"Registered {n}": "Eingetragen {n}"})
	if got := TIn("de", "Registered {n}", "n", 2); got != "Eingetragen 2" {
		t.Errorf("got %q", got)
	}
	Register("xx", map[string]string{"a": "b"}) // unknown language: ignored
}

func TestTexts(t *testing.T) {
	texts := Texts("de")
	if texts["Aborted."] != "Abgebrochen." {
		t.Errorf("Aborted. = %q", texts["Aborted."])
	}
	texts["Aborted."] = "changed"
	if Texts("de")["Aborted."] != "Abgebrochen." {
		t.Error("Texts returns the catalog itself, not a copy")
	}
	if Texts("xx") != nil {
		t.Error("unknown language")
	}
}
