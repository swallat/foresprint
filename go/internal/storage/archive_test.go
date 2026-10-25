package storage

import (
	"os"
	"path/filepath"
	"testing"
)

func archiveRepo(t *testing.T, keys ...string) *Repository {
	t.Helper()
	root := t.TempDir()
	for _, k := range keys {
		if err := os.MkdirAll(filepath.Join(root, k), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, k, "team.yaml"), []byte("name: x\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return NewRepository(root)
}

func TestArchiveRefusesOddKeys(t *testing.T) {
	r := archiveRepo(t, "a")
	for _, k := range []string{"", ".", "..", "../a", "_archiv", "_archiv/a", `x\a`} {
		if r.ArchiveTeam(k) == nil || r.RestoreTeam(k) == nil {
			t.Errorf("key %q was accepted", k)
		}
	}
}

func TestArchiveClashes(t *testing.T) {
	r := archiveRepo(t, "a")
	if err := r.ArchiveTeam("a"); err != nil {
		t.Fatal(err)
	}
	// a second team of the same key cannot be archived over the first
	if err := os.MkdirAll(filepath.Join(r.Root, "a"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(r.Root, "a", "team.yaml"), []byte("name: y\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if r.ArchiveTeam("a") == nil {
		t.Error("archived over an archived team")
	}
	// and the archived one cannot be restored over the live one
	if r.RestoreTeam("a") == nil {
		t.Error("restored over a live team")
	}
}
