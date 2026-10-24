package sprintcal

import (
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/protocol"
	"github.com/swallat/foresprint/internal/storage"
)

// The messages are compared as English text, whatever language the computer is set to.
func TestMain(m *testing.M) {
	i18n.SetLanguage("en")
	os.Exit(m.Run())
}

// demoCopy copies the demo team into a temporary data folder and loads it.
func demoCopy(t *testing.T) (*storage.Repository, *storage.TeamData) {
	t.Helper()
	src, err := filepath.Abs(filepath.Join("..", "..", "..", "examples", "teams", "demo"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(src); err != nil {
		t.Fatalf("the demo team is part of the repository: %v", err)
	}
	root := filepath.Join(t.TempDir(), "teams")
	if err := os.CopyFS(filepath.Join(root, "demo"), os.DirFS(src)); err != nil {
		t.Fatal(err)
	}
	repo := storage.NewRepository(root)
	data, err := repo.Load("demo")
	if err != nil {
		t.Fatal(err)
	}
	if len(data.Sprints) < 8 {
		t.Fatalf("the tests need at least eight saved sprints, the demo team has %d", len(data.Sprints))
	}
	return repo, data
}

// following gives "<year>.<n+1>" for "<year>.<n>" (the numbering of the demo team).
func following(t *testing.T, id string) string {
	t.Helper()
	year, n, ok := strings.Cut(id, ".")
	num, err := strconv.Atoi(n)
	if !ok || err != nil {
		t.Fatalf("the demo sprint IDs must look like year.number, got %q", id)
	}
	return year + "." + strconv.Itoa(num+1)
}

func isDataError(err error) bool {
	var de *storage.DataError
	return errors.As(err, &de)
}

func TestPlanRenamesRefusals(t *testing.T) {
	_, data := demoCopy(t)
	first := data.Sprints[0].ID
	for name, c := range map[string]struct{ sprint, to, want string }{
		"unknown sprint": {"no-such", "2026.99", "is not saved"},
		"empty id":       {first, "  ", "new sprint ID"},
		"bad file name":  {first, "a/b", "not allowed as a file name"},
	} {
		_, err := PlanRenames(data, c.sprint, c.to)
		if err == nil || !isDataError(err) || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: err = %v, want a data error with %q", name, err, c.want)
		}
	}
}

func TestPlanRenamesRefusesAnIDOutsideSequentialNumbering(t *testing.T) {
	_, data := demoCopy(t)
	data.Team.Sprint.Numbering = model.NumberingSequential
	_, err := PlanRenames(data, data.Sprints[0].ID, "abc")
	if err == nil || !isDataError(err) || !strings.Contains(err.Error(), "does not match the numbering") {
		t.Fatalf("err = %v", err)
	}
}

func TestPlanRenamesSameIDChangesNothing(t *testing.T) {
	_, data := demoCopy(t)
	got, err := PlanRenames(data, data.Sprints[0].ID, data.Sprints[0].ID)
	if err != nil || len(got) != 0 {
		t.Fatalf("renames = %v, %v", got, err)
	}
}

func TestPlanRenamesCountsOnForLaterSprints(t *testing.T) {
	_, data := demoCopy(t)
	last := len(data.Sprints) - 1
	second, third := data.Sprints[last-1].ID, data.Sprints[last].ID
	// The second to last sprint takes the ID after the last one: the last one counts on from it.
	to := following(t, third)
	got, err := PlanRenames(data, second, to)
	want := []Rename{{second, to}, {third, following(t, to)}}
	if err != nil || len(got) != 2 || got[0] != want[0] || got[1] != want[1] {
		t.Fatalf("renames = %v, %v, want %v", got, err, want)
	}
	// An ID that an earlier sprint already has is refused.
	_, err = PlanRenames(data, third, second)
	if err == nil || !isDataError(err) || !strings.Contains(err.Error(), "already taken") {
		t.Fatalf("err = %v", err)
	}
}

func TestApplyRenamesMovesSprintsAndKeepsOverlappingMinutes(t *testing.T) {
	repo, data := demoCopy(t)
	last := len(data.Sprints) - 1
	a, b := data.Sprints[last-1].ID, data.Sprints[last].ID
	c := following(t, b)
	// The chain a -> b, b -> c overlaps: b is a target and a source at the same time.
	renames, err := PlanRenames(data, a, b)
	if err != nil || len(renames) != 2 || renames[0] != (Rename{a, b}) || renames[1] != (Rename{b, c}) {
		t.Fatalf("renames = %v, %v", renames, err)
	}
	store := &protocol.Store{Dir: repo.TeamDir("demo")}
	startA, startB := data.SprintByID(a).Start, data.SprintByID(b).Start
	for id, text := range map[string]string{a: "# Minutes of the first\n", b: "# Minutes of the second\n"} {
		if _, created, err := store.WriteNew(id, "review", text, nil); err != nil || !created {
			t.Fatalf("minutes of %s: created %v, %v", id, created, err)
		}
	}
	applied, err := ApplyRenames(repo, data, renames)
	if err != nil {
		t.Fatal(err)
	}
	if len(applied.Files) != 2 || len(applied.Touched) < 4 {
		t.Errorf("applied = %+v", applied)
	}
	after, err := repo.Load("demo")
	if err != nil {
		t.Fatal(err)
	}
	if after.SprintByID(a) != nil || after.SprintByID(b) == nil || after.SprintByID(c) == nil {
		t.Fatalf("sprints after the rename: %v", ids(after.Sprints[len(after.Sprints)-3:]))
	}
	if !after.SprintByID(b).Start.Equal(startA) || !after.SprintByID(c).Start.Equal(startB) {
		t.Errorf("the sprints must keep their dates: %v / %v", after.SprintByID(b).Start, after.SprintByID(c).Start)
	}
	// Each minute went to the new ID of its own sprint; none overwrote the other.
	for id, want := range map[string]string{b: "first", c: "second"} {
		list, err := store.List(id)
		if err != nil || len(list) != 1 {
			t.Fatalf("minutes of %s: %v, %v", id, list, err)
		}
		if body, _ := os.ReadFile(list[0].Path); !strings.Contains(string(body), "Minutes of the "+want) {
			t.Errorf("minutes of %s hold %q", id, body)
		}
	}
	if left, _ := filepath.Glob(filepath.Join(repo.TeamDir("demo"), protocol.Folder, "*.renaming-*")); len(left) != 0 {
		t.Errorf("temporary names are left: %v", left)
	}
	if old, _ := store.List(a); len(old) != 0 {
		t.Errorf("the old ID still has minutes: %v", old)
	}
}

func ids(sprints []model.Sprint) []string {
	out := make([]string, len(sprints))
	for i, s := range sprints {
		out[i] = s.ID
	}
	return out
}

func TestApplyRenamesRefusesAnExistingTargetAndChangesNothing(t *testing.T) {
	repo, data := demoCopy(t)
	last := len(data.Sprints) - 1
	a, b := data.Sprints[last-1].ID, data.Sprints[last].ID
	read := func(id string) string {
		path, _ := repo.SprintPath("demo", id)
		body, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		return string(body)
	}
	beforeA, beforeB := read(a), read(b)
	// b exists and is not renamed away: moving a onto it must be refused.
	_, err := ApplyRenames(repo, data, []Rename{{a, b}})
	if err == nil || !isDataError(err) || !strings.Contains(err.Error(), "already exists") {
		t.Fatalf("err = %v", err)
	}
	if read(a) != beforeA || read(b) != beforeB {
		t.Error("a sprint file changed")
	}
	if _, err := ApplyRenames(repo, data, []Rename{{"no-such", "2099.1"}}); err == nil || !strings.Contains(err.Error(), "not found") {
		t.Errorf("an unknown sprint: %v", err)
	}
	if got, err := ApplyRenames(repo, data, nil); err != nil || len(got.Files) != 0 {
		t.Errorf("no renames must be a no-op: %+v, %v", got, err)
	}
}
