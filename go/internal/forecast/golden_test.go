package forecast_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/golden"
)

// The forecast of every golden case equals the one of the Python core: every sprint with all
// metrics, averages, trends, the plan and the source of the capacity.
func TestBuildMatchesPython(t *testing.T) {
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			var want any
			if !c.LoadExpected(t, &want, "forecast.json") {
				t.Skip("no reference")
			}
			data := coretest.Load(t, c)
			fc, err := forecast.Build(data, coretest.Today(t, c))
			if err != nil {
				t.Fatal(err)
			}
			got := map[string]any{
				"today":    fc.Today,
				"entries":  fc.Entries,
				"absences": fc.Absences,
			}
			golden.Compare(t, coretest.Prune(want), coretest.JSON(t, got))
		})
	}
}
