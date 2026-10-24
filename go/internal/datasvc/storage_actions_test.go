package datasvc

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/gittest"
)

// The actions of the area Data that lose or move work when they go wrong: discard, branches,
// reattach, labels on the server, incoming changes and the storage settings.

func TestDiscardPreviewsAndKeepsATrashCopy(t *testing.T) {
	w := newWorld(t)
	path := filepath.Join(w.alice.root, "teams", "a", "2026.1.yaml")
	w.alice.write("a/2026.1.yaml", "velocity: 99\nscope_creep: 1\n")
	lost, err := w.alice.store.Lost(nil)
	if err != nil || len(lost) != 1 || !strings.HasSuffix(lost[0].File, "2026.1.yaml") {
		t.Fatalf("lost = %+v, %v", lost, err)
	}
	done := w.alice.store.Discard(nil)
	if done.Problem != nil || done.Status.Unsaved != 0 {
		t.Fatalf("discard = %+v", done)
	}
	if got, _ := os.ReadFile(path); !strings.Contains(string(got), "velocity: 10") {
		t.Fatalf("file = %q", got)
	}
	// The warning names the trash folder; the thrown-away value must be in it.
	trash := strings.TrimSuffix(strings.TrimPrefix(done.Warning, "What was discarded is kept in "), ".")
	found := false
	_ = filepath.WalkDir(trash, func(p string, d os.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			if b, _ := os.ReadFile(p); strings.Contains(string(b), "velocity: 99") {
				found = true
			}
		}
		return nil
	})
	if !found {
		t.Fatalf("no copy of the discarded value in the trash folder named by %q", done.Warning)
	}
}

func TestIncomingChangesListWhatOthersSaved(t *testing.T) {
	w := newWorld(t)
	if got := w.alice.store.IncomingChanges(); got == nil || len(got) != 0 {
		t.Fatalf("nothing incoming must be an empty list, got %#v", got)
	}
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	if res := w.bob.store.Save(SaveOptions{Message: "Sprint two"}); res.Outcome != OutcomeSaved {
		t.Fatalf("bob save = %+v", res)
	}
	w.alice.store.CheckForChanges()
	got := w.alice.store.IncomingChanges()
	if len(got) != 1 || got[0].Summary != "Sprint two" || got[0].Who != "Ben" {
		t.Fatalf("incoming = %+v", got)
	}
}

func TestBranchesAreSwitchedAndRefusedWithOpenChanges(t *testing.T) {
	w := newWorld(t)
	gittest.Git(t, w.alice.root, "branch", "other")
	list, err := w.alice.store.Branches()
	if err != nil || len(list) < 2 || list[0].Name != "main" || !list[0].Current {
		t.Fatalf("branches = %+v, %v", list, err)
	}
	if d := w.alice.store.SwitchBranch("other"); d.Problem != nil {
		t.Fatalf("switch = %+v", d)
	}
	if st := w.alice.store.Storage(); st.Branch != "other" {
		t.Fatalf("branch = %q", st.Branch)
	}
	w.alice.write("a/2026.1.yaml", "velocity: 55\nscope_creep: 1\n")
	if d := w.alice.store.SwitchBranch("main"); d.Problem == nil {
		t.Fatal("switching with unsaved changes must be refused")
	}
	if got, _ := os.ReadFile(filepath.Join(w.alice.root, "teams", "a", "2026.1.yaml")); !strings.Contains(string(got), "velocity: 55") {
		t.Fatalf("the unsaved change must stay: %q", got)
	}
	if st := w.alice.store.Storage(); st.Branch != "other" {
		t.Fatalf("a refused switch must stay on %q, is on %q", "other", st.Branch)
	}
	if d := w.alice.store.SwitchBranch("does-not-exist"); d.Problem == nil {
		t.Fatal("an unknown branch must be refused")
	}
}

