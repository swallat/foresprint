package capacity_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/model"
)

// The capacity breakdown of every sprint in the forecast of a team with a people list equals
// the one of the Python core: per person, with a rate, with announced absences, the production
// share.
func TestCapacityMatchesPython(t *testing.T) {
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			var want any
			if !c.LoadExpected(t, &want, "capacity.json") {
				t.Skip("no people list, no reference")
			}
			data := coretest.Load(t, c)
			fc, err := forecast.Build(data, coretest.Today(t, c))
			if err != nil {
				t.Fatal(err)
			}
			rate := 0.0
			if fc.Absences != nil && fc.Absences.Rate != nil {
				rate = *fc.Absences.Rate
			}
			out := []map[string]any{}
			for _, e := range fc.Entries {
				b := capacity.Sprint(&data.Team, data.People, e.Sprint, 0)
				approx := []string{}
				for _, p := range b.Approximated() {
					approx = append(approx, p.Person.ID)
				}
				var share *float64
				if s, ok := capacity.ProductionShare(&data.Team, data.People, e.Sprint); ok {
					share = model.Ptr(s)
				}
				out = append(out, map[string]any{
					"sprint":            e.Sprint.ID,
					"breakdown":         b,
					"rounded":           b.Rounded(),
					"approximated":      approx,
					"with_rate_0_1":     capacity.Sprint(&data.Team, data.People, e.Sprint, 0.1),
					"history_rate":      rate,
					"expected_absences": capacity.WithExpectedAbsences(&data.Team, data.People, e.Sprint),
					"production_share":  share,
				})
			}
			golden.Compare(t, want, coretest.JSON(t, map[string]any{"sprints": out}))
		})
	}
}
