package ticketimport

import (
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

// SourceSettings is what the ticket sources need of the tracker section of team.yaml.
func SourceSettings(t model.TrackerSettings) sources.Settings {
	str := func(p *string) string {
		if p == nil {
			return ""
		}
		return *p
	}
	s := sources.Settings{
		Kind:     t.Kind,
		BaseURL:  str(t.BaseURL),
		Query:    str(t.Query),
		LinkType: t.LinkType,
		Fields: sources.Fields{
			Estimate:  str(t.Fields.Estimate),
			Remaining: str(t.Fields.Remaining),
			Epic:      str(t.Fields.Epic),
		},
	}
	for _, e := range t.RuleFields.Entries {
		s.RuleFields = append(s.RuleFields, sources.RuleField{Name: e.Key, Display: e.Value})
	}
	s.RuleFields = append(s.RuleFields, MappedRuleFields(t)...)
	return s
}

// ForecastSprints answers the sprint ends of the import from the forecast: recorded sprints, the
// forecast timeline, then the calendar up to forecast.DefaultLookupAhead sprints ahead.
type ForecastSprints struct{ Forecast *forecast.Forecast }

// End implements Sprints.
func (f ForecastSprints) End(id string) (time.Time, bool) {
	s, err := f.Forecast.LookupSprint(id, forecast.DefaultLookupAhead)
	if err != nil || s == nil {
		return time.Time{}, false
	}
	return s.End, true
}

// IDs implements Lister.
func (f ForecastSprints) IDs() []string {
	ids := forecast.KnownSprintIDs(f.Forecast.Data, forecast.DefaultLookupAhead)
	for _, e := range f.Forecast.Entries {
		ids = append(ids, e.Sprint.ID)
	}
	return ids
}

var _ Sprints = ForecastSprints{}
var _ Lister = ForecastSprints{}
