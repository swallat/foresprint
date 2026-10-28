package cli

import (
	"math"
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/report"
)

func init() { Register(analysisCommand) }

func analysisCommand(env *Env) *cobra.Command {
	var remaining, sharePercent float64
	var total bool
	cmd := &cobra.Command{
		Use:   "analysis TEAM",
		Short: i18n.T("Supplementary analyses: spread, focus factor, buffer, completion (--remaining)."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			for _, v := range []float64{remaining, sharePercent} {
				if math.IsNaN(v) || math.IsInf(v, 0) {
					return Failf("Please enter a finite number.")
				}
			}
			if sharePercent < 1 || sharePercent > 100 {
				return Failf("Project share in %: which part of the plannable share or total capacity " +
					"goes into the remaining amount (default 100).")
			}
			data, err := env.LoadTeam(args[0])
			if err != nil {
				return err
			}
			fc, err := forecast.Build(data, env.TodayFor(data))
			if err != nil {
				return asFail(err)
			}
			printBand(env, fc)
			printFocus(env, fc)
			printBuffer(env, fc)
			if cmd.Flags().Changed("remaining") {
				return printCompletion(env, fc, remaining, total, sharePercent)
			}
			return nil
		},
	}
	cmd.Flags().Float64Var(&remaining, "remaining", 0, i18n.T("Remaining amount for which the completion sprint is estimated."))
	cmd.Flags().BoolVar(&total, "total", false, i18n.T("Use the entire forecast for --remaining instead of only the plannable share."))
	cmd.Flags().Float64Var(&sharePercent, "share", 100, i18n.T("Project share in %: which part of the plannable share or total capacity "+
		"goes into the remaining amount (default 100)."))
	teamArg(env, cmd)
	return cmd
}

func printBand(env *Env, fc *forecast.Forecast) {
	team := &fc.Data.Team
	unit := string(team.Unit)
	t := &Table{
		Title:  i18n.P("Range {team} – in addition to the Forecast PLAN", "team", team.Name),
		Header: []string{"Sprint", "Forecast PLAN " + unit, i18n.T("conservative"), i18n.T("medium"), i18n.T("optimistic")},
		Right:  []bool{false, true, true, true, true},
	}
	for _, e := range fc.Upcoming() {
		row := []string{e.Sprint.ID, report.Fmt(e.Result.Plan, report.PlanDigits(fc), ""), "–", "–", "–"}
		if b, ok := analysis.BandOf(fc, e); ok {
			row[2], row[3], row[4] = report.Fmt(&b.Low, report.PlanDigits(fc), ""), report.Fmt(&b.Mid, report.PlanDigits(fc), ""), report.Fmt(&b.High, report.PlanDigits(fc), "")
		}
		t.Add(row...)
	}
	t.Render(env.Out)
	env.Println(i18n.P("conservative/median/optimistic = lowest/median/highest normalized velocity of "+
		"the last {window} sprints × capacity.", "window", team.Forecast.Window))
}

func printFocus(env *Env, fc *forecast.Forecast) {
	t := &Table{
		Title:  i18n.T("Focus factor (velocity / capacity)"),
		Header: []string{"Sprint", i18n.T("Focus factor")},
		Right:  []bool{false, true},
	}
	for _, e := range fc.HistoryLast(fc.Data.Team.Forecast.Window) {
		t.Add(e.Sprint.ID, report.Fmt(analysis.FocusFactor(e), 2, ""))
	}
	t.Add("Ø", report.Fmt(analysis.AverageFocusFactor(fc), 2, ""))
	t.Render(env.Out)
}

func printBuffer(env *Env, fc *forecast.Forecast) {
	hint := analysis.Buffer(fc)
	if hint.AverageScopeCreep == nil {
		env.Println(i18n.P("Buffer: scope creep was not recorded recently – no recommendation."))
		return
	}
	verdict := i18n.T("too few values for a recommendation")
	switch {
	case hint.BufferTooSmall():
		verdict = i18n.T("buffer smaller than the unplanned share")
	case hint.SufficientData():
		verdict = i18n.T("fine")
	}
	small := hint.ConfiguredSmallStuff
	env.Println(i18n.P("Buffer: Ø scope creep {scope} of the commitment = {late} of the Forecast "+
		"PLAN ({count} sprints), small-items share {small} – ",
		"scope", report.Pct(hint.AverageScopeCreep), "late", report.Pct(hint.AverageLateShare),
		"count", hint.Samples, "small", report.Pct(&small)) + verdict)
}

func printCompletion(env *Env, fc *forecast.Forecast, remaining float64, total bool, sharePercent float64) error {
	team := &fc.Data.Team
	basisShare := team.Forecast.RoadmapShare
	if total {
		basisShare = 1
	}
	share := basisShare * sharePercent / 100
	result, err := analysis.Simulate(fc.Data, env.TodayFor(fc.Data), remaining, share, analysis.DefaultMaxSprints, 10_000, 1)
	if err != nil {
		return asFail(err)
	}
	if result == nil {
		return Failf("Not enough history for a completion forecast.")
	}
	basis := i18n.T("entire forecast")
	if !total {
		basis = i18n.P("plannable share {share}", "share", report.Pct(&basisShare))
	}
	if sharePercent < 100 {
		hundred := sharePercent
		basis += i18n.P(" × project share {project} % = {share} of the forecast",
			"project", report.Fmt(&hundred, 0, ""), "share", report.Pct(&share))
	}
	last := "–"
	if n := len(result.Sprints); n > 0 {
		last = result.Sprints[n-1]
	}
	later := i18n.P("later than {last} ({count} sprints)", "last", last, "count", len(result.Sprints))
	pick := func(p *string) string {
		if p != nil && *p != "" {
			return *p
		}
		return later
	}
	env.Println(i18n.P("Completion of {rest} {unit} ({basis}, from the next sprint): in 50 % of "+
		"the simulations by {p50}, in 85 % by {p85} "+
		"(model-dependent frequency, sample of {samples} sprints; ≈ {per_sprint} "+
		"{unit} per sprint).",
		"rest", report.Fmt(&remaining, report.PlanDigits(fc), ""), "unit", string(team.Unit), "basis", basis,
		"p50", pick(result.P50), "p85", pick(result.P85), "samples", result.Samples,
		"per_sprint", report.Fmt(&result.PerSprint, report.PlanDigits(fc), "")))
	if n := len(result.TrendCapacitySprints); n > 0 {
		listed := strings.Join(result.TrendCapacitySprints[:min(n, 4)], ", ")
		if n > 4 {
			listed += " …"
		}
		env.Println(i18n.P("Calculated with Ø capacity because there is no people list: {sprints}", "sprints", listed))
	}
	if note := report.CompletionNote(result.Samples); note != "" {
		hint := report.WindowHint(team.Forecast.Window, result.Samples, analysis.AvailableCount(fc), true)
		env.Println("⚠ " + strings.TrimSpace(note+" "+hint))
	}
	return nil
}
