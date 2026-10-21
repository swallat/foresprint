package storage

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/yamlx"
)

// header is not part of the references: they hold what the *_to_dict writes.
func loadMap(t *testing.T, text string) *yamlx.Map {
	t.Helper()
	v, err := yamlx.Load(text)
	if err != nil {
		t.Fatalf("yaml: %v", err)
	}
	if v == nil {
		return &yamlx.Map{}
	}
	m, ok := v.(*yamlx.Map)
	if !ok {
		t.Fatalf("not a mapping: %T", v)
	}
	return m
}

const where = "FILE"

// knownDifferences are deliberate departures from Python (see go/README.md).
var knownDifferences = map[string]string{
	"sprint/note-number": "the note of a sprint is always text in Go; Python keeps a number as a number",
}

// roundTrip reads a document of the given kind and returns what is written back.
func roundTrip(kind string, m *yamlx.Map) (string, error) {
	switch kind {
	case "team":
		team, err := TeamFromDict("key", m, where)
		if err != nil {
			return "", err
		}
		return DumpYAML(TeamToDict(team)), nil
	case "people":
		v, err := PeopleFromDict(m, where)
		if err != nil {
			return "", err
		}
		return DumpYAML(PeopleToDict(v)), nil
	case "products":
		v, err := ProductsFromDict(m, where)
		if err != nil {
			return "", err
		}
		return DumpYAML(ProductsToDict(v)), nil
	case "sprint":
		v, err := SprintFromDict(m, where)
		if err != nil {
			return "", err
		}
		return DumpYAML(SprintToDict(v)), nil
	case "projects":
		v, err := ProjectsFromDict(m, where)
		if err != nil {
			return "", err
		}
		return DumpYAML(ProjectsToDict(v)), nil
	case "tickets":
		v, err := TicketsFromDict(m, where)
		if err != nil {
			return "", err
		}
		return DumpYAML(TicketsToDict(v)), nil
	case "preplan":
		v, err := PreplanFromDict(m, where)
		if err != nil {
			return "", err
		}
		return DumpYAML(PreplanToDict(v)), nil
	}
	panic("unknown kind " + kind)
}

func TestFilesAgainstPython(t *testing.T) {
	var cases []struct {
		Kind      string `json:"kind"`
		Name      string `json:"name"`
		YAML      string `json:"yaml"`
		OK        string `json:"ok"`
		Error     string `json:"error"`
		YAMLError bool   `json:"yaml_error"`
	}
	golden.Load(t, &cases, "storage", "cases.json")
	if len(cases) < 150 {
		t.Fatalf("only %d cases", len(cases))
	}
	for _, c := range cases {
		if c.YAMLError {
			continue
		}
		t.Run(c.Kind+"/"+c.Name, func(t *testing.T) {
			if why, ok := knownDifferences[c.Kind+"/"+c.Name]; ok {
				t.Skip(why)
			}
			got, err := roundTrip(c.Kind, loadMap(t, c.YAML))
			switch {
			case c.Error != "":
				if err == nil {
					t.Fatalf("want error %q, got\n%s", c.Error, got)
				}
				if !IsDataError(err) {
					t.Fatalf("not a data error: %T %v", err, err)
				}
				if err.Error() != c.Error {
					t.Errorf("error\n got: %s\nwant: %s", err.Error(), c.Error)
				}
			case err != nil:
				t.Fatalf("unexpected error: %v\nwant:\n%s", err, c.OK)
			case got != c.OK:
				t.Errorf("--- python\n%s--- go\n%s", c.OK, got)
			}
		})
	}
}

