package engine

import (
	"testing"

	"github.com/swallat/foresprint/internal/model"
)

func TestStartRateWithoutHistory(t *testing.T) {
	settings := model.NewTeam("t", "T").Forecast
	capacity := model.Ptr(10.0)
	inputs := []SprintInput{{ID: "1", Capacity: capacity}}

	res, err := Compute(inputs, settings)
	if err != nil {
		t.Fatal(err)
	}
	if res[0].Plan != nil {
		t.Fatalf("without start rate and history there is no plan, got %v", *res[0].Plan)
	}

	settings.StartRate = 0.75
	res, _ = Compute(inputs, settings)
	if res[0].Plan == nil || *res[0].Plan != 7.5 || *res[0].PlanSource != PlanStart {
		t.Fatalf("plan = %v source = %v, want 7.5 from start rate", res[0].Plan, res[0].PlanSource)
	}

	// From the third sprint with a velocity on, the history takes over.
	inputs = []SprintInput{
		{ID: "1", Capacity: capacity, Velocity: model.Ptr(5.0)},
		{ID: "2", Capacity: capacity, Velocity: model.Ptr(5.0)},
		{ID: "3", Capacity: capacity, Velocity: model.Ptr(5.0)},
		{ID: "4", Capacity: capacity},
	}
	res, _ = Compute(inputs, settings)
	if *res[1].PlanSource != PlanStart {
		t.Fatalf("two sprints are too thin for a trend, source = %v", *res[1].PlanSource)
	}
	if *res[3].PlanSource != PlanForecast || *res[3].Plan != 5 {
		t.Fatalf("plan = %v source = %v, want 5 from the history", *res[3].Plan, *res[3].PlanSource)
	}
}
