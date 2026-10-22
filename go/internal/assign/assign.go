// Package assign decides which project (or product) a ticket belongs to by the assignment
// rules; port of assign_project of ticket_import.py.
package assign

import "github.com/swallat/foresprint/internal/rules"

// Candidate is a project or product with an optional assignment rule.
type Candidate struct {
	ID    string
	Match *rules.Rule
}

// Project returns the id of the project whose rule matches the facts, and the candidates when
// several contradict each other (then the id is empty).
//
// Of all candidates whose rule matches, the one matching via the source earliest in order
// wins; sources outside the order rank last. Several candidates matching via the same best
// source contradict each other: no project, all of them as candidates (in file order).
func Project(facts rules.Facts, candidates []Candidate, order []string) (id string, contradiction []string) {
	rank := func(sources []string) int {
		best := len(order)
		for _, s := range sources {
			for i, o := range order {
				if o == s && i < best {
					best = i
					break
				}
			}
		}
		return best
	}
	type match struct {
		id   string
		rank int
	}
	var matching []match
	for _, c := range candidates {
		if c.Match != nil && c.Match.Matches(facts) {
			matching = append(matching, match{c.ID, rank(c.Match.MatchedSources(facts))})
		}
	}
	if len(matching) == 0 {
		return "", nil
	}
	best := matching[0].rank
	for _, m := range matching {
		if m.rank < best {
			best = m.rank
		}
	}
	var winners []string
	for _, m := range matching {
		if m.rank == best {
			winners = append(winners, m.id)
		}
	}
	if len(winners) == 1 {
		return winners[0], nil
	}
	return "", winners
}
