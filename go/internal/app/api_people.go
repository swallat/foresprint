package app

import (
	"errors"
	"slices"
	"sort"
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/holidays"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

const isoDay = "2006-01-02"

// now is the clock of the Team area; tests set a.Now.
func (a *API) now() time.Time {
	if a.Now != nil {
		return a.Now()
	}
	return now()
}

func (a *API) day() time.Time {
	n := a.now()
	return model.Date(n.Year(), n.Month(), n.Day())
}

func dayText(d *time.Time) string {
	if d == nil {
		return ""
	}
	return d.Format(isoDay)
}

func parseTeamDay(s string) (time.Time, error) {
	t, err := time.Parse(isoDay, s)
	if err != nil {
		return t, errors.New(i18n.T("'{text}' is not a date (YYYY-MM-DD).", "text", s))
	}
	return t, nil
}

func personDTO(p model.Person, used bool) PersonDTO {
	d := PersonDTO{ID: p.ID, Name: p.Name, Kind: string(p.Kind), Production: p.ProductionAccess, Used: used}
	if d.Kind == "" {
		d.Kind = string(model.KindMember)
	}
	if p.Region != nil {
		d.Region = *p.Region
	}
	if p.Country != nil {
		d.Country = *p.Country
	}
	if p.Workweek != nil {
		d.Workweek = *p.Workweek
	}
	d.Memberships = []MembershipDTO{}
	for _, m := range p.Memberships {
		d.Memberships = append(d.Memberships, MembershipDTO{From: m.Start.Format(isoDay), To: dayText(m.End), FTE: m.FTE})
	}
	return d
}

// peopleNewMemberDay is the day a person added now joins the team. While the team is still in its
// first sprint, that is the start of that sprint (even if it lies in the past when the team is
// created), so the capacity of the first sprint counts in full; later it is today.
func (a *API) peopleNewMemberDay(data *storage.TeamData) time.Time {
	today := a.day()
	line, err := forecast.Timeline(data, today)
	if err != nil || len(line) == 0 {
		return today
	}
	first := line[0].Sprint
	if !first.Start.After(today) && today.Before(first.End) {
		return first.Start
	}
	return today
}

// peopleView builds the page from the data of a team.
func (a *API) peopleView(data *storage.TeamData) PeopleView {
	today := a.day()
	view := PeopleView{
		Today:      today.Format(isoDay),
		NewFrom:    a.peopleNewMemberDay(data).Format(isoDay),
		SprintDays: data.Team.Sprint.LengthDays,
		Production: data.Team.Features.Production,
		Country:    data.Team.Capacity.Country,
		People:     []PersonDTO{},
	}
	for _, p := range data.People {
		view.People = append(view.People, personDTO(p, personUsed(data, p, today)))
	}
	return view
}

// peopleSprintIsHistory: the sprint is over or has recorded results; everybody in it stays.
func peopleSprintIsHistory(s model.Sprint, today time.Time) bool {
	return s.End.Before(today) || s.Capacity != nil || s.Velocity != nil
}

// peopleSprintIsPlanned: the sprint was frozen at Planning. Who worked in it before today stays,
// somebody who joined today cannot be part of its commitment.
func peopleSprintIsPlanned(s model.Sprint) bool {
	return s.Commitment != nil || s.Planning != nil || s.ForecastPlan != nil || s.CommittedTickets != nil
}

// personUsed: the person was in the team during a sprint that is over or has recorded results,
// or before today in a planned sprint. Their entries in other open and future sprints do not
// count, they are removed with the person.
func personUsed(data *storage.TeamData, p model.Person, today time.Time) bool {
	for _, s := range data.Sprints {
		switch {
		case peopleSprintIsHistory(s, today):
			// Whoever joined today cannot be part of results recorded before today, even if the
			// sprint was closed early and its end lies ahead.
			end := s.End.AddDate(0, 0, 1)
			if end.After(today) {
				end = today
			}
			if p.ActiveBetween(s.Start, end) {
				return true
			}
		case peopleSprintIsPlanned(s) && s.Start.Before(today):
			if p.ActiveBetween(s.Start, today) {
				return true
			}
		}
	}
	return false
}

// People returns everybody of the team, current and former, with their membership periods.
func (a *API) People(team string) (PeopleView, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return PeopleView{}, err
	}
	return a.peopleView(data), nil
}

