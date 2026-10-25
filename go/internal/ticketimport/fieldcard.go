package ticketimport

import (
	"strconv"

	"github.com/swallat/foresprint/internal/model"
)

// Where a value comes from, as the card "Feldzuordnung und Regeln" shows it (decision 21).
const (
	FromTrackerField = "field"         // always from a tracker field
	FromRules        = "rules"         // rules kept per product and project
	FromFieldOrRules = "field_or_rule" // a mapped field wins; rules are the fallback
	FromHand         = "hand"          // only by hand in Foresprint
)

// Origin says where one value Foresprint needs comes from.
type Origin struct {
	// Value is estimate, status, acceptance, product, project, refined or production.
	Value string
	From  string
	// Field is the tracker field when From says a field takes part; "" otherwise.
	Field string
}

func fieldName(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// Origins lists, for each value Foresprint needs, where it comes from with the current tracker
// settings. A value set by hand always wins (not repeated per line).
func Origins(t model.TrackerSettings) []Origin {
	pick := func(value string, field *string, rulesAvailable bool) Origin {
		o := Origin{Value: value, Field: fieldName(field)}
		switch {
		case o.Field != "" && rulesAvailable:
			o.From = FromFieldOrRules
		case o.Field != "":
			o.From = FromTrackerField
		case rulesAvailable:
			o.From = FromRules
		default:
			o.From = FromHand
		}
		return o
	}
	production := pick("production", t.Fields.Production, len(t.ProductionRules) > 0 ||
		fieldName(t.ProductionLabel) != "")
	return []Origin{
		{Value: "estimate", From: FromTrackerField, Field: fieldName(t.Fields.Estimate)},
		{Value: "status", From: FromTrackerField, Field: fieldName(t.Fields.Status)},
		{Value: "acceptance", From: FromTrackerField, Field: fieldName(t.Fields.Acceptance)},
		pick("product", t.Fields.Product, true),
		pick("project", t.Fields.Project, true),
		pick("refined", t.Fields.Refined, fieldName(t.RefinedLabel) != "" || t.RefinedAlsoIf != nil),
		production,
	}
}

// RuleFieldUsers returns where a rule field is used by a rule: "product <id>", "project <id>",
// "refined", "production rule <n>". A field cannot be removed while the list is not empty.
func RuleFieldUsers(name string, t model.TrackerSettings, products []model.Product, projects []model.Project) []string {
	uses := func(r *model.Rule) bool {
		if r == nil {
			return false
		}
		for _, s := range r.LeafSources() {
			if s == name {
				return true
			}
		}
		return false
	}
	var out []string
	for _, p := range products {
		if uses(p.Match) {
			out = append(out, "product "+p.ID)
		}
	}
	for _, p := range projects {
		if uses(p.Match) {
			out = append(out, "project "+p.ID)
		}
	}
	if uses(t.RefinedAlsoIf) {
		out = append(out, "refined")
	}
	for i, r := range t.ProductionRules {
		if uses(r.Match) {
			out = append(out, "production rule "+strconv.Itoa(i+1))
		}
	}
	return out
}
