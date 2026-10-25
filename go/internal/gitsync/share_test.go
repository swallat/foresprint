package gitsync

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gittest"
)

// gitlabLike makes the server accept push options and answer like GitLab; it records the options.
func gitlabLike(t *testing.T, remote string) string {
	t.Helper()
	needShell(t)
	gittest.Git(t, remote, "config", "receive.advertisePushOptions", "true")
	log := filepath.Join(remote, "push-options.log")
	hook := filepath.Join(remote, "hooks", "post-receive")
	gittest.Write(t, hook, "#!/bin/sh\n"+
		"i=0; line=\"$GIT_PUSH_OPTION_COUNT\"\n"+
		"while [ \"$i\" -lt \"$GIT_PUSH_OPTION_COUNT\" ]; do\n"+
		"  eval \"line=\\\"\\$line:\\$GIT_PUSH_OPTION_$i\\\"\"; i=$((i+1))\n"+
		"done\n"+
		"echo \"$line\" >> \""+log+"\"\n"+
		"echo \"remote: View merge request for x:\" >&2\n"+
		"echo \"remote:   https://gitlab.example.org/team/data/-/merge_requests/7\" >&2\n")
	if err := os.Chmod(hook, 0o755); err != nil {
		t.Fatal(err)
	}
	return log
}

func readLog(path string) string {
	b, _ := os.ReadFile(path)
	return string(b)
}

func mrMode(t *testing.T, p person, host string) {
	t.Helper()
	if err := SetShareMode(bg, p.data(), ShareMergeRequest); err != nil {
		t.Fatal(err)
	}
	if host != "" {
		if err := SetHost(bg, p.data(), host); err != nil {
			t.Fatal(err)
		}
	}
}

func TestShareViaMergeRequestPushesOwnBranch(t *testing.T) {
	w := newWorld(t)
	log := gitlabLike(t, w.remote)
	mrMode(t, w.bob, "gitlab")
	mainBefore := gittest.Git(t, w.remote, "rev-parse", "main")
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.sync("Sprint 2 planned")
	if res.Error != nil || !res.Pushed {
		t.Fatalf("result = %+v", res)
	}
	branch := res.MergeRequestBranch
	if !strings.HasPrefix(branch, "sprintforecast/bob-") || res.MergeRequestURL != "https://gitlab.example.org/team/data/-/merge_requests/7" {
		t.Fatalf("branch = %q url = %q", branch, res.MergeRequestURL)
	}
	if gittest.Git(t, w.remote, "rev-parse", "main") != mainBefore {
		t.Fatal("main changed")
	}
	if gittest.Git(t, w.remote, "log", "-1", "--format=%s", branch) != "Sprint 2 planned" {
		t.Fatal("branch has the wrong commit")
	}
	opts := readLog(log)
	if !strings.Contains(opts, "merge_request.create") || !strings.Contains(opts, "merge_request.target=main") {
		t.Fatalf("options = %q", opts)
	}
	again := w.bob.sync("again")
	if again.Error != nil || gittest.Git(t, w.remote, "rev-parse", "main") != mainBefore {
		t.Fatalf("again = %+v", again)
	}
}

func TestShareModeDefaultsToDirect(t *testing.T) {
	w := newWorld(t)
	if m, _ := ShareMode(bg, w.alice.data()); m != ShareDirect {
		t.Fatalf("mode = %q", m)
	}
	mrMode(t, w.alice, "")
	if err := SetShareMode(bg, w.alice.data(), ShareDirect); err != nil {
		t.Fatal(err)
	}
	if m, _ := ShareMode(bg, w.alice.data()); m != ShareDirect {
		t.Fatalf("mode = %q", m)
	}
}

func TestLegacyShareKeyIsStillRead(t *testing.T) {
	w := newWorld(t)
	w.alice.git("config", "--local", "sprintforecast.share", "merge_request")
	if m, _ := ShareMode(bg, w.alice.data()); m != ShareMergeRequest {
		t.Fatalf("mode = %q", m)
	}
	if err := SetShareMode(bg, w.alice.data(), ShareDirect); err != nil {
		t.Fatal(err)
	}
	if out, _ := git.Lenient(bg, w.alice.root, "config", "--local", "--get", "sprintforecast.share"); out != "" {
		t.Fatalf("legacy key stays: %q", out)
	}
}

