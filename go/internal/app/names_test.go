package app

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// All files of this package share one namespace, so two page packages that each add an
// unexported helper of the same name break the build only after both are merged. To rule that
// out, an unexported name in api_<area>.go or types_<area>.go starts with the area:
// api_plan.go may declare planRound, not round. Names that existed before this rule are listed in
// testdata/names_allowed.txt ("file name"); the list only shrinks. To refresh it after removing
// names: UPDATE_NAMES=1 go test ./internal/app -run TestUnexportedNames.
func TestUnexportedNamesStartWithTheirArea(t *testing.T) {
	allowed := readAllowed(t)
	fset := token.NewFileSet()
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	var present []string
	for _, file := range files {
		if strings.HasSuffix(file, "_test.go") {
			continue
		}
		area := areaOf(file)
		if area == "" {
			continue
		}
		parsed, err := parser.ParseFile(fset, file, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		for _, name := range topLevelNames(parsed) {
			if strings.HasPrefix(name, area) {
				continue
			}
			key := file + " " + name
			present = append(present, key)
			if !allowed[key] && os.Getenv("UPDATE_NAMES") == "" {
				t.Errorf("%s: %q must start with %q (shared namespace of package app; see names_test.go)", file, name, area)
			}
		}
	}
	if os.Getenv("UPDATE_NAMES") != "" {
		sort.Strings(present)
		if err := os.WriteFile("testdata/names_allowed.txt", []byte(strings.Join(present, "\n")+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

// areaOf is "plan" for api_plan.go and types_plan.go, "" for any other file.
func areaOf(file string) string {
	base := strings.TrimSuffix(file, ".go")
	for _, prefix := range []string{"api_", "types_"} {
		if strings.HasPrefix(base, prefix) {
			return strings.TrimPrefix(base, prefix)
		}
	}
	return ""
}

// topLevelNames returns the unexported names a file adds to the package namespace: functions,
// types, variables, constants and unexported methods of API.
func topLevelNames(f *ast.File) []string {
	var out []string
	add := func(name string) {
		if name != "_" && name != "init" && !ast.IsExported(name) {
			out = append(out, name)
		}
	}
	for _, decl := range f.Decls {
		switch d := decl.(type) {
		case *ast.FuncDecl:
			if d.Recv == nil || receiverIsAPI(d.Recv) {
				add(d.Name.Name)
			}
		case *ast.GenDecl:
			for _, spec := range d.Specs {
				switch s := spec.(type) {
				case *ast.TypeSpec:
					add(s.Name.Name)
				case *ast.ValueSpec:
					for _, n := range s.Names {
						add(n.Name)
					}
				}
			}
		}
	}
	return out
}

func receiverIsAPI(recv *ast.FieldList) bool {
	if len(recv.List) == 0 {
		return false
	}
	expr := recv.List[0].Type
	if star, ok := expr.(*ast.StarExpr); ok {
		expr = star.X
	}
	id, ok := expr.(*ast.Ident)
	return ok && id.Name == "API"
}

func readAllowed(t *testing.T) map[string]bool {
	t.Helper()
	raw, err := os.ReadFile("testdata/names_allowed.txt")
	if err != nil {
		if os.IsNotExist(err) {
			return map[string]bool{}
		}
		t.Fatal(err)
	}
	out := map[string]bool{}
	for _, line := range strings.Split(string(raw), "\n") {
		if line != "" {
			out[line] = true
		}
	}
	return out
}
