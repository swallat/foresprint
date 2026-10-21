package gitsync

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gittest"
	"github.com/swallat/foresprint/internal/yamlmerge"
)

const file = "teams/a/2026.1.yaml"

func TestStateWithoutRemote(t *testing.T) {
	setup(t)
	dir := t.TempDir()
	gittest.Git(t, dir, "init", "-q", "-b", "main")
	s, err := State(bg, dir)
	if err != nil {
		t.Fatal(err)
	}
	if s.Remote != "" || s.Upstream != "" || s.CanShare() || s.Branch != "main" || s.Ahead != 0 || s.Behind != 0 {
		t.Fatalf("state = %+v", s)
	}
}

func TestFirstSyncConnectsBranchAndPushes(t *testing.T) {
	w := newWorld(t)
	s := w.alice.state()
	if s.Upstream != "origin/main" || s.Ahead != 0 || s.Behind != 0 {
		t.Fatalf("state = %+v", s)
	}
	if got := gittest.Git(t, w.remote, "log", "-1", "--format=%s", "main"); got != "Start" {
		t.Fatalf("server has %q", got)
	}
}

func TestAheadBehindAndFetch(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.2.yaml", "velocity: 5\n")
	w.alice.git("add", "-A")
	w.alice.git("commit", "-qm", "local")
	if got := w.alice.state().Ahead; got != 1 {
		t.Fatalf("ahead = %d", got)
	}
	w.alice.mustOK("x")
	if got := w.bob.state().Behind; got != 0 {
		t.Fatalf("bob knows too early: %d", got)
	}
	s, err := Fetch(bg, w.bob.data())
	if err != nil {
		t.Fatal(err)
	}
	if s.Behind != 1 || s.FetchError != nil || s.FetchedAt.IsZero() {
		t.Fatalf("state = %+v", s)
	}
}

func TestSyncShowsChangesByOthers(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.2.yaml", "velocity: 5\n")
	w.alice.mustOK("Review 2026.2", "a/2026.2")
	res := w.bob.mustOK("x")
	if res.Committed != "" || len(res.Pulled) != 1 || res.Pulled[0].Subject != "Review 2026.2" || res.Pulled[0].Author != "Alice" {
		t.Fatalf("result = %+v", res)
	}
	if !containsFile(res.PulledFiles, FileChange{"A", "teams/a/2026.2.yaml"}) {
		t.Fatalf("files = %v", res.PulledFiles)
	}
	if w.bob.read("a/2026.2.yaml") != "velocity: 5\n" {
		t.Fatal("file not pulled")
	}
	if !strings.Contains(w.bob.git("tag"), "a/2026.2") {
		t.Fatal("tag did not come along")
	}
}

