package difflib

import (
	"testing"

	"github.com/swallat/foresprint/internal/golden"
)

func TestUnifiedDiffMatchesPython(t *testing.T) {
	var ref struct {
		Cases []struct {
			Name string   `json:"name"`
			A    []string `json:"a"`
			B    []string `json:"b"`
			Diff []string `json:"diff"`
		} `json:"cases"`
	}
	golden.Load(t, &ref, "difflib", "unified.json")
	if len(ref.Cases) < 40 {
		t.Fatalf("only %d cases", len(ref.Cases))
	}
	for _, c := range ref.Cases {
		got := UnifiedDiff(c.A, c.B, c.Name+" (old)", c.Name+" (new)", 2)
		if got == nil {
			got = []string{}
		}
		want := c.Diff
		if want == nil {
			want = []string{}
		}
		if Join(got) != Join(want) {
			t.Errorf("%s:\n got:\n%s\nwant:\n%s", c.Name, Join(got), Join(want))
		}
	}
}
