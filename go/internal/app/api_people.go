package app

import (
	"errors"
	"sort"
	"time"

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
	return time.Now()
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

// peopleView builds the page from the data of a team.
func (a *API) peopleView(data *storage.TeamData) PeopleView {
	today := a.day()
	view := PeopleView{
		Today:      today.Format(isoDay),
		SprintDays: data.Team.Sprint.LengthDays,
		Production: data.Team.Features.Production,
		People:     []PersonDTO{},
	}
	for _, p := range data.People {
		view.People = append(view.People, personDTO(p, personUsed(data, p, today)))
	}
	return view
}

// personUsed: the person was in the team during a sprint that has begun or has recorded absences.
func personUsed(data *storage.TeamData, p model.Person, today time.Time) bool {
	for _, s := range data.Sprints {
		if s.Start.After(today) {
			continue
		}
		if p.ActiveBetween(s.Start, s.End.AddDate(0, 0, 1)) {
			return true
		}
		if _, ok := s.Absences[p.ID]; ok {
			return true
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
		p, err := personFrom(d, old[d.ID])
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
func personFrom(d PersonDTO, stored model.Person) (model.Person, error) {
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
	if stored.ID == "" { // new person: the window sends the optional fields as they are
		p.Region, p.Country, p.Workweek = optionalText(d.Region), optionalText(d.Country), optionalText(d.Workweek)
	}
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
