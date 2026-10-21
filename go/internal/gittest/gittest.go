// Package gittest has helpers for tests with real Git repositories: a data folder in a
// repository, a bare server and clones of it. It is only imported by tests.
package gittest

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// Need skips the test if Git is not installed.
func Need(t testing.TB) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git is not installed")
	}
}

// Git runs a real git in cwd and fails the test on an error. It returns the output without
// whitespace at both ends.
func Git(t testing.TB, cwd string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = cwd
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s: %v\n%s", strings.Join(args, " "), err, out)
	}
	return strings.TrimSpace(string(out))
}

// Isolate gives the test an identity for commits and no Git configuration of the machine (no
// credential service that would open a window).
func Isolate(t testing.TB) {
	t.Helper()
	Need(t)
	empty := filepath.Join(t.TempDir(), "gitconfig")
	if err := os.WriteFile(empty, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	t.Setenv("GIT_CONFIG_GLOBAL", empty)
	t.Setenv("GCM_INTERACTIVE", "never")
	t.Setenv("FORESPRINT_NO_BACKGROUND_FETCH", "1")
	for _, who := range []string{"AUTHOR", "COMMITTER"} {
		t.Setenv("GIT_"+who+"_NAME", "T")
		t.Setenv("GIT_"+who+"_EMAIL", "t@example.org")
	}
}

// Write writes a file (creating folders) and returns its path.
func Write(t testing.TB, path, text string) string {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// MakeLocal creates the data folder <dir>/<name>/teams in a repository (without server),
// optionally with a commit. It returns the root of the repository.
func MakeLocal(t testing.TB, dir, name string, commit bool) string {
	t.Helper()
	root := filepath.Join(dir, name)
	Git(t, dir, "init", "-q", "-b", "main", root)
	Git(t, root, "config", "user.name", "T")
	Git(t, root, "config", "user.email", "t@example.org")
	if err := os.MkdirAll(filepath.Join(root, "teams"), 0o755); err != nil {
		t.Fatal(err)
	}
	if commit {
		Write(t, filepath.Join(root, "teams", "team.yaml"), "name: A\n")
		Git(t, root, "add", "-A")
		Git(t, root, "commit", "-qm", "Start")
	}
	return root
}

// MakeServer creates a bare repository as server; with branch it holds a commit on that branch.
func MakeServer(t testing.TB, dir, name, branch string) string {
	t.Helper()
	bare := filepath.Join(dir, name)
	initial := branch
	if initial == "" {
		initial = "main"
	}
	Git(t, dir, "init", "-q", "--bare", "-b", initial, bare)
	if branch != "" {
		other := MakeLocal(t, dir, name+"-source", true)
		Git(t, other, "branch", "-m", branch)
		Git(t, other, "push", "-q", bare, branch)
	}
	return bare
}

// MakeClone clones remote to target and sets the identity.
func MakeClone(t testing.TB, remote, target, name string) string {
	t.Helper()
	Git(t, filepath.Dir(target), "clone", "-q", remote, target)
	Git(t, target, "config", "user.name", name)
	Git(t, target, "config", "user.email", strings.ToLower(name)+"@example.org")
	return target
}
