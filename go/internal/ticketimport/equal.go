package ticketimport

import "github.com/swallat/foresprint/internal/model"

// Equality like Python's dataclass comparison (the stored files are compared with the plan).

func floatPtrEqual(a, b *float64) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

func stringPtrEqual(a, b *string) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

func stringsEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func extraEqual(a, b model.OrderedMap[[]string]) bool {
	if a.Len() != b.Len() {
		return false
	}
	for _, e := range a.Entries {
		other, ok := b.Get(e.Key)
		if !ok || !stringsEqual(e.Value, other) {
			return false
		}
	}
	return true
}

func ticketEqual(a, b model.Ticket) bool {
	return a.Key == b.Key && a.Title == b.Title &&
		stringPtrEqual(a.Status, b.Status) && stringPtrEqual(a.IssueType, b.IssueType) &&
		stringPtrEqual(a.Priority, b.Priority) && extraEqual(a.Extra, b.Extra) &&
		floatPtrEqual(a.Estimate, b.Estimate) && floatPtrEqual(a.Remaining, b.Remaining) &&
		a.EstimateSource == b.EstimateSource && a.RefinedUnclear == b.RefinedUnclear &&
		stringPtrEqual(a.InSprint, b.InSprint) && stringPtrEqual(a.SprintName, b.SprintName) &&
		stringPtrEqual(a.Rank, b.Rank) && stringPtrEqual(a.Epic, b.Epic) &&
		stringsEqual(a.Labels, b.Labels) && stringsEqual(a.Components, b.Components) &&
		stringsEqual(a.DependsOn, b.DependsOn) && stringPtrEqual(a.Project, b.Project) &&
		stringsEqual(a.ProjectCandidates, b.ProjectCandidates) && a.Done == b.Done
}

func ticketsEqual(a, b []model.Ticket) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if !ticketEqual(a[i], b[i]) {
			return false
		}
	}
	return true
}

func preplanEqual(a, b model.Preplan) bool {
	if len(a.Earmarks) != len(b.Earmarks) || len(a.Estimates) != len(b.Estimates) {
		return false
	}
	for i := range a.Earmarks {
		x, y := a.Earmarks[i], b.Earmarks[i]
		if x.Ticket != y.Ticket || x.Sprint != y.Sprint || !stringPtrEqual(x.Note, y.Note) {
			return false
		}
	}
	for i := range a.Estimates {
		x, y := a.Estimates[i], b.Estimates[i]
		if x.Ticket != y.Ticket || !floatPtrEqual(x.Estimate, y.Estimate) || !stringPtrEqual(x.Note, y.Note) {
			return false
		}
	}
	return true
}