func TestReattachKeepsWorkOfADetachedState(t *testing.T) {
	w := newWorld(t)
	gittest.Git(t, w.alice.root, "checkout", "-q", "--detach")
	w.alice.write("a/2026.2.yaml", "velocity: 3\n")
	res := w.alice.store.Save(SaveOptions{Message: "On no branch"})
	if res.Problem == nil || res.Problem.Kind != "detached" {
		t.Fatalf("saving on no branch must be refused as detached: %+v", res)
	}
	r := w.alice.store.Reattach()
	if r.Problem != nil || r.Branch != "main" || !r.Changes || r.Rescue == "" {
		t.Fatalf("reattach = %+v", r)
	}
	if got := gittest.Git(t, w.alice.root, "show", r.Rescue+":teams/a/2026.2.yaml"); !strings.Contains(got, "velocity: 3") {
		t.Fatalf("the rescue branch must hold the work: %q", got)
	}
	if st := w.alice.store.Status(); st.Unsaved != 0 {
		t.Fatalf("main must be clean after the rescue: %+v", st)
	}
}

func TestReattachKeepsCommitsOfADetachedState(t *testing.T) {
	w := newWorld(t)
	gittest.Git(t, w.alice.root, "checkout", "-q", "--detach")
	w.alice.write("a/2026.3.yaml", "velocity: 8\n")
	gittest.Git(t, w.alice.root, "add", "-A")
	gittest.Git(t, w.alice.root, "commit", "-q", "-m", "Lonely commit")
	r := w.alice.store.Reattach()
	if r.Problem != nil || !r.Commits || r.Rescue == "" {
		t.Fatalf("reattach = %+v", r)
	}
	if got := gittest.Git(t, w.alice.root, "show", r.Rescue+":teams/a/2026.3.yaml"); !strings.Contains(got, "velocity: 8") {
		t.Fatalf("the rescue branch must hold the commit: %q", got)
	}
}

func TestAbortMergeWithoutAMergeKeepsTheOwnWork(t *testing.T) {
	w := newWorld(t)
	w.alice.write("a/2026.2.yaml", "velocity: 4\n")
	st := w.alice.store.AbortMerge()
	if st.Unsaved != 1 {
		t.Fatalf("the own work must stay: %+v", st)
	}
}

func TestShareLabelPutsTheTagOnTheServer(t *testing.T) {
	w := newWorld(t)
	if d := w.alice.store.SetLabel("sprint-1", "", "Done"); d.Problem != nil {
		t.Fatalf("set = %+v", d)
	}
	if d := w.alice.store.ShareLabel("sprint-1"); d.Problem != nil {
		t.Fatalf("share = %+v", d)
	}
	if out := gittest.Git(t, w.tmp, "--git-dir", w.remote, "tag", "--list"); !strings.Contains(out, "sprint-1") {
		t.Fatalf("tags on the server: %q", out)
	}
	if d := w.alice.store.ShareLabel("missing"); d.Problem == nil {
		t.Fatal("sharing an unknown label must say so")
	}
}

func TestStorageSettingsAreWrittenAndRead(t *testing.T) {
	w := newWorld(t)
	if p := w.alice.store.SetHost("gitlab"); p != nil {
		t.Fatalf("host = %+v", p)
	}
	if p := w.alice.store.SetAutoMerge(true); p != nil {
		t.Fatalf("auto merge = %+v", p)
	}
	if p := w.alice.store.SetIdentity("Anna Example", "anna@example.org"); p != nil {
		t.Fatalf("identity = %+v", p)
	}
	// The identity goes to the global settings of the user (isolated in the test).
	if got := strings.TrimSpace(gittest.Git(t, w.tmp, "config", "--global", "user.name")); got != "Anna Example" {
		t.Fatalf("global user.name = %q", got)
	}
	if got := strings.TrimSpace(gittest.Git(t, w.tmp, "config", "--global", "user.email")); got != "anna@example.org" {
		t.Fatalf("global user.email = %q", got)
	}
	if w.alice.store.SetIdentity("", "anna@example.org") == nil || w.alice.store.SetIdentity("Anna", "no-address") == nil {
		t.Fatal("an empty name or an address without @ must be refused")
	}
	st := w.alice.store.Storage()
	if st.Host != "gitlab" || !st.AutoMerge {
		t.Fatalf("storage = %+v", st)
	}
	// An unknown kind means "detect from the address" again.
	if p := w.alice.store.SetHost("no-such-server"); p != nil || w.alice.store.Storage().Host != "" {
		t.Fatalf("unknown kind: %+v, host %q", p, w.alice.store.Storage().Host)
	}
	if g := w.alice.store.SignInGuide("gitlab"); g.Steps == "" {
		t.Fatalf("guide = %+v", g)
	}
}
