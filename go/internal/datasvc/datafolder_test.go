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

// "Start a new one" in a folder that already holds teams adds no "teams" folder and uses the folder.
func TestCreateFolderInAFolderWithTeamsKeepsIt(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "alpha"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "alpha", "team.yaml"), []byte("name: A\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	got := New(root).CreateFolder(root)
	if got.Problem != nil {
		t.Fatalf("problem: %+v", got.Problem)
	}
	if abs, _ := filepath.Abs(root); got.Folder != abs {
		t.Errorf("got %q, want %q", got.Folder, abs)
	}
	if _, err := os.Stat(filepath.Join(root, "teams")); err == nil {
		t.Error("a teams folder was added")
	}
}
