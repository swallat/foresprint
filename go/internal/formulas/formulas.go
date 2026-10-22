// Package formulas is the calculation path per sprint: formula and plugged-in numbers for every
// computed figure. It mirrors the logic of the engine and the capacity calculation so that
// every number in the interface and the report can be traced. It ports
// src/foresprint/formulas.py; the texts are English source texts that the language's catalog
// translates (string).
package formulas

import (
	"fmt"
	"strings"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/textfmt"
)

// Step is one calculation step.
type Step struct {
	// Key is fixed (e.g. "plan"), independent of the language.
	Key         string `json:"key"`
	Name        string `json:"name"`
	Formula     string `json:"formula"`
	Calculation string `json:"calculation"`
}

// Text is the step for tooltips: formula and calculation on two lines.
func (s Step) Text() string { return s.Formula + "\n\n" + s.Calculation }

// Formatter builds the texts in one language.
type Formatter struct {
	Lang string
}

// New returns a Formatter for the language.
func New(l string) Formatter { return Formatter{Lang: l} }

func (f Formatter) t(text string, v ...any) string { return i18n.TIn(f.Lang, text, v...) }

// n is _n of Python: a number with two decimal places (a missing value is a dash).
func (f Formatter) n(v float64) string { return textfmt.Fmt(f.Lang, v, 2, "") }

func (f Formatter) nd(v float64, digits int) string { return textfmt.Fmt(f.Lang, v, digits, "") }

func (f Formatter) np(v *float64) string { return textfmt.FmtPtr(f.Lang, v, 2) }

// g is short, with the decimal separator of the language: 0.5 → "0,5" (German), 3.0 → "3".
func (f Formatter) g(v float64) string {
	text := pymath.General(v)
	if f.Lang == i18n.Default {
		return text
	}
	return strings.ReplaceAll(text, ".", ",")
}

// exact is up to four decimal places without superfluous zeros: 30,4375 · 30 instead of 30,0.
//
// For equations: they must show the number actually used in the calculation, otherwise the
// recalculation does not add up (the capacity is used unrounded and only rounded for display;
// the trend is likewise used unrounded). Zeros are only removed after the decimal separator:
// 100 stays 100.
func (f Formatter) exact(v *float64) string {
	text := textfmt.FmtPtr(f.Lang, v, 4)
	decimal := ","
	if f.Lang == i18n.Default {
		decimal = "."
	}
	if strings.Contains(text, decimal) {
		text = strings.TrimSuffix(strings.TrimRight(text, "0"), decimal)
	}
	if text == "-0" {
		return "0"
	}
	return text
}

// general formulas, e.g. for column headers.
var generalFormulas = map[string]string{
	"capacity": "Capacity = Σ people (working days − holidays − absences) × FTE − Scrum " +
		"events deduction; frozen after the review; unknown absences estimated " +
		"from the history (without history, no deduction); trend only without a " +
		"people list",
	"normalized_velocity": "norm. velocity = velocity / capacity × reference capacity",
	"average":             "Ø norm. velocity = mean(norm. velocity of the last sprints in the window)",
	"trend":               "norm. velocity trend = extrapolation(Ø norm. velocity) according to trend mode",
	"plan":                "Forecast PLAN = rounded down(norm. velocity trend / reference capacity × capacity)",
	"roadmap":             "Plannable = Forecast PLAN × plannable share",
	"small_stuff":         "Small stuff = Forecast PLAN − plannable",
	"fulfillment":         "Fulfillment = velocity / commitment",
	"scope_creep":         "Scope creep = added later / commitment",
	"focus_factor":        "Focus factor = velocity / capacity",
	"delta":               "Planning delta = Forecast PLAN − (carry-over + backlog − corrections)",
	"standard": "Standard = available × share of the product (without fixed share: rest / " +
		"number of these products)",
	"balance": "Balance = Σ done − Σ standard",
}

// GeneralKeys are the keys of General in the order of the Python table.
var GeneralKeys = []string{
	"capacity", "normalized_velocity", "average", "trend", "plan", "roadmap", "small_stuff",
	"fulfillment", "scope_creep", "focus_factor", "delta", "standard", "balance",
}

