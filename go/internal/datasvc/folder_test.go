package datasvc

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/gitsync"
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

func get(t *testing.T, root string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(root, "t1", "team.yaml"))
	if err != nil {
		return "<missing>"
	}
	return string(b)
}

// noValidation switches the data check off: the test data is not a complete team.
func noValidation(t *testing.T) {
	t.Helper()
	gitsync.SetValidator(func(context.Context, string, time.Time) ([]gitsync.Issue, error) { return nil, nil })
	t.Cleanup(func() { gitsync.SetValidator(nil) })
}

// team sets up two people, Anna and Ben, with their own local copies of one shared folder.
func team(t *testing.T) (anna, ben *Store, shared, annaDir, benDir string) {
	t.Helper()
	noValidation(t)
	base := t.TempDir()
	shared, annaDir, benDir = filepath.Join(base, "share"), filepath.Join(base, "anna"), filepath.Join(base, "ben")
	if err := os.MkdirAll(shared, 0o755); err != nil {
		t.Fatal(err)
	}
	anna, ben = New(""), New("")
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 5\nvelocity: 10\n")
	if o := anna.UseSharedFolder(annaDir, shared, "Anna", true); o.Problem != nil {
		t.Fatal(o.Problem)
	}
	if r := anna.Save(SaveOptions{Message: "first"}); r.Outcome != OutcomeSaved {
		t.Fatalf("first save: %+v", r)
	}
	if o := ben.UseSharedFolder(benDir, shared, "Ben", false); o.Problem != nil {
		t.Fatal(o.Problem)
	}
	return
}

