package datasvc

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/sharedfolder"
)

func put(t *testing.T, root, rel, content string) {
	t.Helper()
	p := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func get(t *testing.T, root, rel string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
	if err != nil {
		return "<missing>"
	}
	return string(b)
}

// team sets up two people, Anna and Ben, with their own local copies of one shared folder.
func team(t *testing.T) (anna, ben *Store, shared, annaDir, benDir string) {
	t.Helper()
	base := t.TempDir()
	shared, annaDir, benDir = filepath.Join(base, "share"), filepath.Join(base, "anna"), filepath.Join(base, "ben")
	if err := os.MkdirAll(shared, 0o755); err != nil {
		t.Fatal(err)
	}
	anna, ben = New(""), New("")
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 5\nvelocity: 10\n")
	if o := anna.UseSharedFolder(annaDir, shared, "Anna"); o.Problem != nil {
		t.Fatal(o.Problem)
	}
	if r := anna.Save(SaveOptions{Message: "first"}); r.Outcome != OutcomeSaved {
		t.Fatalf("first save: %+v", r)
	}
	if o := ben.UseSharedFolder(benDir, shared, "Ben"); o.Problem != nil {
		t.Fatal(o.Problem)
	}
	return
}

func TestFolderFirstSaveAndJoin(t *testing.T) {
	_, ben, shared, _, benDir := team(t)
	if got := get(t, benDir, "t1/team.yaml"); !strings.Contains(got, "capacity: 5") {
		t.Fatalf("Ben did not get the data: %q", got)
	}
	if st := ben.Status(); st.Kind != KindFolder || st.Chip.State != ChipOK || st.Unsaved != 0 {
		t.Fatalf("status %+v", st)
	}
	h, err := ben.History("", 0)
	if err != nil || len(h) != 1 || h[0].Who != "Anna" || h[0].Summary != "first" {
		t.Fatalf("history %v %+v", err, h)
	}
	if _, err := os.Stat(filepath.Join(shared, ".foresprint", "storage.yaml")); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(shared, ".foresprint", "lock")); err == nil {
		t.Fatal("lock left behind")
	}
}

func TestFolderMergesDifferentValues(t *testing.T) {
	anna, ben, shared, annaDir, benDir := team(t)
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 6\nvelocity: 10\n")
	put(t, benDir, "t1/team.yaml", "name: Team\ncapacity: 5\nvelocity: 12\n")
	if st := ben.Status(); st.Unsaved != 1 {
		t.Fatalf("unsaved %+v", st)
	}
	if r := anna.Save(SaveOptions{Message: "capacity"}); r.Outcome != OutcomeSaved {
		t.Fatalf("anna: %+v", r)
	}
	if st := ben.Status(); st.Chip.State != ChipIncoming || len(st.IncomingFrom) != 1 || st.IncomingFrom[0] != "Anna" {
		t.Fatalf("ben should see Anna's change: %+v", st)
	}
	r := ben.Save(SaveOptions{Message: "velocity"})
	if r.Outcome != OutcomeSaved || len(r.Taken) != 1 || r.Taken[0].Who != "Anna" {
		t.Fatalf("ben: %+v", r)
	}
	for _, root := range []string{shared, benDir} {
		got := get(t, root, "t1/team.yaml")
		if !strings.Contains(got, "capacity: 6") || !strings.Contains(got, "velocity: 12") {
			t.Fatalf("%s not merged: %q", root, got)
		}
	}
	if r := anna.Refresh(); r.Outcome != OutcomeSaved {
		t.Fatalf("anna refresh: %+v", r)
	}
	if got := get(t, annaDir, "t1/team.yaml"); !strings.Contains(got, "velocity: 12") {
		t.Fatalf("anna: %q", got)
	}
	if r := anna.Refresh(); r.Outcome != OutcomeNothing {
		t.Fatalf("second refresh should find nothing: %+v", r)
	}
	// Two saves, snapshot of the day holds the state before the first of them.
	if data, ok := sharedfolder.SnapshotFile(shared, "t1/team.yaml", time.Now().Format("2006-01-02")); !ok || !strings.Contains(string(data), "capacity: 5") {
		t.Fatalf("snapshot %q %v", data, ok)
	}
}

func TestFolderConflictAndDecision(t *testing.T) {
	anna, ben, shared, annaDir, benDir := team(t)
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 6\nvelocity: 10\n")
	put(t, benDir, "t1/team.yaml", "name: Team\ncapacity: 7\nvelocity: 10\n")
	anna.Save(SaveOptions{})
	r := ben.Save(SaveOptions{})
	if r.Outcome != OutcomeConflict || r.Conflicts != 1 {
		t.Fatalf("expected a conflict: %+v", r)
	}
	if got := get(t, shared, "t1/team.yaml"); !strings.Contains(got, "capacity: 6") {
		t.Fatalf("shared must stay untouched by the failed save: %q", got)
	}
	cs := ben.Conflicts()
	if len(cs) != 1 || len(cs[0].Entries) != 1 || cs[0].Entries[0].Mine != "7" || cs[0].Entries[0].Theirs != "6" {
		t.Fatalf("conflicts %+v", cs)
	}
	res := ben.ResolveConflicts([]Decision{{File: "t1/team.yaml", Path: cs[0].Entries[0].Path, Choice: Mine}})
	if res.Outcome != OutcomeDecided {
		t.Fatalf("resolve: %+v", res)
	}
	if r := ben.Save(SaveOptions{Message: "mine wins"}); r.Outcome != OutcomeSaved {
		t.Fatalf("save after decision: %+v", r)
	}
	if got := get(t, shared, "t1/team.yaml"); !strings.Contains(got, "capacity: 7") {
		t.Fatalf("shared: %q", got)
	}
}

