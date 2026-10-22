package excel

import (
	"testing"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/i18n"
)

// Every golden case is exported and read back; the workbook equals what the Python version
// writes: cells, formulas, cached results, looks, widths, panes, charts, names, properties.
func TestWorkbookMatchesPython(t *testing.T) {
	i18n.SetLanguage("en")
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			var want any
			golden.Load(t, &want, "excel", c.Name+".json")
			fc, err := forecast.Build(coretest.Load(t, c), coretest.Today(t, c))
			if err != nil {
				t.Fatal(err)
			}
			data, err := Build(fc)
			if err != nil {
				t.Fatal(err)
			}
			golden.Compare(t, want, dumpWorkbook(t, data))
		})
	}
}

// The warnings about sprint ids the import would refuse equal the Python texts.
func TestUnsafeSprintIDsMatchPython(t *testing.T) {
	i18n.SetLanguage("en")
	var want []struct {
		Case     string   `json:"case"`
		Warnings []string `json:"warnings"`
	}
	golden.Load(t, &want, "excel", "warnings.json")
	cases := golden.Cases(t)
	if len(want) != len(cases) {
		t.Fatalf("%d cases, Python %d", len(cases), len(want))
	}
	for i, c := range cases {
		got := ImportUnsafeSprintIDs(coretest.Load(t, c))
		if got == nil {
			got = []string{}
		}
		golden.Compare(t, want[i].Warnings, got)
		if want[i].Case != c.Name {
			t.Fatalf("case %d is %s, Python %s", i, c.Name, want[i].Case)
		}
	}
}