// General is the general formula for a key, e.g. for column headers; empty for an unknown key.
func (f Formatter) General(key string) string { return f.t(generalFormulas[key]) }

// FTEChangeNote is the note on the approximation for an FTE change within the sprint.
func (f Formatter) FTEChangeNote(names []string) string {
	return f.t("≈ Approximation: with an FTE change within the sprint, absences are weighted with "+
		"the mean FTE ({names}).", "names", strings.Join(names, ", "))
}

func indexOf(fc *forecast.Forecast, e *forecast.TimelineEntry) int {
	for i := range fc.Entries {
		if fc.Entries[i].Sprint.ID == e.Sprint.ID {
			return i
		}
	}
	panic("formulas: the entry " + e.Sprint.ID + " is not part of the forecast")
}

func (f Formatter) code(s string, code bool) string {
	if code {
		return textfmt.MdCode(s)
	}
	return s
}

func (f Formatter) sprintID(id string, code bool) string {
	if code {
		return textfmt.MdCode(id)
	}
	return textfmt.SprintText(id)
}

func (f Formatter) fmtCap(v *float64, digits int) string {
	return textfmt.FmtCapacity(f.Lang, v, digits)
}

// CapacityStep is the calculation path of the capacity. code=true sets sprint IDs as code
// (Markdown, e.g. tooltips); note=false omits the note on the uncertain absence rate (the
// command line shows it separately).
func (f Formatter) CapacityStep(fc *forecast.Forecast, e *forecast.TimelineEntry, code, note bool) Step {
	r := e.Result
	team := &fc.Data.Team
	name := f.t("Capacity")
	step := func(formula, calculation string) Step {
		return Step{"capacity", name, formula, calculation}
	}
	same := fmt.Sprintf("= %s PT", f.fmtCap(r.PlanCapacity, e.CapacityDigits))
	if r.PlanCapacitySource == nil {
		return step(f.t("cannot be determined"), "–")
	}
	switch *r.PlanCapacitySource {
	case engine.SourceRecorded:
		return step(f.t("Recorded in the sprint file (frozen at the review)"), same)
	case engine.SourcePeople:
		b := capacity.Sprint(team, fc.Data.People, forecast.EffectiveSprint(fc.Data, e.Sprint), 0)
		parts := make([]string, len(b.People))
		for i, p := range b.People {
			parts[i] = fmt.Sprintf("%s (%d − %d − %s) × %s", f.code(p.Person.Name, code), p.Workdays,
				p.Holidays, f.g(p.AbsenceDays), f.g(pymath.Round(p.MeanFTE, 2)))
		}
		minus := ""
		if b.OverheadDaysPart != 0 {
			minus += fmt.Sprintf(" − %s (%s)", f.n(b.OverheadDaysPart), f.t("Scrum events PT"))
		}
		if b.OverheadSharePart != 0 {
			minus += fmt.Sprintf(" − %s (%s)", f.n(b.OverheadSharePart), textfmt.Pct(f.Lang, team.Capacity.OverheadShare))
		}
		calculation := f.t("{parts} = {gross}{minus} → {capacity} PT (rounded)",
			"parts", strings.Join(parts, " + "),
			"gross", f.n(b.Gross),
			"minus", minus,
			"capacity", f.fmtCap(&b.Capacity, b.Rounding))
		if approx := b.Approximated(); len(approx) > 0 {
			names := make([]string, len(approx))
			for i, p := range approx {
				names[i] = f.code(p.Person.Name, code)
			}
			calculation += " · " + f.FTEChangeNote(names)
		}
		return step(f.General("capacity"), calculation)
	case engine.SourceTrend:
		return step(f.t("No people list → capacity trend (extrapolated like the norm. velocity)"), same)
	case engine.SourceCalendar:
		return step(f.t("Absences unknown and no history yet → capacity from the people list and "+
			"calendar (holidays, sprint length) without deduction for absences"), same)
	case engine.SourceExpected:
		return step(f.t("No absences confirmed → capacity from the people list with the announced "+
			"absences from the PO pre-planning"), same)
	case engine.SourceEstimated:
		history := fc.Absences
		var used []string
		quota := 0.0
		if history != nil {
			used = history.Sprints
			if history.Rate != nil {
				quota = *history.Rate
			}
		}
		ids := make([]string, len(used))
		for i, id := range used {
			ids[i] = f.sprintID(id, code)
		}
		formula := f.t("Absences unknown → capacity from the people list and calendar, reduced by the "+
			"average absences ({share}) of sprints {sprints}",
			"share", textfmt.Pct(f.Lang, quota),
			"sprints", strings.Join(ids, ", "))
		// Short and without sprint IDs (the formula also serves as a tooltip); the list is on the
		// absences page, in the explanation and in the report.
		if note {
			if unsure, ok := textfmt.AbsenceDerivedHint(f.Lang, history); ok {
				formula += ". " + unsure
			}
		}
		return step(formula, same)
	}
	return step(f.t("cannot be determined"), "–")
}