// SavePeople replaces the people of the team (people.yaml). A person with an empty id is new and
// gets one from the name. A person who is missing from the list is removed, which only works
// for people without history; everybody else is ended with a leaving day. The answer is the
// page as saved.
func (a *API) SavePeople(team string, people []PersonDTO) (PeopleView, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return PeopleView{}, err
	}
	today := a.day()
	old := map[string]model.Person{}
	taken := map[string]bool{}
	for _, p := range data.People {
		old[p.ID] = p
		taken[p.ID] = true
	}
	var out []model.Person
	seen := map[string]bool{}
	for _, d := range people {
		p, err := personFrom(d, old[d.ID], data.Team.Capacity.Country)
		if err != nil {
			return PeopleView{}, err
		}
		if p.ID == "" {
			p.ID = model.NewPersonID(p.Name, taken, "person")
			taken[p.ID] = true
		}
		if seen[p.ID] {
			return PeopleView{}, errors.New(i18n.T("{name} is listed twice.", "name", p.Name))
		}
		seen[p.ID] = true
		out = append(out, p)
	}
	for _, p := range data.People {
		if !seen[p.ID] && personUsed(data, p, today) {
			return PeopleView{}, errors.New(i18n.T("{name} stands in sprints and cannot be removed. Enter a leaving day instead.", "name", p.Name))
		}
	}
	a.forget(team)
	repo := storage.NewRepository(a.DataDir())
	// Entries of removed people go with them, in every sprint: whoever passed personUsed was not in
	// any sprint with results, so what is left there is a plan or a leftover of an earlier namesake. The sprints are written
	// first and all or nothing, so a failure leaves the people as they were.
	var changedSprints []*model.Sprint
	for _, sp := range data.Sprints {
		s := sp
		changed := false
		for _, p := range data.People {
			if seen[p.ID] {
				continue
			}
			if _, ok := s.Absences[p.ID]; ok {
				s.Absences = peopleWithout(s.Absences, p.ID)
				changed = true
			}
			if _, ok := s.ExpectedAbsences[p.ID]; ok {
				s.ExpectedAbsences = peopleWithout(s.ExpectedAbsences, p.ID)
				changed = true
			}
		}
		if changed {
			changedSprints = append(changedSprints, &s)
		}
	}
	if len(changedSprints) > 0 {
		if _, err := storage.SaveSprintsTogether(repo, team, changedSprints); err != nil {
			return PeopleView{}, err
		}
	}
	if _, err := repo.SavePeople(team, out); err != nil {
		return PeopleView{}, err
	}
	// Absences of people who are gone would make every later save of the absences fail.
	if abs, changed := dropAbsences(data.AbsencePeriods, seen); changed {
		if _, err := repo.SaveAbsences(team, abs); err != nil {
			return PeopleView{}, err
		}
	}
	data.People = out
	return a.peopleView(data), nil
}

// personFrom checks a person of the window and turns it into the model. The fields the window
// does not edit are taken from the stored person if there is one.
func personFrom(d PersonDTO, stored model.Person, teamCountry string) (model.Person, error) {
	p := stored
	p.ID = d.ID
	p.Name = trimSpace(d.Name)
	if p.Name == "" {
		return p, errors.New(i18n.T("Every person needs a name."))
	}
	switch k := model.PersonKind(d.Kind); k {
	case model.KindMember, model.KindGuest, model.KindExternal:
		p.Kind = k
	case "":
		p.Kind = model.KindMember
	default:
		return p, errors.New(i18n.T("Unknown kind '{kind}' for {name}.", "kind", d.Kind, "name", p.Name))
	}
	p.ProductionAccess = d.Production
	if stored.ID == "" { // new person: the window sends the workweek as it is
		p.Workweek = optionalText(d.Workweek)
	}
	// Holidays: the person's own country and region, empty = the team's.
	storedCountry, storedRegion := peopleOptionalValue(stored.Country), peopleOptionalValue(stored.Region)
	if d.Country != "" && d.Country != storedCountry && !knownCountry(d.Country) {
		return p, errors.New(i18n.T("{name}: unknown country {country}.", "name", p.Name, "country", d.Country))
	}
	if d.Region != "" && (d.Region != storedRegion || d.Country != storedCountry) {
		country := d.Country
		if country == "" {
			country = teamCountry
		}
		if !slices.Contains(holidays.Subdivisions(country), d.Region) {
			return p, errors.New(i18n.T("{name}: unknown region {region}.", "name", p.Name, "region", d.Region))
		}
	}
	p.Region, p.Country = optionalText(d.Region), optionalText(d.Country)
	if len(d.Memberships) == 0 {
		return p, errors.New(i18n.T("{name} needs at least one period in the team.", "name", p.Name))
	}
	p.Memberships = nil
	var prevEnd *time.Time
	for i, m := range d.Memberships {
		from, err := parseTeamDay(m.From)
		if err != nil {
			return p, err
		}
		ms := model.Membership{Start: from, FTE: m.FTE}
		if !(m.FTE > 0 && m.FTE <= 1) {
			return p, errors.New(i18n.T("The share of {name} must be between 0.1 and 1.0.", "name", p.Name))
		}
		if m.To != "" {
			to, err := parseTeamDay(m.To)
			if err != nil {
				return p, err
			}
			if to.Before(from) {
				return p, errors.New(i18n.T("The end of a period of {name} lies before its start.", "name", p.Name))
			}
			ms.End = &to
		}
		if i > 0 && (prevEnd == nil || !from.After(*prevEnd)) {
			return p, errors.New(i18n.T("The periods of {name} overlap.", "name", p.Name))
		}
		prevEnd = ms.End
		p.Memberships = append(p.Memberships, ms)
	}
	return p, nil
}