func squash(t *testing.T, w *world, name string, files map[string]string) {
	t.Helper()
	dir := filepath.Join(w.tmp, name)
	gittest.Git(t, w.tmp, "clone", "-q", w.remote, dir)
	gittest.Git(t, dir, "config", "user.name", "S")
	gittest.Git(t, dir, "config", "user.email", "s@example.org")
	for rel, text := range files {
		gittest.Write(t, filepath.Join(dir, "teams", "a", rel), text)
	}
	gittest.Git(t, dir, "add", "-A")
	gittest.Git(t, dir, "commit", "-qm", "Squash")
	gittest.Git(t, dir, "push", "-q", "origin", "main")
}

func TestMergeRequestSquashMergeDoesNotStayAhead(t *testing.T) {
	w := newWorld(t)
	gitlabLike(t, w.remote)
	mrMode(t, w.bob, "gitlab")
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	if first := w.bob.sync("Sprint 2"); first.Error != nil {
		t.Fatalf("first = %+v", first)
	}
	squash(t, w, "squasher", map[string]string{"2026.2.yaml": "velocity: 7\n"})
	again := w.bob.sync("again")
	if again.Error != nil || again.MergeRequestURL != "" {
		t.Fatalf("again = %+v", again)
	}
	if s := w.bob.state(); s.Ahead != 0 || s.Behind != 0 {
		t.Fatalf("state = %+v", s)
	}
}

func TestMergeRequestBranchIsOverwrittenWhenItDiverged(t *testing.T) {
	w := newWorld(t)
	gitlabLike(t, w.remote)
	mrMode(t, w.bob, "gitlab")
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	branch := w.bob.sync("one").MergeRequestBranch
	gittest.Git(t, w.remote, "update-ref", "refs/heads/"+branch, gittest.Git(t, w.remote, "rev-parse", "main"))
	w.bob.write("a/2026.3.yaml", "velocity: 8\n")
	res := w.bob.sync("two")
	if res.Error != nil || !res.Pushed || gittest.Git(t, w.remote, "log", "-1", "--format=%s", branch) != "two" {
		t.Fatalf("result = %+v", res)
	}
}

