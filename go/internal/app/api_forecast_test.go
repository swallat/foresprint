package app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func TestForecastOfTheDemoTeam(t *testing.T) {
	api := newAPI(t, demoDir(t))
	teams := api.Teams()
	if len(teams) == 0 {
		t.Fatal("no teams")
	}
	key := teams[0].Key
	v, err := api.Forecast(key)
	if err != nil {
		t.Fatal(err)
	}
	if len(v.Past) == 0 || len(v.Upcoming) == 0 {
		t.Fatalf("past %d, upcoming %d", len(v.Past), len(v.Upcoming))
	}
	if v.Upcoming[0].Plan == nil {
		t.Error("the next sprint has no plan")
	}

	for _, r := range v.Upcoming {
		if r.Plan == nil || r.Plannable == nil || r.Small == nil || r.Overbooked {
			continue
		}
		if sum := *r.Plannable + *r.Small + r.CarryIn; sum < *r.Plan-1e-9 || sum > *r.Plan+1e-9 {
			t.Errorf("%s: plannable %v + small %v + carry-over %v is not the plan %v", r.ID, *r.Plannable, *r.Small, r.CarryIn, *r.Plan)
		}
	}

	same, err := api.ForecastWhatIf(key, ForecastAssumption{FocusPercent: 100})
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range same {
		if r.Delta != 0 {
			t.Errorf("%s: unchanged assumptions change the forecast by %v", r.ID, r.Delta)
		}
	}
	focused, _ := api.ForecastWhatIf(key, ForecastAssumption{FocusPercent: 90})
	if len(focused) > 0 && focused[0].Forecast > focused[0].Base {
		t.Errorf("a lower focus must not raise the forecast: %v > %v", focused[0].Forecast, focused[0].Base)
	}
	less, _ := api.ForecastWhatIf(key, ForecastAssumption{ExtraAbsenceDays: 3, FocusPercent: 100})
	if len(less) > 0 && less[0].Delta >= 0 {
		t.Errorf("fewer person days must lower the forecast, delta %v", less[0].Delta)
	}
	if _, err := api.ForecastWhatIf(key, ForecastAssumption{ExtraAbsenceDays: -1, FocusPercent: 100}); err == nil {
		t.Error("negative days must be refused")
	}

	w1, err := api.ForecastWhenDone(key, 60, 50, "")
	if err != nil {
		t.Fatal(err)
	}
	w2, _ := api.ForecastWhenDone(key, 60, 50, "")
	if w1.P50 != w2.P50 || w1.P85 != w2.P85 {
		t.Error("the simulation is not repeatable")
	}
	if _, err := api.ForecastWhenDone(key, 60, 150, ""); err == nil {
		t.Error("a share above 100 must be refused")
	}
}

// copyTree copies a directory so a test can change its data.
func copyTree(t *testing.T, from, to string) {
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

func TestForecastPlannableAfterCarryOver(t *testing.T) {
	dir := t.TempDir()
	copyTree(t, demoDir(t), dir)
	api := newAPI(t, dir)
	key := api.Teams()[0].Key
	base, err := api.Forecast(key)
	if err != nil || len(base.Past) == 0 || len(base.Upcoming) == 0 {
		t.Fatalf("forecast: %v", err)
	}
	last := base.Past[len(base.Past)-1].ID
	first := base.Upcoming[0].ID

	file := filepath.Join(dir, key, "sprints", last+".yaml")
	f, err := os.OpenFile(file, os.O_APPEND|os.O_WRONLY, 0)
	if err != nil {
		t.Skip("sprint file not found: " + err.Error())
	}
	if _, err := f.WriteString("\nrest_next: 4\n"); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}

	v, err := api.Forecast(key)
	if err != nil {
		t.Fatal(err)
	}
	r := v.Upcoming[0]
	if r.ID != first || r.Plan == nil || r.Plannable == nil {
		t.Fatalf("row %+v", r)
	}
	if r.CarryIn != 4 || r.CarryAssumed {
		t.Errorf("carry-over %v (assumed %v), want 4 definitive", r.CarryIn, r.CarryAssumed)
	}
	b := base.Upcoming[0]
	if b.Plannable != nil && *r.Plannable >= *b.Plannable {
		t.Errorf("plannable %v did not drop below %v", *r.Plannable, *b.Plannable)
	}
}

