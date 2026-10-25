package cli

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestDataDirCommand(t *testing.T) {
	isolate(t)
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git is not installed")
	}
	if code, out, _ := run(t, "data-dir"); code != 0 || !strings.HasPrefix(out, "No data folder saved.\nUsed (without --data): ") {
		t.Errorf("empty: %d %q", code, out)
	}
	if code, _, errOut := run(t, "data-dir", filepath.Join(t.TempDir(), "missing")); code != 1 || !strings.HasPrefix(errOut, "Folder not found: ") {
		t.Errorf("missing: %d %q", code, errOut)
	}
	plain := t.TempDir()
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(plain))
	if code, _, errOut := run(t, "data-dir", plain); code != 1 || !strings.Contains(errOut, "is not inside a Git repository") {
		t.Errorf("no repository: %d %q", code, errOut)
	}

	repo := t.TempDir()
	if out, err := exec.Command("git", "-C", repo, "init", "-q").CombinedOutput(); err != nil {
		t.Fatalf("git init: %v %s", err, out)
	}
	team := filepath.Join(repo, "teams", "alpha")
	if err := os.MkdirAll(team, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(team, "team.yaml"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	code, out, errOut := run(t, "data-dir", repo)
	want := absPath(filepath.Join(repo, "teams"))
	if code != 0 || out != "Data folder saved: "+want+"\n" {
		t.Fatalf("set: %d %q %q", code, out, errOut)
	}
	if _, out, _ := run(t, "data-dir"); !strings.Contains(out, "Remembered: "+want+"\n") {
		t.Errorf("show: %q", out)
	}
}

// A folder remembered as "<repository>/teams" while the teams sit in the repository is found.
func TestTeamsDirFindsTeamsAboveARememberedTeamsFolder(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "teams"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, "alpha"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "alpha", "team.yaml"), []byte("name: A\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := teamsDir(filepath.Join(root, "teams")); got != root {
		t.Errorf("got %q, want %q", got, root)
	}
}
