package report

import (
	"fmt"
	"os"
	"testing"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
)

func TestRenderGolden(t *testing.T) {
	i18n.SetLanguage("en")
	t.Cleanup(func() { i18n.SetLanguage("") })
	for _, c := range golden.Cases(t) {
		data, err := storage.NewRepository(golden.RepoRoot(t) + "/" + c.Root).Load(c.Team)
		if err != nil {
			t.Fatalf("%s: %v", c.Name, err)
		}
		data.PhasesByDate = true
		fc, err := forecast.Build(data, coretest.Today(t, c))
		if err != nil {
			t.Fatalf("%s: %v", c.Name, err)
		}
		for _, h := range []int{10, 3, 0} {
			t.Run(fmt.Sprintf("%s-h%d", c.Name, h), func(t *testing.T) {
				raw, err := os.ReadFile(golden.Path(t, "report", fmt.Sprintf("%s-h%d.md", c.Name, h)))
				if err != nil {
					t.Skip("no reference")
				}
				got, err := Render(fc, h)
				if err != nil {
					t.Fatal(err)
				}
				if want := string(raw); got != want {
					t.Errorf("report differs from the Python reference:\n%s", firstDiff(want, got))
				}
			})
		}
	}
}

func firstDiff(want, got string) string {
	w, g := []rune(want), []rune(got)
	i := 0
	for i < len(w) && i < len(g) && w[i] == g[i] {
		i++
	}
	cut := func(r []rune) string { return string(r[max(0, i-80):min(len(r), i+120)]) }
	return fmt.Sprintf("at offset %d\n want …%q\n got  …%q", i, cut(w), cut(g))
}

func TestHelpersGolden(t *testing.T) {
	i18n.SetLanguage("en")
	t.Cleanup(func() { i18n.SetLanguage("") })
	var ref struct {
		Fmt []struct {
			Value  *float64 `json:"value"`
			Digits int      `json:"digits"`
			Suffix string   `json:"suffix"`
			Text   string   `json:"text"`
		} `json:"fmt"`
		FmtCapacity []struct {
			Value  *float64 `json:"value"`
			Digits int      `json:"digits"`
			Text   string   `json:"text"`
		} `json:"fmt_capacity"`
		Pct []struct {
			Value *float64 `json:"value"`
			Text  string   `json:"text"`
		} `json:"pct"`
		WindowHint []struct {
			Window, Samples, Available int
			Simulation                 bool
			Text                       string
		} `json:"window_hint"`
		CompletionNote []struct {
			Samples int
			Text    *string
		} `json:"completion_note"`
		Remedy []struct {
			Window int
			Text   string
		} `json:"absence_derived_remedy"`
		CLIRemedy []struct {
			Window int
			Text   string
		} `json:"absence_derived_cli_remedy"`
	}
	golden.Load(t, &ref, "report", "helpers.json")
	for _, c := range ref.Fmt {
		if got := Fmt(c.Value, c.Digits, c.Suffix); got != c.Text {
			t.Errorf("Fmt(%v, %d, %q) = %q, want %q", c.Value, c.Digits, c.Suffix, got, c.Text)
		}
	}
	for _, c := range ref.FmtCapacity {
		if got := FmtCapacity(c.Value, c.Digits); got != c.Text {
			t.Errorf("FmtCapacity(%v, %d) = %q, want %q", c.Value, c.Digits, got, c.Text)
		}
	}
	for _, c := range ref.Pct {
		if got := Pct(c.Value); got != c.Text {
			t.Errorf("Pct(%v) = %q, want %q", c.Value, got, c.Text)
		}
	}
	for _, c := range ref.WindowHint {
		if got := WindowHint(c.Window, c.Samples, c.Available, c.Simulation); got != c.Text {
			t.Errorf("WindowHint(%d,%d,%d,%v) = %q, want %q", c.Window, c.Samples, c.Available, c.Simulation, got, c.Text)
		}
	}
	for _, c := range ref.CompletionNote {
		want := ""
		if c.Text != nil {
			want = *c.Text
		}
		if got := CompletionNote(c.Samples); got != want {
			t.Errorf("CompletionNote(%d) = %q, want %q", c.Samples, got, want)
		}
	}
	for _, c := range ref.Remedy {
		if got := AbsenceDerivedRemedy(c.Window); got != c.Text {
			t.Errorf("AbsenceDerivedRemedy(%d) = %q", c.Window, got)
		}
	}
	for _, c := range ref.CLIRemedy {
		if got := AbsenceDerivedCLIRemedy(c.Window, "team-a"); got != c.Text {
			t.Errorf("AbsenceDerivedCLIRemedy(%d) = %q", c.Window, got)
		}
	}
}
