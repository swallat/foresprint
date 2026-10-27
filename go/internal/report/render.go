package report

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/preplan"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() { English = func() bool { return i18n.Language() == "en" } }

func t(text string, values ...any) string { return i18n.T(text, values...) }

// FmtCapacity is a capacity for display, rounded half up (from .5 up) like Rounded and the
// frozen value; digits is the team's capacity.rounding setting.
func FmtCapacity(value *float64, digits int) string {
	if value == nil {
		return "–"
	}
	v := engine.RoundHalfUp(*value, digits)
	return Fmt(&v, digits, "")
}

func num(v float64, digits int) string { return FmtValue(v, digits) }

// PlanDigits is the decimals of the Forecast PLAN and of amounts like its range in tables and on the
// command line: one as always, or the team's rounding if that has more. The two ways of rounding
// below that (whole points, one decimal) keep the one decimal of the reports.
func PlanDigits(fc *forecast.Forecast) int { return max(1, fc.Data.Team.Forecast.Rounding) }

// SplitDigits is the decimals of plannable and small items: two, or the team's rounding if that has more.
func SplitDigits(fc *forecast.Forecast) int { return max(2, fc.Data.Team.Forecast.Rounding) }

// Period is the period of a sprint as "dd.mm. – dd.mm.yyyy".
func Period(e *forecast.TimelineEntry) string {
	return e.Sprint.Start.Format("02.01.") + " – " + e.Sprint.End.Format("02.01.2006")
}

// SourceLabel is the display text of a capacity source ("" without one).
func SourceLabel(source *engine.CapacitySource) string {
	if source == nil {
		return ""
	}
	return t(string(*source))
}

// CapacitySourceNote is the source of the capacity alone (without the number), for metrics whose
// value should not be shortened by an appended text; with the warning prefix for an uncertain
// source (the web UI passes none: no emojis there), empty without a source.
func CapacitySourceNote(e *forecast.TimelineEntry, warning string) string {
	source := e.Result.PlanCapacitySource
	if source != nil && source.Unsure() {
		return warning + SourceLabel(source)
	}
	return SourceLabel(source)
}

// CapacityLabel is the capacity with the source appended, as one text (tables, reports, command
// line).
func CapacityLabel(e *forecast.TimelineEntry) string {
	source := e.Result.PlanCapacitySource
	value := FmtCapacity(e.Result.PlanCapacity, e.CapacityDigits)
	switch {
	case source != nil && source.Unsure():
		return value + " " + CapacitySourceNote(e, "⚠️ ")
	case source != nil:
		return value + " (" + CapacitySourceNote(e, "⚠️ ") + ")"
	}
	return value
}

func bandOf(fc *forecast.Forecast, e *forecast.TimelineEntry) (analysis.Band, bool) {
	if !e.Sprint.End.After(fc.Today) {
		return analysis.Band{}, false
	}
	return analysis.BandOf(fc, e)
}

// BandRange is the range of a future sprint as "low–high" for tables ("–" if it cannot be
// calculated or the sprint is already completed).
func BandRange(fc *forecast.Forecast, e *forecast.TimelineEntry) string {
	b, ok := bandOf(fc, e)
	if !ok {
		return "–"
	}
	return num(b.Low, PlanDigits(fc)) + "–" + num(b.High, PlanDigits(fc))
}

// BandNote is the range with the sample size as a sentence right at a forecast tile; with a hint
// if there is little data. Empty if the range cannot be calculated or the sprint is already
// completed. withoutAssumption: the forecast next to it calculates with an assumption, the range
// does not.
func BandNote(fc *forecast.Forecast, e *forecast.TimelineEntry, withoutAssumption bool) string {
	b, ok := bandOf(fc, e)
	if !ok {
		return ""
	}
	note := t("Range {low}–{high} from the last {samples} sprints",
		"low", num(b.Low, PlanDigits(fc)), "high", num(b.High, PlanDigits(fc)), "samples", b.Samples)
	if withoutAssumption {
		note = note + " (" + t("without the assumption") + ")"
	}
	if analysis.FewSamples(fc) {
		return note + " · " + t("little data, rough hint")
	}
	return note
}

// AbsenceStatusLabel is the state of a sprint's absences in words.
func AbsenceStatusLabel(sprint model.Sprint) string {
	switch sprint.AbsenceStatus() {
	case model.AbsencesConfirmed:
		return t("confirmed")
	case model.AbsencesExpected:
		return t("announced")
	}
	return t("unknown")
}

// AbsenceDerivedRemedy is what to do about an uncertain absence rate (without sprint IDs).
func AbsenceDerivedRemedy(window int) string {
	return textfmt.AbsenceDerivedRemedy(i18n.Language(), window)
}

