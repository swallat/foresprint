package yamlmerge_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/yamlmerge"
	"github.com/swallat/foresprint/internal/yamlx"
)

func load(t *testing.T, text string) any {
	t.Helper()
	v, err := yamlx.Load(text)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

// The merge works on trees loaded by the real reader and the result is written by the real writer.
func TestMergesLoadedYAML(t *testing.T) {
	base := load(t, "start: 2026-01-05\nvelocity: 10\nprognoses:\n- at: 2026-01-05 09:00:00+00:00\n  v: 1\n")
	ours := load(t, "start: 2026-01-06\nvelocity: 10\nprognoses:\n- at: 2026-01-05 09:00:00+00:00\n  v: 1\n- at: 2026-01-06 09:00:00+00:00\n  v: 2\n")
	theirs := load(t, "start: 2026-01-05\nvelocity: 12\nprognoses:\n- at: 2026-01-05 09:00:00+00:00\n  v: 1\n- at: 2026-01-07 09:00:00+00:00\n  v: 3\n")
	merged, conflicts := yamlmerge.Merge3(base, ours, theirs, nil)
	if len(conflicts) != 0 {
		t.Fatalf("conflicts: %v", conflicts)
	}
	got, err := yamlx.Dump(merged)
	if err != nil {
		t.Fatal(err)
	}
	want := "start: 2026-01-06\nvelocity: 12\nprognoses:\n- at: 2026-01-05 09:00:00+00:00\n  v: 1\n- at: 2026-01-06 09:00:00+00:00\n  v: 2\n- at: 2026-01-07 09:00:00+00:00\n  v: 3\n"
	if got != want {
		t.Fatalf("got:\n%s\nwant:\n%s", got, want)
	}
}

func TestChangesListValuesAndApplyPutsThemBack(t *testing.T) {
	before := load(t, "velocity: 10\npeople:\n- id: a\n  days: 5\n- id: b\n  days: 4\nprognoses:\n- at: 2026-01-05 09:00:00+00:00\n  v: 1\n")
	after := load(t, "velocity: 12\npeople:\n- id: a\n  days: 6\n- id: b\n  days: 4\n- id: c\n  days: 3\nprognoses:\n- at: 2026-01-05 09:00:00+00:00\n  v: 1\n- at: 2026-01-06 09:00:00+00:00\n  v: 2\n")
	changes := yamlmerge.Changes(before, after)
	var labels []string
	for _, c := range changes {
		labels = append(labels, c.Label())
	}
	want := []string{"velocity", "people.[a].days", "people.[c]", "prognoses.[2026-01-06T09:00:00]"}
	if len(labels) != len(want) {
		t.Fatalf("labels = %v", labels)
	}
	for i := range want {
		if labels[i] != want[i] {
			t.Fatalf("labels = %v, want %v", labels, want)
		}
	}
	tree := after
	for _, c := range changes {
		var ok bool
		if tree, ok = yamlmerge.Apply(tree, c.Path, c.Before); !ok {
			t.Fatalf("apply %s", c.Label())
		}
	}
	if left := yamlmerge.Changes(before, tree); len(left) != 0 {
		t.Fatalf("still different: %v", left)
	}
}

func TestACustomChoiceDecidesAConflict(t *testing.T) {
	base := load(t, "velocity: 10\n")
	ours := load(t, "velocity: 8\n")
	theirs := load(t, "velocity: 12\n")
	choices := yamlmerge.Choices{}
	choices.Choose(yamlmerge.Path{"velocity"}, yamlmerge.CustomChoice("11"))
	merged, conflicts := yamlmerge.Merge3(base, ours, theirs, choices)
	if len(conflicts) != 0 {
		t.Fatalf("conflicts: %v", conflicts)
	}
	if got, _ := yamlx.Dump(merged); got != "velocity: 11\n" {
		t.Fatalf("merged = %q", got)
	}
}
