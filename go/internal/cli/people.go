package cli

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() { Register(peopleCommand) }

func peopleCommand(env *Env) *cobra.Command {
	var doCommit, former bool
	var newKind, until string
	cmd := &cobra.Command{
		Use:   "people TEAM",
		Short: i18n.T("Show and maintain the list of people (joining, FTE change, leaving)."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			kind, err := parseKind(newKind)
			if err != nil {
				return err
			}
			var end *time.Time
			if until != "" {
				d, err := time.Parse("2006-01-02", until)
				if err != nil {
					return Failf("--until needs a date as YYYY-MM-DD.")
				}
				end = &d
			}
			return runPeople(env, args[0], doCommit, former, newPerson{kind: kind, end: end})
		},
	}
	teamArg(env, cmd)
	commitFlag(cmd, &doCommit)
	cmd.Flags().BoolVar(&former, "former", false, i18n.T("Show people who left."))
	cmd.Flags().StringVar(&newKind, "kind", "", i18n.T("Kind of a new person: member (default), guest or external."))
	cmd.Flags().StringVar(&until, "until", "", i18n.T("Last day of a new person in the team, YYYY-MM-DD (asked for external people)."))
	return cmd
}

// newPerson carries the options for people added in this run.
type newPerson struct {
	kind model.PersonKind
	end  *time.Time
}

func parseKind(s string) (model.PersonKind, error) {
	switch k := model.PersonKind(strings.ToLower(strings.TrimSpace(s))); k {
	case "", model.KindMember:
		return model.KindMember, nil
	case model.KindGuest, model.KindExternal:
		return k, nil
	}
	return "", Failf("--kind must be member, guest or external.")
}

func day(d time.Time) string { return d.Format("02.01.2006") }

func peopleTable(people []model.Person, today time.Time, showFormer bool) *Table {
	t := &Table{
		Title:  i18n.P("People (as of {day})", "day", day(today)),
		Header: []string{i18n.T("Name"), i18n.T("State"), i18n.T("FTE today"), i18n.T("Periods in the team")},
	}
	withKind := false
	for _, p := range people {
		if p.Kind != "" && p.Kind != model.KindMember {
			withKind = true
		}
	}
	if withKind {
		t.Header = append(t.Header, i18n.T("Kind"))
	}
	hidden := 0
	for _, p := range people {
		if !showFormer && !p.IsCurrent(today) {
			hidden++
			continue
		}
		var spans, shares []string
		for _, m := range p.Memberships {
			if m.End != nil {
				spans = append(spans, day(m.Start)+"–"+day(*m.End))
			} else {
				spans = append(spans, i18n.P("from {day}", "day", day(m.Start)))
			}
			shares = append(shares, plainNumber(m.FTE))
		}
		text := strings.Join(spans, ", ")
		if len(p.Memberships) > 0 {
			text += " (" + strings.Join(shares, "/") + ")"
		}
		region, fte := "–", "–"
		if p.Region != nil && *p.Region != "" {
			region = textfmt.BlankControls(*p.Region)
		}
		if v := p.FTEOn(today); v != 0 {
			fte = plainNumber(v)
		}
		row := []string{textfmt.BlankControls(p.Name), region, fte, text}
		if withKind {
			row = append(row, kindLabel(p.Kind))
		}
		t.Add(row...)
	}
	if hidden > 0 {
		t.Caption = i18n.P("{count} former person(s) hidden – show with --former", "count", hidden)
	}
	return t
}

// choosePerson selects a person by name; identical names are told apart by the internal ID.
func (e *Env) choosePerson(people []model.Person) (int, error) {
	counts := map[string]int{}
	for _, p := range people {
		counts[p.Name]++
	}
	labels := make([]string, len(people))
	for i, p := range people {
		labels[i] = p.Name
		if counts[p.Name] > 1 {
			labels[i] = fmt.Sprintf("%s (%s)", p.Name, p.ID)
		}
	}
	e.Println(i18n.P("People") + ": " + textfmt.BlankControls(strings.Join(labels, ", ")))
	for {
		raw, err := e.Ask(i18n.P("Name"), "")
		if err != nil {
			return 0, err
		}
		raw = strings.ToLower(strings.TrimSpace(raw))
		var matches []int
		for i, l := range labels {
			if strings.ToLower(l) == raw {
				return i, nil
			}
			if raw != "" && strings.HasPrefix(strings.ToLower(l), raw) {
				matches = append(matches, i)
			}
		}
		if len(matches) == 1 {
			return matches[0], nil
		}
		e.Println(i18n.P("Name not found unambiguously – please enter it as shown above."))
	}
}

