package storage

import (
	"encoding/json"
	"path/filepath"
	"testing"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/golden"
)

// Core hands the calculation packages the same data as the test loader reads from the files.
func TestCoreMatchesTestLoader(t *testing.T) {
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			data, err := NewRepository(filepathDir(c.TeamDir(t))).Load(c.Team)
			if err != nil {
				t.Fatal(err)
			}
			got, err := json.Marshal(data.Core())
			if err != nil {
				t.Fatal(err)
			}
			want, err := json.Marshal(coretest.Load(t, c))
			if err != nil {
				t.Fatal(err)
			}
			var g, w any
			_ = json.Unmarshal(got, &g)
			_ = json.Unmarshal(want, &w)
			golden.Compare(t, w, g)
		})
	}
}

func filepathDir(p string) string { return filepath.Dir(p) }
