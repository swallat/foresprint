package cli

import (
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/formulas"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/report"
)

func init() { Register(forecastCommand) }

func forecastCommand(env *Env) *cobra.Command {
	var history int
	var explain string
	cmd := &cobra.Command{
		Use:   "forecast TEAM",
		Short: i18n.T("Show the forecast for the current and the coming sprints."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if history < 0 {
				return Failf("Number of past sprints shown.")
			}
			data, err := env.LoadTeam(args[0])
			if err != nil {
				return err
			}
			fc, err := forecast.Build(data, env.Today)
			if err != nil {
				return asFail(err)
			}
			printForecast(env, fc, args[0], history)
			if cmd.Flags().Changed("explain") {
				return printExplanation(env, fc, explain)
			}
			env.Println(i18n.P("Calculation of a sprint: --explain SPRINT (or - )"))
			return nil
		},
	}
	cmd.Flags().IntVar(&history, "history", 5, i18n.T("Number of past sprints shown."))
	cmd.Flags().StringVar(&explain, "explain", "", i18n.T(
		`Show the calculation (formulas with numbers) of a sprint; "-" = next planning.`))
	teamArg(env, cmd)
	return cmd
}

func printForecast(env *Env, fc *forecast.Forecast, teamKey string, history int) {
	team := &fc.Data.Team
	unit := string(team.Unit)
	t := &Table{
		Title: i18n.P("Sprint forecast {team} (as of {day})", "team", team.Name, "day", fc.Today.Format("02.01.2006")),
		Header: []string{"Sprint", i18n.T("Period"), "Status", i18n.T("Capacity PT"), "Velocity",
			i18n.T("norm. vel. (Ø/trend)"), "Forecast PLAN " + unit, i18n.T("Range"), i18n.T("Plannable"), i18n.T("Small items")},
		Right: []bool{false, false, false, true, true, true, true, true, true, true},
	}
	entries := append(fc.HistoryLast(history), fc.Upcoming()...)
	for _, e := range entries {
		r := e.Result
		future := fc.Phase(e.Sprint) != model.PhasePast
		nVel := r.NormalizedVelocity.Average
		capacity := report.FmtCapacity(r.Capacity.Value, e.CapacityDigits)
		bandRange, roadmap, small := "", "", ""
		if future {
			nVel = r.NormalizedVelocity.Trend
			capacity = report.CapacityLabel(e)
			bandRange = report.BandRange(fc, e)
			roadmap = report.Fmt(r.Roadmap, report.SplitDigits(fc), "")
			small = report.Fmt(r.SmallStuff, report.SplitDigits(fc), "")
		}
		t.Add(e.Sprint.ID, report.Period(e), strings.ReplaceAll(report.Status(fc, e), "**", ""),
			capacity, report.Fmt(r.Velocity.Value, 2, ""), report.Fmt(nVel, 2, ""),
			report.Fmt(r.Plan, report.PlanDigits(fc), ""), bandRange, roadmap, small)
	}
	t.Render(env.Out)
	for _, e := range fc.Upcoming() {
		if src := e.Result.PlanCapacitySource; src != nil && src.Unsure() {
			env.Println(i18n.P("⚠ Trend/calendar = no absences known, capacity estimated. More reliable with: {command}",
				"command", "foresprint absences "+teamKey+" <SPRINT>"))
			break
		}
	}
	for _, note := range report.ReliabilityNotes(fc, false) {
		env.Println("⚠ " + note)
	}
}

func printExplanation(env *Env, fc *forecast.Forecast, id string) error {
	var entry *forecast.TimelineEntry
	if id == "-" {
		var err error
		if entry, err = fc.DefaultEntry(forecast.PurposePlanning); err != nil {
			return asFail(err)
		}
	} else {
		entry = fc.Entry(id)
	}
	if entry == nil {
		return Failf("Sprint {id} is not in the forecast.", "id", id)
	}
	f := formulas.New(i18n.Language())
	env.Println(strings.ReplaceAll(f.PlainExplanation(fc, entry, false), "**", ""))
	steps, err := f.Steps(fc, entry, false, false)
	if err != nil {
		return asFail(err)
	}
	t := &Table{
		Title:  i18n.P("Calculation sprint {id}", "id", entry.Sprint.ID),
		Header: []string{i18n.T("Metric"), i18n.T("Formula"), i18n.T("Calculation")},
	}
	for _, s := range steps {
		t.Add(s.Name, s.Formula, s.Calculation)
	}
	t.Render(env.Out)
	return nil
}
