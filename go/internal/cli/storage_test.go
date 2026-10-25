package cli

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func gitIn(t *testing.T, dir string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
}

func TestStorageSaveAndHistory(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git is not installed")
	}
	isolate(t)
	t.Setenv("GIT_CONFIG_GLOBAL", filepath.Join(t.TempDir(), "gitconfig"))
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	data := filepath.Join(t.TempDir(), "data")
	copyTree(t, demoTeams, data)
	remote := filepath.Join(t.TempDir(), "remote.git")
	gitIn(t, data, "init", "-q", "-b", "main", ".")
	gitIn(t, data, "config", "user.name", "Tester")
	gitIn(t, data, "config", "user.email", "tester@example.org")
	gitIn(t, data, "add", "-A")
	gitIn(t, data, "commit", "-q", "-m", "start")
	gitIn(t, t.TempDir(), "init", "-q", "--bare", "-b", "main", remote)

	args := func(extra ...string) []string { return append([]string{"--data", data, "storage"}, extra...) }

	if code, out, errOut := run(t, args()...); code != 0 || !strings.Contains(out, "Tester") || !strings.Contains(out, "not set") {
		t.Fatalf("show: %d %q %q", code, out, errOut)
	}
	if code, out, errOut := run(t, args("server", remote)...); code != 0 || !strings.Contains(out, "no data yet") {
		t.Fatalf("server: %d %q %q", code, out, errOut)
	}
	team := filepath.Join(data, "demo", "team.yaml")
	f, err := os.OpenFile(team, os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = f.WriteString("# changed\n")
	_ = f.Close()
	if code, out, errOut := run(t, args("save", "-m", "second")...); code != 0 || !strings.Contains(out, "Saved") {
		t.Fatalf("save: %d %q %q", code, out, errOut)
	}
	if code, out, _ := run(t, args("save")...); code != 0 || !strings.Contains(out, "Nothing to save") {
		t.Errorf("second save: %d %q", code, out)
	}
	_, hist, _ := run(t, args("history", "--limit", "5")...)
	if !strings.Contains(hist, "second") || !strings.Contains(hist, "start") {
		t.Errorf("history:\n%s", hist)
	}
	if _, branches, _ := run(t, args("branch")...); !strings.Contains(branches, "* main") {
		t.Errorf("branches: %q", branches)
	}
	if code, _, errOut := run(t, args("identity", "--name", "Only Name")...); code == 0 || errOut == "" {
		t.Errorf("identity without email must fail")
	}
	if code, _, _ := run(t, args("share", "sideways")...); code == 0 {
		t.Errorf("unknown way to share must fail")
	}
}