func TestWhenDoneForAProject(t *testing.T) {
	dir := t.TempDir()
	copyTree(t, demoDir(t), dir)
	api := newAPI(t, dir)
	key := api.Teams()[0].Key
	teamFile := filepath.Join(dir, key, "team.yaml")
	raw, err := os.ReadFile(teamFile)
	if err != nil {
		t.Fatal(err)
	}
	raw = []byte(strings.Replace(string(raw), "features:\n", "features:\n  projects: true\n", 1))
	if err := os.WriteFile(teamFile, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	scope := 40.0
	soon := time.Date(2027, 12, 31, 0, 0, 0, 0, time.UTC)
	early := time.Date(2020, 1, 1, 0, 0, 0, 0, time.UTC)
	projects := []model.Project{
		{ID: "late", Name: "Late", End: &soon, OpenScope: &scope},
		{ID: "past", Name: "Past", End: &early, OpenScope: &scope},
		{ID: "open-ended", Name: "Open ended"},
		{ID: "done", Name: "Done", State: model.ProjectFinished},
	}
	if _, err := storage.NewRepository(dir).SaveProjects(key, projects); err != nil {
		t.Fatal(err)
	}

	list, err := api.ForecastWhenProjects(key)
	if err != nil || len(list) != 3 {
		t.Fatalf("projects %v %v", list, err)
	}
	if list[0].OpenScope == nil || *list[0].OpenScope != 40 || list[0].End != "2027-12-31" {
		t.Errorf("first project %+v", list[0])
	}

	v, err := api.ForecastWhenDone(key, 40, 50, "late")
	if err != nil || !v.Available {
		t.Fatalf("answer %+v %v", v, err)
	}
	if v.ProjectName != "Late" || v.ProjectEnd != "2027-12-31" || len(v.Starts) != len(v.Sprints) || len(v.Ends) != len(v.Sprints) {
		t.Errorf("project answer %+v", v)
	}
	if v.Earliest == "" || v.Light == "none" {
		t.Errorf("earliest %q light %q", v.Earliest, v.Light)
	}
	if past, _ := api.ForecastWhenDone(key, 40, 50, "past"); past.Light != "bad" {
		t.Errorf("an end in the past must be red, got %q", past.Light)
	}
	if free, _ := api.ForecastWhenDone(key, 40, 50, "open-ended"); free.Light != "none" || free.ProjectEnd != "" {
		t.Errorf("no project end: %+v", free)
	}
}

func TestForecastWhatIfForTheRunningSprint(t *testing.T) {
	dir := t.TempDir()
	copyTree(t, demoDir(t), dir)
	api := newAPI(t, dir)
	key := api.Teams()[0].Key
	v, err := api.Forecast(key)
	if err != nil {
		t.Fatal(err)
	}
	if v.Running == "" || v.Next == "" {
		t.Skip("the demo data has no running sprint")
	}
	low, high := 1.0, 1000.0
	base := ForecastAssumption{Sprint: v.Next, FocusPercent: 100}
	same, err := api.ForecastWhatIf(key, base)
	if err != nil || len(same) != 1 || same[0].ID != v.Next {
		t.Fatalf("one sprint expected, got %v, %v", same, err)
	}
	base.ExpectedVelocity = &low
	worse, _ := api.ForecastWhatIf(key, base)
	base.ExpectedVelocity = &high
	better, _ := api.ForecastWhatIf(key, base)
	if len(worse) != 1 || len(better) != 1 || worse[0].Forecast > better[0].Forecast {
		t.Errorf("a better running sprint must not lower the next one: %v vs %v", worse, better)
	}
	all, _ := api.ForecastWhatIf(key, ForecastAssumption{FocusPercent: 100})
	if len(all) < 2 {
		t.Errorf("all coming sprints expected, got %d", len(all))
	}

	allWith, _ := api.ForecastWhatIf(key, ForecastAssumption{FocusPercent: 100, ExpectedVelocity: &high})
	if len(allWith) != len(all) {
		t.Errorf("an expected velocity must not drop a sprint: %d vs %d", len(allWith), len(all))
	}

	save := ForecastAssumption{Sprint: v.Next, FocusPercent: 100, ExpectedVelocity: &low}
	if err := api.ForecastSaveWhatIf(key, save); err != nil {
		t.Fatal(err)
	}
	data, err := storage.NewRepository(dir).Load(key)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, s := range data.Sprints {
		if s.ID != v.Running {
			continue
		}
		for _, p := range s.Prognoses {
			if str(p.Target) == v.Next && p.Plan != nil && p.ExpectedDone != nil && p.Commitment != nil {
				found = true
			}
		}
	}
	if !found {
		t.Error("the prognosis is not in the running sprint")
	}
	if err := api.ForecastSaveWhatIf(key, save); err != nil {
		t.Fatal(err)
	}
	data, _ = storage.NewRepository(dir).Load(key)
	labels := map[string]bool{}
	for _, s := range data.Sprints {
		if s.ID == v.Running {
			for _, p := range s.Prognoses {
				if str(p.Target) == v.Next {
					labels[labelOf(p)] = true
				}
			}
		}
	}
	if len(labels) < 2 {
		t.Errorf("a second save must not replace the first: labels %v", labels)
	}
	save.Sprint = ""
	if err := api.ForecastSaveWhatIf(key, save); err == nil {
		t.Error("saving without the next sprint must be refused")
	}
}
