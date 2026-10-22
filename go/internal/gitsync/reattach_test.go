package gitsync

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gittest"
)

func TestDetachedHeadBlocksAndReattach(t *testing.T) {
	w := newWorld(t)
	w.alice.git("checkout", "-q", "--detach")
	git.InvalidateStatus()
	if !w.alice.state().Detached() {
		t.Fatal("not detached")
	}
	w.alice.write("a/2026.2.yaml", "velocity: 5\n")
	res := w.alice.sync("Detached")
	if res.Error == nil || res.Error.Kind != "detached" || res.Committed != "" {
		t.Fatalf("result = %+v", res)
	}
	w.alice.git("stash", "-u", "-q")
	done, err := Reattach(bg, w.alice.data())
	if err != nil || done.Branch != "main" || w.alice.state().Branch != "main" {
		t.Fatalf("done = %+v err = %v", done, err)
	}
}

func TestReattachRescuesOrphanCommits(t *testing.T) {
	w := newWorld(t)
	w.alice.git("checkout", "-q", "--detach")
	gittest.Write(t, filepath.Join(w.alice.data(), "a", "new.yaml"), "x: 1\n")
	w.alice.git("add", "-A")
	w.alice.git("commit", "-qm", "on a loose state")
	git.InvalidateStatus()
	done, err := Reattach(bg, w.alice.data())
	if err != nil || done.Branch != "main" || !strings.HasPrefix(done.Rescue, "rescue-") || !done.Commits {
		t.Fatalf("done = %+v err = %v", done, err)
	}
	if !strings.Contains(w.alice.git("branch", "--list"), "rescue-") {
		t.Fatal("no rescue branch")
	}
}

// detachWithOpenChange detaches at the state before the last change of main, with an open change
// to the same file: switching back would overwrite it.
func detachWithOpenChange(w *world, orphan bool) {
	t := w.alice.t
	p := filepath.Join(w.alice.data(), "a", "2026.1.yaml")
	gittest.Write(t, p, "velocity: 11\nscope_creep: 1\n")
	w.alice.git("commit", "-qam", "New state")
	w.alice.git("checkout", "-q", "--detach", "HEAD~1")
	if orphan {
		gittest.Write(t, filepath.Join(w.alice.data(), "a", "new.yaml"), "x: 1\n")
		w.alice.git("add", "-A")
		w.alice.git("commit", "-qm", "on a loose state")
	}
	gittest.Write(t, p, "velocity: 99\nscope_creep: 1\n")
	git.InvalidateStatus()
}

func TestReattachWithOpenChangesSavesThemOnARescueBranch(t *testing.T) {
	w := newWorld(t)
	detachWithOpenChange(w, false)
	done, err := Reattach(bg, w.alice.data())
	if err != nil || done.Branch != "main" || !done.Changes || done.Commits || !strings.HasPrefix(done.Rescue, "rescue-") {
		t.Fatalf("done = %+v err = %v", done, err)
	}
	if w.alice.git("status", "--porcelain") != "" || w.alice.read("a/2026.1.yaml") != "velocity: 11\nscope_creep: 1\n" {
		t.Fatal("main is not clean")
	}
	if w.alice.git("show", done.Rescue+":teams/a/2026.1.yaml") != "velocity: 99\nscope_creep: 1" {
		t.Fatal("changes not on the rescue branch")
	}
	if w.alice.git("log", "-1", "--format=%s", done.Rescue) != "Open changes saved before the switch" {
		t.Fatal("wrong subject")
	}
}

func TestReattachSavesNewFilesAndCommitsTogether(t *testing.T) {
	w := newWorld(t)
	detachWithOpenChange(w, true)
	gittest.Write(t, filepath.Join(w.alice.data(), "a", "fresh.yaml"), "y: 2\n")
	git.InvalidateStatus()
	done, err := Reattach(bg, w.alice.data())
	if err != nil || !done.Commits || !done.Changes {
		t.Fatalf("done = %+v err = %v", done, err)
	}
	if got := w.alice.git("branch", "--list", "rescue-*", "--format=%(refname:short)"); got != done.Rescue {
		t.Fatalf("rescue branches = %q", got)
	}
	files := w.alice.git("ls-tree", "-r", "--name-only", done.Rescue)
	if !strings.Contains(files, "teams/a/new.yaml") || !strings.Contains(files, "teams/a/fresh.yaml") {
		t.Fatalf("files = %q", files)
	}
}

func TestReattachWithoutOpenChangesMakesNoExtraCommit(t *testing.T) {
	w := newWorld(t)
	detachWithOpenChange(w, true)
	w.alice.git("checkout", "--", ".")
	git.InvalidateStatus()
	done, err := Reattach(bg, w.alice.data())
	if err != nil || !done.Commits || done.Changes {
		t.Fatalf("done = %+v err = %v", done, err)
	}
	if w.alice.git("log", "-1", "--format=%s", done.Rescue) != "on a loose state" {
		t.Fatal("extra commit")
	}
}

func TestReattachKeepsTheStateWhenSavingFails(t *testing.T) {
	w := newWorld(t)
	w.alice.git("checkout", "-q", "--detach")
	gittest.Write(t, filepath.Join(w.alice.data(), "a", "plan.xlsx"), "x")
	git.InvalidateStatus()
	head := w.alice.git("rev-parse", "HEAD")
	if _, err := Reattach(bg, w.alice.data()); err == nil {
		t.Fatal("expected an error")
	}
	if !w.alice.state().Detached() || w.alice.git("rev-parse", "HEAD") != head {
		t.Fatal("state changed")
	}
	if strings.Contains(w.alice.git("branch", "--list"), "rescue-") {
		t.Fatal("rescue branch left behind")
	}
}

func TestReattachBlockedOutsideTheDataFolderNamesTheRescueBranch(t *testing.T) {
	w := newWorld(t)
	// a file outside the data folder that differs between the two states
	gittest.Write(t, filepath.Join(w.alice.root, "outside.txt"), "1")
	w.alice.git("add", "-A")
	w.alice.git("commit", "-qm", "outside 1")
	w.alice.git("checkout", "-q", "--detach", "HEAD~1")
	gittest.Write(t, filepath.Join(w.alice.root, "outside.txt"), "mine")
	gittest.Write(t, filepath.Join(w.alice.data(), "a", "2026.1.yaml"), "velocity: 99\n")
	git.InvalidateStatus()
	_, err := Reattach(bg, w.alice.data())
	e := git.As(err)
	if e == nil || e.Kind != "detached" || !strings.Contains(e.Hint(), "rescue-") {
		t.Fatalf("err = %v", err)
	}
	if !w.alice.state().Detached() {
		t.Fatal("not detached again")
	}
	// the next attempt names the same rescue branch
	_, err2 := Reattach(bg, w.alice.data())
	if e2 := git.As(err2); e2 == nil || !strings.Contains(e2.Hint(), "rescue-") {
		t.Fatalf("second err = %v", err2)
	}
	if n := strings.Count(w.alice.git("branch", "--list", "rescue-*"), "rescue-"); n != 1 {
		t.Fatalf("%d rescue branches", n)
	}
}

func TestOlderRescueNamesAreStillRecognised(t *testing.T) {
	if !isSaveSubject(legacySaveSubject) || !isRescue("rettung-20260101-000000") || !isRescue("rescue-20260101-000000") {
		t.Fatal("legacy names not recognised")
	}
}
