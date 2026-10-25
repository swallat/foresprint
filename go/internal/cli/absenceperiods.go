package cli

import (
	"slices"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
)

// periodOptions are the flags of absences that work on absence periods (abwesenheiten.yaml,
// decision 23): only dates are stored, never a reason.
type periodOptions struct {
	list, remove, confirm bool
	person, from, to      string
}

func (o *periodOptions) flags(cmd *cobra.Command) {
	f := cmd.Flags()
	f.BoolVar(&o.list, "periods", false, i18n.T("List the absence periods and their working days per sprint."))
	f.StringVar(&o.person, "person", "", i18n.T("Person (name or ID) for an absence period."))
	f.StringVar(&o.from, "from", "", i18n.T("First day of the absence period, YYYY-MM-DD."))
	f.StringVar(&o.to, "to", "", i18n.T("Last day of the absence period, YYYY-MM-DD (default: the first day)."))
	f.BoolVar(&o.confirm, "confirmed", false, i18n.T("Mark the period as confirmed (closed lock), otherwise it is announced."))
	f.BoolVar(&o.remove, "remove", false, i18n.T("Remove the period that starts on --from."))
}

func (o *periodOptions) used() bool {
	return o.list || o.person != "" || o.from != "" || o.to != "" || o.confirm || o.remove
}

func parseDay(flag, raw string) (time.Time, error) {
	d, err := time.Parse("2006-01-02", strings.TrimSpace(raw))
	if err != nil {
		return d, Failf("{option} needs a date as YYYY-MM-DD.", "option", flag)
	}
	return d, nil
}

func runAbsencePeriods(env *Env, key string, data *storage.TeamData, o periodOptions, doCommit bool) error {
	if o.person == "" && o.from == "" && o.to == "" && !o.confirm && !o.remove {
		periodsTable(data).Render(env.Out)
		return nil
	}
	if o.person == "" || o.from == "" {
		return Failf("An absence period needs --person and --from.")
	}
	person, err := findPerson(data.People, o.person)
	if err != nil {
		return err
	}
	from, err := parseDay("--from", o.from)
	if err != nil {
		return err
	}
	to := from
	if o.to != "" {
		if to, err = parseDay("--to", o.to); err != nil {
			return err
		}
	}
	if to.Before(from) {
		return Failf("The last day must not be before the first day.")
	}
	list := slices.Clone(mustGet(data.AbsencePeriods, person.ID))
	if o.remove {
		i := slices.IndexFunc(list, func(p model.AbsencePeriod) bool { return p.From.Equal(from) })
		if i < 0 {
			return Failf("{person} has no absence period starting on {day}.", "person", person.Name, "day", day(from))
		}
		list = slices.Delete(list, i, i+1)
	} else {
		list = addPeriod(list, model.AbsencePeriod{From: from, To: to, Confirmed: o.confirm})
	}
	after := *data
	after.AbsencePeriods = model.Absences{Entries: slices.Clone(data.AbsencePeriods.Entries)}
	if len(list) == 0 {
		after.AbsencePeriods.Entries = slices.DeleteFunc(after.AbsencePeriods.Entries, func(e model.Entry[[]model.AbsencePeriod]) bool { return e.Key == person.ID })
	} else {
		after.AbsencePeriods.Set(person.ID, list)
	}
	if err := env.refuseInvalid(data, &after, "abwesenheiten.yaml"); err != nil {
		return err
	}
	if !o.remove {
		showPeriodDays(env, data, person, from, to)
	}
	path, err := env.Repo().SaveAbsences(key, after.AbsencePeriods)
	if err != nil {
		return asFail(err)
	}
	env.saved(path)
	return env.maybeCommit(key, []string{path}, i18n.T("{team}: absence periods updated", "team", data.Team.Name), "", doCommit)
}

func mustGet(a model.Absences, id string) []model.AbsencePeriod {
	list, _ := a.Get(id)
	return list
}

// addPeriod inserts p and joins it with the periods it overlaps or touches.
func addPeriod(list []model.AbsencePeriod, p model.AbsencePeriod) []model.AbsencePeriod {
	var out []model.AbsencePeriod
	for _, q := range list {
		if q.From.After(p.To.AddDate(0, 0, 1)) || p.From.After(q.To.AddDate(0, 0, 1)) {
			out = append(out, q)
			continue
		}
		if q.From.Before(p.From) {
			p.From = q.From
		}
		if q.To.After(p.To) {
			p.To = q.To
		}
		p.Confirmed = p.Confirmed && q.Confirmed
	}
	out = append(out, p)
	slices.SortFunc(out, func(a, b model.AbsencePeriod) int { return a.From.Compare(b.From) })
	return out
}

func findPerson(people []model.Person, ref string) (model.Person, error) {
	ref = strings.ToLower(strings.TrimSpace(ref))
	var found []model.Person
	for _, p := range people {
		if strings.ToLower(p.ID) == ref || strings.ToLower(p.Name) == ref {
			found = append(found, p)
		}
	}
	switch len(found) {
	case 1:
		return found[0], nil
	case 0:
		return model.Person{}, Failf("Person not found: {name}", "name", ref)
	}
	return model.Person{}, Failf("The name {name} is not unique – use the ID.", "name", ref)
}

// showPeriodDays prints the working days a period takes from each sprint it overlaps.
func showPeriodDays(env *Env, data *storage.TeamData, p model.Person, from, to time.Time) {
	days := capacity.PeriodDays(&data.Team, p, from, to, data.Sprints)
	if len(days) == 0 {
		env.Println(i18n.P("The period has no working day in a known sprint."))
		return
	}
	t := &Table{Title: i18n.P("Working days of {name} in the period", "name", textfmt.BlankControls(p.Name)),
		Header: []string{i18n.T("Sprint"), i18n.T("Working days")}}
	for _, s := range data.Sprints {
		if n, ok := days[s.ID]; ok {
			t.Add(s.ID, plainNumber(n))
		}
	}
	t.Render(env.Out)
}

func periodsTable(data *storage.TeamData) *Table {
	t := &Table{Title: i18n.P("Absence periods"),
		Header: []string{i18n.T("Name"), i18n.T("From"), i18n.T("To"), i18n.T("State")}}
	for _, e := range data.AbsencePeriods.Entries {
		name := e.Key
		for _, p := range data.People {
			if p.ID == e.Key {
				name = p.Name
			}
		}
		for _, a := range e.Value {
			state := i18n.P("announced")
			if a.Confirmed {
				state = i18n.P("confirmed")
			}
			t.Add(textfmt.BlankControls(name), day(a.From), day(a.To), state)
		}
	}
	if len(t.Rows) == 0 {
		t.Caption = i18n.P("No absence periods.")
	}
	return t
}
