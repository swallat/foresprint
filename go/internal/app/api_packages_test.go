package app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func packagesAPI(t *testing.T, csv string) (*API, string, string) {
	t.Helper()
	api, team := copyDemoTeam(t)
	in, err := api.TrackerSettings(team)
	if err != nil {
		t.Fatal(err)
	}
	in.Source = "packages"
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "packages.csv")
	if err := os.WriteFile(path, []byte(csv), 0o644); err != nil {
		t.Fatal(err)
	}
	api.ChooseTable = func(string) (string, error) { return path, nil }
	return api, team, path
}

func TestPackageImportPreviewApply(t *testing.T) {
	api, team, _ := packagesAPI(t, "Titel;Schätzung;Status\nLogin bauen;5;Offen\nExport;3,5;Offen\n;2;Offen\n")
	p, err := api.PackageImportPreview(team)
	if err != nil {
		t.Fatal(err)
	}
	if p.New != 2 || p.Updated != 0 || len(p.Problems) != 1 || p.Problems[0].Row != 4 {
		t.Fatalf("preview: %+v", p)
	}
	res, err := api.PackageImportApply(team, p.Path, p.Hash)
	if err != nil || !res.OK {
		t.Fatalf("apply: %+v %v", res, err)
	}
	// A second import of the same table adds nothing new: keys were generated, so rows are new
	// again, but a table that carries the keys updates them.
	_, data, err := api.loadRepoTeam(team)
	if err != nil {
		t.Fatal(err)
	}
	if len(data.Tickets) != 2 || !strings.HasPrefix(data.Tickets[0].Key, "AP-") {
		t.Fatalf("tickets: %+v", data.Tickets)
	}
}

func TestPackageImportRefusesChangedFile(t *testing.T) {
	api, team, path := packagesAPI(t, "Titel\nA\n")
	p, err := api.PackageImportPreview(team)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("Titel\nB\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := api.PackageImportApply(team, p.Path, p.Hash); err == nil {
		t.Fatal("a changed file must be refused")
	}
}

func TestPackageImportNeedsPackages(t *testing.T) {
	api, team := copyDemoTeam(t)
	path := filepath.Join(t.TempDir(), "p.csv")
	_ = os.WriteFile(path, []byte("Titel\nA\n"), 0o644)
	api.ChooseTable = func(string) (string, error) { return path, nil }
	if _, err := api.PackageImportPreview(team); err == nil {
		t.Fatal("a tracker team must not import work packages")
	}
}

func TestPackageImportCancelled(t *testing.T) {
	api, team, _ := packagesAPI(t, "Titel\nA\n")
	api.ChooseTable = func(string) (string, error) { return "", nil }
	p, err := api.PackageImportPreview(team)
	if err != nil || !p.Cancelled {
		t.Fatalf("%+v %v", p, err)
	}
}

func TestPackageImportKeepsLabelsAndRefusesNonFiles(t *testing.T) {
	api, team, path := packagesAPI(t, "Key;Titel;Labels\nAP-1;A;ui,web\n")
	p, err := api.PackageImportPreview(team)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := api.PackageImportApply(team, p.Path, p.Hash); err != nil {
		t.Fatal(err)
	}
	// Same key again, now with a Refined column and no Labels column: the labels stay.
	if err := os.WriteFile(path, []byte("Key;Titel;Bereit\nAP-1;A;ja\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	p, err = api.PackageImportPreview(team)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := api.PackageImportApply(team, p.Path, p.Hash); err != nil {
		t.Fatal(err)
	}
	_, data, _ := api.loadRepoTeam(team)
	got := strings.Join(data.Tickets[0].Labels, ",")
	if got != "ui,web,refined" {
		t.Fatalf("labels: %q", got)
	}
	api.ChooseTable = func(string) (string, error) { return t.TempDir(), nil }
	if _, err := api.PackageImportPreview(team); err == nil {
		t.Fatal("a directory is not a table")
	}
}
