package datasvc

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/gittest"
)

type person struct {
	t     *testing.T
	root  string
	store *Store
}

func (p person) write(rel, text string) {
	p.t.Helper()
	gittest.Write(p.t, filepath.Join(p.root, "teams", filepath.FromSlash(rel)), text)
	git.InvalidateStatus()
}

type world struct {
	tmp, remote string
	alice, bob  person
}

func newPerson(t *testing.T, root string) person {
	return person{t, root, New(filepath.Join(root, "teams"))}
}

func newWorld(t *testing.T) *world {
	t.Helper()
	gittest.Isolate(t)
	for _, who := range []string{"AUTHOR", "COMMITTER"} {
		for _, f := range []string{"NAME", "EMAIL"} {
			_ = os.Unsetenv("GIT_" + who + "_" + f)
		}
	}
	git.ResetGitCache()
	git.InvalidateStatus()
	gitsync.SetCodec(gittest.FlatCodec{})
	gitsync.SetValidator(func(context.Context, string, time.Time) ([]gitsync.Issue, error) { return nil, nil })
	t.Cleanup(func() {
		gitsync.SetCodec(nil)
		gitsync.SetValidator(nil)
		git.InvalidateStatus()
	})
	tmp := t.TempDir()
	remote := filepath.Join(tmp, "server.git")
	gittest.Git(t, tmp, "init", "-q", "--bare", "-b", "main", remote)
	aliceRoot := filepath.Join(tmp, "alice")
	gittest.Git(t, tmp, "init", "-q", "-b", "main", aliceRoot)
	gittest.Git(t, aliceRoot, "config", "user.name", "Anna")
	gittest.Git(t, aliceRoot, "config", "user.email", "anna@example.org")
	gittest.Git(t, aliceRoot, "remote", "add", "origin", remote)
	alice := newPerson(t, aliceRoot)
	alice.write("a/team.yaml", "name: A\n")
	alice.write("a/2026.1.yaml", "velocity: 10\nscope_creep: 1\n")
	if res := alice.store.Save(SaveOptions{Message: "Start"}); res.Outcome != OutcomeSaved {
		t.Fatalf("first save = %+v", res)
	}
	bobRoot := gittest.MakeClone(t, remote, filepath.Join(tmp, "bob"), "Ben")
	return &world{tmp, remote, alice, newPerson(t, bobRoot)}
}

func TestSaveAndRefreshShowAsTheChip(t *testing.T) {
	w := newWorld(t)
	if st := w.alice.store.Status(); st.Chip.State != ChipOK || !st.Configured || st.Location == "" {
		t.Fatalf("status = %+v", st)
	}
	w.alice.write("a/2026.2.yaml", "velocity: 7\n")
	if st := w.alice.store.Status(); st.Chip.State != ChipUnsaved || st.Unsaved != 1 {
		t.Fatalf("unsaved: %+v", st.Chip)
	}
	if res := w.alice.store.Save(SaveOptions{Message: "Sprint 2"}); res.Outcome != OutcomeSaved || res.Status.Chip.State != ChipOK {
		t.Fatalf("save = %+v", res)
	}
	if res := w.alice.store.Save(SaveOptions{}); res.Outcome != OutcomeNothing {
		t.Fatalf("second save = %+v", res)
	}
	st := w.bob.store.CheckForChanges()
	if st.Chip.State != ChipIncoming || st.Incoming != 1 || !strings.Contains(st.Chip.Text, "1 new change from Anna") {
		t.Fatalf("bob sees %+v", st)
	}
	res := w.bob.store.Refresh()
	if res.Outcome != OutcomeSaved || len(res.Taken) != 1 || res.Taken[0].Who != "Anna" || res.Status.Chip.State != ChipOK {
		t.Fatalf("refresh = %+v", res)
	}
}