// AverageStep is the calculation path of the rolling average. e must be an entry of fc.
func (f Formatter) AverageStep(fc *forecast.Forecast, e *forecast.TimelineEntry) Step {
	i := indexOf(fc, e)
	window := fc.Data.Team.Forecast.Window
	var present []float64
	for _, x := range fc.Entries[:i+1] {
		if v := x.Result.NormalizedVelocity.Value; v != nil {
			present = append(present, *v)
		}
	}
	if window > 0 && len(present) > window { // sprints without a value do not count
		present = present[len(present)-window:]
	}
	avg := e.Result.NormalizedVelocity.Average
	name := f.t("Ø norm. velocity")
	if avg == nil {
		return Step{"average", name, f.General("average"), f.t("– (sprint without its own value)")}
	}
	nums := make([]string, len(present))
	for k, v := range present {
		nums[k] = f.n(v)
	}
	return Step{"average", name, f.t("Ø norm. velocity = mean of the norm. velocity of the last {window} sprints "+
		"with a value (sprints without a value do not count)", "window", window),
		fmt.Sprintf("(%s) / %d = %s", strings.Join(nums, " + "), len(present), f.np(avg))}
}

// TrendStep is the calculation path of the normalized velocity trend, same as engine.Trend. e
// must be an entry of fc.
func (f Formatter) TrendStep(fc *forecast.Forecast, e *forecast.TimelineEntry) (Step, error) {
	i := indexOf(fc, e)
	mode, err := engine.ParseTrendMode(fc.Data.Team.Forecast.TrendMode)
	if err != nil {
		return Step{}, err
	}
	m := make([]engine.Metric, len(fc.Entries))
	for k, x := range fc.Entries {
		m[k] = x.Result.NormalizedVelocity
	}
	value := m[i].Trend
	name := f.t("norm. velocity trend")
	made := func(formula, calculation string) (Step, error) {
		return Step{"trend", name, formula, calculation}, nil
	}
	if m[i].Average != nil {
		return made(f.t("norm. velocity trend = Ø norm. velocity – past sprint"), "Ø = "+f.np(m[i].Average))
	}
	if value == nil {
		return made(f.General("trend"), f.t("– (not enough history)"))
	}
	avg := func(j int) *float64 {
		if j >= 0 {
			return m[j].Average
		}
		return nil
	}
	tr := func(j int) *float64 {
		if j >= 0 {
			return m[j].Trend
		}
		return nil
	}
	known := func(j int) *float64 {
		if a := avg(j); a != nil {
			return a
		}
		return tr(j)
	}
	if e.Result.TrendFallback {
		return made(f.t("Thin history: {mode} needs a second average, so norm. velocity trend = "+
			"value_prev (flat) applies", "mode", string(mode)), "= "+f.np(known(i-1)))
	}
	if mode == model.TrendFlat {
		return made(f.t("norm. velocity trend = value_prev (flat)"), "= "+f.np(known(i-1)))
	}
	a1, a2 := avg(i-1), avg(i-2)
	if mode == model.TrendClassic && a1 != nil && a2 != nil {
		return made(f.t("norm. velocity trend = Ø_prev + (Ø_prev − Ø_prev2) (classic, 1st future sprint)"),
			fmt.Sprintf("%s + (%s − %s) = %s", f.np(a1), f.np(a1), f.np(a2), f.np(value)))
	}
	if mode == model.TrendClassic && i >= 2 && tr(i-2) == nil {
		return made(f.t("norm. velocity trend = Ø[−2] / Ø[−3] × trend[−1] (classic, 2nd future sprint)"),
			fmt.Sprintf("%s / %s × %s = %s", f.np(avg(i-2)), f.np(avg(i-3)), f.np(tr(i-1)), f.np(value)))
	}
	k1, k2 := known(i-1), known(i-2)
	return made(f.t("norm. velocity trend = value_prev + (value_prev − value_prev2) (linear)"),
		fmt.Sprintf("%s + (%s − %s) = %s", f.np(k1), f.np(k1), f.np(k2), f.np(value)))
}

