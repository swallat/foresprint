package gitsync

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// The default validator reports a team folder that does not load as an error.
func TestFolderValidatorReportsLoadErrors(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "demo")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "team.yaml"), []byte("name: [broken\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	issues, err := FolderValidator(bg, dir, time.Date(2026, 1, 5, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 1 || issues[0].Where != "demo" {
		t.Fatalf("issues: %+v", issues)
	}
}

// The default validator checks the team folders inside a data folder, not the data folder itself.
func TestFolderValidatorChecksTeamsOfDataFolder(t *testing.T) {
	data := filepath.Join(t.TempDir(), "teams")
	today := time.Date(2026, 1, 5, 0, 0, 0, 0, time.UTC)
	good := filepath.Join(data, "alpha")
	bad := filepath.Join(data, "beta")
	for dir, text := range map[string]string{good: "name: Alpha\n", bad: "name: [broken\n"} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "team.yaml"), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	issues, err := FolderValidator(bg, data, today)
	if err != nil {
		t.Fatal(err)
	}
	for _, i := range issues {
		if i.Where == "teams" {
			t.Fatalf("data folder taken for a team: %+v", issues)
		}
	}
	found := false
	for _, i := range issues {
		if i.Key == "beta" {
			found = true
		}
	}
	if !found {
		t.Fatalf("error of beta missing: %+v", issues)
	}
}

// A data folder without any error gives no issue (and no "team not found").
func TestFolderValidatorEmptyDataFolder(t *testing.T) {
	issues, err := FolderValidator(bg, filepath.Join(t.TempDir(), "teams"), time.Now())
	if err != nil || len(issues) != 0 {
		t.Fatalf("issues %+v err %v", issues, err)
	}
}