func TestConflictIsDecidedAndSaved(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
	w.alice.store.Save(SaveOptions{Message: "Anna"})
	w.bob.write("a/2026.1.yaml", "velocity: 8\nscope_creep: 1\n")
	res := w.bob.store.Save(SaveOptions{Message: "Ben"})
	if res.Outcome != OutcomeConflict || res.Conflicts != 1 || res.Status.Chip.State != ChipConflict {
		t.Fatalf("save = %+v", res)
	}
	list := w.bob.store.Conflicts()
	if len(list) != 1 || len(list[0].Entries) != 1 {
		t.Fatalf("conflicts = %+v", list)
	}
	e := list[0].Entries[0]
	if e.Mine != "8" || e.Theirs != "12" || e.Before != "10" || !e.HasBefore || e.Label != "velocity" {
		t.Fatalf("entry = %+v", e)
	}
	if r := w.bob.store.ResolveConflicts([]Decision{{File: list[0].File, Path: e.Path, Choice: Theirs}}); r.Conflicts != 0 || r.Outcome != OutcomeDecided || r.Status.Chip.State != ChipDecided || r.Status.Conflicts != 0 {
		t.Fatalf("resolve = %+v", r)
	}
	if res := w.bob.store.Save(SaveOptions{Message: "Ben"}); res.Outcome != OutcomeSaved || res.Status.Chip.State != ChipOK {
		t.Fatalf("final save = %+v", res)
	}
	if got, _ := os.ReadFile(filepath.Join(w.bob.root, "teams", "a", "2026.1.yaml")); !strings.Contains(string(got), "velocity: 12") {
		t.Fatalf("file = %q", got)
	}
}

func TestTakeTheirsSettlesEverything(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
	w.alice.store.Save(SaveOptions{Message: "Anna"})
	w.bob.write("a/2026.1.yaml", "velocity: 8\nscope_creep: 1\n")
	w.bob.store.Save(SaveOptions{Message: "Ben"})
	if r := w.bob.store.TakeTheirs(); r.Conflicts != 0 {
		t.Fatalf("take theirs = %+v", r)
	}
}

// A server that refuses the direct upload gets the work on an own branch (D4).
func TestProtectedBranchFallsBackToAReviewBranch(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the server hook is a shell script")
	}
	w := newWorld(t)
	hook := filepath.Join(w.remote, "hooks", "pre-receive")
	gittest.Write(t, hook, "#!/bin/sh\nwhile read old new ref; do\n"+
		"  if [ \"$ref\" = refs/heads/main ]; then echo 'remote: GitLab: You are not allowed to push code to protected branches on this project.' >&2; exit 1; fi\n"+
		"done\n")
	if err := os.Chmod(hook, 0o755); err != nil {
		t.Fatal(err)
	}
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.store.Save(SaveOptions{Message: "Sprint 2"})
	if res.Outcome != OutcomeWaitingForReview || res.Status.Chip.State != ChipWaitingForReview {
		t.Fatalf("save = %+v", res)
	}
	if got := w.bob.store.Storage().Share; got != gitsync.ShareMergeRequest {
		t.Fatalf("share = %q", got)
	}
	if !strings.Contains(gittest.Git(t, w.remote, "branch", "--list"), "foresprint") &&
		!strings.Contains(gittest.Git(t, w.remote, "branch", "--list"), "sprintforecast") {
		t.Fatalf("branches: %s", gittest.Git(t, w.remote, "branch", "--list"))
	}
}

func TestHistoryRestoreAndRevert(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
	w.alice.store.Save(SaveOptions{Message: "Raise velocity"})
	list, err := w.alice.store.History("a", 0)
	if err != nil || len(list) != 2 || list[0].Summary != "Raise velocity" || list[0].Who != "Anna" {
		t.Fatalf("history = %+v, %v", list, err)
	}
	done := w.alice.store.Restore("a", list[1].ID, "")
	if done.Problem != nil || done.Version == "" {
		t.Fatalf("restore = %+v", done)
	}
	if got, _ := os.ReadFile(filepath.Join(w.alice.root, "teams", "a", "2026.1.yaml")); !strings.Contains(string(got), "velocity: 10") {
		t.Fatalf("file = %q", got)
	}
	if st := w.alice.store.Status(); st.Chip.State != ChipPending {
		t.Fatalf("status = %+v", st.Chip)
	}
	if done := w.alice.store.Revert(done.Version); done.Problem != nil {
		t.Fatalf("revert = %+v", done)
	}
	if _, err := w.alice.store.History("../outside", 0); err == nil {
		t.Fatal("a scope outside the data folder must be refused")
	}
}

