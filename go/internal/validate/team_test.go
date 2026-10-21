package validate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/storage"
)

type teamCase struct {
	Name      string   `json:"name"`
	Base      string   `json:"base"`
	Team      string   `json:"team"`
	Today     string   `json:"today"`
	Overrides []string `json:"overrides"`
	Deleted   []string `json:"deleted"`
	LoadError string   `json:"load_error"`
	Issues    []struct {
		Level   string `json:"level"`
		Where   string `json:"where"`
		Message string `json:"message"`
	} `json:"issues"`
}

func copyTree(t *testing.T, from, to string) {
	t.Helper()
	err := filepath.Walk(from, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(path, ".yaml") {
			return err
		}
		rel, _ := filepath.Rel(from, path)
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		dest := filepath.Join(to, rel)
		if err := os.MkdirAll(filepath.Dir(dest), 0o777); err != nil {
			return err
		}
		return os.WriteFile(dest, b, 0o666)
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestCheckTeam(t *testing.T) {
	var cases struct {
		Cases []teamCase `json:"cases"`
	}
	golden.Load(t, &cases, "validate", "cases.json")
	bases := map[string]golden.Case{}
	for _, c := range golden.Cases(t) {
		bases[c.Name] = c
	}
	for _, tc := range cases.Cases {
		t.Run(tc.Name, func(t *testing.T) {
			if strings.Contains(tc.LoadError, "invalid YAML (while parsing") {
				// The text of a YAML syntax error is PyYAML's parser message with its marks;
				// the Go loader's parser words it differently. Not a question of the checks.
				t.Skip("YAML syntax error wording differs between PyYAML and the Go parser")
			}
			base, ok := bases[tc.Base]
			if !ok {
				t.Fatalf("no base case %q", tc.Base)
			}
			root := t.TempDir()
			folder := filepath.Join(root, tc.Team)
			copyTree(t, base.TeamDir(t), folder)
			for _, name := range tc.Deleted {
				if err := os.Remove(filepath.Join(folder, filepath.FromSlash(name))); err != nil {
					t.Fatal(err)
				}
			}
			for _, name := range tc.Overrides {
				src := filepath.Join(golden.RepoRoot(t), "golden", "inputs", "validate", tc.Name, filepath.FromSlash(name))
				b, err := os.ReadFile(src)
				if err != nil {
					t.Fatal(err)
				}
				dest := filepath.Join(folder, filepath.FromSlash(name))
				if err := os.MkdirAll(filepath.Dir(dest), 0o777); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(dest, b, 0o666); err != nil {
					t.Fatal(err)
				}
			}
			today, err := time.Parse("2006-01-02", tc.Today)
			if err != nil {
				t.Fatal(err)
			}
			var got []Issue
			data, err := storage.NewRepository(root).Load(tc.Team)
			if err != nil {
				got = []Issue{{Level: Error, Where: tc.Team, Message: strings.ReplaceAll(err.Error(), root, "<data>")}}
				if tc.LoadError == "" {
					t.Fatalf("load failed: %v", err)
				}
			} else {
				got = append(CheckTeam(data, today), CheckTeamFiles(folder, data.Team.Features.Tickets)...)
			}
			if tc.LoadError != "" && (len(got) != 1 || got[0].Message != tc.LoadError) {
				t.Errorf("load error %v, want %q", got, tc.LoadError)
			}
			for i := 0; i < len(got) || i < len(tc.Issues); i++ {
				switch {
				case i >= len(got):
					t.Errorf("missing issue %d: %+v", i, tc.Issues[i])
				case i >= len(tc.Issues):
					t.Errorf("extra issue %d: %+v", i, got[i])
				default:
					want := tc.Issues[i]
					if string(got[i].Level) != want.Level || got[i].Where != want.Where || got[i].Message != want.Message {
						t.Errorf("issue %d:\n got  %+v\n want %+v", i, got[i], want)
					}
				}
			}
		})
	}
}
