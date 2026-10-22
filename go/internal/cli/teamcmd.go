package cli

import (
	"fmt"
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/settings"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() {
	Register(initCommand)
	Register(settingsCommand)
}

// askSetting asks for one setting and stores the answer in the team.
func (e *Env) askSetting(s settings.Setting, team *model.Team, required bool) error {
	e.Println(s.Text())
	label := s.Title()
	if opts := s.Choices(); len(opts) > 0 && len(opts) <= 25 {
		parts := make([]string, len(opts))
		for i, o := range opts {
			parts[i] = o.Key + " = " + o.Label
		}
		e.Println(i18n.P("Possible: {options}", "options", strings.Join(parts, ", ")))
	}
	if s.Optional && !required {
		label += " (" + i18n.P("empty = not specified") + ")"
	}
	current := s.Display(team)
	for {
		raw, err := e.Ask(label, current)
		if err != nil {
			return err
		}
		value, err := s.Parse(raw)
		if err != nil {
			e.Println(err.Error())
			continue
		}
		if value == nil && required {
			e.Println(i18n.P("Please enter a value."))
			continue
		}
		s.Set(team, value)
		return nil
	}
}

func existsText(team, existing string) string {
	if existing == team {
		return i18n.P("Team {team} already exists.", "team", fmt.Sprintf("'%s'", team))
	}
	return i18n.P("Team {team} already exists (as {existing}; Windows and macOS do not distinguish "+
		"folders by upper and lower case).", "team", fmt.Sprintf("'%s'", team), "existing", fmt.Sprintf("'%s'", existing))
}

func initCommand(env *Env) *cobra.Command {
	var doCommit bool
	cmd := &cobra.Command{
		Use:   "init TEAM",
		Short: i18n.T("Create a new team with guided input."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return runInit(env, args[0], doCommit)
		},
	}
	commitFlag(cmd, &doCommit)
	return cmd
}

func runInit(env *Env, key string, doCommit bool) error {
	repo := env.Repo()
	if clash, ok := repo.ClashingTeam(key); ok {
		return &Fail{Msg: existsText(key, clash)}
	}
	if problem := storage.TeamKeyProblem(key); problem != "" {
		return &Fail{Msg: problem}
	}
	env.Println(i18n.P("Create new team [bold]{team}[/bold]. All values can be changed later with "+
		"[bold]{command}[/bold].\nThe areas product distribution (several "+
		"products), PO assignment and production access are optional; they are off "+
		"at first (Enter accepts “off”).", "team", key, "command", "foresprint settings "+key))
	team := model.NewTeam(key, strings.ToUpper(key))
	list := settings.Applicable(false)
	byKey := map[string]settings.Setting{}
	for _, s := range list {
		byKey[s.Key] = s
	}
	if err := env.askSetting(byKey["name"], &team, false); err != nil {
		return err
	}
	env.Println(i18n.P("[bold]First sprint:[/bold] the sprint that is running now or starts next. " +
		"Its ID and start are where the count begins; the following sprints follow " +
		"from it. If the team has been working for a while, that is e.g. " +
		"[bold]2026.15[/bold] rather than 2026.1."))
	for _, k := range settings.FirstSprintKeys {
		if err := env.askSetting(byKey[k], &team, true); err != nil {
			return err
		}
	}
	for {
		start := env.Today
		if team.Sprint.FirstStart != nil {
			start = *team.Sprint.FirstStart
		}
		first := ""
		if team.Sprint.FirstID != nil {
			first = *team.Sprint.FirstID
		}
		next := start.AddDate(0, 0, team.Sprint.LengthDays)
		if calendar.IDFitsNumbering(first, next, team.Sprint.Numbering) {
			break
		}
		env.Println(i18n.P("Sprint ID {id} does not match the numbering (expected {expected}).",
			"id", fmt.Sprintf("'%s'", first), "expected", calendar.ExpectedIDForm(i18n.Language(), team.Sprint.Numbering)))
		if err := env.askSetting(byKey["sprint.first_id"], &team, true); err != nil {
			return err
		}
	}
	for _, s := range list {
		if s.Key == "name" || isFirstSprintKey(s.Key) {
			continue
		}
		if err := env.askSetting(s, &team, s.OnlyWithoutSprints); err != nil {
			return err
		}
	}
	path, err := repo.SaveTeam(team)
	if err != nil {
		return asFail(err)
	}
	people, err := repo.SavePeople(key, nil)
	if err != nil {
		return asFail(err)
	}
	env.Println(i18n.P("Created: {path}", "path", path))
	if err := env.maybeCommit(key, []string{path, people}, i18n.T("{team}: team created", "team", team.Name), "", doCommit); err != nil {
		return err
	}
	env.Println(i18n.P("Next: [bold]{command}[/bold]", "command", "foresprint people "+key))
	return nil
}

func isFirstSprintKey(key string) bool {
	for _, k := range settings.FirstSprintKeys {
		if k == key {
			return true
		}
	}
	return false
}

func settingsCommand(env *Env) *cobra.Command {
	var doCommit bool
	cmd := &cobra.Command{
		Use:   "settings TEAM",
		Short: i18n.T("Change team settings with guided input (unit, federal state, reference capacity …)."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return runSettings(env, args[0], doCommit)
		},
	}
	teamArg(env, cmd)
	commitFlag(cmd, &doCommit)
	return cmd
}

func runSettings(env *Env, key string, doCommit bool) error {
	data, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	before := data.Team
	current := data.Team
	env.Println(i18n.P("Settings [bold]{team}[/bold] – Enter keeps the current value.", "team", textfmt.BlankControls(current.Name)))
	for _, s := range settings.Applicable(len(data.Sprints) > 0) {
		if err := env.askSetting(s, &current, false); err != nil {
			return err
		}
	}
	diff := settings.Changes(&before, &current)
	if len(diff) == 0 {
		env.Println(i18n.P("No changes."))
		return nil
	}
	t := &Table{Title: i18n.P("Changes"), Header: []string{i18n.T("Setting"), i18n.T("before"), i18n.T("new")}}
	retro := false
	for _, c := range diff {
		old, nw := c.Old, c.New
		if old == "" {
			old = "–"
		}
		if nw == "" {
			nw = "–"
		}
		t.Add(c.Setting.Title(), textfmt.BlankControls(old), textfmt.BlankControls(nw))
		retro = retro || c.Setting.Retroactive
	}
	t.Render(env.Out)
	if retro {
		env.Println(i18n.P("Note: at least one change applies retroactively to all calculated values " +
			"(Ø, trend, Forecast PLAN)."))
	}
	ok, err := env.Confirm(i18n.P("Save?"), true)
	if err != nil {
		return err
	}
	if !ok {
		return nil
	}
	old := *data
	old.Team = before
	after := *data
	after.Team = current
	if err := env.refuseInvalid(&old, &after, "team.yaml"); err != nil {
		return err
	}
	path, err := env.Repo().SaveTeam(current)
	if err != nil {
		return asFail(err)
	}
	env.saved(path)
	return env.maybeCommit(key, []string{path}, i18n.T("{team}: settings changed", "team", current.Name), "", doCommit)
}