func optionalText(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func trimSpace(s string) string {
	b, e := 0, len(s)
	for b < e && (s[b] == ' ' || s[b] == '\t' || s[b] == '\n') {
		b++
	}
	for e > b && (s[e-1] == ' ' || s[e-1] == '\t' || s[e-1] == '\n') {
		e--
	}
	return s[b:e]
}

// AbsencePeriods lists the planned absences of the team as periods per person.
func (a *API) AbsencePeriods(team string) ([]AbsencePeriodDTO, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return nil, err
	}
	return absenceDTOs(data.AbsencePeriods), nil
}

func absenceDTOs(abs model.Absences) []AbsencePeriodDTO {
	out := []AbsencePeriodDTO{}
	for _, e := range abs.Entries {
		for _, p := range e.Value {
			out = append(out, AbsencePeriodDTO{Person: e.Key, From: p.From.Format(isoDay), To: p.To.Format(isoDay), Confirmed: p.Confirmed})
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].From < out[j].From })
	return out
}

// dropAbsences keeps only the periods of the people in keep.
func dropAbsences(abs model.Absences, keep map[string]bool) (model.Absences, bool) {
	var out model.Absences
	changed := false
	for _, e := range abs.Entries {
		if keep[e.Key] {
			out.Set(e.Key, e.Value)
		} else {
			changed = true
		}
	}
	return out, changed
}

// SaveAbsencePeriods replaces the planned absences of the team (abwesenheiten.yaml). Periods of
// one person must not overlap; the answer is the list as saved.
func (a *API) SaveAbsencePeriods(team string, list []AbsencePeriodDTO) ([]AbsencePeriodDTO, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return nil, err
	}
	known := map[string]bool{}
	for _, p := range data.People {
		known[p.ID] = true
	}
	var abs model.Absences
	for _, d := range list {
		if !known[d.Person] {
			return nil, errors.New(i18n.T("Unknown person '{id}'.", "id", d.Person))
		}
		from, err := parseTeamDay(d.From)
		if err != nil {
			return nil, err
		}
		to, err := parseTeamDay(d.To)
		if err != nil {
			return nil, err
		}
		if to.Before(from) {
			return nil, errors.New(i18n.T("The last day of an absence lies before its first day."))
		}
		periods, _ := abs.Get(d.Person)
		for _, q := range periods {
			if !from.After(q.To) && !to.Before(q.From) {
				return nil, errors.New(i18n.T("Two absences of the same person overlap."))
			}
		}
		abs.Set(d.Person, append(periods, model.AbsencePeriod{From: from, To: to, Confirmed: d.Confirmed}))
	}
	a.forget(team)
	if _, err := storage.NewRepository(a.DataDir()).SaveAbsences(team, abs); err != nil {
		return nil, err
	}
	return absenceDTOs(abs), nil
}

// peopleOptionalValue is the text of an optional field, "" if unset.
func peopleOptionalValue(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// peopleWithout copies the per-person map without one person (the source is shared with the loaded data).
func peopleWithout(m map[string]float64, id string) map[string]float64 {
	out := make(map[string]float64, len(m))
	for k, v := range m {
		if k != id {
			out[k] = v
		}
	}
	return out
}
