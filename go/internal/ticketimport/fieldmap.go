package ticketimport

import (
	"strconv"
	"strings"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/sources"
)

// Names under which the tracker fields of the field mapping (decision 21) travel through the
// sources: as rule fields, so that CSV and Jira read them without a second path. The leading
// underscore keeps them apart from the rule fields the team configures (RuleFieldName).
const (
	MapProduction = "_production"
	MapProduct    = "_product"
	MapProject    = "_project"
	MapRefined    = "_refined"
)

// mappedFields are the mapped fields of the tracker settings in a fixed order.
func mappedFields(t model.TrackerSettings) []struct{ Name, Display string } {
	var out []struct{ Name, Display string }
	for _, m := range []struct {
		name  string
		field *string
	}{
		{MapProduction, t.Fields.Production},
		{MapProduct, t.Fields.Product},
		{MapProject, t.Fields.Project},
		{MapRefined, t.Fields.Refined},
	} {
		if m.field != nil && strings.TrimSpace(*m.field) != "" {
			out = append(out, struct{ Name, Display string }{m.name, *m.field})
		}
	}
	return out
}

// MappedRuleFields are the mapped fields as extra fields for the sources.
func MappedRuleFields(t model.TrackerSettings) []sources.RuleField {
	var out []sources.RuleField
	for _, m := range mappedFields(t) {
		out = append(out, sources.RuleField{Name: m.Name, Display: m.Display})
	}
	return out
}

// ParsePercent reads a production share from the values of a field: "60", "60 %", "60%" or
// "0,5" are read as a percentage in 0 to 100 (a plain fraction below or at 1 is not guessed:
// "1" is 1 percent). Anything else is no value.
func ParsePercent(values []string) (float64, bool) {
	for _, v := range values {
		text := strings.TrimSpace(strings.TrimSuffix(pytext.Strip(v), "%"))
		text = strings.ReplaceAll(text, ",", ".")
		f, err := strconv.ParseFloat(text, 64)
		if err != nil || f != f || f < 0 || f > 100 {
			continue
		}
		return f, true
	}
	return 0, false
}

// falseWords are the values of a refined field that mean "not refined".
var falseWords = map[string]bool{
	"": true, "0": true, "no": true, "nein": true, "false": true, "falsch": true, "n": true,
	"not refined": true, "nicht verfeinert": true,
}

// RefinedFromField reads the mapped "refined" field: any value except the words for no. ok is
// false when the ticket has no value in the field (the label and rule decide then).
func RefinedFromField(values []string) (refined, ok bool) {
	for _, v := range values {
		if strings.TrimSpace(v) == "" {
			continue
		}
		return !falseWords[strings.ToLower(pytext.Strip(v))], true
	}
	return false, false
}

// ProductionSource says where the production share of a ticket comes from.
type ProductionSource string

// The sources of a production share, in the order they are tried.
const (
	ProductionHand  ProductionSource = "hand"  // set in Foresprint (preplan.yaml)
	ProductionField ProductionSource = "field" // the mapped tracker field
	ProductionLabel ProductionSource = "label" // the production label: 100 %
	ProductionRule  ProductionSource = "rule"  // the first matching production rule
	ProductionNone  ProductionSource = "none"  // nothing applies: 0 %
)

// Production is the production share of a ticket (0 to 100) and where it comes from.
type Production struct {
	Percent float64
	Source  ProductionSource
	// Rule is the index in tracker.production_rules for ProductionRule.
	Rule int
}

// ProductionOf resolves the production share of a ticket (decision 20): a value set by hand
// wins over the mapped tracker field, that over the production label, that over the first
// matching production rule; otherwise 0 %.
func ProductionOf(t model.Ticket, tracker model.TrackerSettings, preplan model.Preplan) Production {
	if h := preplan.ProductionFor(t.Key); h != nil {
		return Production{Percent: clampPercent(h.Percent), Source: ProductionHand}
	}
	if tracker.Fields.Production != nil {
		if values, ok := t.Extra.Get(MapProduction); ok {
			if p, ok := ParsePercent(values); ok {
				return Production{Percent: p, Source: ProductionField}
			}
		}
	}
	if tracker.ProductionLabel != nil && *tracker.ProductionLabel != "" {
		for _, l := range t.Labels {
			if l == *tracker.ProductionLabel {
				return Production{Percent: 100, Source: ProductionLabel}
			}
		}
	}
	facts := t.Facts()
	for i, r := range tracker.ProductionRules {
		if r.Match != nil && r.Match.Matches(facts) {
			return Production{Percent: clampPercent(r.Percent), Source: ProductionRule, Rule: i}
		}
	}
	return Production{Source: ProductionNone}
}

func clampPercent(p float64) float64 {
	switch {
	case p < 0:
		return 0
	case p > 100:
		return 100
	}
	return p
}

// matchByIDOrName finds the id of the entry whose id or name equals value (case-insensitive).
func matchByIDOrName(value string, ids, names []string) (string, bool) {
	value = pytext.Casefold(pytext.Strip(value))
	for i, id := range ids {
		if pytext.Casefold(id) == value || pytext.Casefold(names[i]) == value {
			return id, true
		}
	}
	return "", false
}

// applyMappedAssignment lets a mapped project or product field decide (decision 21): the value
// is matched against the id or the name of the projects and products; a value that matches
// nothing leaves the decision to the rules.
func applyMappedAssignment(t *model.Ticket, env Env) {
	if env.Tracker.Fields.Project != nil {
		if values, ok := t.Extra.Get(MapProject); ok {
			ids, names := make([]string, len(env.Projects)), make([]string, len(env.Projects))
			for i, p := range env.Projects {
				ids[i], names[i] = p.ID, p.Name
			}
			for _, v := range values {
				if id, ok := matchByIDOrName(v, ids, names); ok {
					t.Project = &id
					t.ProjectCandidates = []string{}
					break
				}
			}
		}
	}
	if env.Tracker.Fields.Product != nil {
		if values, ok := t.Extra.Get(MapProduct); ok {
			ids, names := make([]string, len(env.Products)), make([]string, len(env.Products))
			for i, p := range env.Products {
				ids[i], names[i] = p.ID, p.Name
			}
			for _, v := range values {
				if id, ok := matchByIDOrName(v, ids, names); ok {
					t.Product = &id
					break
				}
			}
		}
	}
}
