package msg_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/msg"
)

func TestFormat(t *testing.T) {
	cases := []struct {
		template string
		values   msg.Values
		want     string
	}{
		{"plain", nil, "plain"},
		{"{a} and {b}", msg.Values{"a": "x", "b": 3}, "x and 3"},
		{"{{literal}} {a}", msg.Values{"a": "1"}, "{literal} 1"},
		{"{missing} stays", msg.Values{"a": "1"}, "{missing} stays"},
		{"{a}{a}", msg.Values{"a": "ab"}, "abab"},
		{"open {", msg.Values{}, "open {"},
		{"value {x}", msg.Values{"x": "{a}"}, "value {a}"},
	}
	for _, c := range cases {
		if got := msg.Format(c.template, c.values); got != c.want {
			t.Errorf("Format(%q) = %q, want %q", c.template, got, c.want)
		}
	}
}

func TestLang(t *testing.T) {
	de := msg.Lang{Code: "de", Catalog: map[string]string{"Hello {name}": "Hallo {name}"}}
	if got := de.T("Hello {name}", msg.Values{"name": "Ann"}); got != "Hallo Ann" {
		t.Errorf("German: %q", got)
	}
	if got := de.T("Untranslated {name}", msg.Values{"name": "Ann"}); got != "Untranslated Ann" {
		t.Errorf("missing text stays English: %q", got)
	}
	if got := msg.English.T("Hello {name}", msg.Values{"name": "Ann"}); got != "Hello Ann" {
		t.Errorf("English: %q", got)
	}
	// Without values the text is returned as it is, braces included (like t(text) in Python).
	if got := msg.English.T("keep {x}", nil); got != "keep {x}" {
		t.Errorf("no values: %q", got)
	}
	if !(msg.Lang{}).IsEnglish() {
		t.Error("the zero language is English")
	}
}
