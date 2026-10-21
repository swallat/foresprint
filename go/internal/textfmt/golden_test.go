package textfmt_test

import (
	"fmt"
	"testing"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/textfmt"
)

type reference struct {
	Texts []struct {
		Text   string `json:"text"`
		MdCode string `json:"md_code"`
		Blank  string `json:"blank"`
	} `json:"texts"`
	Numbers []struct {
		Lang    string             `json:"lang"`
		Rows    []map[string]any   `json:"rows"`
		FTENote string             `json:"fte_note"`
		Notes   map[string]*string `json:"notes"`
	} `json:"numbers"`
}

func TestExternalTextMatchesPython(t *testing.T) {
	var ref reference
	golden.Load(t, &ref, "textfmt", "cases.json")
	for _, c := range ref.Texts {
		if got := textfmt.MdCode(c.Text); got != c.MdCode {
			t.Errorf("MdCode(%q) = %q, Python %q", c.Text, got, c.MdCode)
		}
		if got := textfmt.BlankControls(c.Text); got != c.Blank {
			t.Errorf("BlankControls(%q) = %q, Python %q", c.Text, got, c.Blank)
		}
	}
}

func num(v any) float64 {
	n, _ := v.(interface{ Float64() (float64, error) }).Float64()
	return n
}

func TestNumbersAndNotesMatchPython(t *testing.T) {
	var ref reference
	golden.Load(t, &ref, "textfmt", "cases.json")
	langs := map[string]string{"en": "en", "de": coretest.German(t)}
	for _, block := range ref.Numbers {
		l := langs[block.Lang]
		for _, row := range block.Rows {
			x := num(row["value"])
			if got := textfmt.Pct(l, x); got != row["pct"] {
				t.Errorf("%s Pct(%v) = %q, Python %q", block.Lang, x, got, row["pct"])
			}
			if got := textfmt.FmtPtr(l, nil, 1); got != row["none"] {
				t.Errorf("%s FmtPtr(nil) = %q, Python %q", block.Lang, got, row["none"])
			}
			for digits := 0; digits <= 4; digits++ {
				if got := textfmt.Fmt(l, x, digits, ""); got != row[fmt.Sprintf("fmt%d", digits)] {
					t.Errorf("%s Fmt(%v, %d) = %q, Python %q", block.Lang, x, digits, got, row[fmt.Sprintf("fmt%d", digits)])
				}
				if got := textfmt.FmtCapacity(l, &x, digits); got != row[fmt.Sprintf("cap%d", digits)] {
					t.Errorf("%s FmtCapacity(%v, %d) = %q, Python %q", block.Lang, x, digits, got, row[fmt.Sprintf("cap%d", digits)])
				}
			}
		}

		one := &capacity.AbsenceHistory{Derived: []string{"2026.20"}}
		two := &capacity.AbsenceHistory{Derived: []string{"2026.20", "x`y"}}
		check := func(name string, got string, ok bool) {
			t.Helper()
			want := block.Notes[name]
			switch {
			case want == nil && ok:
				t.Errorf("%s %s: %q, Python has none", block.Lang, name, got)
			case want != nil && (!ok || got != *want):
				t.Errorf("%s %s:\n got %q (%v)\nwant %q", block.Lang, name, got, ok, *want)
			}
		}
		g, ok := textfmt.AbsenceDerivedNote(l, one, false, true, 0)
		check("one", g, ok)
		g, ok = textfmt.AbsenceDerivedNote(l, one, true, true, 4)
		check("one_detailed", g, ok)
		g, ok = textfmt.AbsenceDerivedNote(l, two, false, false, 6)
		check("two_plain", g, ok)
		g, ok = textfmt.AbsenceDerivedNote(l, two, true, true, 6)
		check("two_detailed", g, ok)
		g, ok = textfmt.AbsenceDerivedNote(l, &capacity.AbsenceHistory{}, false, true, 0)
		check("none", g, ok)
		g, ok = textfmt.AbsenceDerivedHint(l, one)
		check("hint_one", g, ok)
		g, ok = textfmt.AbsenceDerivedHint(l, two)
		check("hint_two", g, ok)
		g, ok = textfmt.AbsenceDerivedHint(l, nil)
		check("hint_none", g, ok)
	}
}
