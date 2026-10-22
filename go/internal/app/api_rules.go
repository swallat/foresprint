package app

import (
	"errors"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/rules"
	"github.com/swallat/foresprint/internal/storage"
)

// RuleFields lists the fields a rule of the team may name.
func (a *API) RuleFields(team string) ([]string, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return nil, err
	}
	return model.RuleSourcesWith(data.Team.Tracker.RuleFields), nil
}

// CheckRule parses the text of a rule and says what it would match among the tickets of the
// team. An empty text is not a rule (a product without a rule is allowed; the caller decides).
// It never fails for bad text: the problem is part of the answer.
func (a *API) CheckRule(team, text string, owner RuleOwner) (RulePreview, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return RulePreview{}, err
	}
	return checkRule(data, text, owner), nil
}

func checkRule(data *storage.TeamData, text string, owner RuleOwner) RulePreview {
	fields := model.RuleSourcesWith(data.Team.Tracker.RuleFields)
	out := RulePreview{Fields: fields, Pos: -1, Sample: []string{}}
	rule, err := rules.ParseRule(text, fields)
	if err != nil {
		out.Error = err.Error()
		var se *rules.SyntaxError
		if errors.As(err, &se) {
			out.Pos = se.Position
		}
		return out
	}
	out.Valid = true
	out.Normalized = rules.FormatRule(rule)

	others := otherRules(data, owner)
	for _, t := range data.Tickets {
		facts := t.Facts()
		if !rule.Matches(facts) {
			continue
		}
		out.Matches++
		if t.Estimate != nil {
			out.Points += *t.Estimate
		}
		if len(out.Sample) < 5 {
			out.Sample = append(out.Sample, t.Key)
		}
		for _, o := range others {
			if o.Matches(facts) {
				out.Clash++
				break
			}
		}
		if owner.Kind == "project" && t.Project != nil && *t.Project != owner.ID {
			out.Moved++
		}
	}
	return out
}

// otherRules are the rules of the same kind as owner, without the owner's own.
func otherRules(data *storage.TeamData, owner RuleOwner) []*rules.Rule {
	var list []*rules.Rule
	switch owner.Kind {
	case "product":
		for _, p := range data.Products {
			if p.ID != owner.ID && p.Match != nil {
				list = append(list, p.Match)
			}
		}
	case "project":
		for _, p := range data.Projects {
			if p.ID != owner.ID && !p.Closed() && p.Match != nil {
				list = append(list, p.Match)
			}
		}
	}
	return list
}
