package sprintcal

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// demoCopy copies the demo team into a temporary data folder and loads it.
func demoCopy(t *testing.T) (*storage.Repository, *storage.TeamData) {
	t.Helper()
	src, err := filepath.Abs(filepath.Join("..", "..", "..", "examples", "teams", "demo"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(src); err != nil {
		t.Skip("no examples/teams/demo: " + err.Error())
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
	return repo, data
}

func TestPlanRenamesRefusals(t *testing.T) {
	_, data := demoCopy(t)
	first := data.Sprints[0].ID
	for name, c := range map[string]struct{ sprint, to, want string }{
		"unknown sprint": {"no-such", "2026.99", "not saved"},
		"empty id":       {first, "  ", "new sprint ID"},
		"bad file name":  {first, "a/b", "not allowed"},
	} {
		_, err := PlanRenames(data, c.sprint, c.to)
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: err = %v, want a message with %q", name, err, c.want)
		}
	}
}

func TestPlanRenamesRefusesAnIDOutsideSequentialNumbering(t *testing.T) {
	_, data := demoCopy(t)
	data.Team.Sprint.Numbering = model.NumberingSequential
	if _, err := PlanRenames(data, data.Sprints[0].ID, "abc"); err == nil || !strings.Contains(err.Error(), "numbering") {
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
	if last < 2 {
		t.Fatal("the demo team needs at least three sprints")
	}
	// Renaming the second to last sprint moves the last one along with it.
	old1, old2 := data.Sprints[last-1].ID, data.Sprints[last].ID
	to, err := nextIDAfter(old2)
	if err != "" {
		t.Skip(err)
	}
	got, perr := PlanRenames(data, old2, to)
	if perr != nil || len(got) != 1 || got[0].Old != old2 || got[0].New != to {
		t.Fatalf("renames = %v, %v", got, perr)
	}
	// A new ID that an earlier sprint already uses is refused.
	if _, perr := PlanRenames(data, old2, old1); perr == nil {
		t.Error("an ID of an earlier sprint was accepted")
	}
}

// nextIDAfter gives "<year>.<n+1>" for "<year>.<n>".
func nextIDAfter(id string) (string, string) {
	year, n, ok := strings.Cut(id, ".")
	if !ok {
		return "", "the demo IDs are not year.number"
	}
	num := 0
	for _, r := range n {
		if r < '0' || r > '9' {
			return "", "the demo IDs are not year.number"
		}
		num = num*10 + int(r-'0')
	}
	return year + "." + itoa(num+1), ""
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b []byte
	for ; n > 0; n /= 10 {
		b = append([]byte{byte('0' + n%10)}, b...)
	}
	return string(b)
}

func TestApplyRenamesMovesFilesAndMinutes(t *testing.T) {
	repo, data := demoCopy(t)
	last := data.Sprints[len(data.Sprints)-1].ID
	to, msg := nextIDAfter(last)
	if msg != "" {
		t.Skip(msg)
	}
	renames := []Rename{{last, to}}
	oldPath, _ := repo.SprintPath("demo", last)
	newPath, _ := repo.SprintPath("demo", to)
	applied, err := ApplyRenames(repo, data, renames)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(oldPath); !os.IsNotExist(err) {
		t.Errorf("the old file is still there: %v", err)
	}
	if _, err := os.Stat(newPath); err != nil {
		t.Errorf("the new file is missing: %v", err)
	}
	if len(applied.Files) != 1 || len(applied.Touched) < 2 {
		t.Errorf("applied = %+v", applied)
	}
	again, _ := repo.Load("demo")
	if again.SprintByID(to) == nil || again.SprintByID(last) != nil {
		t.Errorf("sprints after the rename: %v", again.Sprints[len(again.Sprints)-1].ID)
	}
}

func TestApplyRenamesRefusesAnExistingTargetAndChangesNothing(t *testing.T) {
	repo, data := demoCopy(t)
	if len(data.Sprints) < 2 {
		t.Fatal("the demo team needs two sprints")
	}
	a, b := data.Sprints[len(data.Sprints)-2].ID, data.Sprints[len(data.Sprints)-1].ID
	pathA, _ := repo.SprintPath("demo", a)
	before, err := os.ReadFile(pathA)
	if err != nil {
		t.Fatal(err)
	}
	// b exists and is not renamed away: moving a onto it must be refused.
	if _, err := ApplyRenames(repo, data, []Rename{{a, b}}); err == nil {
		t.Fatal("renaming onto an existing sprint file was accepted")
	}
	after, err := os.ReadFile(pathA)
	if err != nil || string(after) != string(before) {
		t.Errorf("the sprint file changed: %v", err)
	}
	if _, err := ApplyRenames(repo, data, []Rename{{"no-such", "2099.1"}}); err == nil {
		t.Error("an unknown sprint was accepted")
	}
	if got, err := ApplyRenames(repo, data, nil); err != nil || len(got.Files) != 0 {
		t.Errorf("no renames must be a no-op: %+v, %v", got, err)
	}
}
