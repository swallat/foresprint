package app

import (
	"os"
	"path/filepath"
	"testing"
)

func TestArchiveAndRestoreTeam(t *testing.T) {
	dir := t.TempDir()
	if err := os.CopyFS(dir, os.DirFS(demoDir(t))); err != nil {
		t.Fatal(err)
	}
	api := newAPI(t, dir)
	teams := api.Teams()
	if len(teams) == 0 {
		t.Skip("no demo team")
	}
	key, name := teams[0].Key, teams[0].Name
	before := len(teams)
	if err := api.ArchiveTeam(key, "wrong"); err == nil {
		t.Fatal("archived without the right name")
	}
	if err := api.ArchiveTeam(key, name); err != nil {
		t.Fatal(err)
	}
	if len(api.Teams()) != before-1 {
		t.Fatalf("teams after archive = %d", len(api.Teams()))
	}
	if _, err := os.Stat(filepath.Join(dir, "_archiv", key, "team.yaml")); err != nil {
		t.Fatal("team.yaml not in archive: ", err)
	}
	arch := api.ArchivedTeams()
	if len(arch) != 1 || arch[0].Key != key || arch[0].Name != name {
		t.Fatalf("archived = %+v", arch)
	}
	if err := api.RestoreTeam(key); err != nil {
		t.Fatal(err)
	}
	if len(api.Teams()) != before || len(api.ArchivedTeams()) != 0 {
		t.Fatal("restore did not bring the team back")
	}
	if err := api.RestoreTeam(key); err == nil {
		t.Fatal("restored a team that is not archived")
	}
}