// AbsenceDerivedCLIRemedy is like AbsenceDerivedRemedy, for the command line: the command
// instead of the web UI steps, without Markdown.
func AbsenceDerivedCLIRemedy(window int, team string) string {
	return t("If someone was absent in one of these sprints, add the absences with: "+
		"foresprint absences {team} <SPRINT>. If nobody was absent, the rate is "+
		"correct. The note stays until the sprints drop out of the window of the last "+
		"{window} sprints (setting absence_history) or absences are entered.",
		"team", team, "window", window)
}

// WindowHint is the addition to "Little data" when the forecast window below MinSamples actually
// caps the sample (available recorded values, samples of them in the calculation): the sample
// can then never reach the threshold. Otherwise empty. simulation: the hint is attached to the
// completion simulation's warning.
func WindowHint(window, samples, available int, simulation bool) string {
	if window >= analysis.MinSamples || available <= samples {
		return ""
	}
	if simulation {
		return t("The forecast window is set to {window} sprints; with a larger window "+
			"(settings) more values go into the range and the simulation.", "window", window)
	}
	return t("The forecast window is set to {window} sprints; with a larger window (settings) "+
		"more values go into the range.", "window", window)
}

// CompletionNote is the warning of the completion simulation for little data ("" = none).
func CompletionNote(samples int) string {
	if samples >= analysis.MinSamples {
		return ""
	}
	return t("Little data: the simulation draws from only {samples} sprints (from {min} on, "+
		"statements are more reliable). The frequencies are rough hints.",
		"samples", samples, "min", analysis.MinSamples)
}

// FewSamplesNote is the warning "Little data" of the forecast (command line, report and web UI):
// the sample of range and simulation is below MinSamples. If the window caps it, the sentence
// names both numbers and explains the window. "" without values or from the threshold on.
func FewSamplesNote(fc *forecast.Forecast) string {
	samples := analysis.SampleCount(fc)
	if samples == 0 || samples >= analysis.MinSamples {
		return ""
	}
	available := analysis.AvailableCount(fc)
	var note string
	if available > samples {
		note = t("Little data: the range draws from only {samples} of the {available} recorded "+
			"sprints with velocity (from {min} on, the range is more reliable). Plan and "+
			"range are rough hints.", "samples", samples, "available", available, "min", analysis.MinSamples)
	} else {
		note = t("Little data: so far only {samples} sprints with velocity (from {min} on, the "+
			"range is more reliable). Plan and range are rough hints.", "samples", samples, "min", analysis.MinSamples)
	}
	if hint := WindowHint(fc.Data.Team.Forecast.Window, samples, available, false); hint != "" {
		return note + " " + hint
	}
	return note
}

// ReliabilityNotes are hints on the reliability of the forecast (command line and report).
// code=false for the command line: sprint IDs without Markdown backticks, plus the command to
// add them later.
func ReliabilityNotes(fc *forecast.Forecast, code bool) []string {
	var notes []string
	estimated := false
	for _, e := range fc.Upcoming() {
		if s := e.Result.PlanCapacitySource; s != nil && *s == engine.SourceEstimated {
			estimated = true
		}
	}
	if estimated {
		if note, ok := textfmt.AbsenceDerivedNote(i18n.Language(), fc.Absences, false, code, 0); ok {
			if !code {
				team := fc.Data.Team
				note += " " + AbsenceDerivedCLIRemedy(team.Capacity.AbsenceHistory, team.Key)
			}
			notes = append(notes, note)
		}
	}
	if note := FewSamplesNote(fc); note != "" {
		notes = append(notes, note)
	}
	mode := fc.Data.Team.Forecast.TrendMode
	for _, e := range fc.Upcoming() {
		if e.Result.TrendFallback {
			notes = append(notes, t("Thin history: the history is not enough for trend mode {mode}, “constant” "+
				"(last average) applies.", "mode", string(mode)))
			break
		}
	}
	if mode != model.TrendFlat {
		notes = append(notes, t("Trend mode {mode}: extrapolates fluctuations and can rise or fall "+
			"(caution with long horizons). “Constant” (flat) is robust – set with "+
			"`foresprint settings`.", "mode", string(mode)))
	}
	return notes
}

// Status is the state of a sprint in words ("running" in bold).
func Status(fc *forecast.Forecast, e *forecast.TimelineEntry) string {
	switch {
	case !e.Sprint.End.After(fc.Today):
		return t("finished")
	case !e.Sprint.Start.After(fc.Today):
		return "**" + t("running") + "**"
	}
	return t("planned")
}