// basisSprints are the IDs of the sprints before the entry with a normalized velocity, the last
// Window of them.
func basisSprints(fc *forecast.Forecast, i int) []string {
	var basis []string
	for _, x := range fc.Entries[:i] {
		if x.Result.NormalizedVelocity.Value != nil {
			basis = append(basis, x.Sprint.ID)
		}
	}
	if w := fc.Data.Team.Forecast.Window; w > 0 && len(basis) > w {
		basis = basis[len(basis)-w:]
	}
	return basis
}

func (f Formatter) absenceNote(fc *forecast.Forecast, e *forecast.TimelineEntry, note bool) (string, bool) {
	src := e.Result.PlanCapacitySource
	if !note || src == nil || *src != engine.SourceEstimated {
		return "", false
	}
	return textfmt.AbsenceDerivedNote(f.Lang, fc.Absences, true, true, fc.Data.Team.Capacity.AbsenceHistory)
}

func (f Formatter) trendNote(fc *forecast.Forecast, e *forecast.TimelineEntry) (string, bool) {
	if e.Result.TrendFallback {
		return f.t("The history is thin: the last average applies, without extrapolation."), true
	}
	if mode, err := engine.ParseTrendMode(fc.Data.Team.Forecast.TrendMode); err == nil && mode != model.TrendFlat {
		return f.t("Trend mode {mode} extrapolates fluctuations of the last sprints – read "+
			"with caution.", "mode", string(mode)), true
	}
	return "", false
}

func rawPlan(r engine.SprintResult, ref float64) float64 {
	if r.NormalizedVelocity.Trend == nil {
		return 0
	}
	c := 0.0
	if r.PlanCapacity != nil {
		c = *r.PlanCapacity
	}
	return *r.NormalizedVelocity.Trend / ref * c
}

// PlainExplanation is a short plain-language explanation of how a sprint's forecast comes about,
// with the key numbers and sources. Steps provides the detailed formulas. note=false omits the
// note on the uncertain absence rate (the command line shows it once separately, with the
// command instead of the web UI operation).
func (f Formatter) PlainExplanation(fc *forecast.Forecast, e *forecast.TimelineEntry, note bool) string {
	team := &fc.Data.Team
	fs := team.Forecast
	r := e.Result
	unit := string(team.Unit)
	if r.Plan == nil {
		return f.t("No forecast can be calculated for this sprint yet (too little history).")
	}
	if r.PlanSource != nil && *r.PlanSource == engine.PlanActual {
		return f.t("Past sprint: the commitment ({value} {unit}) counts, rounded down to {plan}.",
			"value", f.np(r.Commitment.Value), "unit", unit, "plan", textfmt.Fmt(f.Lang, *r.Plan, fs.Rounding, ""))
	}
	i := indexOf(fc, e)
	basis := basisSprints(fc, i)
	trend := r.NormalizedVelocity.Trend
	source := "–"
	if r.PlanCapacitySource != nil {
		source = f.t(string(*r.PlanCapacitySource))
	}
	parts := []string{
		f.t("The team recently (sprints {sprints}) achieved an average of {trend} {unit}, "+
			"converted to a reference capacity of {ref} PT (normalized velocity).",
			"sprints", strings.Join(basis, ", "), "ref", f.nd(fs.ReferenceCapacity, 0), "trend", f.np(trend), "unit", unit),
		f.t("{capacity} PT are available for {id} ({source}). That gives {trend} / {ref} × "+
			"{exact} = {raw} {unit}, rounded down **{plan} {unit}**.",
			"id", e.Sprint.ID, "capacity", f.fmtCap(r.PlanCapacity, e.CapacityDigits), "exact", f.exact(r.PlanCapacity),
			"source", source, "trend", f.exact(trend), "ref", f.nd(fs.ReferenceCapacity, 0),
			"raw", f.nd(rawPlan(r, fs.ReferenceCapacity), 3), "unit", unit, "plan", textfmt.Fmt(f.Lang, *r.Plan, fs.Rounding, "")),
	}
	if s, ok := f.absenceNote(fc, e, note); ok {
		parts = append(parts, s)
	}
	if s, ok := f.trendNote(fc, e); ok {
		parts = append(parts, s)
	}
	return strings.Join(parts, " ")
}