// TestRoundTripCases loads every team of the golden cases and writes all files again; the bytes
// must be what Python writes (the input where it did not change, else the reference).
func TestRoundTripCases(t *testing.T) {
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			var manifest struct {
				Files []struct {
					File      string `json:"file"`
					Identical bool   `json:"identical"`
				} `json:"files"`
			}
			golden.Load(t, &manifest, strings.Split(c.YAML, "/")...)
			src := c.TeamDir(t)
			tmp := t.TempDir()
			copyTree(t, src, filepath.Join(tmp, c.Team))
			repo := NewRepository(tmp)
			data, err := repo.Load(c.Team)
			if err != nil {
				t.Fatal(err)
			}
			mustSave := func(_ string, err error) {
				t.Helper()
				if err != nil {
					t.Fatal(err)
				}
			}
			dir := repo.TeamDir(c.Team)
			mustSave(repo.SaveTeam(data.Team))
			if fileExists(filepath.Join(dir, "people.yaml")) {
				mustSave(repo.SavePeople(c.Team, data.People))
			}
			if fileExists(filepath.Join(dir, "products.yaml")) {
				mustSave(repo.SaveProducts(c.Team, data.Products))
			}
			if fileExists(filepath.Join(dir, "projects.yaml")) {
				mustSave(repo.SaveProjects(c.Team, data.Projects))
			}
			if fileExists(filepath.Join(dir, "tickets.yaml")) {
				mustSave(repo.SaveTickets(c.Team, TicketsFile{Tickets: data.Tickets, Imported: data.TicketsImported, Source: data.TicketsSource}))
			}
			if fileExists(filepath.Join(dir, "preplan.yaml")) {
				mustSave(repo.SavePreplan(c.Team, data.Preplan))
			}
			for i := range data.Sprints {
				mustSave(repo.SaveSprint(c.Team, &data.Sprints[i]))
			}
			for _, f := range manifest.Files {
				after, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(f.File)))
				if err != nil {
					t.Fatal(err)
				}
				want, err := os.ReadFile(filepath.Join(src, filepath.FromSlash(f.File)))
				if err != nil {
					t.Fatal(err)
				}
				if !f.Identical {
					want, err = os.ReadFile(golden.Path(t, "yaml", c.Name, filepath.FromSlash(f.File)))
					if err != nil {
						t.Fatal(err)
					}
				}
				if string(after) != string(want) {
					t.Errorf("%s differs\n--- python\n%s\n--- go\n%s", f.File, want, after)
				}
			}
		})
	}
}

func copyTree(t *testing.T, src, dst string) {
	t.Helper()
	err := filepath.WalkDir(src, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, path)
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
}

func newTeamFolder(t *testing.T) (*Repository, string) {
	t.Helper()
	repo := NewRepository(t.TempDir())
	team := model.NewTeam("alpha", "Alpha")
	if _, err := repo.SaveTeam(team); err != nil {
		t.Fatal(err)
	}
	return repo, filepath.Join(repo.Root, "alpha")
}

func TestSaveIsStableAndSkipsUnchanged(t *testing.T) {
	repo, dir := newTeamFolder(t)
	path := filepath.Join(dir, "team.yaml")
	first, _ := os.ReadFile(path)
	old := yamlxTime(t)
	if err := os.Chtimes(path, old, old); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.SaveTeam(model.NewTeam("alpha", "Alpha")); err != nil {
		t.Fatal(err)
	}
	info, _ := os.Stat(path)
	if !info.ModTime().Equal(old) {
		t.Error("an unchanged file was rewritten")
	}
	if !strings.HasPrefix(string(first), TeamHeader+"name: Alpha\nunit: PT\n") || strings.Contains(string(first), "\r") {
		t.Errorf("unexpected content:\n%s", first)
	}
}

func TestConflictMarkersBlockReadAndWrite(t *testing.T) {
	repo, dir := newTeamFolder(t)
	path := filepath.Join(dir, "team.yaml")
	conflict := "<<<<<<< HEAD\nname: A\n=======\nname: B\n>>>>>>> branch\n"
	if err := os.WriteFile(path, []byte(conflict), 0o644); err != nil {
		t.Fatal(err)
	}
	var ce *ConflictError
	if _, err := repo.Load("alpha"); !errors.As(err, &ce) || len(ce.Files) != 1 {
		t.Fatalf("load: %v", err)
	}
	if _, err := repo.SaveTeam(model.NewTeam("alpha", "Alpha")); !errors.As(err, &ce) {
		t.Fatalf("save: %v", err)
	}
	if b, _ := os.ReadFile(path); string(b) != conflict {
		t.Error("the conflict was overwritten")
	}
	if !HasConflictMarkers(strings.ReplaceAll(conflict, "\n", "\r\n")) {
		t.Error("CRLF markers not found")
	}
	if HasConflictMarkers("<<<<<<< x\nabc\n") {
		t.Error("one marker is not a conflict")
	}
}

