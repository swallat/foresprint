package app

import "testing"

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
