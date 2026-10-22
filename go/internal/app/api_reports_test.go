package app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"golang.org/x/text/encoding/charmap"
)

func TestReportsOfTheDemoTeam(t *testing.T) {
	api := newAPI(t, demoDir(t))
	key := api.Teams()[0].Key

	text, err := api.ForecastReport(key)
	if err != nil || !strings.HasPrefix(text, "# ") {
		t.Fatalf("report: %v %.40q", err, text)
	}

	if _, err := api.ForecastSave(key, "markdown"); err == nil {
		t.Error("saving without a folder dialog must fail")
	}
	out := t.TempDir()
	api.ChooseFolder = func(string) (string, error) { return out, nil }
	for kind, name := range map[string]string{"markdown": key + "-forecast.md", "excel": key + "-forecast.xlsx"} {
		file, err := api.ForecastSave(key, kind)
		if err != nil {
			t.Fatalf("%s: %v", kind, err)
		}
		if file.Path != filepath.Join(out, name) {
			t.Errorf("%s: wrote %s", kind, file.Path)
		}
		if info, err := os.Stat(file.Path); err != nil || info.Size() == 0 {
			t.Errorf("%s: no file written", kind)
		}
	}
	if _, err := api.ForecastSave(key, "pdf"); err == nil {
		t.Error("an unknown format must be refused")
	}
	api.ChooseFolder = func(string) (string, error) { return "", nil }
	if file, err := api.ForecastSave(key, "markdown"); err != nil || !file.Cancelled {
		t.Errorf("a cancelled dialog is not an error: %+v %v", file, err)
	}

	// The workbook of the export reads back without changes.
	api.ChooseFolder = func(string) (string, error) { return out, nil }
	if _, err := api.ForecastSave(key, "excel"); err != nil {
		t.Fatal(err)
	}
	preview, err := api.previewImport(key, filepath.Join(out, key+"-forecast.xlsx"))
	if err != nil {
		t.Fatal(err)
	}
	if len(preview.Changes) != 0 {
		t.Errorf("round trip changes %d values, first %+v", len(preview.Changes), preview.Changes[0])
	}
	if _, err := api.ExcelImportApply(key, filepath.Join(out, key+"-forecast.xlsx"), "stale"); err == nil {
		t.Error("a changed workbook must be refused")
	}
	again, _ := api.ForecastSave(key, "excel")
	if again.Path == filepath.Join(out, key+"-forecast.xlsx") {
		t.Error("an export must not replace an existing file")
	}
	if _, err := api.ExcelImportPreview(key); err == nil {
		t.Error("importing without a file dialog must fail")
	}
}

func TestProductsOverTimeNeedsSeveralProducts(t *testing.T) {
	api := newAPI(t, demoDir(t))
	for _, team := range api.Teams() {
		v, err := api.ForecastProducts(team.Key)
		if err != nil {
			t.Fatal(err)
		}
		if v.Enabled && team.Products < 2 {
			t.Errorf("%s: enabled with %d products", team.Key, team.Products)
		}
		if v.Enabled && (len(v.Lines) < team.Products || len(v.Lines[0].Cells) != len(v.Sprints)) {
			t.Errorf("%s: %d lines, %d cells for %d sprints", team.Key, len(v.Lines), len(v.Lines[0].Cells), len(v.Sprints))
		}
	}
}

func TestCSVImportOfWorkPackages(t *testing.T) {
	dir := t.TempDir()
	copyTree(t, demoDir(t), dir)
	api := newAPI(t, dir)
	key := api.Teams()[0].Key
	csvFile := filepath.Join(t.TempDir(), "ap.csv")
	// Windows-1252 text with semicolons and a decimal comma, as German Excel writes it.
	table := "Schlüssel;Titel;Schätzung;Status\r\nAP-1;Anmeldung bauen;2,5;offen\r\nAP-2;;1;offen\r\nAP-3;Bericht;3;erledigt\r\n"
	enc, err := charmap.Windows1252.NewEncoder().String(table)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(csvFile, []byte(enc), 0o644); err != nil {
		t.Fatal(err)
	}

	// A team with a tracker refuses the table.
	if _, err := api.previewImport(key, csvFile); err == nil {
		t.Error("a tracker team accepted a CSV table")
	}

	teamFile := filepath.Join(dir, key, "team.yaml")
	raw, err := os.ReadFile(teamFile)
	if err != nil {
		t.Fatal(err)
	}
	raw = []byte(strings.Replace(string(raw), "features:\n", "features:\n  tickets: true\n", 1))
	if err := os.WriteFile(teamFile, append(raw, []byte("tracker:\n  kind: packages\n")...), 0o644); err != nil {
		t.Fatal(err)
	}

	pv, err := api.previewImport(key, csvFile)
	if err != nil {
		t.Fatal(err)
	}
	if pv.Kind != "packages" || len(pv.Changes) != 2 || len(pv.Problems) != 1 {
		t.Fatalf("preview %+v", pv)
	}
	if pv.Changes[0].New != "Anmeldung bauen" || pv.Changes[0].Old != "–" {
		t.Errorf("first change %+v", pv.Changes[0])
	}
	if _, err := os.Stat(filepath.Join(dir, key, "arbeitspakete.yaml")); err == nil {
		t.Fatal("the preview wrote a file")
	}

	if _, err := api.ExcelImportApply(key, csvFile, "wrong"); err == nil {
		t.Error("a changed file was applied")
	}
	files, err := api.ExcelImportApply(key, csvFile, pv.Hash)
	if err != nil || len(files) != 1 || files[0] != "arbeitspakete.yaml" {
		t.Fatalf("apply %v %v", files, err)
	}

	// Importing the same table again changes nothing.
	again, err := api.previewImport(key, csvFile)
	if err != nil {
		t.Fatal(err)
	}
	if len(again.Changes) != 0 {
		t.Errorf("an identical table changes %+v", again.Changes)
	}

	// A new estimate shows as a change of that field; labels stay without a labels column.
	enc2, _ := charmap.Windows1252.NewEncoder().String("Schlüssel;Titel;Schätzung\r\nAP-1;Anmeldung bauen;5\r\n")
	if err := os.WriteFile(csvFile, []byte(enc2), 0o644); err != nil {
		t.Fatal(err)
	}
	next, err := api.previewImport(key, csvFile)
	if err != nil {
		t.Fatal(err)
	}
	if len(next.Changes) != 1 || next.Changes[0].Path != "AP-1.estimate" || next.Changes[0].Old != "2.5" || next.Changes[0].New != "5" {
		t.Errorf("changes %+v", next.Changes)
	}
}
