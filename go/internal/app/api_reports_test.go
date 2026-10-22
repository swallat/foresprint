package app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
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
		if v.Enabled != (team.Products > 1) {
			t.Errorf("%s: enabled %v with %d products", team.Key, v.Enabled, team.Products)
		}
		if v.Enabled && (len(v.Lines) != team.Products || len(v.Lines[0].Cells) != len(v.Sprints)) {
			t.Errorf("%s: %d lines, %d cells for %d sprints", team.Key, len(v.Lines), len(v.Lines[0].Cells), len(v.Sprints))
		}
	}
}
