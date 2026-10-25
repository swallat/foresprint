package golden_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
)

// The manifest and the files it names exist; the Go cores rely on that.
func TestManifest(t *testing.T) {
	cases := golden.Cases(t)
	names := map[string]bool{}
	for _, c := range cases {
		if names[c.Name] {
			t.Errorf("case %s twice", c.Name)
		}
		names[c.Name] = true
		if _, err := os.Stat(filepath.Join(c.TeamDir(t), "team.yaml")); err != nil {
			t.Errorf("%s: %v", c.Name, err)
		}
		var forecast map[string]any
		if !c.LoadExpected(t, &forecast, "forecast.json") {
			t.Errorf("%s: no forecast reference", c.Name)
		}
		var yamlFiles struct {
			Files []struct {
				File      string `json:"file"`
				Identical bool   `json:"identical"`
			} `json:"files"`
		}
		golden.Load(t, &yamlFiles, c.YAML)
		for _, f := range yamlFiles.Files {
			if f.Identical {
				continue
			}
			if _, err := os.Stat(golden.Path(t, "yaml", c.Name, filepath.FromSlash(f.File))); err != nil {
				t.Errorf("%s: %v", c.Name, err)
			}
		}
	}
	for _, want := range []string{"demo", "tickets-simple", "tickets-products", "people-days", "yaml-messy"} {
		if !names[want] {
			t.Errorf("case %s is missing", want)
		}
	}
}
