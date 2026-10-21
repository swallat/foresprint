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
