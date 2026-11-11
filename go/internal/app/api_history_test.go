package app

import (
	"os"
	"path/filepath"
	"testing"
)

func histAPI(t *testing.T) (*API, string) {
	t.Helper()
	dir := t.TempDir()
	return New("test", dir), dir
}

func write(t *testing.T, p, s string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(s), 0o644); err != nil {
		t.Fatal(err)
	}
}

func read(t *testing.T, p string) string {
	t.Helper()
	b, err := os.ReadFile(p)
	if err != nil {
		return "<missing>"
	}
	return string(b)
}

func step(a *API, f func()) {
	tok := a.HistoryBegin()
	f()
	a.HistoryEnd(tok)
}

func TestHistoryUndoRedo(t *testing.T) {
	a, dir := histAPI(t)
	p := filepath.Join(dir, "teams", "x", "a.yaml")
	n := filepath.Join(dir, "new.yaml")
	write(t, p, "v1")
	step(a, func() { write(t, p, "v2"); write(t, n, "n") })
	step(a, func() { write(t, p, "v3") })
	if !a.HistoryInfo().CanUndo || a.HistoryInfo().CanRedo {
		t.Fatal("state after two steps")
	}
	if r := a.HistoryUndo(); !r.OK || read(t, p) != "v2" {
		t.Fatalf("undo 1: %+v %s", r, read(t, p))
	}
	if r := a.HistoryUndo(); !r.OK || read(t, p) != "v1" || read(t, n) != "<missing>" {
		t.Fatalf("undo 2: %+v", r)
	}
	if a.HistoryUndo().OK {
		t.Fatal("undo past the first step")
	}
	if r := a.HistoryRedo(); !r.OK || read(t, p) != "v2" || read(t, n) != "n" {
		t.Fatalf("redo: %+v", r)
	}
	// A new step drops the redo list.
	step(a, func() { write(t, p, "v9") })
	if a.HistoryInfo().CanRedo {
		t.Fatal("redo survived a new step")
	}
}

func TestHistoryRefusesAfterOutsideChange(t *testing.T) {
	a, dir := histAPI(t)
	p := filepath.Join(dir, "a.yaml")
	write(t, p, "v1")
	step(a, func() { write(t, p, "v2") })
	write(t, p, "other")
	if r := a.HistoryUndo(); r.OK || read(t, p) != "other" || a.HistoryInfo().CanUndo {
		t.Fatalf("undo must refuse and clear: %+v", r)
	}
}

func TestHistoryNoChangeNoStep(t *testing.T) {
	a, dir := histAPI(t)
	write(t, filepath.Join(dir, "a.yaml"), "v1")
	step(a, func() {})
	write(t, filepath.Join(dir, ".git", "x"), "1")
	if a.HistoryInfo().CanUndo {
		t.Fatal("empty step recorded")
	}
	a.HistoryClear()
}

func TestHistoryOverlapAndEmptyFolders(t *testing.T) {
	a, dir := histAPI(t)
	p := filepath.Join(dir, "x", "deep", "a.yaml")
	q := filepath.Join(dir, "b.yaml")
	write(t, q, "1")
	t1 := a.HistoryBegin()
	t2 := a.HistoryBegin()
	write(t, q, "2")
	a.HistoryEnd(t1)
	a.HistoryEnd(t2)
	if a.HistoryInfo().CanUndo {
		t.Fatal("overlapping steps must not be recorded")
	}
	step(a, func() { write(t, p, "n") })
	if r := a.HistoryUndo(); !r.OK {
		t.Fatal(r)
	}
	if _, err := os.Stat(filepath.Join(dir, "x")); err == nil {
		t.Fatal("empty folder left behind")
	}
}
