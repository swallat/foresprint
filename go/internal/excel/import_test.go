package excel

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/yamlx"
)

type scenario struct {
	Name  string  `json:"name"`
	Key   string  `json:"key"`
	Case  *string `json:"case"`
	Today string  `json:"today"`
	Read  struct {
		Docs     map[string]string `json:"docs"`
		FileTeam *string           `json:"file_team"`
		Error    *string           `json:"error"`
	} `json:"read"`
	Plan *struct {
		Changes []struct {
			File string `json:"file"`
			Path string `json:"path"`
			Old  any    `json:"old"`
			New  any    `json:"new"`
		} `json:"changes"`
		Files     []string          `json:"files"`
		Untouched []string          `json:"untouched"`
		Written   map[string]string `json:"written"`
		Error     *string           `json:"error"`
	} `json:"plan"`
}

// jsonValue is a change value the way the Python reference writes it.
func jsonValue(v any) any {
	switch x := v.(type) {
	case yamlx.Date:
		return time.Time(x).Format("2006-01-02")
	case time.Time:
		return x.Format("2006-01-02T15:04:05")
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = jsonValue(e)
		}
		return out
	}
	return v
}

func copyDir(t *testing.T, from, to string) {
	t.Helper()
	err := filepath.Walk(from, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(from, p)
		dst := filepath.Join(to, rel)
		if info.IsDir() {
			return os.MkdirAll(dst, 0o755)
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(dst, b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
}

// Every workbook of the reference is read, planned against its team folder and written; the
// documents, the error texts, the changes and the bytes equal what Python does.
func TestImportMatchesPython(t *testing.T) {
	i18n.SetLanguage("en")
	var scenarios []scenario
	golden.Load(t, &scenarios, "excel_import", "scenarios.json")
	cases := map[string]golden.Case{}
	for _, c := range golden.Cases(t) {
		cases[c.Name] = c
	}
	for _, sc := range scenarios {
		t.Run(sc.Name, func(t *testing.T) {
			raw, err := os.ReadFile(golden.Path(t, "excel_import", "workbooks", sc.Name+".xlsx"))
			if err != nil {
				t.Fatal(err)
			}
			data, fileTeam, err := ReadWorkbook(raw, sc.Key)
			if sc.Read.Error != nil {
				if err == nil {
					t.Fatalf("want error %q, got none", *sc.Read.Error)
				}
				if sc.Name == "not-a-workbook" {
					if !strings.HasPrefix(err.Error(), "The file is not a readable Excel workbook:") {
						t.Fatalf("got %q", err)
					}
				} else if err.Error() != *sc.Read.Error {
					t.Fatalf("error\n got: %s\nwant: %s", err, *sc.Read.Error)
				}
			} else {
				if err != nil {
					t.Fatal(err)
				}
				names, texts := Documents(data)
				if len(names) != len(sc.Read.Docs) {
					t.Fatalf("%d documents, want %d", len(names), len(sc.Read.Docs))
				}
				for name, want := range sc.Read.Docs {
					if texts[name] != want {
						t.Errorf("%s differs\n got:\n%s\nwant:\n%s", name, texts[name], want)
					}
				}
				if (fileTeam == nil) != (sc.Read.FileTeam == nil) || (fileTeam != nil && *fileTeam != *sc.Read.FileTeam) {
					t.Errorf("file team %v, want %v", fileTeam, sc.Read.FileTeam)
				}
			}
			if sc.Plan == nil {
				return
			}
			root := t.TempDir()
			if sc.Case != nil && cases[*sc.Case].Team == sc.Key {
				c := cases[*sc.Case]
				copyDir(t, c.TeamDir(t), filepath.Join(root, sc.Key))
			}
			repo := storage.NewRepository(root)
			if sc.Read.Error != nil {
				return
			}
			today, _ := time.Parse("2006-01-02", sc.Today)
			plan, err := Plan(repo, data, today)
			if sc.Plan.Error != nil {
				if err == nil || err.Error() != *sc.Plan.Error {
					t.Fatalf("plan error\n got: %v\nwant: %s", err, *sc.Plan.Error)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			changes := []map[string]any{}
			for _, c := range plan.Changes {
				changes = append(changes, map[string]any{"file": c.File, "path": c.Path, "old": jsonValue(c.Old), "new": jsonValue(c.New)})
			}
			wantChanges := []map[string]any{}
			b, _ := json.Marshal(sc.Plan.Changes)
			_ = json.Unmarshal(b, &wantChanges)
			gb, _ := json.Marshal(changes)
			gotChanges := []map[string]any{}
			_ = json.Unmarshal(gb, &gotChanges)
			golden.Compare(t, wantChanges, gotChanges)
			golden.Compare(t, nonNil(sc.Plan.Files), nonNil(plan.Files))
			golden.Compare(t, nonNil(sc.Plan.Untouched), nonNil(plan.Untouched))
			written, err := Apply(repo, plan)
			if err != nil {
				t.Fatal(err)
			}
			got := map[string]string{}
			for _, p := range written {
				rel, _ := filepath.Rel(filepath.Join(root, sc.Key), p)
				body, err := os.ReadFile(p)
				if err != nil {
					t.Fatal(err)
				}
				got[filepath.ToSlash(rel)] = string(body)
			}
			if len(got) != len(sc.Plan.Written) {
				t.Errorf("%d files written, want %d", len(got), len(sc.Plan.Written))
			}
			for name, want := range sc.Plan.Written {
				if got[name] != want {
					t.Errorf("%s differs\n got:\n%s\nwant:\n%s", name, got[name], want)
				}
			}
		})
	}
}

func nonNil(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}
