package validate

import (
	"os"
	"path/filepath"
	"regexp"
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

// yamlSyntax picks the file and the problem out of the reference text of a YAML syntax error.
var yamlSyntax = regexp.MustCompile(`^(.+?): invalid YAML \(while parsing[^\n]*\n[^\n]*\n(did not find[^\n]*|expected[^\n]*|could not[^\n]*)\n`)

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

// scrub replaces the temporary folder by <data> and writes paths with slashes like the reference.
func scrub(s, root string) string {
	s = strings.ReplaceAll(s, root, "<data>")
	if filepath.Separator != '/' {
		s = strings.ReplaceAll(s, string(filepath.Separator), "/")
	}
	return s
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
			if err != nil && yamlSyntax.MatchString(tc.LoadError) {
				// Known deviation: the text of a YAML syntax error is PyYAML's parser message
				// with its marks; the Go parser words it differently. The file and the problem
				// itself must agree.
				want, have := yamlSyntax.FindStringSubmatch(tc.LoadError), err.Error()
				if !strings.Contains(scrub(have, root), want[1]+": invalid YAML (") ||
					!strings.Contains(have, want[2]) {
					t.Errorf("load error %q does not match the reference %q", have, tc.LoadError)
				}
				return
			}
			if err != nil {
				got = []Issue{{Level: Error, Where: tc.Team, Message: scrub(err.Error(), root)}}
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
