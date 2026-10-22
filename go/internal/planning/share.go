package planning

import "github.com/swallat/foresprint/internal/model"

// ShareSource says where the production share of a ticket comes from.
type ShareSource string

// The sources, strongest first (decision 20).
const (
	ShareByHand ShareSource = "hand"
	ShareField  ShareSource = "field"
	ShareLabel  ShareSource = "label"
	ShareRule   ShareSource = "rule"
	ShareNone   ShareSource = "none"
)

// ShareOf is the production share of a ticket, from 0 to 1, and where it comes from. The
// value set by hand in the pre-planning wins, then the value of the mapped tracker field
// (field, nil if not mapped or empty), then the production label (all of the ticket), then the
// first production rule that fits; a ticket without any of them has no production share. Values
// outside 0 to 100 percent are cut to the range.
func ShareOf(ticket model.Ticket, preplan model.Preplan, tracker model.TrackerSettings, field *float64) (float64, ShareSource) {
	if hand := preplan.ProductionFor(ticket.Key); hand != nil {
		return percent(hand.Percent), ShareByHand
	}
	if field != nil {
		return percent(*field), ShareField
	}
	if tracker.ProductionLabel != nil && *tracker.ProductionLabel != "" {
		for _, l := range ticket.Labels {
			if l == *tracker.ProductionLabel {
				return 1, ShareLabel
			}
		}
	}
	facts := ticket.Facts()
	for _, r := range tracker.ProductionRules {
		if r.Match != nil && r.Match.Matches(facts) {
			return percent(r.Percent), ShareRule
		}
	}
	return 0, ShareNone
}

func percent(p float64) float64 {
	switch {
	case p <= 0:
		return 0
	case p >= 100:
		return 1
	}
	return p / 100
}
