package planning

import "github.com/swallat/foresprint/internal/model"

// UnitAt is the estimation unit that applies to a sprint (decision 19): the unit of the team
// until a UnitChange takes over from its first sprint on. order lists the sprint ids from the
// oldest to the newest; an id that is not in it gets the unit and factor of the team.
func UnitAt(team *model.Team, order []string, id string) model.Unit {
	unit, _ := settingAt(team, order, id)
	return unit
}

// FactorAt is the fixed points-per-PD factor that applies to a sprint, or nil when the
// measured team rate is to be used. A change that sets no factor falls back to the team's.
func FactorAt(team *model.Team, order []string, id string) *float64 {
	_, factor := settingAt(team, order, id)
	return factor
}

func settingAt(team *model.Team, order []string, id string) (model.Unit, *float64) {
	index := map[string]int{}
	for i, s := range order {
		index[s] = i
	}
	unit, factor := team.Unit, team.Estimation.Factor
	at, ok := index[id]
	if !ok {
		return unit, factor
	}
	best := -1
	for _, c := range team.Estimation.Changes {
		from, known := index[c.From]
		if !known || from > at || from < best {
			continue
		}
		best = from
		unit = c.Unit
		if c.Factor != nil {
			factor = c.Factor
		} else {
			factor = team.Estimation.Factor
		}
	}
	return unit, factor
}

// Value is an amount with its unit. Estimate marks a value that was converted between story
// points and person days: it rests on a rate and is shown as an estimate.
type Value struct {
	Amount   float64
	Unit     model.Unit
	Estimate bool
}

// Convert expresses an amount of the unit from in the unit to. A fixed factor wins; without
// one the given measured rate is used (planned work: the forecast rate of the sprint, done
// work: the actual rate). ok is false if a conversion is needed but no rate is valid.
func Convert(amount float64, from, to model.Unit, factor *float64, measured Rate) (Value, bool) {
	if from == to {
		return Value{Amount: amount, Unit: to}, true
	}
	rate := measured
	if factor != nil {
		rate = Rate(*factor)
	}
	var out float64
	var ok bool
	if from == model.UnitSP {
		out, ok = rate.ToPD(amount)
	} else {
		out, ok = rate.ToPoints(amount)
	}
	if !ok {
		return Value{}, false
	}
	return Value{Amount: out, Unit: to, Estimate: true}, true
}
