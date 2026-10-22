package githistory

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/gittest"
)

var bg = context.Background()

const a1 = "teams/a/2026.1.yaml"

type env struct {
	t      *testing.T
	remote string
	root   string
	data   string
}

func (e *env) git(args ...string) string { e.t.Helper(); return gittest.Git(e.t, e.root, args...) }

func (e *env) write(rel, text string) {
	e.t.Helper()
	gittest.Write(e.t, filepath.Join(e.data, filepath.FromSlash(rel)), text)
	git.InvalidateStatus()
}

func (e *env) read(rel string) string {
	e.t.Helper()
	b, err := os.ReadFile(filepath.Join(e.data, filepath.FromSlash(rel)))
	if err != nil {
		e.t.Fatal(err)
	}
	return string(b)
}

func (e *env) exists(rel string) bool {
	_, err := os.Stat(filepath.Join(e.data, filepath.FromSlash(rel)))
	return err == nil
}

// commit saves all open changes as one commit and pushes it (like "Save and share").
func (e *env) commit(message string) {
	e.t.Helper()
	e.git("add", "-A")
	e.git("commit", "-qm", message)
	e.git("push", "-q")
	git.InvalidateStatus()
}

func newEnv(t *testing.T) *env {
	t.Helper()
	gittest.Isolate(t)
	git.ResetGitCache()
	git.InvalidateStatus()
	for _, who := range []string{"AUTHOR", "COMMITTER"} {
		for _, f := range []string{"NAME", "EMAIL"} {
			t.Setenv("GIT_"+who+"_"+f, "")
			_ = os.Unsetenv("GIT_" + who + "_" + f)
		}
	}
	tmp := t.TempDir()
	remote := filepath.Join(tmp, "server.git")
	gittest.Git(t, tmp, "init", "-q", "--bare", "-b", "main", remote)
	root := filepath.Join(tmp, "alice")
	gittest.Git(t, tmp, "init", "-q", "-b", "main", root)
	gittest.Git(t, root, "config", "user.name", "Alice")
	gittest.Git(t, root, "config", "user.email", "alice@example.org")
	gittest.Git(t, root, "remote", "add", "origin", remote)
	e := &env{t, remote, root, filepath.Join(root, "teams")}
	e.write("a/team.yaml", "name: A\n")
	e.write("a/2026.1.yaml", "velocity: 10\nscope_creep: 1\n")
	e.git("add", "-A")
	e.git("commit", "-qm", "Start")
	e.git("push", "-q", "-u", "origin", "main")
	return e
}

func TestDiscardPreviewAndSingleFile(t *testing.T) {
	e := newEnv(t)
	e.write("a/2026.1.yaml", "velocity: 99\nscope_creep: 1\n")
	e.write("a/new.yaml", "x: 1\ny: 2\n")
	if err := os.Remove(filepath.Join(e.data, "a", "team.yaml")); err != nil {
		t.Fatal(err)
	}
	git.InvalidateStatus()
	lost, err := DiscardPreview(bg, e.data, nil)
	if err != nil {
		t.Fatal(err)
	}
	by := map[string]Lost{}
	for _, l := range lost {
		by[l.File] = l
	}
	if l := by[a1]; l.Status != "M" || l.Added != 1 || l.Removed != 1 {
		t.Fatalf("modified = %+v", l)
	}
	if l := by["teams/a/new.yaml"]; l.Status != "??" || l.Added != 2 {
		t.Fatalf("new = %+v", l)
	}
	if by["teams/a/team.yaml"].Status != "D" {
		t.Fatalf("deleted = %+v", by["teams/a/team.yaml"])
	}
	trash, err := Discard(bg, e.data, []string{a1})
	if err != nil {
		t.Fatal(err)
	}
	if e.read("a/2026.1.yaml") != "velocity: 10\nscope_creep: 1\n" || !e.exists("a/new.yaml") {
		t.Fatal("wrong files discarded")
	}
	saved, err := os.ReadFile(filepath.Join(trash, filepath.FromSlash(a1)))
	if trash == "" || err != nil || !strings.HasPrefix(string(saved), "velocity: 99") {
		t.Fatalf("trash = %q err = %v", trash, err)
	}
	if !strings.Contains(trash, "sprintforecast-verworfen") {
		t.Fatalf("trash folder name changed: %q", trash)
	}
}

