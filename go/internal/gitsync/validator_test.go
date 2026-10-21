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
