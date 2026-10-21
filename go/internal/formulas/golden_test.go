package formulas_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/formulas"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/msg"
)

// The general formulas equal the Python texts.
func TestGeneralMatchesPython(t *testing.T) {
	var want map[string]string
	golden.Load(t, &want, "formulas", "general.json")
	f := formulas.New(msg.English)
	if len(want) != len(formulas.GeneralKeys) {
		t.Fatalf("%d formulas in Python, %d keys here", len(want), len(formulas.GeneralKeys))
	}
	for _, key := range formulas.GeneralKeys {
		if got := f.General(key); got != want[key] {
			t.Errorf("%s: %q, Python %q", key, got, want[key])
		}
	}
}

// Every step and explanation of every sprint of every golden case equals the Python text, in
// English: the formula, the plugged-in numbers, the notes.
func TestTextsMatchPython(t *testing.T) {
	f := formulas.New(msg.English)
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			var ref struct {
				Entries []struct {
					Sprint           string `json:"sprint"`
					Steps            any    `json:"steps"`
					StepsCodeNoNote  any    `json:"steps_code_no_note"`
					Plain            string `json:"plain"`
					PlainNoNote      string `json:"plain_no_note"`
					Structured       any    `json:"structured"`
					StructuredNoNote any    `json:"structured_no_note"`
				} `json:"entries"`
			}
			golden.Load(t, &ref, "formulas", c.Name+".json")
			fc, err := forecast.Build(coretest.Load(t, c), coretest.Today(t, c))
			if err != nil {
				t.Fatal(err)
			}
			if len(ref.Entries) != len(fc.Entries) {
				t.Fatalf("%d entries, Python %d", len(fc.Entries), len(ref.Entries))
			}
			for i, want := range ref.Entries {
				e := &fc.Entries[i]
				if e.Sprint.ID != want.Sprint {
					t.Fatalf("entry %d is %s, Python %s", i, e.Sprint.ID, want.Sprint)
				}
				steps, err := f.Steps(fc, e, false, true)
				if err != nil {
					t.Fatal(err)
				}
				golden.Compare(t, want.Steps, coretest.JSON(t, steps))
				steps, err = f.Steps(fc, e, true, false)
				if err != nil {
					t.Fatal(err)
				}
				golden.Compare(t, want.StepsCodeNoNote, coretest.JSON(t, steps))
				if got := f.PlainExplanation(fc, e, true); got != want.Plain {
					t.Errorf("%s plain:\n got %q\nwant %q", want.Sprint, got, want.Plain)
				}
				if got := f.PlainExplanation(fc, e, false); got != want.PlainNoNote {
					t.Errorf("%s plain without note:\n got %q\nwant %q", want.Sprint, got, want.PlainNoNote)
				}
				golden.Compare(t, tuples(want.Structured), coretest.JSON(t, f.StructuredExplanation(fc, e, true)))
				golden.Compare(t, tuples(want.StructuredNoNote), coretest.JSON(t, f.StructuredExplanation(fc, e, false)))
			}
		})
	}
}

// tuples turns the inputs of the Python explanation (pairs as lists) into the objects of the Go
// type.
func tuples(v any) any {
	m, ok := v.(map[string]any)
	if !ok {
		return v
	}
	inputs, _ := m["inputs"].([]any)
	pairs := []any{}
	for _, in := range inputs {
		if p, ok := in.([]any); ok && len(p) == 2 {
			pairs = append(pairs, map[string]any{"label": p[0], "value": p[1]})
		}
	}
	m["inputs"] = pairs
	return m
}

func TestStepText(t *testing.T) {
	s := formulas.Step{Formula: "a", Calculation: "b"}
	if got := s.Text(); got != "a\n\nb" {
		t.Errorf("%q", got)
	}
}

// The German texts equal the Python ones when the same part of the catalog translates them: a
// source text that differs by one character would show up here as an untranslated text.
func TestGermanTextsMatchPython(t *testing.T) {
	german := coretest.German(t)
	f := formulas.New(german)
	var general map[string]string
	golden.Load(t, &general, "formulas-de", "general.json")
	for _, key := range formulas.GeneralKeys {
		if got := f.General(key); got != general[key] {
			t.Errorf("%s: %q, Python %q", key, got, general[key])
		}
	}
	for _, name := range []string{"demo", "people-days", "thin", "trend-classic"} {
		var c golden.Case
		for _, k := range golden.Cases(t) {
			if k.Name == name {
				c = k
			}
		}
		if c.Name == "" {
			t.Fatalf("no case %s", name)
		}
		t.Run(name, func(t *testing.T) {
			var ref struct {
				Entries []struct {
					Sprint     string `json:"sprint"`
					Steps      any    `json:"steps"`
					Plain      string `json:"plain"`
					Structured any    `json:"structured"`
				} `json:"entries"`
			}
			golden.Load(t, &ref, "formulas-de", name+".json")
			fc, err := forecast.Build(coretest.Load(t, c), coretest.Today(t, c))
			if err != nil {
				t.Fatal(err)
			}
			for i, want := range ref.Entries {
				e := &fc.Entries[i]
				steps, err := f.Steps(fc, e, false, true)
				if err != nil {
					t.Fatal(err)
				}
				golden.Compare(t, want.Steps, coretest.JSON(t, steps))
				if got := f.PlainExplanation(fc, e, true); got != want.Plain {
					t.Errorf("%s plain:\n got %q\nwant %q", want.Sprint, got, want.Plain)
				}
				golden.Compare(t, tuples(want.Structured), coretest.JSON(t, f.StructuredExplanation(fc, e, true)))
			}
		})
	}
}

func TestFTEChangeNote(t *testing.T) {
	var ref struct {
		Numbers []struct {
			Lang    string `json:"lang"`
			FTENote string `json:"fte_note"`
		} `json:"numbers"`
	}
	golden.Load(t, &ref, "textfmt", "cases.json")
	langs := map[string]msg.Lang{"en": msg.English, "de": coretest.German(t)}
	for _, n := range ref.Numbers {
		got := formulas.New(langs[n.Lang]).FTEChangeNote([]string{"Ben", "`Cem`"})
		if got != n.FTENote {
			t.Errorf("%s: %q, Python %q", n.Lang, got, n.FTENote)
		}
	}
}
