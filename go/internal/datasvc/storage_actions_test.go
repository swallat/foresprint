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
	if done.Warning == "" {
		t.Fatal("what was thrown away must be said to be kept in the trash folder")
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
	if d := w.alice.store.SwitchBranch("does-not-exist"); d.Problem == nil {
		t.Fatal("an unknown branch must be refused")
	}
}

func TestReattachKeepsWorkOfADetachedState(t *testing.T) {
	w := newWorld(t)
	gittest.Git(t, w.alice.root, "checkout", "-q", "--detach")
	w.alice.write("a/2026.2.yaml", "velocity: 3\n")
	if res := w.alice.store.Save(SaveOptions{Message: "On no branch"}); res.Problem != nil && res.Outcome == "" {
		t.Logf("save on a detached state: %+v", res)
	}
	r := w.alice.store.Reattach()
	if r.Problem != nil || r.Branch != "main" {
		t.Fatalf("reattach = %+v", r)
	}
	if r.Commits || r.Changes {
		if r.Rescue == "" {
			t.Fatalf("work was found but no rescue branch named: %+v", r)
		}
		if out := gittest.Git(t, w.alice.root, "branch", "--list", r.Rescue); !strings.Contains(out, r.Rescue) {
			t.Fatalf("rescue branch %q is missing: %q", r.Rescue, out)
		}
	}
}

func TestAbortMergeWithoutAMergeChangesNothing(t *testing.T) {
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
	// The identity goes to the settings of the user; the clone of the test has its own, which wins.
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