// orValue is Python's "a or b" for optional numbers: 0 and nil are false.
func orValue(a, b *float64) *float64 {
	if a != nil && *a != 0 {
		return a
	}
	return b
}

func series(values []*float64) string {
	parts := make([]string, len(values))
	for i, v := range values {
		if v == nil {
			parts[i] = "0"
		} else {
			parts[i] = strconv.FormatFloat(*v, 'f', 2, 64)
		}
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

// Render is the Markdown report of a forecast (rendered by GitHub/GitLab, including the
// Mermaid chart); history is the number of completed sprints shown.
func Render(fc *forecast.Forecast, history int) (string, error) {
	team := fc.Data.Team
	unit := string(team.Unit)
	f := team.Forecast
	share := f.RoadmapShare
	lines := []string{
		"# Sprint-Forecast " + team.Name,
		"",
		t("As of: {today} · unit: {unit} · reference capacity: {ref} PT · Ø over "+
			"{window} sprints · trend: `{mode}`",
			"today", fc.Today.Format("02.01.2006"), "unit", unit,
			"ref", num(f.ReferenceCapacity, 0), "window", f.Window, "mode", string(f.TrendMode)),
		"",
		t("> Generated automatically with `foresprint report`. Do not edit by hand."),
		"",
		"## " + t("Projection"),
		"",
		"| Sprint | " + t("Period | Status | Capacity (PT) | norm. velocity trend | **Forecast PLAN** "+
			"({unit}) | Range | Plannable ({share}) | Small items |", "unit", unit, "share", Pct(&share)),
		"|---|---|---|---|---|---|---|---|---|",
	}
	upcoming := fc.Upcoming()
	unsure := false
	for _, e := range upcoming {
		r := e.Result
		lines = append(lines, "| "+e.Sprint.ID+" | "+Period(e)+" | "+Status(fc, e)+" | "+CapacityLabel(e)+
			" | "+Fmt(r.NormalizedVelocity.Trend, 2, "")+" | **"+Fmt(r.Plan, PlanDigits(fc), "")+"**"+
			" | "+BandRange(fc, e)+" | "+Fmt(r.Roadmap, SplitDigits(fc), "")+" | "+Fmt(r.SmallStuff, SplitDigits(fc), "")+" |")
		if s := r.PlanCapacitySource; s != nil && s.Unsure() {
			unsure = true
		}
	}
	if unsure {
		lines = append(lines, "", t("⚠️ *Trend/calendar*: no absences are recorded for this sprint yet, the "+
			"capacity is estimated. `foresprint absences {team} <SPRINT>` makes "+
			"the forecast reliable.", "team", team.Key))
	}
	for _, note := range ReliabilityNotes(fc, true) {
		lines = append(lines, "", "⚠️ "+note)
	}

	if current := fc.Current(); current != nil && current.Result.PlanningTotal != nil {
		r := current.Result
		lines = append(lines, "", t("**Planning {id}:** total {total} {unit}, delta to the Forecast PLAN "+
			"{delta} {unit}", "id", current.Sprint.ID, "total", Fmt(r.PlanningTotal, 2, ""),
			"delta", Fmt(r.PlanningDelta, 2, ""), "unit", unit))
	}

	past := fc.HistoryLast(history)
	lines = append(lines, "", t("## History (last {count} sprints)", "count", len(past)), "",
		"| Sprint | "+t("Capacity (PT) | Commitment | Velocity | norm. velocity | Ø norm. velocity | "+
			"Fulfillment | Scope creep |"),
		"|---|---|---|---|---|---|---|---|")
	for _, e := range past {
		r := e.Result
		lines = append(lines, "| "+e.Sprint.ID+" | "+FmtCapacity(r.Capacity.Value, e.CapacityDigits)+
			" | "+Fmt(r.Commitment.Value, 2, "")+
			" | "+Fmt(r.Velocity.Value, 2, "")+" | "+Fmt(r.NormalizedVelocity.Value, 2, "")+
			" | "+Fmt(r.NormalizedVelocity.Average, 2, "")+" | "+Pct(r.Fulfillment.Value)+
			" | "+Pct(r.ScopeCreep.Value)+" |")
	}

	chart := append(append([]*forecast.TimelineEntry{}, past...), upcoming...)
	if len(chart) >= 2 {
		ids := make([]string, len(chart))
		var commit, vel, nvel []*float64
		for i, e := range chart {
			ids[i] = `"` + e.Sprint.ID + `"`
			r := e.Result
			commit = append(commit, orValue(r.Commitment.Value, r.Plan))
			vel = append(vel, orValue(r.Velocity.Value, r.Velocity.Trend))
			nvel = append(nvel, orValue(r.NormalizedVelocity.Value, r.NormalizedVelocity.Trend))
		}
		lines = append(lines, "", "## "+t("Chart"), "",
			t("Lines: commitment (past) or Forecast PLAN (future), velocity and "+
				"normalized velocity (past: actual value, future: trend)."), "",
			"```mermaid", "xychart-beta",
			"    x-axis ["+strings.Join(ids, ", ")+"]",
			`    y-axis "`+unit+`"`,
			"    line "+series(commit), "    line "+series(vel), "    line "+series(nvel), "```")
	}
	lines = append(lines, productsSection(fc, 6)...)
	tickets, err := ticketsSection(fc, 6)
	if err != nil {
		return "", err
	}
	lines = append(lines, tickets...)
	lines = append(lines, analysisSection(fc)...)
	return strings.Join(lines, "\n") + "\n", nil
}

// ticketsSection is the ticket pre-planning: project traffic light and the next sprints (only
// with features.tickets and imported tickets).
func ticketsSection(fc *forecast.Forecast, sprints int) ([]string, error) {
	data := fc.Data
	if !data.Team.Features.Tickets || len(data.Tickets) == 0 {
		return nil, nil
	}
	dist, err := preplan.Distribute(data, fc.Today, 26, preplan.Median)
	if err != nil {
		return nil, err
	}
	lines := []string{"", "## " + t("Tickets")}
	if len(dist.Projects) > 0 {
		lines = append(lines, "",
			"| "+t("Project")+" | "+t("Target")+" | "+t("Target sprint")+" | "+t("Last sprint")+
				" | "+t("Traffic light")+" | "+t("Outstanding")+" | "+t("Not distributable")+" |",
			"|---|---|---|---|---|---|---|")
		for _, status := range dist.Projects {
			name, target := status.Project, "–"
			if p := data.ProjectByID(status.Project); p != nil {
				name = p.Name
				if p.Target != nil {
					target = p.Target.Format("02.01.2006")
				}
			}
			lines = append(lines, "| "+name+" | "+target+" | "+orDash(status.TargetSprint)+
				" | "+orDash(status.LastSprint)+" | "+t(preplan.Lights[status.Light])+
				" | "+strconv.Itoa(status.OpenTickets)+" | "+strconv.Itoa(status.NotDistributable)+" |")
		}
	}
	shown := dist.Sprints
	if len(shown) > sprints {
		shown = shown[:sprints]
	}
	if len(shown) > 0 {
		unit := unitNow(fc)
		lines = append(lines, "",
			"| Sprint | "+t("Budget")+" ("+unit+") | "+t("Used")+" | "+t("Free")+" | "+t("Tickets")+" |",
			"|---|---|---|---|---|")
		for _, id := range shown {
			var bases, useds []float64
			for _, b := range dist.Budgets {
				if b.Sprint == id {
					bases = append(bases, b.Base)
					useds = append(useds, b.Fixed+b.Placed)
				}
			}
			base, used := pymath.Sum(bases), pymath.Sum(useds)
			lines = append(lines, "| "+id+" | "+num(base, PlanDigits(fc))+" | "+num(used, PlanDigits(fc))+" | "+num(base-used, PlanDigits(fc))+
				" | "+strconv.Itoa(len(dist.InSprint(id)))+" |")
		}
	}
	if refine, open := len(dist.Refinement), len(dist.NotDistributable()); refine > 0 || open > 0 {
		lines = append(lines, "", t("{refine} tickets still have to be refined, {open} cannot be distributed.",
			"refine", refine, "open", open))
	}
	return lines, nil
}

func orDash(s *string) string {
	if s == nil || *s == "" {
		return "–"
	}
	return *s
}

// analysisSection holds the supplementary analyses (range, focus factor, buffer) at the end of
// the report.
func analysisSection(fc *forecast.Forecast) []string {
	unit := unitNow(fc)
	type row struct {
		e *forecast.TimelineEntry
		b analysis.Band
	}
	var rows []row
	for _, e := range fc.Upcoming() {
		if b, ok := analysis.BandOf(fc, e); ok {
			rows = append(rows, row{e, b})
		}
	}
	var lines []string
	if len(rows) > 0 {
		lines = append(lines, "", t("## Additionally: range"), "",
			t("Forecast with the lowest, median and highest normalized velocity of the "+
				"last {count} sprints (instead of the trend).", "count", rows[0].b.Samples), "",
			t("| Sprint | Forecast PLAN ({unit}) | conservative | median | optimistic |", "unit", unit),
			"|---|---|---|---|---|")
		for _, r := range rows {
			lines = append(lines, "| "+r.e.Sprint.ID+" | "+Fmt(r.e.Result.Plan, PlanDigits(fc), "")+" | "+num(r.b.Low, PlanDigits(fc))+
				" | "+num(r.b.Mid, PlanDigits(fc))+" | "+num(r.b.High, PlanDigits(fc))+" |")
		}
	}
	var facts []string
	if focus := analysis.AverageFocusFactor(fc); focus != nil {
		facts = append(facts, t("Ø focus factor (velocity / capacity): {value}", "value", Fmt(focus, 2, "")))
	}
	hint := analysis.Buffer(fc)
	if hint.AverageScopeCreep != nil {
		small := hint.ConfiguredSmallStuff
		fact := t("Ø scope creep ({count} sprints): {scope} of the commitment = {late} of "+
			"the Forecast PLAN · small-items share: {small}",
			"count", hint.Samples, "scope", Pct(hint.AverageScopeCreep),
			"late", Pct(hint.AverageLateShare), "small", Pct(&small))
		if hint.BufferTooSmall() {
			fact += t(" ⚠️ buffer smaller than the unplanned share")
		}
		facts = append(facts, fact)
	}
	if len(facts) > 0 {
		lines = append(lines, "")
		for _, f := range facts {
			lines = append(lines, "- "+f)
		}
	}
	return lines
}

// productsSection is the distribution per product: current and next sprint, balance of the last
// sprints.
func productsSection(fc *forecast.Forecast, history int) []string {
	if len(fc.Data.Products) == 0 {
		return nil
	}
	unit := unitNow(fc)
	lines := []string{"", "## " + t("Products")}
	var shown []*forecast.TimelineEntry
	planning, _ := fc.DefaultEntry(forecast.PurposePlanning)
	for _, e := range []*forecast.TimelineEntry{fc.Current(), planning} {
		if e == nil {
			continue
		}
		dup := false
		for _, s := range shown {
			dup = dup || s.Sprint.ID == e.Sprint.ID
		}
		if !dup {
			shown = append(shown, e)
		}
	}
	for _, e := range shown {
		d := products.Distribute(fc, e)
		if len(d.Rows) == 0 {
			continue
		}
		head := make([]string, len(products.Measures))
		for i, m := range products.Measures {
			head[i] = products.MeasureLabel(m.Key) + " (" + unit + ")"
		}
		lines = append(lines, "",
			fmt.Sprintf("**Sprint %s** (%s)", e.Sprint.ID, strings.ReplaceAll(Status(fc, e), "*", "")), "",
			"| "+t("Product")+" | PO | "+strings.Join(head, " | ")+" |",
			"|---|---|"+strings.Repeat("---|", len(products.Measures)))
		for _, r := range d.Rows {
			po := ""
			if r.Product.PO != nil {
				po = *r.Product.PO
			}
			cells := make([]string, len(products.Measures))
			for i, m := range products.Measures {
				cells[i] = Fmt(r.Value(m.Key), 2, "")
			}
			lines = append(lines, "| "+r.Product.Name+" | "+po+" | "+strings.Join(cells, " | ")+" |")
		}
	}
	// only products with at least one value (as in the web UI)
	var rows []products.Balance
	for _, b := range products.BalanceOf(fc, fc.HistoryLast(history)) {
		if b.Sprints > 0 {
			rows = append(rows, b)
		}
	}
	if len(rows) > 0 {
		withMissing := false
		for _, b := range rows {
			withMissing = withMissing || b.Missing > 0
		}
		header := t("| Product | Sprints | Σ standard | Σ done | Balance ({unit}) |", "unit", unit)
		sep := "|---|---|---|---|---|"
		if withMissing {
			header += " " + t("no value") + " |"
			sep += "---|"
		}
		lines = append(lines, "", t("**Balance** (Σ done − Σ standard, last {count} sprints)", "count", history), "", header, sep)
		for _, b := range rows {
			line := "| " + b.Product.Name + " | " + strconv.Itoa(b.Sprints) + " | " + num(b.Standard, 2) +
				" | " + num(b.Done, 2) + " | " + num(b.Difference(), 2) + " |"
			if withMissing {
				line += " " + strconv.Itoa(b.Missing) + " |"
			}
			lines = append(lines, line)
		}
		if withMissing {
			lines = append(lines, "", "*"+products.MissingFootnote()+"*")
		}
	}
	return lines
}

// unitNow is the estimation unit valid today, not the one the team started with.
func unitNow(fc *forecast.Forecast) string {
	u, _ := forecast.UnitAt(fc.Data, fc.Today)
	return string(u)
}
