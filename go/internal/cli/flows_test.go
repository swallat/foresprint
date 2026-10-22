package cli

import (
	"bytes"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
)

type flow struct {
	AsOf     string            `json:"as_of"`
	Args     []string          `json:"args"`
	Input    string            `json:"input"`
	ExitCode int               `json:"exit_code"`
	Files    map[string]string `json:"files"`
	Deleted  []string          `json:"deleted"`
	Seed     map[string]string `json:"seed"`
}

// snapshot reads all files below root (slash paths).
func snapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	out := map[string]string{}
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(root, path)
		out[filepath.ToSlash(rel)] = string(raw)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// TestFlowsMatchPython replays the interactive scenarios of the Python command line (typed
// answers) on a copy of the demo teams and compares the exit code and every file written.
func TestFlowsMatchPython(t *testing.T) {
	dir := filepath.Join(golden.Dir(t), "expected", "cliflows")
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) == 0 {
		t.Fatalf("no scenarios in %s: %v", dir, err)
	}
	for _, entry := range entries {
		name := strings.TrimSuffix(entry.Name(), ".json")
		t.Run(name, func(t *testing.T) {
			var want flow
			golden.Load(t, &want, "cliflows", entry.Name())
			isolate(t)
			t.Setenv("FORESPRINT_LANG", "en")
			data := t.TempDir()
			copyTree(t, filepath.Join(golden.RepoRoot(t), "examples", "teams"), data)
			for rel, text := range want.Seed {
				path := filepath.Join(data, filepath.FromSlash(rel))
				if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
					t.Fatal(err)
				}
			}
			before := snapshot(t, data)
			var out, errOut bytes.Buffer
			args := append([]string{"--data", data, "--as-of", want.AsOf}, want.Args...)
			code := Execute(args, strings.NewReader(want.Input), &out, &errOut)
			if code != want.ExitCode {
				t.Errorf("exit code %d, want %d\nout: %s\nerr: %s", code, want.ExitCode, out.String(), errOut.String())
			}
			got := map[string]string{}
			after := snapshot(t, data)
			for rel, text := range after {
				if before[rel] != text {
					got[rel] = text
				}
			}
			var deleted []string
			for rel := range before {
				if _, ok := after[rel]; !ok {
					deleted = append(deleted, rel)
				}
			}
			sort.Strings(deleted)
			if strings.Join(deleted, "\n") != strings.Join(want.Deleted, "\n") {
				t.Errorf("deleted files %v, want %v", deleted, want.Deleted)
			}
			for rel, text := range want.Files {
				if got[rel] != text {
					t.Errorf("%s differs\n--- want\n%s\n--- got\n%s", rel, text, got[rel])
				}
			}
			for rel := range got {
				if _, ok := want.Files[rel]; !ok {
					t.Errorf("unexpected file written: %s", rel)
				}
			}
		})
	}
}
