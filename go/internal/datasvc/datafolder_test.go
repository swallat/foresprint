package datasvc

import (
	"os"
	"path/filepath"
	"testing"
)

// The teams sit in the repository itself and an empty "teams" folder is left over: the data
// folder is the repository, not that empty folder.
func TestDataFolderPrefersTheFolderThatHoldsTeams(t *testing.T) {
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
	if got := dataFolder(root); got != root {
		t.Errorf("teams in the folder: got %q, want %q", got, root)
	}

	nested := t.TempDir()
	if err := os.MkdirAll(filepath.Join(nested, "teams", "alpha"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(nested, "teams", "alpha", "team.yaml"), []byte("name: A\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got, want := dataFolder(nested), filepath.Join(nested, "teams"); got != want {
		t.Errorf("teams in teams/: got %q, want %q", got, want)
	}

	fresh := t.TempDir()
	if err := os.MkdirAll(filepath.Join(fresh, "teams"), 0o755); err != nil {
		t.Fatal(err)
	}
	if got, want := dataFolder(fresh), filepath.Join(fresh, "teams"); got != want {
		t.Errorf("new repository: got %q, want %q", got, want)
	}
}