func TestFolderConflictCopyAndLock(t *testing.T) {
	_, ben, shared, _, benDir := team(t)
	put(t, shared, "t1/team (Anna's conflicted copy 2026-11-06).yaml", "name: Other\n")
	if st := ben.Status(); st.Chip.State != ChipConflict || st.Conflicts != 1 {
		t.Fatalf("status %+v", st)
	}
	cs := ben.Conflicts()
	if len(cs) != 1 || !cs[0].Whole || !strings.Contains(cs[0].File, "conflicted copy") {
		t.Fatalf("%+v", cs)
	}
	ben.ResolveConflicts([]Decision{{File: cs[0].File, Path: []string{}, Choice: Theirs}})
	if got := get(t, benDir, "t1/team.yaml"); !strings.Contains(got, "name: Other") {
		t.Fatalf("copy not taken over: %q", got)
	}
	if _, err := os.Stat(filepath.Join(shared, filepath.FromSlash(cs[0].File))); err == nil {
		t.Fatal("copy still in the shared folder")
	}
	// A lock held by someone else blocks Save with a clear problem.
	rel, err := sharedfolder.Acquire(shared, "Carla", "pc", time.Second, time.Now)
	if err != nil {
		t.Fatal(err)
	}
	defer rel()
	// Shorten the wait: the lock stays for the test, Save waits 10 s at most.
	start := time.Now()
	r := ben.Save(SaveOptions{})
	if r.Outcome != OutcomeProblem || r.Problem == nil || r.Problem.Kind != "locked" || !strings.Contains(r.Problem.Message, "Carla") {
		t.Fatalf("expected a lock problem: %+v", r)
	}
	if time.Since(start) > 15*time.Second {
		t.Fatal("waited too long")
	}
}

func TestFolderOfflineDiscardRevert(t *testing.T) {
	anna, _, shared, annaDir, _ := team(t)
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 9\nvelocity: 10\n")
	un, err := anna.UnsavedChanges()
	if err != nil || len(un) != 1 || len(un[0].Values) != 1 || un[0].Values[0].After != "9" || un[0].Values[0].Before != "5" {
		t.Fatalf("unsaved %v %+v", err, un)
	}
	if d := anna.Discard(nil); d.Problem != nil || d.Status.Unsaved != 0 {
		t.Fatalf("discard %+v", d)
	}
	if got := get(t, annaDir, "t1/team.yaml"); !strings.Contains(got, "capacity: 5") {
		t.Fatalf("not discarded: %q", got)
	}
	// Second save of the day: the exact earlier state is not kept, Revert says so.
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 9\nvelocity: 10\n")
	anna.Save(SaveOptions{Message: "second"})
	h, _ := anna.History("", 0)
	if len(h) != 2 {
		t.Fatalf("history %+v", h)
	}
	if d := anna.Revert(h[0].ID); d.Problem == nil && !strings.Contains(get(t, annaDir, "t1/team.yaml"), "capacity: 5") {
		t.Fatalf("revert gave neither the old state nor an explanation: %+v", d)
	}
	// Offline: the shared folder is gone; editing works, saving waits.
	if err := os.Rename(shared, shared+"-away"); err != nil {
		t.Fatal(err)
	}
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 1\nvelocity: 10\n")
	r := anna.Save(SaveOptions{})
	if r.Outcome != OutcomeOffline || r.Problem == nil || r.Status.Chip.State != ChipOffline {
		t.Fatalf("offline: %+v", r)
	}
	if st := anna.Status(); st.Unsaved != 1 || st.Connected {
		t.Fatalf("status offline %+v", st)
	}
}

func TestFolderCheckAndSetupGuards(t *testing.T) {
	s := New("")
	shared := t.TempDir()
	c := s.CheckSharedFolder(shared)
	if !c.OK || c.HasData {
		t.Fatalf("check %+v", c)
	}
	if _, err := os.Stat(filepath.Join(shared, ".foresprint-check")); err == nil {
		t.Fatal("check left its folder")
	}
	if o := s.UseSharedFolder(shared, shared, ""); o.Problem == nil {
		t.Fatal("same folder accepted")
	}
	if o := s.UseSharedFolder(filepath.Join(shared, "in"), shared, ""); o.Problem == nil {
		t.Fatal("local inside shared accepted")
	}
	if o := s.UseSharedFolder(t.TempDir(), filepath.Join(shared, "missing"), ""); o.Problem == nil {
		t.Fatal("missing shared accepted")
	}
}