func TestMergeRequestAutoMergeOptionAndPullNote(t *testing.T) {
	w := newWorld(t)
	log := gitlabLike(t, w.remote)
	mrMode(t, w.bob, "gitlab")
	if on, _ := AutoMerge(bg, w.bob.data()); !on {
		t.Fatal("auto-merge should default to on")
	}
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	if res := w.bob.sync("with auto-merge"); res.Error != nil {
		t.Fatalf("result = %+v", res)
	}
	if !strings.Contains(readLog(log), "merge_request.merge_when_pipeline_succeeds") {
		t.Fatal("no auto-merge option")
	}
	pulled := w.bob.syncWith(SyncOptions{Message: "pull", PullOnly: true})
	if pulled.Error != nil || len(pulled.Notes) != 1 || !strings.Contains(pulled.Notes[0], "merge request is still open") {
		t.Fatalf("pulled = %+v", pulled)
	}
	if err := SetAutoMerge(bg, w.bob.data(), false); err != nil {
		t.Fatal(err)
	}
	if on, _ := AutoMerge(bg, w.bob.data()); on {
		t.Fatal("still on")
	}
	if err := os.WriteFile(log, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	w.bob.write("a/2026.3.yaml", "velocity: 8\n")
	if res := w.bob.sync("without"); res.Error != nil {
		t.Fatalf("result = %+v", res)
	}
	if strings.Contains(readLog(log), "merge_when_pipeline_succeeds") {
		t.Fatal("option still sent")
	}
}

func TestPullNoteNotShownAfterSquashMerge(t *testing.T) {
	w := newWorld(t)
	gitlabLike(t, w.remote)
	mrMode(t, w.bob, "gitlab")
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	w.bob.sync("Sprint 2")
	w.bob.write("a/2026.3.yaml", "velocity: 8\n")
	w.bob.git("add", "-A")
	w.bob.git("commit", "-qm", "local")
	notes := w.bob.syncWith(SyncOptions{Message: "pull", PullOnly: true}).Notes
	if len(notes) == 0 || !strings.Contains(notes[0], "not shared") {
		t.Fatalf("notes = %v", notes)
	}
	squash(t, w, "squasher2", map[string]string{"2026.2.yaml": "velocity: 7\n", "2026.3.yaml": "velocity: 8\n"})
	if notes := w.bob.syncWith(SyncOptions{Message: "pull", PullOnly: true}).Notes; len(notes) != 0 {
		t.Fatalf("notes = %v", notes)
	}
}

func TestHostIsDetectedFromTheAddress(t *testing.T) {
	for url, host := range map[string]string{
		"https://github.com/o/r.git":                HostGitHub,
		"git@github.com:o/r.git":                    HostGitHub,
		"https://gitlab.example.org/team/data.git":  HostGitLab,
		"ssh://git@gitlab.example.org:2222/t/d.git": HostGitLab,
		"https://codeberg.org/o/r":                  HostForgejo,
		"https://gitea.example.org/o/r.git":         HostForgejo,
		"https://git.example.org/team/data.git":     HostGeneric,
		"/srv/git/data.git":                         HostGeneric,
	} {
		if got := DetectHost(url); got != host {
			t.Errorf("DetectHost(%q) = %q, want %q", url, got, host)
		}
	}
}

func TestCompareURLForGitHub(t *testing.T) {
	if got := CompareURL("git@github.com:o/r.git", "main", "sprintforecast/bob-1"); got != "https://github.com/o/r/compare/main...sprintforecast/bob-1?expand=1" {
		t.Fatalf("got %q", got)
	}
	for _, url := range []string{"/srv/git/data.git", `C:\data\repo`} {
		if got := CompareURL(url, "main", "x"); got != "" {
			t.Errorf("CompareURL(%q) = %q", url, got)
		}
	}
	if got := CompareURL("github.com:o/r.git", "main", "b"); got != "https://github.com/o/r/compare/main...b?expand=1" {
		t.Fatalf("got %q", got)
	}
}

func TestHostSettingOverridesDetection(t *testing.T) {
	w := newWorld(t)
	if h, _ := HostSetting(bg, w.bob.data()); h != "" {
		t.Fatalf("setting = %q", h)
	}
	if k, _ := HostKind(bg, w.bob.data()); k != HostGeneric {
		t.Fatalf("kind = %q", k)
	}
	_ = SetHost(bg, w.bob.data(), HostGitHub)
	if k, _ := HostKind(bg, w.bob.data()); k != HostGitHub {
		t.Fatalf("kind = %q", k)
	}
	_ = SetHost(bg, w.bob.data(), "")
	if h, _ := HostSetting(bg, w.bob.data()); h != "" {
		t.Fatalf("setting = %q", h)
	}
}

func TestGitHubFlowPushesOnlyTheBranchWithoutPushOptions(t *testing.T) {
	w := newWorld(t)
	log := gitlabLike(t, w.remote)
	mrMode(t, w.bob, HostGitHub)
	mainBefore := gittest.Git(t, w.remote, "rev-parse", "main")
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.sync("Sprint 2")
	if res.Error != nil || res.MergeRequestBranch == "" {
		t.Fatalf("result = %+v", res)
	}
	if gittest.Git(t, w.remote, "rev-parse", "main") != mainBefore {
		t.Fatal("main changed")
	}
	gittest.Git(t, w.remote, "rev-parse", "--verify", "refs/heads/"+res.MergeRequestBranch)
	if strings.Contains(readLog(log), "merge_request") {
		t.Fatal("push options sent")
	}
}

func TestUnknownServerWithoutPushOptionsStillGetsTheBranch(t *testing.T) {
	w := newWorld(t)
	mrMode(t, w.bob, "")
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.sync("Sprint 2")
	if res.Error != nil || res.MergeRequestURL != "" {
		t.Fatalf("result = %+v", res)
	}
	gittest.Git(t, w.remote, "rev-parse", "--verify", "refs/heads/"+res.MergeRequestBranch)
}

func TestUnknownServerWithPushOptionsGetsAMergeRequest(t *testing.T) {
	w := newWorld(t)
	log := gitlabLike(t, w.remote)
	mrMode(t, w.bob, "")
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.sync("Sprint 2")
	if res.Error != nil || res.MergeRequestURL == "" || !strings.Contains(readLog(log), "merge_request.create") {
		t.Fatalf("result = %+v", res)
	}
}

func TestForgejoUsesTheAGitFlow(t *testing.T) {
	needShell(t)
	w := newWorld(t)
	gittest.Git(t, w.remote, "config", "receive.advertisePushOptions", "true")
	log := filepath.Join(w.remote, "agit.log")
	hook := filepath.Join(w.remote, "hooks", "post-receive")
	gittest.Write(t, hook, "#!/bin/sh\necho \"$GIT_PUSH_OPTION_0|$GIT_PUSH_OPTION_1\" >> \""+log+"\"\n"+
		"echo \"remote: Visit the new pull request:\" >&2\n"+
		"echo \"remote:   https://forgejo.example.org/team/data/pulls/4\" >&2\n")
	_ = os.Chmod(hook, 0o755)
	mrMode(t, w.bob, HostForgejo)
	mainBefore := gittest.Git(t, w.remote, "rev-parse", "main")
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.sync("Sprint 2")
	if res.Error != nil || res.MergeRequestURL != "https://forgejo.example.org/team/data/pulls/4" {
		t.Fatalf("result = %+v", res)
	}
	if gittest.Git(t, w.remote, "rev-parse", "main") != mainBefore {
		t.Fatal("main changed")
	}
	gittest.Git(t, w.remote, "rev-parse", "--verify", "refs/for/main")
	if !strings.Contains(readLog(log), "topic="+res.MergeRequestBranch) {
		t.Fatalf("log = %q", readLog(log))
	}
}

func TestForgejoWithoutAGitFallsBackToTheBranch(t *testing.T) {
	needShell(t)
	w := newWorld(t)
	hook := filepath.Join(w.remote, "hooks", "pre-receive")
	gittest.Write(t, hook, "#!/bin/sh\nwhile read old new ref; do case \"$ref\" in refs/for/*) exit 1;; esac; done\n")
	_ = os.Chmod(hook, 0o755)
	gittest.Git(t, w.remote, "config", "receive.advertisePushOptions", "true")
	mrMode(t, w.bob, HostForgejo)
	w.bob.write("a/2026.2.yaml", "velocity: 7\n")
	res := w.bob.sync("Sprint 2")
	if res.Error != nil {
		t.Fatalf("result = %+v", res)
	}
	gittest.Git(t, w.remote, "rev-parse", "--verify", "refs/heads/"+res.MergeRequestBranch)
}

func TestSetRemoteChecksBeforeSaving(t *testing.T) {
	setup(t)
	tmp := t.TempDir()
	server := gittest.MakeServer(t, tmp, "server.git", "main")
	root := gittest.MakeLocal(t, tmp, "work", true)
	saved, err := SetRemote(bg, filepath.Join(root, "teams"), server, SetRemoteOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if saved.Name != "origin" || !saved.Verified {
		t.Fatalf("saved = %+v", saved)
	}
	info, err := GetRemoteInfo(bg, root)
	if err != nil || info.Name != "origin" || info.Branch != "main" {
		t.Fatalf("info = %+v err = %v", info, err)
	}
	// a folder that does not exist is no repository: never saved
	gone := filepath.Join(tmp, "gone", "data.git")
	if _, err := SetRemote(bg, root, gone, SetRemoteOptions{}); err == nil {
		t.Fatal("unreachable server was saved")
	}
}

func TestBranchesAndSwitch(t *testing.T) {
	setup(t)
	root := gittest.MakeLocal(t, t.TempDir(), "work", true)
	gittest.Git(t, root, "branch", "other")
	found, err := Branches(bg, root)
	if err != nil || len(found) != 2 || found[0].Name != "main" || !found[0].Current || found[1].Name != "other" {
		t.Fatalf("branches = %+v err = %v", found, err)
	}
	gittest.Write(t, filepath.Join(root, "teams", "team.yaml"), "name: B\n")
	git.InvalidateStatus()
	if _, err := SwitchBranch(bg, filepath.Join(root, "teams"), "other"); err == nil {
		t.Fatal("switched with open changes")
	}
	gittest.Git(t, root, "checkout", "--", ".")
	git.InvalidateStatus()
	if name, err := SwitchBranch(bg, filepath.Join(root, "teams"), "other"); err != nil || name != "other" {
		t.Fatalf("name = %q err = %v", name, err)
	}
	if _, err := SwitchBranch(bg, filepath.Join(root, "teams"), "nope"); err == nil {
		t.Fatal("unknown branch accepted")
	}
}

func TestSwitchToRemoteOnlyBranchWithTwoRemotes(t *testing.T) {
	setup(t)
	tmp := t.TempDir()
	server := gittest.MakeLocal(t, tmp, "server", true)
	gittest.Git(t, server, "branch", "feat")
	work := filepath.Join(tmp, "work")
	gittest.Git(t, tmp, "clone", "-q", server, work)
	gittest.Git(t, work, "remote", "add", "up", server)
	gittest.Git(t, work, "fetch", "-q", "up")
	all, err := Branches(bg, work)
	if err != nil {
		t.Fatal(err)
	}
	var feat *Branch
	for i := range all {
		if all[i].Name == "feat" {
			feat = &all[i]
		}
	}
	if feat == nil || !feat.Remote || feat.Local {
		t.Fatalf("branches = %+v", all)
	}
	if name, err := SwitchBranch(bg, work, "feat"); err != nil || name != "feat" {
		t.Fatalf("name = %q err = %v", name, err)
	}
	gittest.Git(t, work, "checkout", "-q", "--detach")
	all, _ = Branches(bg, work)
	for _, b := range all {
		if strings.HasPrefix(b.Name, "(") || strings.Contains(b.Name, " ") {
			t.Fatalf("detached state listed: %+v", b)
		}
	}
}