// Pair is a label and a value.
type Pair struct {
	Label string `json:"label"`
	Value string `json:"value"`
}

// Explanation is PlainExplanation split for display: inputs, calculation, result, notes.
type Explanation struct {
	// Message is only this sentence (past sprint, or no forecast possible yet).
	Message     string   `json:"message"`
	Inputs      []Pair   `json:"inputs"`
	Calculation string   `json:"calculation"`
	ResultLabel string   `json:"result_label"`
	Result      string   `json:"result"`
	Notes       []string `json:"notes"`
}

// StructuredExplanation has the same facts as PlainExplanation, but as a short sequence (inputs
// → calculation → result, notes apart) instead of one paragraph.
func (f Formatter) StructuredExplanation(fc *forecast.Forecast, e *forecast.TimelineEntry, note bool) Explanation {
	team := &fc.Data.Team
	fs := team.Forecast
	r := e.Result
	unit := string(team.Unit)
	if r.Plan == nil || (r.PlanSource != nil && *r.PlanSource == engine.PlanActual) {
		return Explanation{Message: f.PlainExplanation(fc, e, note), Inputs: []Pair{}, Notes: []string{}}
	}
	i := indexOf(fc, e)
	basis := basisSprints(fc, i)
	ids := make([]string, len(basis))
	for k, id := range basis {
		ids[k] = textfmt.MdCode(id)
	}
	trend := r.NormalizedVelocity.Trend
	source := "–"
	if r.PlanCapacitySource != nil {
		source = f.t(string(*r.PlanCapacitySource))
	}
	notes := []string{}
	if s, ok := f.absenceNote(fc, e, note); ok {
		notes = append(notes, s)
	}
	if s, ok := f.trendNote(fc, e); ok {
		notes = append(notes, s)
	}
	return Explanation{
		Inputs: []Pair{
			{f.t("Basis sprints"), strings.Join(ids, ", ")},
			{f.t("Normalized velocity (reference capacity {ref} PT)", "ref", f.nd(fs.ReferenceCapacity, 0)),
				f.np(trend) + " " + unit},
			{f.t("Available in {id}", "id", textfmt.MdCode(e.Sprint.ID)),
				fmt.Sprintf("%s PT (%s)", f.fmtCap(r.PlanCapacity, e.CapacityDigits), source)},
		},
		Calculation: fmt.Sprintf("%s / %s × %s = %s %s", f.exact(trend), f.nd(fs.ReferenceCapacity, 0),
			f.exact(r.PlanCapacity), f.nd(rawPlan(r, fs.ReferenceCapacity), 3), unit),
		ResultLabel: f.t("Forecast PLAN (rounded down)"),
		Result:      textfmt.Fmt(f.Lang, *r.Plan, fs.Rounding, "") + " " + unit,
		Notes:       notes,
	}
}