func runPeople(env *Env, key string, doCommit, former bool, opts newPerson) error {
	data, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	before := cloneData(data)
	people := data.People
	changed := false
	for {
		peopleTable(people, env.TodayFor(data), former).Render(env.Out)
		action, err := env.AskChoice(i18n.P("Action: n = new person, f = change FTE, a = leaves the team, q = done"),
			[]string{"n", "f", "a", "q"}, "q")
		if err != nil {
			return err
		}
		if action == "q" {
			break
		}
		if action == "n" {
			person, ok, err := askNewPerson(env, data, people, opts)
			if err != nil {
				return err
			}
			if !ok {
				continue
			}
			people = append(people, person)
			data.People = people
		} else {
			ok, err := changeMembership(env, people, action)
			if err != nil {
				return err
			}
			if !ok {
				continue
			}
		}
		changed = true
	}
	if !changed {
		return nil
	}
	after := *data
	after.People = people
	if err := env.refuseInvalid(before, &after, "people.yaml"); err != nil {
		return err
	}
	path, err := env.Repo().SavePeople(key, people)
	if err != nil {
		return asFail(err)
	}
	env.saved(path)
	return env.maybeCommit(key, []string{path}, i18n.T("{team}: people list updated", "team", data.Team.Name), "", doCommit)
}

// askNewPerson asks for a new person; ok is false if the input was refused (the loop goes on).
func askNewPerson(env *Env, data *storage.TeamData, people []model.Person, opts newPerson) (model.Person, bool, error) {
	name, err := env.Ask(i18n.P("Name"), "")
	if err != nil {
		return model.Person{}, false, err
	}
	name = strings.TrimSpace(name)
	if name == "" {
		env.Println(i18n.P("Please enter a name."))
		return model.Person{}, false, nil
	}
	ids := map[string]bool{}
	for _, p := range people {
		if strings.EqualFold(p.Name, name) {
			env.Println(i18n.P(`This person already exists – choose "f" to change the FTE.`))
			return model.Person{}, false, nil
		}
		ids[p.ID] = true
	}
	id := model.NewPersonID(name, ids, "person")
	raw, err := env.Ask(i18n.P("German state, if different from the team (empty = team setting)"), "")
	if err != nil {
		return model.Person{}, false, err
	}
	var region *string
	if r := strings.ToUpper(strings.TrimSpace(raw)); r != "" {
		region = &r
	}
	start, err := env.AskDate(i18n.P("In the team from"), &env.Today)
	if err != nil {
		return model.Person{}, false, err
	}
	one := 1.0
	fte, err := env.AskNumber(i18n.P("FTE share in the team (1 = full time, 0.5 = half time)"), &one, false, 0)
	if err != nil {
		return model.Person{}, false, err
	}
	share := *fte
	if share == 0 {
		share = 1
	}
	end := opts.end
	if opts.kind == model.KindExternal && end == nil {
		d, err := env.AskDate(i18n.P("Last day in the team (external people need an end date)"), nil)
		if err != nil {
			return model.Person{}, false, err
		}
		end = &d
	}
	person := model.Person{ID: id, Name: name, Region: region, Memberships: []model.Membership{{Start: start, End: end, FTE: share}}}
	if opts.kind != model.KindMember {
		person.Kind = opts.kind
	}
	tentative := *data
	tentative.People = append(append([]model.Person{}, people...), person)
	if env.reportNewErrors(data, &tentative, "people.yaml") {
		return model.Person{}, false, nil
	}
	return person, true, nil
}

// changeMembership changes the FTE (action "f") or ends the membership (action "a") of a person.
func changeMembership(env *Env, people []model.Person, action string) (bool, error) {
	var candidates []model.Person
	var index []int
	for i, p := range people {
		if p.IsCurrent(env.Today) {
			candidates = append(candidates, p)
			index = append(index, i)
		}
	}
	if len(candidates) == 0 {
		env.Println(i18n.P("No active people."))
		return false, nil
	}
	chosen, err := env.choosePerson(candidates)
	if err != nil {
		return false, err
	}
	person := &people[index[chosen]]
	var active *model.Membership
	for i := range person.Memberships {
		if person.Memberships[i].End == nil {
			active = &person.Memberships[i]
			break
		}
	}
	if active == nil {
		env.Println(i18n.P("No open membership."))
		return false, nil
	}
	label := i18n.P("Last day in the team")
	if action == "f" {
		label = i18n.P("Valid from")
	}
	when, err := env.AskDate(label, &env.Today)
	if err != nil {
		return false, err
	}
	if !when.After(active.Start) {
		env.Println(i18n.P("The date must be after the start of the current membership."))
		return false, nil
	}
	if action == "a" {
		active.End = &when
		return true, nil
	}
	fte, err := env.AskNumber(i18n.P("New FTE share"), &active.FTE, false, 0)
	if err != nil {
		return false, err
	}
	share := *fte
	if share == 0 {
		share = active.FTE
	}
	end := when.AddDate(0, 0, -1)
	active.End = &end
	person.Memberships = append(person.Memberships, model.Membership{Start: when, FTE: share})
	return true, nil
}

// kindLabel names a person kind for the table.
func kindLabel(k model.PersonKind) string {
	switch k {
	case model.KindGuest:
		return i18n.P("guest")
	case model.KindExternal:
		return i18n.P("external")
	}
	return i18n.P("member")
}