func TestDiscardEverythingIncludingNewAndDeletedFiles(t *testing.T) {
	e := newEnv(t)
	e.write("a/2026.1.yaml", "velocity: 99\n")
	e.write("a/new.yaml", "x: 1\n")
	if err := os.Remove(filepath.Join(e.data, "a", "team.yaml")); err != nil {
		t.Fatal(err)
	}
	e.git("add", "teams/a/new.yaml") // also a new file that is already staged
	git.InvalidateStatus()
	if _, err := Discard(bg, e.data, nil); err != nil {
		t.Fatal(err)
	}
	if e.git("status", "--porcelain") != "" || !e.exists("a/team.yaml") || e.exists("a/new.yaml") {
		t.Fatal("not discarded")
	}
	if _, err := Discard(bg, e.data, nil); err == nil || !strings.Contains(err.Error(), "No changes") {
		t.Fatalf("err = %v", err)
	}
}

func TestDiscardLeavesFilesOutsideTheDataFolder(t *testing.T) {
	e := newEnv(t)
	gittest.Write(t, filepath.Join(e.root, "other.txt"), "x")
	e.write("a/2026.1.yaml", "velocity: 99\n")
	if _, err := Discard(bg, e.data, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(e.root, "other.txt")); err != nil {
		t.Fatal("file outside was discarded")
	}
}

func TestHistoryByTeamAndFile(t *testing.T) {
	e := newEnv(t)
	e.write("a/2026.2.yaml", "velocity: 5\n")
	e.commit("Review 2026.2")
	e.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	e.commit("Fix 2026.1")
	team, err := History(bg, e.data, filepath.Join(e.data, "a"), 0)
	if err != nil {
		t.Fatal(err)
	}
	var subjects []string
	for _, x := range team {
		subjects = append(subjects, x.Subject)
	}
	if strings.Join(subjects, "|") != "Fix 2026.1|Review 2026.2|Start" {
		t.Fatalf("subjects = %v", subjects)
	}
	if team[0].Author != "Alice" || len(team[0].Files) != 1 || team[0].Files[0] != a1 || team[0].Merge {
		t.Fatalf("entry = %+v", team[0])
	}
	only, _ := History(bg, e.data, filepath.Join(e.data, "a", "2026.1.yaml"), 0)
	if len(only) != 2 || only[0].Subject != "Fix 2026.1" {
		t.Fatalf("only = %+v", only)
	}
}

func TestRestoreIsAChangeThatCanBeUndone(t *testing.T) {
	e := newEnv(t)
	e.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	e.commit("Fix")
	e.write("a/2026.9.yaml", "velocity: 1\n")
	e.commit("New sprint")
	hist, _ := History(bg, e.data, filepath.Join(e.data, "a"), 0)
	start := hist[len(hist)-1]
	newRev, err := RestoreVersion(bg, e.data, filepath.Join(e.data, "a"), start.Rev, "")
	if err != nil {
		t.Fatal(err)
	}
	if e.read("a/2026.1.yaml") != "velocity: 10\nscope_creep: 1\n" || e.exists("a/2026.9.yaml") {
		t.Fatal("not restored")
	}
	if !strings.HasPrefix(e.git("log", "-1", "--format=%s"), "State of ") || e.git("status", "--porcelain") != "" {
		t.Fatalf("log = %q", e.git("log", "-1", "--format=%s"))
	}
	if _, err := RevertCommit(bg, e.data, newRev); err != nil {
		t.Fatal(err)
	}
	if e.read("a/2026.1.yaml") != "velocity: 11\nscope_creep: 1\n" || !e.exists("a/2026.9.yaml") {
		t.Fatal("not taken back")
	}
}

func TestRestoreSingleFile(t *testing.T) {
	e := newEnv(t)
	e.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	e.commit("Fix")
	e.write("a/team.yaml", "name: B\n")
	e.commit("Name")
	file := filepath.Join(e.data, "a", "2026.1.yaml")
	hist, _ := History(bg, e.data, file, 0)
	if _, err := RestoreVersion(bg, e.data, file, hist[len(hist)-1].Rev, ""); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(e.read("a/2026.1.yaml"), "velocity: 10") || e.read("a/team.yaml") != "name: B\n" {
		t.Fatal("wrong files restored")
	}
}

func TestRestoreRefusesWithOpenChangesOrNoDifference(t *testing.T) {
	e := newEnv(t)
	hist, _ := History(bg, e.data, "", 0)
	head := hist[0]
	if _, err := RestoreVersion(bg, e.data, filepath.Join(e.data, "a"), head.Rev, ""); err == nil ||
		!strings.Contains(err.Error(), "already has exactly this state") {
		t.Fatalf("err = %v", err)
	}
	e.write("a/2026.1.yaml", "velocity: 99\n")
	if _, err := RestoreVersion(bg, e.data, filepath.Join(e.data, "a"), head.Rev, ""); git.KindOf(err) != "dirty" {
		t.Fatalf("err = %v", err)
	}
	if _, err := RevertCommit(bg, e.data, head.Rev); git.KindOf(err) != "dirty" {
		t.Fatalf("err = %v", err)
	}
}