func TestIncomingBeforePull(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	w.alice.mustOK("Fix")
	if _, err := Fetch(bg, w.bob.data()); err != nil {
		t.Fatal(err)
	}
	commits, files, err := Incoming(bg, w.bob.data(), 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(commits) != 1 || commits[0].Subject != "Fix" || len(files) != 1 || files[0] != (FileChange{"M", file}) {
		t.Fatalf("incoming = %v %v", commits, files)
	}
}

func commitWithoutSubject(p person, rel, text string) {
	p.write(rel, text)
	p.git("add", "-A")
	p.git("commit", "-q", "--allow-empty-message", "-m", "")
}

func TestIncomingWithAnEmptySubjectOfTheOldestCommit(t *testing.T) {
	w := newWorld(t)
	commitWithoutSubject(w.alice, "a/2026.2.yaml", "velocity: 5\n")
	w.alice.write("a/2026.3.yaml", "velocity: 6\n")
	w.alice.git("add", "-A")
	w.alice.git("commit", "-qm", "Second")
	w.alice.git("push", "-q")
	if _, err := Fetch(bg, w.bob.data()); err != nil {
		t.Fatal(err)
	}
	commits, files, err := Incoming(bg, w.bob.data(), 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(commits) != 2 || commits[0].Subject != "Second" || commits[1].Subject != "" || commits[1].Author != "Alice" || len(files) != 2 {
		t.Fatalf("incoming = %v %v", commits, files)
	}
}

func TestParallelChangesInDifferentFilesAreMerged(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.2.yaml", "velocity: 5\n")
	w.bob.write("a/2026.3.yaml", "velocity: 7\n")
	w.alice.mustOK("Alice")
	res := w.bob.mustOK("Bob")
	if !res.Pushed || res.Committed == "" {
		t.Fatalf("result = %+v", res)
	}
	w.alice.mustOK("x")
	if w.alice.read("a/2026.3.yaml") == "" || w.alice.read("a/2026.2.yaml") == "" {
		t.Fatal("files missing")
	}
	log := w.alice.git("log", "--format=%s", "--no-merges")
	if !strings.Contains(log, "Alice") || !strings.Contains(log, "Bob") {
		t.Fatalf("log = %q", log)
	}
}

func TestPushRaceIsRetried(t *testing.T) {
	w := newWorld(t)
	carol := w.clone("Carol")
	carol.write("a/2026.9.yaml", "velocity: 1\n")
	calls := 0
	real := pushUpload
	t.Cleanup(func() { pushUpload = real })
	pushUpload = func(ctx context.Context, root string, current SyncState) error {
		if root != git.Resolve(w.bob.root) {
			return real(ctx, root, current)
		}
		calls++
		if calls == 1 {
			carol.mustOK("Carol") // gets there before Bob
		}
		return real(ctx, root, current)
	}
	w.bob.write("a/2026.3.yaml", "velocity: 7\n")
	res := w.bob.mustOK("Bob")
	if calls != 2 || !res.Pushed {
		t.Fatalf("calls = %d result = %+v", calls, res)
	}
	if w.bob.read("a/2026.9.yaml") == "" || w.bob.state().Ahead != 0 {
		t.Fatal("not merged and pushed")
	}
}

func TestPushRejectedForGoodReportsNextStep(t *testing.T) {
	w := newWorld(t)
	real := pushUpload
	t.Cleanup(func() { pushUpload = real })
	pushUpload = func(context.Context, string, SyncState) error {
		return git.Classify("! [rejected] main -> main (fetch first)", git.ClassifyOpts{})
	}
	w.bob.write("a/2026.3.yaml", "velocity: 7\n")
	res := w.bob.sync("Bob")
	if res.Error == nil || res.Error.Kind != "rejected" || res.Committed == "" {
		t.Fatalf("result = %+v", res)
	}
	if w.bob.git("status", "--porcelain") != "" {
		t.Fatal("not saved locally")
	}
}

func TestServerDeniesPush(t *testing.T) {
	needShell(t)
	w := newWorld(t)
	hook := filepath.Join(w.remote, "hooks", "pre-receive")
	gittest.Write(t, hook, "#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
	if err := os.Chmod(hook, 0o755); err != nil {
		t.Fatal(err)
	}
	w.bob.write("a/2026.3.yaml", "velocity: 7\n")
	res := w.bob.sync("Bob")
	if res.Error == nil || res.Error.Kind != "denied" || w.bob.state().Ahead != 1 {
		t.Fatalf("result = %+v", res)
	}
}

func conflictBetweenAliceAndBob(w *world) *SyncResult {
	w.alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	w.alice.mustOK("Alice")
	w.bob.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
	return w.bob.sync("Bob")
}

func TestValueConflictStaysOpenAndNothingIsLost(t *testing.T) {
	w := newWorld(t)
	res := conflictBetweenAliceAndBob(w)
	if res.Error == nil || res.Error.Kind != "conflict" || res.Pushed || len(res.Conflicts) != 1 {
		t.Fatalf("result = %+v", res)
	}
	c := res.Conflicts[0]
	if c.File != file || c.Whole || len(c.Keys) != 1 {
		t.Fatalf("conflict = %+v", c)
	}
	k := c.Keys[0]
	if len(k.Path) != 1 || k.Path[0] != "velocity" || k.Ours != int64(12) || k.Theirs != int64(11) {
		t.Fatalf("key = %+v", k)
	}
	s := w.bob.state()
	if s.Unfinished != "merge" || len(s.Conflicts) != 1 || s.Conflicts[0] != file {
		t.Fatalf("state = %+v", s)
	}
	if !strings.HasPrefix(w.onServer(), "velocity: 11") {
		t.Fatal("server changed")
	}
	if !strings.Contains(w.bob.git("log", "--format=%s"), "Bob") {
		t.Fatal("own commit missing")
	}
}

func TestResolveMineOrOtherAndContinue(t *testing.T) {
	for choice, want := range map[string]string{"ours": "velocity: 12\nscope_creep: 1\n", "theirs": "velocity: 11\nscope_creep: 1\n"} {
		t.Run(choice, func(t *testing.T) {
			w := newWorld(t)
			conflictBetweenAliceAndBob(w)
			remaining, err := ResolveConflicts(bg, w.bob.data(),
				Choices{file: yamlmerge.Choices{yamlmerge.Path{"velocity"}.Key(): choice}})
			if err != nil || len(remaining) != 0 {
				t.Fatalf("remaining = %v err = %v", remaining, err)
			}
			res := w.bob.mustOK("whatever") // resume: finish the merge, check, upload
			if !res.Merged || !res.Pushed || w.bob.state().Unfinished != "" {
				t.Fatalf("result = %+v", res)
			}
			if got := w.onServer(); got != strings.TrimSpace(want) {
				t.Fatalf("server has %q", got)
			}
			log := gittest.Git(t, w.remote, "log", "--format=%s", "main")
			if !strings.Contains(log, "Alice") || !strings.Contains(log, "Bob") {
				t.Fatalf("log = %q", log)
			}
		})
	}
}

func TestResumeAfterRestartAndAbort(t *testing.T) {
	w := newWorld(t)
	conflictBetweenAliceAndBob(w)
	git.InvalidateStatus()
	again := w.bob.sync("once more")
	if again.Error == nil || again.Error.Kind != "conflict" || len(again.Conflicts) == 0 {
		t.Fatalf("result = %+v", again)
	}
	if err := AbortUnfinished(bg, w.bob.data()); err != nil {
		t.Fatal(err)
	}
	if w.bob.read("a/2026.1.yaml") != "velocity: 12\nscope_creep: 1\n" {
		t.Fatal("own state lost")
	}
}

func TestDifferentKeysOfSameFileAreMerged(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	w.alice.mustOK("Alice")
	w.bob.write("a/2026.1.yaml", "velocity: 10\nscope_creep: 2\nnote: Bob\n")
	res := w.bob.mustOK("Bob")
	if !res.Merged || !res.Pushed || len(res.Conflicts) != 0 {
		t.Fatalf("result = %+v", res)
	}
	if got := w.onServer(); got != "velocity: 11\nscope_creep: 2\nnote: Bob" {
		t.Fatalf("merged = %q", got)
	}
}

func TestDeletedOnOneSideIsDecidedAsWholeFile(t *testing.T) {
	w := newWorld(t)
	if err := os.Remove(filepath.Join(w.alice.data(), "a", "2026.1.yaml")); err != nil {
		t.Fatal(err)
	}
	git.InvalidateStatus()
	w.alice.mustOK("Delete")
	w.bob.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
	res := w.bob.sync("Bob changes")
	if len(res.Conflicts) != 1 || !res.Conflicts[0].Whole || !res.Conflicts[0].TheirsDeleted || res.Conflicts[0].OursDeleted {
		t.Fatalf("result = %+v", res)
	}
	remaining, err := ResolveConflicts(bg, w.bob.data(), Choices{file: yamlmerge.Choices{yamlmerge.Path(nil).Key(): "ours"}})
	if err != nil || len(remaining) != 0 {
		t.Fatalf("remaining = %v err = %v", remaining, err)
	}
	w.bob.mustOK("go on")
	if !strings.HasPrefix(w.onServer(), "velocity: 12") {
		t.Fatal("kept version not on the server")
	}
}

func TestInvalidMergeResultIsNotPushed(t *testing.T) {
	w := newWorld(t)
	SetValidator(func(_ context.Context, dir string, _ time.Time) ([]Issue, error) {
		total := 0.0
		for _, name := range []string{"x.yaml", "y.yaml"} {
			b, err := os.ReadFile(filepath.Join(dir, "a", name))
			if err != nil {
				continue
			}
			v, _ := gittest.FlatCodec{}.Parse(string(b))
			if m, ok := v.(*yamlmerge.Map); ok {
				if s, ok := m.Get("share"); ok {
					switch n := s.(type) {
					case int64:
						total += float64(n)
					case float64:
						total += n
					}
				}
			}
		}
		if total > 100 {
			return []Issue{{"shares", "a", "shares add up to over 100 %"}}, nil
		}
		return nil, nil
	})
	w.alice.write("a/x.yaml", "share: 40\n")
	w.alice.write("a/y.yaml", "share: 40\n")
	w.alice.mustOK("base")
	w.bob.mustOK("pull")
	w.alice.write("a/x.yaml", "share: 60\n")
	w.alice.mustOK("Alice 60")
	w.bob.write("a/y.yaml", "share: 60\n")
	res := w.bob.sync("Bob 60")
	if !res.Merged || len(res.Conflicts) != 0 || res.Pushed || res.Error == nil || res.Error.Kind != "invalid" {
		t.Fatalf("result = %+v", res)
	}
	if len(res.Validation) == 0 || !strings.Contains(res.Validation[0], "100") {
		t.Fatalf("validation = %v", res.Validation)
	}
	if w.bob.state().Ahead < 1 {
		t.Fatal("not stored locally")
	}
	forced := w.bob.syncWith(SyncOptions{Message: "anyway", AllowInvalid: true})
	if !forced.OK() || !forced.Pushed {
		t.Fatalf("forced = %+v", forced)
	}
}

func TestOfflineKeepsLocalWork(t *testing.T) {
	w := newWorld(t)
	w.alice.git("remote", "set-url", "origin", filepath.Join(w.tmp, "disconnected", "data.git"))
	w.alice.write("a/2026.2.yaml", "velocity: 5\n")
	res := w.alice.sync("Offline")
	if res.Error == nil || res.Error.Kind != "offline" || res.Committed == "" {
		t.Fatalf("result = %+v", res)
	}
	if w.alice.git("status", "--porcelain") != "" {
		t.Fatal("work not saved locally")
	}
}

func TestNoRemoteStillSaves(t *testing.T) {
	setup(t)
	root := gittest.MakeLocal(t, t.TempDir(), "work", true)
	p := person{t, "T", root}
	p.write("a/new.yaml", "x: 1\n")
	res := p.sync("Local")
	if res.Error == nil || res.Error.Kind != "no_remote" || res.Committed == "" {
		t.Fatalf("result = %+v", res)
	}
}

func TestNothingToShareInAFreshRepository(t *testing.T) {
	setup(t)
	root := gittest.MakeLocal(t, t.TempDir(), "work", false)
	gittest.Git(t, root, "remote", "add", "origin", filepath.Join(t.TempDir(), "s.git"))
	res := person{t, "T", root}.sync("Nothing")
	if res.Error == nil || res.Error.Kind != "nothing_to_share" {
		t.Fatalf("result = %+v", res)
	}
}

func TestPullOnlyTakesOverServerStateWithoutPushing(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.2.yaml", "velocity: 5\n")
	w.alice.mustOK("Alice")
	w.bob.write("a/2026.3.yaml", "velocity: 7\n")
	res := w.bob.syncWith(SyncOptions{Message: "Bob", PullOnly: true})
	if !res.OK() || res.Pushed || !res.Merged || res.Committed == "" {
		t.Fatalf("result = %+v", res)
	}
	if w.bob.read("a/2026.2.yaml") == "" || w.bob.state().Ahead != 2 {
		t.Fatalf("state = %+v", w.bob.state())
	}
	if strings.Contains(gittest.Git(t, w.remote, "ls-tree", "-r", "--name-only", "main"), "2026.3") {
		t.Fatal("pushed")
	}
}

func TestUnfinishedMergeFromOutsideCanBeAborted(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	w.alice.mustOK("Alice")
	w.bob.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
	w.bob.git("add", "-A")
	w.bob.git("commit", "-qm", "Bob")
	w.bob.git("fetch", "-q")
	cmd := exec.Command("git", "merge", "origin/main")
	cmd.Dir = w.bob.root
	_ = cmd.Run() // conflict
	s := w.bob.state()
	if s.Unfinished != "merge" || len(s.Conflicts) != 1 || s.Conflicts[0] != file {
		t.Fatalf("state = %+v", s)
	}
	pending, err := PendingConflicts(bg, w.bob.data())
	if err != nil || len(pending) != 1 || pending[0].File != file {
		t.Fatalf("pending = %v err = %v", pending, err)
	}
	if err := AbortUnfinished(bg, w.bob.data()); err != nil {
		t.Fatal(err)
	}
	s = w.bob.state()
	if s.Unfinished != "" || len(s.Conflicts) != 0 || w.bob.read("a/2026.1.yaml") != "velocity: 12\nscope_creep: 1\n" {
		t.Fatalf("state = %+v", s)
	}
}

func TestTagFromTheOtherSideIsNotMoved(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.2.yaml", "velocity: 5\n")
	w.alice.mustOK("Alice", "a/2026.2")
	w.bob.write("a/2026.3.yaml", "velocity: 6\n")
	res := w.bob.mustOK("Bob", "a/2026.2")
	if !res.Pushed {
		t.Fatalf("result = %+v", res)
	}
	found := false
	for _, n := range res.Notes {
		if strings.Contains(n, "a/2026.2") {
			found = true
		}
	}
	if !found {
		t.Fatalf("notes = %v", res.Notes)
	}
}

func TestBusySyncGivesAnErrorInsteadOfWaiting(t *testing.T) {
	w := newWorld(t)
	release := make(chan struct{})
	started := make(chan struct{})
	go func() {
		_ = locked(bg, w.bob.data(), -1, func(context.Context) error {
			close(started)
			<-release
			return nil
		})
	}()
	<-started
	defer close(release)
	err := locked(bg, w.bob.data(), 20*time.Millisecond, func(context.Context) error { return nil })
	if !git.IsKind(err, "sync_busy") {
		t.Fatalf("err = %v", err)
	}
	if _, running := SyncRunningSeconds(w.bob.data()); !running {
		t.Fatal("not running")
	}
}

func TestSyncWithCancelledContextReturnsTheError(t *testing.T) {
	w := newWorld(t)
	ctx, cancel := context.WithCancel(bg)
	cancel()
	_, err := Sync(ctx, w.bob.data(), SyncOptions{Message: "x"})
	if err == nil || !errors.Is(err, context.Canceled) {
		if !git.IsKind(err, "aborted") {
			t.Fatalf("err = %v", err)
		}
	}
}
