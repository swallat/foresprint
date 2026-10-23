package app

import (
	"context"
	"github.com/swallat/foresprint/internal/config"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/datasvc"
	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/gittest"
)

// dataAPI returns an API whose data folder is a Git repository with a server, and the folder.
func dataAPI(t *testing.T) (*API, string) {
	t.Helper()
	gittest.Isolate(t)
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
	root := filepath.Join(tmp, "work")
	gittest.Git(t, tmp, "init", "-q", "-b", "main", root)
	gittest.Git(t, root, "config", "user.name", "Anna")
	gittest.Git(t, root, "config", "user.email", "anna@example.org")
	gittest.Git(t, root, "remote", "add", "origin", remote)
	dir := filepath.Join(root, "teams")
	gittest.Write(t, filepath.Join(dir, "a", "team.yaml"), "name: A\n")
	git.InvalidateStatus()
	return newAPI(t, dir), dir
}

func TestStatusAndSaveFollowTheStorage(t *testing.T) {
	api, dir := dataAPI(t)
	if st := api.Status(); st.Storage != StorageDirty || st.Data.Unsaved != 1 {
		t.Fatalf("before save: %+v", st)
	}
	res, err := api.Save()
	if err != nil || !res.OK || res.Outcome != datasvc.OutcomeSaved {
		t.Fatalf("save = %+v, %v", res, err)
	}
	if st := api.Status(); st.Storage != StorageSaved {
		t.Fatalf("after save: %+v", st)
	}
	res, _ = api.Save()
	if res.Outcome != datasvc.OutcomeNothing || res.Message == "" {
		t.Fatalf("second save = %+v", res)
	}
	gittest.Write(t, filepath.Join(dir, "a", "team.yaml"), "name: B\n")
	git.InvalidateStatus()
	lost, err := api.Lost([]string{}) // the window sends an empty list for "all"
	if err != nil || len(lost) != 1 {
		t.Fatalf("lost = %+v, %v", lost, err)
	}
	if d := api.Discard([]string{}); d.Problem != nil || d.Status.Unsaved != 0 {
		t.Fatalf("discard = %+v", d)
	}
	versions, err := api.History("", 10)
	if err != nil || len(versions) != 1 {
		t.Fatalf("history = %+v, %v", versions, err)
	}
	if c := api.Conflicts(); len(c) != 0 {
		t.Fatalf("conflicts = %+v", c)
	}
}

func TestNoFolderIsAProblemNotAPanic(t *testing.T) {
	api := newAPI(t, "")
	api.data.SetFolder("")
	if st := api.Status(); st.Storage != StorageProblem || st.Data.Problem == nil {
		t.Fatalf("status = %+v", st)
	}
	res, err := api.Save()
	if err != nil || res.OK || res.Message == "" {
		t.Fatalf("save = %+v, %v", res, err)
	}
}

func TestOpeningAFolderMakesItTheDataFolder(t *testing.T) {
	api := newAPI(t, "")
	gittest.Isolate(t)
	folder := filepath.Join(t.TempDir(), "new")
	o := api.CreateFolder(folder)
	if o.Problem != nil || o.Folder == "" {
		t.Fatalf("create = %+v", o)
	}
	if api.DataDir() != o.Folder || api.data.Folder() != o.Folder {
		t.Fatalf("data folder %q, store %q, want %q", api.DataDir(), api.data.Folder(), o.Folder)
	}
}

func TestOpenFileOnlyInsideTheDataFolder(t *testing.T) {
	a, dir := dataAPI(t)
	var opened string
	a.OpenPath = func(p string) error { opened = p; return nil }
	file := filepath.Join(dir, "a", "team.yaml")
	if err := a.OpenFile(file); err != nil {
		t.Fatal(err)
	}
	if want, _ := filepath.EvalSymlinks(file); opened != want {
		t.Fatalf("opened %q, want %q", opened, want)
	}
	opened = ""
	for _, bad := range []string{filepath.Join(dir, "..", "server.git", "HEAD"), filepath.Join(dir, "a"), filepath.Join(dir, "missing.md")} {
		if err := a.OpenFile(bad); err == nil || opened != "" {
			t.Fatalf("%s: err=%v opened=%q", bad, err, opened)
		}
	}
}

func TestPendingTagsShowWhatTheNextSaveSets(t *testing.T) {
	a, _ := dataAPI(t)
	a.addTag("a", "2026.22", "2026.22")
	got := a.PendingTags()
	if len(got) != 1 || got[0].Name != "2026.22" || !got[0].Ready {
		t.Fatalf("%+v", got)
	}
}

func TestOpenFileRefusesProgramsAndGit(t *testing.T) {
	a, dir := dataAPI(t)
	called := false
	a.OpenPath = func(string) error { called = true; return nil }
	for _, name := range []string{"run.bat", "tool.exe", "x.desktop", ".git/config"} {
		gittest.Write(t, filepath.Join(dir, name), "x")
		if err := a.OpenFile(filepath.Join(dir, name)); err == nil || called {
			t.Fatalf("%s: err=%v called=%v", name, err, called)
		}
	}
}

func TestPendingTagsGoWithTheDataFolder(t *testing.T) {
	a, dir := dataAPI(t)
	a.addTag("a", "2026.22", "2026.22")
	other := t.TempDir()
	if err := a.SetDataDir(other); err != nil {
		t.Fatal(err)
	}
	if got := a.PendingTags(); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
	_ = dir
}

func TestRecentFoldersMarkInUseAndMissing(t *testing.T) {
	a, dir := dataAPI(t)
	gone := t.TempDir()
	if err := config.SaveDataDir(gone); err != nil {
		t.Fatal(err)
	}
	if err := config.SaveDataDir(dir); err != nil {
		t.Fatal(err)
	}
	if err := os.RemoveAll(gone); err != nil {
		t.Fatal(err)
	}
	var inUse, missing int
	for _, f := range a.RecentFolders() {
		if f.InUse {
			inUse++
		}
		if f.Missing {
			missing++
		}
	}
	if inUse != 1 || missing != 1 {
		t.Fatalf("%+v", a.RecentFolders())
	}
}
