package app

import (
	"os"
	"path/filepath"
	"testing"
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

	same, err := api.ForecastWhatIf(key, 0, 100)
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range same {
		if r.Delta != 0 {
			t.Errorf("%s: unchanged assumptions change the forecast by %v", r.ID, r.Delta)
		}
	}
	focused, _ := api.ForecastWhatIf(key, 0, 90)
	if len(focused) > 0 && focused[0].Forecast > focused[0].Base {
		t.Errorf("a lower focus must not raise the forecast: %v > %v", focused[0].Forecast, focused[0].Base)
	}
	less, _ := api.ForecastWhatIf(key, 3, 100)
	if len(less) > 0 && less[0].Delta >= 0 {
		t.Errorf("fewer person days must lower the forecast, delta %v", less[0].Delta)
	}
	if _, err := api.ForecastWhatIf(key, -1, 100); err == nil {
		t.Error("negative days must be refused")
	}

	w1, err := api.ForecastWhenDone(key, 60, 50)
	if err != nil {
		t.Fatal(err)
	}
	w2, _ := api.ForecastWhenDone(key, 60, 50)
	if w1.P50 != w2.P50 || w1.P85 != w2.P85 {
		t.Error("the simulation is not repeatable")
	}
	if _, err := api.ForecastWhenDone(key, 60, 150); err == nil {
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
	f.Close()

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