func TestLoadErrors(t *testing.T) {
	repo, dir := newTeamFolder(t)
	if _, err := repo.Load("nope"); err == nil || !strings.Contains(err.Error(), "Team 'nope' not found") || !strings.Contains(err.Error(), "available: alpha") {
		t.Errorf("missing team: %v", err)
	}
	if err := os.MkdirAll(filepath.Join(dir, "sprints"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "sprints", "2026.1.yaml"), []byte("id: '2026.2'\nstart: 2026-01-01\nend: 2026-01-15\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.Load("alpha"); err == nil || !strings.Contains(err.Error(), "does not match the file name") {
		t.Errorf("id mismatch: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "people.yaml"), []byte("- a\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(dir, "sprints", "2026.1.yaml")); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.Load("alpha"); err == nil || !strings.Contains(err.Error(), "content must be a YAML mapping") {
		t.Errorf("list at top level: %v", err)
	}
}

func TestSprintAbsenceStatePinned(t *testing.T) {
	repo, dir := newTeamFolder(t)
	start, end := model.Date(2026, 1, 7), model.Date(2026, 1, 21)
	// An evaluated sprint (legacy file without state) stays "confirmed" when planning is saved.
	legacy := "id: '2026.1'\nstart: 2026-01-07\nend: 2026-01-21\nvelocity: 5\n"
	if err := os.MkdirAll(filepath.Join(dir, "sprints"), 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "sprints", "2026.1.yaml")
	if err := os.WriteFile(path, []byte(legacy), 0o644); err != nil {
		t.Fatal(err)
	}
	s := model.Sprint{ID: "2026.1", Start: start, End: end, Planning: &model.Planning{Backlog: 3}}
	if _, err := repo.SaveSprint("alpha", &s); err != nil {
		t.Fatal(err)
	}
	if s.AbsenceState == nil || *s.AbsenceState != model.AbsencesConfirmed {
		t.Errorf("state %v", s.AbsenceState)
	}
	// A new sprint file without content stays unknown.
	n := model.Sprint{ID: "2026.2", Start: end, End: model.Date(2026, 2, 4)}
	if _, err := repo.SaveSprint("alpha", &n); err != nil {
		t.Fatal(err)
	}
	if *n.AbsenceState != model.AbsencesUnknown {
		t.Errorf("new sprint state %v", *n.AbsenceState)
	}
	b, _ := os.ReadFile(filepath.Join(dir, "sprints", "2026.2.yaml"))
	if strings.Contains(string(b), "absence_state") {
		t.Errorf("a state that the fields give anyway is not stored:\n%s", b)
	}
	// A state that differs from what the fields give is stored.
	e := model.Sprint{ID: "2026.3", Start: end, End: end, Velocity: model.Ptr(5.0), AbsenceState: model.Ptr(model.AbsencesUnknown)}
	if _, err := repo.SaveSprint("alpha", &e); err != nil {
		t.Fatal(err)
	}
	if b, _ = os.ReadFile(filepath.Join(dir, "sprints", "2026.3.yaml")); !strings.Contains(string(b), "absence_state: unknown") {
		t.Errorf("state not stored:\n%s", b)
	}
}

func TestSprintPathRefusesUnsafeIDs(t *testing.T) {
	repo := NewRepository(t.TempDir())
	for _, id := range []string{"", "../x", "a/b", ".hidden", "trail.", " lead", strings.Repeat("x", 81)} {
		if _, err := repo.SprintPath("alpha", id); err == nil {
			t.Errorf("%q accepted", id)
		}
	}
	if _, err := repo.SprintPath("alpha", "2026.20"); err != nil {
		t.Error(err)
	}
}

func TestSaveSprintsTogetherRollsBack(t *testing.T) {
	repo, dir := newTeamFolder(t)
	a := model.Sprint{ID: "2026.1", Start: model.Date(2026, 1, 7), End: model.Date(2026, 1, 21)}
	if _, err := repo.SaveSprint("alpha", &a); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(filepath.Join(dir, "sprints", "2026.1.yaml"))
	a2 := a
	a2.Velocity = model.Ptr(9.0)
	bad := model.Sprint{ID: "bad/id", Start: a.End, End: a.End}
	if _, err := SaveSprintsTogether(repo, "alpha", []*model.Sprint{&a2, &bad}); err == nil {
		t.Fatal("expected an error")
	}
	if after, _ := os.ReadFile(filepath.Join(dir, "sprints", "2026.1.yaml")); string(after) != string(before) {
		t.Error("the first file was not restored")
	}
	// A failure while writing the second file rolls back the first and removes new files.
	if err := os.MkdirAll(filepath.Join(dir, "sprints", "2026.3.yaml"), 0o755); err != nil { // a folder in the way
		t.Fatal(err)
	}
	fresh := model.Sprint{ID: "2026.2", Start: a.End, End: model.Date(2026, 2, 4)}
	blocked := model.Sprint{ID: "2026.3", Start: a.End, End: model.Date(2026, 2, 4)}
	if _, err := SaveSprintsTogether(repo, "alpha", []*model.Sprint{&a2, &fresh, &blocked}); err == nil {
		t.Fatal("expected an error")
	}
	if after, _ := os.ReadFile(filepath.Join(dir, "sprints", "2026.1.yaml")); string(after) != string(before) {
		t.Error("the first file was not restored after a write failure")
	}
	if fileExists(filepath.Join(dir, "sprints", "2026.2.yaml")) {
		t.Error("a new file was left behind")
	}
}

func TestImportSprints(t *testing.T) {
	repo := NewRepository(t.TempDir())
	team := model.NewTeam("beta", "Beta")
	s := model.Sprint{ID: "2026.1", Start: model.Date(2026, 1, 7), End: model.Date(2026, 1, 21), Velocity: model.Ptr(5.0)}
	paths, err := ImportSprints(repo, team, []*model.Sprint{&s})
	if err != nil || len(paths) != 3 {
		t.Fatalf("%v %v", paths, err)
	}
	if err := os.MkdirAll(filepath.Join(repo.Root, "Gamma"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(repo.Root, "Gamma", "team.yaml"), []byte("name: G\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	// On a case-insensitive file system "gamma" is the folder "Gamma" itself, so there is no clash.
	if !repo.Exists("gamma") {
		if _, err := ImportSprints(repo, model.NewTeam("gamma", "x"), nil); err == nil || !strings.Contains(err.Error(), "already exists") {
			t.Errorf("case clash: %v", err)
		}
	}
	if _, err := ImportSprints(repo, model.NewTeam("a b", "x"), nil); err == nil {
		t.Error("bad key accepted")
	}
	data, err := repo.Load("beta")
	if err != nil || len(data.Sprints) != 1 || data.Team.Features.Explicit != true {
		t.Fatalf("%+v %v", data, err)
	}
}

func TestOlderFileDerivesFeatures(t *testing.T) {
	repo, dir := newTeamFolder(t)
	if err := os.WriteFile(filepath.Join(dir, "team.yaml"), []byte("name: Old\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "products.yaml"), []byte("products: [{id: a, po: Pat}]\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "people.yaml"), []byte("people: [{id: p, production_access: true}]\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	data, err := repo.Load("alpha")
	if err != nil {
		t.Fatal(err)
	}
	f := data.Team.Features
	if f.Explicit || !f.Products || !f.PO || !f.Production || f.Tickets {
		t.Errorf("%+v", f)
	}
}

func TestTeamKeyProblem(t *testing.T) {
	for key, bad := range map[string]bool{"alpha": false, "a-b_c1": false, "Alpha": true, "-x": true, "a/b": true,
		"con": true, "COM1.txt": true, "": true, strings.Repeat("a", 65): true, strings.Repeat("a", 64): false, "ä": true} {
		if got := TeamKeyProblem(key) != ""; got != bad {
			t.Errorf("%q: problem=%v", key, got)
		}
	}
}

func TestFileNameProblem(t *testing.T) {
	for name, bad := range map[string]bool{"2026.1": false, "a b": false, "ok-1_x": false, "a:b": true, "a*b": true,
		"nul": true, "CON.x": true, "a\x01": true, "x.": true, "Ünï": false} {
		if got := FileNameProblem(name, true) != ""; got != bad {
			t.Errorf("%q portable: problem=%v", name, got)
		}
	}
	if FileNameProblem("a:b", false) != "" && !isWindows() {
		t.Error("a colon is an ordinary character outside Windows")
	}
}
