package planning

import (
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
)

// CarryIn is the rest of earlier sprints that continues in a sprint.
type CarryIn struct {
	// Rest is the sum of the parts that continue in the sprint (team unit).
	Rest float64
	// Items are those parts, each with the sprint it comes from.
	Items []CarryFrom
	// Assumed is true if at least one part is only an assumption of a running sprint; a
	// definitive rest from the Review replaces the assumption of its sprint.
	Assumed bool
}

// CarryFrom is one carried-over part and the sprint it comes from.
type CarryFrom struct {
	Sprint string
	model.CarryItem
}

// CarryInto adds up what the earlier sprints carry into the sprint target. A sprint with a
// definitive rest (entered in the Review: Carry or RestNext) counts with that; otherwise its
// assumption with the given label counts (empty label = the newest assumption). A target of
// "" means the sprint after the one the rest comes from, so a rest without a target
// continues in the next sprint. Rest that goes to the backlog or a pro-forma sprint never
// lowers what is plannable in a sprint. sprints must be ordered from oldest to newest.
func CarryInto(sprints []model.Sprint, target, label string) CarryIn {
	var in CarryIn
	var rests []float64
	for i, s := range sprints {
		items, assumed := carryOf(s, label)
		for _, item := range items {
			dest := item.Target
			if dest == "" && i+1 < len(sprints) {
				dest = sprints[i+1].ID
			}
			if dest != target {
				continue
			}
			rests = append(rests, item.Rest)
			in.Items = append(in.Items, CarryFrom{Sprint: s.ID, CarryItem: item})
			in.Assumed = in.Assumed || assumed
		}
	}
	in.Rest = pymath.Sum(rests)
	return in
}

// carryOf is what a sprint carries on: the definitive rest, else the chosen assumption.
func carryOf(s model.Sprint, label string) ([]model.CarryItem, bool) {
	if len(s.Carry) > 0 {
		return s.Carry, false
	}
	if s.RestNext != nil {
		return []model.CarryItem{{Rest: *s.RestNext}}, false
	}
	if s.Velocity != nil { // reviewed: nothing carried over is the definitive result
		return nil, false
	}
	p := pick(s.Prognoses, label)
	if p == nil {
		return nil, false
	}
	if len(p.Carry) > 0 {
		return p.Carry, true
	}
	if p.RestNext != nil {
		return []model.CarryItem{{Rest: *p.RestNext}}, true
	}
	return nil, false
}

func pick(list []model.Prognosis, label string) *model.Prognosis {
	for i := len(list) - 1; i >= 0; i-- {
		l := ""
		if list[i].Label != nil {
			l = *list[i].Label
		}
		if label == "" || l == label {
			return &list[i]
		}
	}
	return nil
}