func TestRevertWithConflictChangesNothing(t *testing.T) {
	e := newEnv(t)
	e.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	e.commit("First")
	hist, _ := History(bg, e.data, "", 0)
	first := hist[0]
	e.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
	e.commit("Second")
	if _, err := RevertCommit(bg, e.data, first.Rev); git.KindOf(err) != "conflict" {
		t.Fatalf("err = %v", err)
	}
	s, _ := gitsync.State(bg, e.data)
	if s.Unfinished != "" || e.git("status", "--porcelain") != "" {
		t.Fatalf("state = %+v", s)
	}
}

func TestMergesCannotBeReverted(t *testing.T) {
	e := newEnv(t)
	other := filepath.Join(filepath.Dir(e.root), "bob")
	gittest.MakeClone(t, e.remote, other, "Bob")
	gittest.Write(t, filepath.Join(other, "teams", "a", "2026.3.yaml"), "velocity: 7\n")
	gittest.Git(t, other, "add", "-A")
	gittest.Git(t, other, "commit", "-qm", "B")
	gittest.Git(t, other, "push", "-q")
	e.write("a/2026.2.yaml", "velocity: 5\n")
	e.git("add", "-A")
	e.git("commit", "-qm", "A")
	e.git("pull", "-q", "--no-rebase", "--no-edit")
	git.InvalidateStatus()
	hist, _ := History(bg, e.data, "", 0)
	var merge *Entry
	for i := range hist {
		if hist[i].Merge {
			merge = &hist[i]
		}
	}
	if merge == nil {
		t.Fatal("no merge in the history")
	}
	if _, err := RevertCommit(bg, e.data, merge.Rev); err == nil || !strings.Contains(err.Error(), "merge cannot be taken back") {
		t.Fatalf("err = %v", err)
	}
}

func TestRestoreRefusesAStateWithConflictMarkers(t *testing.T) {
	e := newEnv(t)
	e.write("a/2026.1.yaml", "<<<<<<< HEAD\nvelocity: 1\n=======\nvelocity: 2\n>>>>>>> origin/main\n")
	e.git("add", "-A")
	e.git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "broken")
	bad := e.git("rev-parse", "--short", "HEAD")
	e.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
	e.commit("Repaired")
	before := e.git("rev-parse", "HEAD")
	_, err := RestoreVersion(bg, e.data, filepath.Join(e.data, "a"), bad, "")
	if git.KindOf(err) != "conflict" || e.git("rev-parse", "HEAD") != before || e.git("status", "--porcelain") != "" {
		t.Fatalf("err = %v", err)
	}
	if !strings.HasPrefix(e.read("a/2026.1.yaml"), "velocity: 11") {
		t.Fatal("current state changed")
	}
	// reverting the repair would bring the markers back
	repair := e.git("rev-parse", "--short", "HEAD")
	if _, err := RevertCommit(bg, e.data, repair); git.KindOf(err) != "conflict" || e.git("rev-parse", "HEAD") != before {
		t.Fatalf("revert err = %v", err)
	}
}

func TestRestoreBacksUpIgnoredFilesItWouldOverwrite(t *testing.T) {
	e := newEnv(t)
	e.write("a/old.tmp", "old\n")
	e.git("add", "-f", "-A")
	e.git("commit", "-qm", "with tmp")
	first := e.git("rev-parse", "--short", "HEAD")
	e.git("rm", "-q", "--cached", "teams/a/old.tmp")
	gittest.Write(t, filepath.Join(e.root, ".gitignore"), "*.tmp\n")
	e.git("add", "-A")
	e.git("commit", "-qm", "ignore tmp")
	e.write("a/old.tmp", "mine\n")
	if _, err := RestoreVersion(bg, e.data, filepath.Join(e.data, "a"), first, ""); err != nil {
		t.Fatalf("restore: %v", err)
	}
	if e.read("a/old.tmp") != "old\n" {
		t.Fatalf("content = %q", e.read("a/old.tmp"))
	}
}

