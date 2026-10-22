package cli

import (
	"slices"
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func init() { Register(estimationCommand) }

func estimationCommand(env *Env) *cobra.Command {
	var unit, from, remove string
	var factor float64
	var doCommit bool
	cmd := &cobra.Command{
		Use:   "estimation TEAM",
		Short: i18n.T("Show or change the estimation unit (SP or PT) and the conversion factor between them."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			key := args[0]
			data, err := env.LoadTeam(key)
			if err != nil {
				return err
			}
			if from != "" && unit == "" {
				return Failf("--from needs --unit.")
			}
			if unit == "" && remove == "" && !cmd.Flags().Changed("factor") {
				estimationTable(data).Render(env.Out)
				return nil
			}
			if from != "" && data.SprintByID(from) == nil {
				return Failf("Sprint not found: {id}", "id", from)
			}
			if factor < 0 {
				return Failf("The factor must not be negative (0 = use the measured team rate).")
			}
			var u model.Unit
			if unit != "" {
				if u = model.Unit(strings.ToUpper(unit)); u != model.UnitSP && u != model.UnitPT {
					return Failf("--unit must be SP or PT.")
				}
			}
			team := data.Team
			est := team.Estimation
			est.Changes = slices.Clone(est.Changes)
			var f *float64
			if factor > 0 {
				f = &factor
			}
			switch {
			case remove != "":
				n := len(est.Changes)
				est.Changes = slices.DeleteFunc(est.Changes, func(c model.UnitChange) bool { return c.From == remove })
				if len(est.Changes) == n {
					return Failf("No unit change starts at sprint {id}.", "id", remove)
				}
			case from != "" && u != "":
				c := model.UnitChange{From: from, Unit: u, Factor: f}
				if i := slices.IndexFunc(est.Changes, func(x model.UnitChange) bool { return x.From == from }); i >= 0 {
					est.Changes[i] = c
				} else {
					est.Changes = append(est.Changes, c)
				}
				order := map[string]int{}
				for i, s := range data.Sprints {
					order[s.ID] = i
				}
				slices.SortFunc(est.Changes, func(a, b model.UnitChange) int { return order[a.From] - order[b.From] })
			default:
				if u != "" {
					team.Unit = u
				}
				if cmd.Flags().Changed("factor") {
					est.Factor = f
				}
			}
			team.Estimation = est
			after := *data
			after.Team = team
			if env.reportNewErrors(data, &after, "team.yaml") {
				return errExit1
			}
			estimationTable(&after).Render(env.Out)
			path, err := env.Repo().SaveTeam(team)
			if err != nil {
				return asFail(err)
			}
			env.saved(path)
			return env.maybeCommit(key, []string{path}, i18n.T("{team}: estimation unit updated", "team", team.Name), "", doCommit)
		},
	}
	teamArg(env, cmd)
	commitFlag(cmd, &doCommit)
	f := cmd.Flags()
	f.StringVar(&unit, "unit", "", i18n.T("New unit: SP (story points) or PT (person days); with --from from that sprint on."))
	f.StringVar(&from, "from", "", i18n.T("Sprint ID from which the unit (and factor) applies; past sprints keep their unit."))
	f.Float64Var(&factor, "factor", 0, i18n.T("Story points per person day (0 = use the measured team rate)."))
	f.StringVar(&remove, "remove", "", i18n.T("Remove the unit change that starts at this sprint."))
	return cmd
}

// unitAt is the unit valid for the sprint at index i.
func unitAt(team *model.Team, sprints []model.Sprint, i int) model.Unit {
	u := team.Unit
	pos := map[string]int{}
	for j, s := range sprints {
		pos[s.ID] = j
	}
	for _, c := range team.Estimation.Changes {
		if p, ok := pos[c.From]; ok && p <= i {
			u = c.Unit
		}
	}
	return u
}

func estimationTable(data *storage.TeamData) *Table {
	t := &Table{Title: i18n.P("Estimation unit"), Header: []string{i18n.T("Sprint"), i18n.T("Unit")}}
	last := model.Unit("")
	for i, s := range data.Sprints {
		u := unitAt(&data.Team, data.Sprints, i)
		if u != last || i == 0 {
			t.Add(s.ID, string(u))
			last = u
		}
	}
	factor := i18n.P("measured team rate")
	if f := data.Team.Estimation.Factor; f != nil {
		factor = plainNumber(*f) + " " + i18n.P("points per person day")
	}
	t.Caption = i18n.P("Conversion: {factor}. Changes of the unit are listed with the first sprint they apply to.", "factor", factor)
	return t
}