func TestLabelsAreListedAndRemoved(t *testing.T) {
	w := newWorld(t)
	if d := w.alice.store.SetLabel("sprint-1", "", "Done"); d.Problem != nil {
		t.Fatalf("set = %+v", d)
	}
	labels, err := w.alice.store.Labels(false)
	if err != nil || len(labels) != 1 || labels[0].Name != "sprint-1" {
		t.Fatalf("labels = %+v, %v", labels, err)
	}
	if d := w.alice.store.DeleteLabel("sprint-1"); d.Problem != nil {
		t.Fatalf("delete = %+v", d)
	}
}

func TestStorageSettingsHideCredentialsAndOfferChoices(t *testing.T) {
	w := newWorld(t)
	s := w.bob.store.Storage()
	if !s.Ready || s.Share != gitsync.ShareDirect || !s.AutoMerge || s.Server == "" || len(s.Hosts) == 0 {
		t.Fatalf("settings = %+v", s)
	}
	if s.Name != "Ben" {
		t.Fatalf("name = %q", s.Name)
	}
	if p := w.bob.store.SetShare("merge_request"); p != nil {
		t.Fatal(p)
	}
	if got := w.bob.store.Storage().Share; got != gitsync.ShareMergeRequest {
		t.Fatalf("share = %q", got)
	}
	if p := w.bob.store.SetShare("nonsense"); p == nil {
		t.Fatal("an unknown way to share must be refused")
	}
}

func TestOpenAndCreateFolders(t *testing.T) {
	w := newWorld(t)
	s := New("")
	if st := s.Status(); st.Problem == nil || st.Chip.State != ChipProblem {
		t.Fatalf("status without folder = %+v", st)
	}
	created := s.CreateFolder(filepath.Join(w.tmp, "fresh"))
	if created.Problem != nil || !strings.HasSuffix(filepath.ToSlash(created.Folder), "fresh/teams") {
		t.Fatalf("create = %+v", created)
	}
	if st := s.Status(); st.Configured || st.Chip.State == ChipOK {
		t.Fatalf("fresh status = %+v", st.Chip)
	}
	cloned := New("").CloneFrom(w.remote, filepath.Join(w.tmp, "copy"))
	if cloned.Problem != nil {
		t.Fatalf("clone = %+v", cloned)
	}
	if opened := New("").OpenFolder(filepath.Join(w.tmp, "nowhere")); opened.Problem == nil {
		t.Fatal("a folder that is no repository must be refused")
	}
}

func TestSaveWithoutServerCommitsLocally(t *testing.T) {
	w := newWorld(t)
	s := New("")
	created := s.CreateFolder(filepath.Join(w.tmp, "local"))
	if created.Problem != nil {
		t.Fatal(created.Problem)
	}
	gittest.Git(t, filepath.Dir(created.Folder), "config", "user.name", "Mia")
	gittest.Git(t, filepath.Dir(created.Folder), "config", "user.email", "mia@example.org")
	gittest.Write(t, filepath.Join(created.Folder, "a", "team.yaml"), "name: A\n")
	git.InvalidateStatus()
	if res := s.Save(SaveOptions{Message: "First"}); res.Outcome != OutcomeSaved || res.Problem != nil {
		t.Fatalf("save = %+v", res)
	}
	if res := s.Save(SaveOptions{}); res.Outcome != OutcomeNothing || res.Problem != nil {
		t.Fatalf("second save = %+v", res)
	}
	if res := s.Refresh(); res.Outcome != OutcomeNothing || res.Problem != nil {
		t.Fatalf("refresh = %+v", res)
	}
	if st := s.Status(); st.Chip.State != ChipLocal {
		t.Fatalf("status = %+v", st.Chip)
	}
}

