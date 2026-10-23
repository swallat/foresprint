package gitsync

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The default validator reports a team folder of the data folder that does not load as an error,
// with the team as key, and never takes the data folder for a team.
func TestFolderValidatorChecksTeamsOfDataFolder(t *testing.T) {
	data := filepath.Join(t.TempDir(), "teams")
	dir := filepath.Join(data, "demo")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "team.yaml"), []byte("name: [broken\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	issues, err := FolderValidator(bg, data, time.Date(2026, 1, 5, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) != 1 || issues[0].Key != "demo" || issues[0].Where != "demo" {
		t.Fatalf("issues: %+v", issues)
	}
}

// Missing and empty data folders give no issue (and no "team not found").
func TestFolderValidatorNoTeams(t *testing.T) {
	empty := t.TempDir()
	for _, dir := range []string{empty, filepath.Join(empty, "missing")} {
		issues, err := FolderValidator(bg, dir, time.Now())
		if err != nil || len(issues) != 0 {
			t.Fatalf("%s: issues %+v err %v", dir, issues, err)
		}
	}
}

// With the real validator, errors that exist in the baseline are not new, and the data folder is
// not taken for a team (the bug: "Team 'teams' not found" on every save).
func TestNewErrorsWithRealValidator(t *testing.T) {
	w := newWorld(t)
	SetValidator(nil)
	issues, err := FolderValidator(bg, w.alice.data(), time.Date(2026, 1, 5, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, i := range issues {
		if strings.Contains(i.Message, "not found") {
			t.Fatalf("issues: %+v", issues)
		}
	}
	got, err := NewErrors(bg, w.alice.data(), "HEAD", time.Date(2026, 1, 5, 0, 0, 0, 0, time.UTC))
	if err != nil || len(got) != 0 {
		t.Fatalf("new errors %v err %v", got, err)
	}
}