// Steps are all calculation steps of a sprint in reading order (code and note as in
// CapacityStep).
func (f Formatter) Steps(fc *forecast.Forecast, e *forecast.TimelineEntry, code, note bool) ([]Step, error) {
	team := &fc.Data.Team
	fs := team.Forecast
	r := e.Result
	unit := string(team.Unit)
	ref := fs.ReferenceCapacity
	steps := []Step{f.CapacityStep(fc, e, code, note)}
	if r.Velocity.Value != nil {
		steps = append(steps, Step{"normalized_velocity", f.t("norm. velocity"), f.General("normalized_velocity"),
			fmt.Sprintf("%s / %s × %s = %s", f.np(r.Velocity.Value), f.exact(r.Capacity.Value), f.nd(ref, 0),
				f.np(r.NormalizedVelocity.Value))})
	}
	if r.NormalizedVelocity.Average != nil {
		steps = append(steps, f.AverageStep(fc, e))
	}
	trend, err := f.TrendStep(fc, e)
	if err != nil {
		return nil, err
	}
	steps = append(steps, trend)
	if r.PlanSource != nil {
		switch *r.PlanSource {
		case engine.PlanForecast:
			steps = append(steps, Step{"plan", "Forecast PLAN",
				f.t("Forecast PLAN = rounded down to {digits} digit(s): (norm. velocity "+
					"trend / reference capacity × capacity)", "digits", fs.Rounding),
				fmt.Sprintf("%s / %s × %s = %s → %s %s", f.exact(r.NormalizedVelocity.Trend), f.nd(ref, 0),
					f.exact(r.PlanCapacity), f.nd(*r.NormalizedVelocity.Trend/ref**r.PlanCapacity, 3),
					textfmt.Fmt(f.Lang, *r.Plan, fs.Rounding, ""), unit)})
		case engine.PlanActual:
			steps = append(steps, Step{"plan", "Forecast PLAN",
				f.t("Forecast PLAN = rounded down(commitment) – past sprint"),
				fmt.Sprintf("%s → %s %s", f.np(r.Commitment.Value), textfmt.Fmt(f.Lang, *r.Plan, fs.Rounding, ""), unit)})
		}
	}
	if r.Plan != nil {
		plan := textfmt.Fmt(f.Lang, *r.Plan, fs.Rounding, "")
		steps = append(steps,
			Step{"roadmap", f.t("Plannable"), f.General("roadmap"),
				fmt.Sprintf("%s × %s = %s", plan, textfmt.Pct(f.Lang, fs.RoadmapShare), f.np(r.Roadmap))},
			Step{"small_stuff", f.t("Small items"), f.General("small_stuff"),
				fmt.Sprintf("%s − %s = %s", plan, f.np(r.Roadmap), f.np(r.SmallStuff))})
	}
	if r.Fulfillment.Value != nil {
		steps = append(steps, Step{"fulfillment", "Fulfillment", f.General("fulfillment"),
			fmt.Sprintf("%s / %s = %s", f.np(r.Velocity.Value), f.np(r.Commitment.Value),
				textfmt.Pct(f.Lang, *r.Fulfillment.Value))})
	}
	if r.PlanningTotal != nil && e.Sprint.Planning != nil {
		p := e.Sprint.Planning
		corr := "0"
		if len(p.Corrections) > 0 {
			cs := make([]string, len(p.Corrections))
			for k, c := range p.Corrections {
				cs[k] = f.n(c)
			}
			corr = strings.Join(cs, " − ")
		}
		steps = append(steps, Step{"delta", f.t("Planning delta"), f.General("delta"),
			fmt.Sprintf("%s − (%s + %s − %s) = %s", textfmt.Fmt(f.Lang, *r.Plan, fs.Rounding, ""),
				f.n(p.Carryover), f.n(p.Backlog), corr, f.np(r.PlanningDelta))})
	}
	return steps, nil
}

// StepByKey is one calculation step by key (capacity, trend, plan, roadmap, small_stuff ...); ok
// is false if the sprint has no such step.
func (f Formatter) StepByKey(fc *forecast.Forecast, e *forecast.TimelineEntry, key string, code bool) (Step, bool, error) {
	steps, err := f.Steps(fc, e, code, true)
	if err != nil {
		return Step{}, false, err
	}
	for _, s := range steps {
		if s.Key == key {
			return s, true, nil
		}
	}
	return Step{}, false, nil
}