// Without a folder nothing may act on the repository of the current directory.
func TestNoFolderTouchesNothing(t *testing.T) {
	s := New("")
	checks := map[string]bool{
		"Save":     s.Save(SaveOptions{}).Problem != nil,
		"Refresh":  s.Refresh().Problem != nil,
		"Revert":   s.Revert("HEAD").Problem != nil,
		"Restore":  s.Restore("", "HEAD", "").Problem != nil,
		"Discard":  s.Discard(nil).Problem != nil,
		"Reattach": s.Reattach().Problem != nil,
		"Switch":   s.SwitchBranch("main").Problem != nil,
		"SetLabel": s.SetLabel("x", "", "").Problem != nil,
		"Server":   s.SaveServer("https://example.org/x.git", ServerOptions{}).Problem != nil,
		"Storage":  s.Storage().Problem != nil && !s.Storage().Ready,
		"Share":    s.SetShare("direct") != nil,
	}
	if _, err := s.History("", 0); err == nil {
		t.Error("History worked without a folder")
	}
	if _, err := s.Labels(false); err == nil {
		t.Error("Labels worked without a folder")
	}
	if _, err := s.Branches(); err == nil {
		t.Error("Branches worked without a folder")
	}
	for name, refused := range checks {
		if !refused {
			t.Errorf("%s did not refuse without a folder", name)
		}
	}
}

// Only a refusal because of a protected branch switches to merge requests (D4).
func TestOtherHookRefusalsKeepDirectSharing(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the server hook is a shell script")
	}
	w := newWorld(t)
	hook := filepath.Join(w.remote, "hooks", "pre-receive")
	gittest.Write(t, hook, "#!/bin/sh\necho 'remote: file too large' >&2\nexit 1\n")
	if err := os.Chmod(hook, 0o755); err != nil {
		t.Fatal(err)
	}
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.store.Save(SaveOptions{Message: "Sprint 2"})
	if res.Outcome != OutcomeProblem {
		t.Fatalf("save = %+v", res)
	}
	if got := w.bob.store.Storage().Share; got != gitsync.ShareDirect {
		t.Fatalf("share = %q", got)
	}
}

func TestFallbackKeepsWhatWasTakenOver(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the server hook is a shell script")
	}
	w := newWorld(t)
	w.alice.write("a/2026.3.yaml", "velocity: 9\n")
	w.alice.store.Save(SaveOptions{Message: "Anna's change"})
	hook := filepath.Join(w.remote, "hooks", "pre-receive")
	gittest.Write(t, hook, "#!/bin/sh\nwhile read old new ref; do\n"+
		"  if [ \"$ref\" = refs/heads/main ]; then echo 'remote: GitLab: You are not allowed to push code to protected branches on this project.' >&2; exit 1; fi\n"+
		"done\n")
	if err := os.Chmod(hook, 0o755); err != nil {
		t.Fatal(err)
	}
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.store.Save(SaveOptions{Message: "Sprint 2"})
	if res.Outcome != OutcomeWaitingForReview || len(res.Taken) != 1 || res.Taken[0].Who != "Anna" || len(res.Notes) == 0 {
		t.Fatalf("save = %+v", res)
	}
}

func TestCloneUsesTheTeamsFolder(t *testing.T) {
	w := newWorld(t)
	cloned := New("").CloneFrom(w.remote, filepath.Join(w.tmp, "copy"))
	if cloned.Problem != nil || !strings.HasSuffix(filepath.ToSlash(cloned.Folder), "copy/teams") {
		t.Fatalf("clone = %+v", cloned)
	}
}