func TestTagsSetLaterListedAndDeletedAlsoOnServer(t *testing.T) {
	e := newEnv(t)
	e.write("a/2026.2.yaml", "velocity: 5\n")
	e.commit("Review 2026.2")
	hist, _ := History(bg, e.data, "", 0)
	first := hist[len(hist)-1]
	if tags, _ := ListTags(bg, e.data, false); len(tags) != 0 {
		t.Fatalf("tags = %+v", tags)
	}
	if w, err := SetTag(bg, e.data, "a/2026.1", first.Rev, "Review 2026.1"); w != nil || err != nil {
		t.Fatalf("warning = %v err = %v", w, err)
	}
	tags, _ := ListTags(bg, e.data, false)
	if len(tags) != 1 || tags[0].Name != "a/2026.1" || tags[0].Target != first.Short || tags[0].Subject != "Review 2026.1" {
		t.Fatalf("tags = %+v", tags)
	}
	if !strings.Contains(gittest.Git(t, e.remote, "tag"), "a/2026.1") {
		t.Fatal("not uploaded")
	}
	withServer, _ := ListTags(bg, e.data, true)
	if len(withServer) != 1 || withServer[0].OnServer == nil || !*withServer[0].OnServer || withServer[0].Differs {
		t.Fatalf("with server = %+v", withServer)
	}
	if _, err := SetTag(bg, e.data, "a/2026.1", "", ""); err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatalf("err = %v", err)
	}
	if _, err := SetTag(bg, e.data, "invalid name ~", "", ""); err == nil || !strings.Contains(err.Error(), "Invalid") {
		t.Fatalf("err = %v", err)
	}
	if w, err := DeleteTag(bg, e.data, "a/2026.1"); w != nil || err != nil {
		t.Fatalf("warning = %v err = %v", w, err)
	}
	if tags, _ := ListTags(bg, e.data, false); len(tags) != 0 || gittest.Git(t, e.remote, "tag") != "" {
		t.Fatal("tag not deleted")
	}
}

func TestTagOnServerForADifferentVersionIsNotCreated(t *testing.T) {
	e := newEnv(t)
	e.git("tag", "-a", "a/x", "-m", "x")
	e.git("push", "-q", "origin", "a/x")
	e.git("tag", "-d", "a/x")
	e.write("a/2026.2.yaml", "velocity: 5\n")
	e.commit("More")
	_, err := SetTag(bg, e.data, "a/x", "", "")
	if git.KindOf(err) != "tag_exists" {
		t.Fatalf("err = %v", err)
	}
	tags, _ := ListTags(bg, e.data, true)
	if len(tags) != 1 || tags[0].Local || tags[0].OnServer == nil || !*tags[0].OnServer {
		t.Fatalf("tags = %+v", tags)
	}
}

func TestTagsWithAnEmptySubjectOfTheOldestTag(t *testing.T) {
	e := newEnv(t)
	t.Setenv("GIT_COMMITTER_DATE", "2020-01-01T10:00:00")
	e.write("a/2026.2.yaml", "velocity: 5\n")
	e.git("add", "-A")
	e.git("commit", "-q", "--allow-empty-message", "-m", "")
	e.git("tag", "a/empty")
	t.Setenv("GIT_COMMITTER_DATE", "2021-01-01T10:00:00")
	e.write("a/2026.3.yaml", "velocity: 6\n")
	e.git("add", "-A")
	e.git("commit", "-qm", "Later")
	e.git("tag", "-a", "a/later", "-m", "With text")
	tags, _ := ListTags(bg, e.data, false)
	if len(tags) != 2 || tags[0].Name != "a/later" || tags[0].Subject != "With text" || tags[1].Name != "a/empty" || tags[1].Subject != "" {
		t.Fatalf("tags = %+v", tags)
	}
}

func TestATagMessageWithAUnicodeLineSeparatorStaysOneTag(t *testing.T) {
	e := newEnv(t)
	e.git("tag", "-a", "a/sep", "-m", "Release Notes: important")
	tags, _ := ListTags(bg, e.data, false)
	if len(tags) != 1 || tags[0].Name != "a/sep" {
		t.Fatalf("tags = %+v", tags)
	}
}

func TestTagUploadFailureIsAWarningAndTheTagStays(t *testing.T) {
	e := newEnv(t)
	e.git("remote", "set-url", "origin", filepath.Join(filepath.Dir(e.root), "disconnected", "data.git"))
	w, err := SetTag(bg, e.data, "a/local", "", "")
	if err != nil || w == nil {
		t.Fatalf("warning = %v err = %v", w, err)
	}
	if tags, _ := ListTags(bg, e.data, false); len(tags) != 1 || tags[0].Name != "a/local" {
		t.Fatalf("tags = %+v", tags)
	}
	if err := UploadTag(bg, e.data, "a/local"); err == nil {
		t.Fatal("upload to a missing server succeeded")
	}
	if ok, _ := ServerReachable(bg, e.data); ok {
		t.Fatal("server reachable")
	}
}
