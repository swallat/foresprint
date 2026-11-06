package sharedfolder

import (
	"errors"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestLockExcludesAndExpires(t *testing.T) {
	root := t.TempDir()
	var n atomic.Int64
	count, max := 0, 0
	var mu sync.Mutex
	var wg sync.WaitGroup
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			h, err := Acquire(root, "p", "h", 10*time.Second, time.Now)
			if err != nil {
				t.Error(err)
				return
			}
			mu.Lock()
			count++
			if count > max {
				max = count
			}
			mu.Unlock()
			time.Sleep(5 * time.Millisecond)
			n.Add(1)
			mu.Lock()
			count--
			mu.Unlock()
			h.Release()
		}()
	}
	wg.Wait()
	if max != 1 || n.Load() != 6 {
		t.Fatalf("max holders %d, done %d", max, n.Load())
	}
	// A held lock is reported with its owner after the wait.
	h1, _ := Acquire(root, "anna", "h", time.Second, time.Now)
	_, err := Acquire(root, "ben", "h", 50*time.Millisecond, time.Now)
	var h *Held
	if !errors.As(err, &h) || h.By.Owner != "anna" {
		t.Fatalf("got %v", err)
	}
	h1.Release()
	// An expired lock is taken over.
	past := time.Now().Add(-2 * LockTTL)
	if _, err := Acquire(root, "dead", "h", time.Second, func() time.Time { return past }); err != nil {
		t.Fatal(err)
	}
	if _, err := Acquire(root, "ben", "h", time.Second, time.Now); err != nil {
		t.Fatalf("expired lock not taken over: %v", err)
	}
}

func TestReleaseKeepsForeignLock(t *testing.T) {
	root := t.TempDir()
	a, _ := Acquire(root, "a", "h", time.Second, time.Now)
	must(t, os.Remove(LockPath(root)))
	b, _ := Acquire(root, "b", "h", time.Second, time.Now)
	a.Release() // must not remove b's lock
	if a.Renew(time.Now) != ErrLockLost {
		t.Fatal("renew of a lost lock must fail")
	}
	if l, ok := ReadLock(root); !ok || l.Owner != "b" {
		t.Fatal("lock of b was removed")
	}
	if err := b.Renew(time.Now); err != nil {
		t.Fatal(err)
	}
	b.Release()
}

func TestWriteFileAtomic(t *testing.T) {
	p := filepath.Join(t.TempDir(), "x", "f.yaml")
	if err := WriteFile(p, []byte("a: 1\n"), time.Second); err != nil {
		t.Fatal(err)
	}
	if err := WriteFile(p, []byte("a: 2\n"), time.Second); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(p); string(b) != "a: 2\n" {
		t.Fatal(string(b))
	}
	if m, _ := filepath.Glob(filepath.Join(filepath.Dir(p), "*.tmp")); len(m) != 0 {
		t.Fatalf("temp files left: %v", m)
	}
	if s, _ := SumFile(filepath.Join(filepath.Dir(p), "missing")); s != "" {
		t.Fatal("missing file has a sum")
	}
}

func TestJournal(t *testing.T) {
	root := t.TempDir()
	t0 := time.Date(2026, 11, 6, 10, 0, 0, 0, time.UTC)
	must(t, Append(root, Entry{ID: "1", Who: "Anna Müller", Time: t0, Summary: "a"}))
	must(t, Append(root, Entry{ID: "2", Who: "Ben", Time: t0.Add(time.Hour), Summary: "b", Files: map[string]Change{"t/x.yaml": {Before: "1", After: "2"}}}))
	must(t, os.WriteFile(filepath.Join(journalDir(root), "Ben.jsonl"), append(mustRead(t, filepath.Join(journalDir(root), "Ben.jsonl")), []byte("{half\n")...), 0o644))
	got, err := ReadJournal(root)
	if err != nil || len(got) != 2 || got[0].ID != "2" {
		t.Fatalf("%v %+v", err, got)
	}
	if PersonFile("../Anna/x") != "Anna_x.jsonl" {
		t.Fatal(PersonFile("../Anna/x"))
	}
}

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func mustRead(t *testing.T, p string) []byte {
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestSnapshots(t *testing.T) {
	root := t.TempDir()
	put := func(rel, c string) {
		must(t, WriteFile(filepath.Join(root, filepath.FromSlash(rel)), []byte(c), time.Second))
	}
	data := func(rel string) bool { return len(rel) > 6 && rel[:6] == "teams/" }
	put("teams/a/p.yaml", "v1")
	d1 := time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC)
	if err := Snapshot(root, []string{"teams/a/p.yaml"}, d1, data); err != nil {
		t.Fatal(err)
	}
	put("teams/a/p.yaml", "v2")
	// Same day: the oldest state of the day stays.
	must(t, Snapshot(root, []string{"teams/a/p.yaml"}, d1.Add(time.Hour), data))
	if b, ok := SnapshotFile(root, "teams/a/p.yaml", "2026-01-01"); !ok || string(b) != "v1" {
		t.Fatalf("%q %v", b, ok)
	}
	if len(snapshotNames(root, true)) != 1 {
		t.Fatal("first save should store a full snapshot")
	}
	// 40 days later: pruned to 30 daily ones, one more full after a week.
	for i := 1; i <= 40; i++ {
		d := d1.AddDate(0, 0, i)
		put("teams/a/p.yaml", d.Format("v-2006-01-02"))
		if err := Snapshot(root, []string{"teams/a/p.yaml"}, d, data); err != nil {
			t.Fatal(err)
		}
	}
	if n := len(snapshotNames(root, false)); n != KeepDays {
		t.Fatalf("daily snapshots %d", n)
	}
	if n := len(snapshotNames(root, true)); n < 5 || n > KeepFulls {
		t.Fatalf("full snapshots %d", n)
	}
}

func TestConflictCopies(t *testing.T) {
	yes := map[string]string{
		"teams/a/p (Anna's conflicted copy 2026-11-06).yaml":              "teams/a/p.yaml",
		"teams/a/p (conflicted copy 2026-11-06 101010).yaml":              "teams/a/p.yaml",
		"teams/a/p.sync-conflict-20261106-101010-ABCDEFG.yaml":            "teams/a/p.yaml",
		"teams/a/p_conflict-20261106-101010.yaml":                         "teams/a/p.yaml",
		"teams/a/p (In Konflikt stehende Kopie von Anna 2026-11-06).yaml": "",
	}
	for name, orig := range yes {
		if !IsConflictCopy(name) {
			t.Errorf("%s not recognised", name)
		}
		if orig != "" && OriginalOf(name) != orig {
			t.Errorf("%s: original %q", name, OriginalOf(name))
		}
	}
	for _, n := range []string{"teams/a/plan-Q1-FY26.yaml", "teams/a/2026.20.yaml", "teams/a/team.yaml", "teams/a/Risiken (Konflikte).yaml"} {
		if IsConflictCopy(n) {
			t.Errorf("%s wrongly recognised", n)
		}
	}
}

func TestCorruptLockExpires(t *testing.T) {
	root := t.TempDir()
	must(t, os.MkdirAll(filepath.Join(root, Dir), 0o755))
	must(t, os.WriteFile(LockPath(root), nil, 0o644))
	old := time.Now().Add(-2 * LockTTL)
	must(t, os.Chtimes(LockPath(root), old, old))
	h, err := Acquire(root, "x", "h", time.Second, time.Now)
	if err != nil {
		t.Fatalf("empty old lock must be taken over: %v", err)
	}
	h.Release()
}