func TestFolderFirstSaveAndJoin(t *testing.T) {
	_, ben, shared, _, benDir := team(t)
	if got := get(t, benDir); !strings.Contains(got, "capacity: 5") {
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
		got := get(t, root)
		if !strings.Contains(got, "capacity: 6") || !strings.Contains(got, "velocity: 12") {
			t.Fatalf("%s not merged: %q", root, got)
		}
	}
	if r := anna.Refresh(); r.Outcome != OutcomeSaved {
		t.Fatalf("anna refresh: %+v", r)
	}
	if got := get(t, annaDir); !strings.Contains(got, "velocity: 12") {
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
	if got := get(t, shared); !strings.Contains(got, "capacity: 6") {
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
	if got := get(t, shared); !strings.Contains(got, "capacity: 7") {
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
	if got := get(t, benDir); !strings.Contains(got, "name: Other") {
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
	defer rel.Release()
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
	if got := get(t, annaDir); !strings.Contains(got, "capacity: 5") {
		t.Fatalf("not discarded: %q", got)
	}
	// Second save of the day: the exact earlier state is not kept, Revert says so.
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 9\nvelocity: 10\n")
	anna.Save(SaveOptions{Message: "second"})
	h, _ := anna.History("", 0)
	if len(h) != 2 {
		t.Fatalf("history %+v", h)
	}
	if d := anna.Revert(h[0].ID); d.Problem == nil && !strings.Contains(get(t, annaDir), "capacity: 5") {
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
	if o := s.UseSharedFolder(shared, shared, "", true); o.Problem == nil {
		t.Fatal("same folder accepted")
	}
	if o := s.UseSharedFolder(filepath.Join(shared, "in"), shared, "", true); o.Problem == nil {
		t.Fatal("local inside shared accepted")
	}
	if o := s.UseSharedFolder(t.TempDir(), filepath.Join(shared, "missing"), "", true); o.Problem == nil {
		t.Fatal("missing shared accepted")
	}
}

func TestFolderEmptyShareIsNotReachable(t *testing.T) {
	anna, _, shared, annaDir, _ := team(t)
	// A mount point that is not mounted, or a sync folder not filled yet: an empty folder without
	// the marker. Refresh must not delete the local copy, Save must not publish into it.
	gone := shared + "-away"
	if err := os.Rename(shared, gone); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(shared, 0o755); err != nil {
		t.Fatal(err)
	}
	if r := anna.Refresh(); r.Outcome != OutcomeOffline {
		t.Fatalf("refresh: %+v", r)
	}
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 8\nvelocity: 10\n")
	if r := anna.Save(SaveOptions{}); r.Outcome != OutcomeOffline {
		t.Fatalf("save: %+v", r)
	}
	if got := get(t, annaDir); !strings.Contains(got, "capacity: 8") {
		t.Fatalf("local copy changed: %q", got)
	}
	if entries, _ := os.ReadDir(shared); len(entries) != 0 {
		t.Fatalf("something was written into the empty folder: %v", entries)
	}
}

func TestFolderJournalNamesCannotLeaveTheCopy(t *testing.T) {
	anna, _, shared, annaDir, _ := team(t)
	outside := filepath.Join(filepath.Dir(annaDir), "precious.txt")
	if err := os.WriteFile(outside, []byte("keep"), 0o644); err != nil {
		t.Fatal(err)
	}
	evil := sharedfolder.Entry{ID: "evil", Who: "Mallory", Time: time.Now(), Summary: "x", Files: map[string]sharedfolder.Change{
		"../precious.txt": {Before: "", After: ""}, "../../etc/x": {Before: "a", After: "b"}}}
	if err := sharedfolder.Append(shared, evil); err != nil {
		t.Fatal(err)
	}
	h, _ := anna.History("", 0)
	for _, v := range h {
		for _, f := range v.Files {
			if strings.Contains(f, "..") {
				t.Fatalf("history shows %q", f)
			}
		}
	}
	anna.Revert("evil")
	anna.Restore("", "evil", "")
	if b, err := os.ReadFile(outside); err != nil || string(b) != "keep" {
		t.Fatalf("file outside the copy touched: %q %v", b, err)
	}
}

func TestFolderKeepsDiscardedAndReplacedEdits(t *testing.T) {
	anna, _, shared, annaDir, _ := team(t)
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 42\nvelocity: 10\n")
	anna.Discard(nil)
	trashed := func() string {
		var found string
		_ = filepath.WalkDir(filepath.Join(annaDir, ".foresprint-local", "trash"), func(p string, d os.DirEntry, err error) error {
			if err == nil && !d.IsDir() {
				b, _ := os.ReadFile(p)
				found += string(b)
			}
			return nil
		})
		return found
	}
	if !strings.Contains(trashed(), "capacity: 42") {
		t.Fatalf("discarded edit not kept: %q", trashed())
	}
	// Taking a conflict copy over an unsaved edit keeps the edit.
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 77\nvelocity: 10\n")
	put(t, shared, "t1/team (Ben's conflicted copy 2026-11-06).yaml", "name: Copy\n")
	cs := anna.Conflicts()
	anna.ResolveConflicts([]Decision{{File: cs[0].File, Path: []string{}, Choice: Theirs}})
	if !strings.Contains(trashed(), "capacity: 77") || !strings.Contains(get(t, annaDir), "name: Copy") {
		t.Fatalf("copy taken without keeping the edit: %q / %q", trashed(), get(t, annaDir))
	}
}

func TestFolderNewShareDoesNotDeleteTheLocalCopy(t *testing.T) {
	anna, _, _, annaDir, _ := team(t)
	// The old share is gone; the person points the copy at a new, empty folder to republish.
	fresh := filepath.Join(t.TempDir(), "newshare")
	if err := os.MkdirAll(fresh, 0o755); err != nil {
		t.Fatal(err)
	}
	if o := anna.UseSharedFolder(annaDir, fresh, "Anna", false); o.Problem == nil {
		t.Fatal("an empty folder without the marker must not become a storage by itself")
	}
	if o := anna.UseSharedFolder(annaDir, fresh, "Anna", true); o.Problem != nil {
		t.Fatal(o.Problem)
	}
	if got := get(t, annaDir); !strings.Contains(got, "capacity: 5") {
		t.Fatalf("local copy lost: %q", got)
	}
	if r := anna.Save(SaveOptions{Message: "republish"}); r.Outcome != OutcomeSaved {
		t.Fatalf("republish: %+v", r)
	}
	if got := get(t, fresh); !strings.Contains(got, "capacity: 5") {
		t.Fatalf("not republished: %q", got)
	}
}

func TestFolderTrashKeepsEveryReplacement(t *testing.T) {
	anna, _, shared, annaDir, _ := team(t)
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: 77\nvelocity: 10\n")
	put(t, shared, "t1/team (Ben's conflicted copy 2026-11-06).yaml", "name: One\n")
	put(t, shared, "t1/team (Carla's conflicted copy 2026-11-06).yaml", "name: Two\n")
	anna.TakeTheirs()
	n, found := 0, ""
	_ = filepath.WalkDir(filepath.Join(annaDir, ".foresprint-local", "trash"), func(p string, d os.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			n++
			b, _ := os.ReadFile(p)
			found += string(b)
		}
		return nil
	})
	if n < 2 || !strings.Contains(found, "capacity: 77") {
		t.Fatalf("trash lost an edit: %d entries %q", n, found)
	}
}

func TestFolderCopyInsideGitIsRefusedAndLabelsAreEmpty(t *testing.T) {
	s := New("")
	shared := t.TempDir()
	repo := t.TempDir()
	if err := os.MkdirAll(filepath.Join(repo, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	if o := s.UseSharedFolder(filepath.Join(repo, "teams"), shared, "", true); o.Problem == nil {
		t.Fatal("copy inside a Git work tree accepted")
	}
	if _, err := os.Stat(filepath.Join(repo, "teams", ".foresprint-local")); err == nil {
		t.Fatal("config written into the repository")
	}
	anna, _, _, annaDir, _ := team(t)
	if l, err := anna.Labels(false); err != nil || l == nil || len(l) != 0 {
		t.Fatalf("labels %v %v", l, err)
	}
	other := New("")
	if o := other.OpenFolder(annaDir); o.Problem != nil || o.Folder != annaDir {
		t.Fatalf("open the copy again: %+v", o)
	}
}

func TestFolderSaveStopsOnNewDataErrors(t *testing.T) {
	anna, _, shared, annaDir, _ := team(t)
	bad := func(_ context.Context, dir string, _ time.Time) ([]gitsync.Issue, error) {
		if b, err := os.ReadFile(filepath.Join(dir, "t1", "team.yaml")); err == nil && strings.Contains(string(b), "capacity: -1") {
			return []gitsync.Issue{{Key: "t1", Where: filepath.Join(dir, "t1", "team.yaml"), Message: "capacity must not be negative"}}, nil
		}
		return nil, nil
	}
	gitsync.SetValidator(bad)
	t.Cleanup(func() { gitsync.SetValidator(nil) })
	put(t, annaDir, "t1/team.yaml", "name: Team\ncapacity: -1\nvelocity: 10\n")
	// The first save into a new shared folder has nothing to compare with.
	if found, err := ((&folderBackend{s: anna, dir: annaDir, cfg: folderConfig{Shared: t.TempDir()}}).newErrors(nil)); err != nil || len(found) != 0 {
		t.Fatalf("empty shared folder: %v %v", found, err)
	}
	r := anna.Save(SaveOptions{Message: "bad"})
	if r.Outcome != OutcomeFindings || len(r.Findings) != 1 {
		t.Fatalf("save with a new error: %+v", r)
	}
	if got := get(t, shared); !strings.Contains(got, "capacity: 5") {
		t.Fatalf("shared folder changed: %s", got)
	}
	if r := anna.Save(SaveOptions{Message: "bad", SaveAnyway: true}); r.Outcome != OutcomeSaved {
		t.Fatalf("save anyway: %+v", r)
	}
	// An error the shared folder has already is not new.
	put(t, annaDir, "t1/team.yaml", "name: Team 2\ncapacity: -1\nvelocity: 10\n")
	if r := anna.Save(SaveOptions{Message: "again"}); r.Outcome != OutcomeSaved {
		t.Fatalf("old error blocks the save: %+v", r)
	}
}
