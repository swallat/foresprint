package cli

import (
	"slices"
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() { Register(sprintNamingCommand) }

func sprintNamingCommand(env *Env) *cobra.Command {
	var pattern, from string
	var clear, doCommit bool
	cmd := &cobra.Command{
		Use:   "sprint-naming TEAM",
		Short: i18n.T("Show or set the sprint naming pattern (placeholders {JJJJ} {JJ} {NN} {N} {LFD} {Q} {MM} {KW})."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			key := args[0]
			data, err := env.LoadTeam(key)
			if err != nil {
				return err
			}
			if pattern == "" && !clear {
				namingTable(data).Render(env.Out)
				return nil
			}
			if from != "" && data.SprintByID(from) == nil {
				return Failf("Sprint not found: {id}", "id", from)
			}
			team := data.Team
			team.Sprint.Naming = slices.Clone(team.Sprint.Naming)
			rules := team.Sprint.Naming
			at := func(r model.NamingRule) bool { return str(r.From) == from }
			switch {
			case clear:
				team.Sprint.Naming = slices.DeleteFunc(rules, at)
			default:
				if bad := model.NamingProblem(pattern); bad != "" {
					return Failf("Unknown placeholder {placeholder} (allowed: {allowed}).",
						"placeholder", bad, "allowed", "{"+strings.Join(model.NamingPlaceholders, "} {")+"}")
				}
				rule := model.NamingRule{Pattern: pattern}
				if from != "" {
					rule.From = &from
				}
				if i := slices.IndexFunc(rules, at); i >= 0 {
					team.Sprint.Naming[i] = rule
				} else {
					team.Sprint.Naming = append(rules, rule)
				}
			}
			after := *data
			after.Team = team
			if env.reportNewErrors(data, &after, "team.yaml") {
				return errExit1
			}
			namingTable(&after).Render(env.Out)
			path, err := env.Repo().SaveTeam(team)
			if err != nil {
				return asFail(err)
			}
			env.saved(path)
			return env.maybeCommit(key, []string{path}, i18n.T("{team}: sprint naming updated", "team", team.Name), "", doCommit)
		},
	}
	teamArg(env, cmd)
	commitFlag(cmd, &doCommit)
	cmd.Flags().StringVar(&pattern, "pattern", "", i18n.T("Naming pattern, e.g. \"{JJJJ}-{NN}\" (from the first sprint, or from --from)."))
	cmd.Flags().StringVar(&from, "from", "", i18n.T("Sprint ID from which the pattern applies."))
	cmd.Flags().BoolVar(&clear, "clear", false, i18n.T("Remove the pattern (of --from): the sprints are named by their ID again."))
	return cmd
}

// namingTable shows the patterns and the names that the sprints get; names that occur twice are
// marked.
func namingTable(data *storage.TeamData) *Table {
	t := &Table{Title: i18n.P("Sprint naming"), Header: []string{i18n.T("Sprint"), i18n.T("Name"), i18n.T("Pattern from here")}}
	names := map[string]int{}
	shown := make([]string, len(data.Sprints))
	for i, s := range data.Sprints {
		shown[i] = model.SprintDisplayName(&data.Team, data.Sprints, s.ID)
		names[shown[i]]++
	}
	patterns := map[string]string{}
	for _, r := range data.Team.Sprint.Naming {
		patterns[str(r.From)] = r.Pattern
	}
	for i, s := range data.Sprints {
		note := patterns[s.ID]
		if i == 0 && note == "" {
			note = patterns[""]
		}
		name := textfmt.BlankControls(shown[i])
		if names[shown[i]] > 1 {
			name += " " + i18n.P("(twice)")
		}
		t.Add(s.ID, name, note)
	}
	if len(data.Team.Sprint.Naming) == 0 {
		t.Caption = i18n.P("No naming pattern: the sprints are named by their ID.")
	}
	return t
}

// str dereferences an optional text; nil is "".
func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
