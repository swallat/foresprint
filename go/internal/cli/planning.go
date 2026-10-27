package cli

import (
	"time"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/report"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() {
	Register(planningCommand)
	Register(reviewCommand)
}

// rule prints a heading line.
func (e *Env) rule(title string) {
	e.Println()
	e.Println("── " + title + " ──")
}

// distributionTable is the table of the products of a sprint.
func distributionTable(d *products.Distribution, unit string) *Table {
	l := i18n.Language()
	basis := "Forecast PLAN"
	if d.Basis == model.BasisRoadmap {
		basis = i18n.T("Plannable share")
	}
	t := &Table{Title: i18n.P("Products sprint {id}", "id", d.Sprint.ID)}
	t.Header = []string{i18n.T("Product")}
	t.Right = []bool{false}
	if d.Features.PO {
		t.Header = append(t.Header, "PO")
		t.Right = append(t.Right, false)
	}
	for _, m := range products.Measures {
		t.Header = append(t.Header, products.MeasureLabel(m.Key)+" "+unit)
		t.Right = append(t.Right, true)
	}
	for _, r := range d.Rows {
		name := textfmt.BlankControls(r.Product.Name)
		if !r.Active {
			name += " (" + i18n.P("not handled") + ")"
		}
		row := []string{name}
		if d.Features.PO {
			po := ""
			if r.Product.PO != nil {
				po = textfmt.BlankControls(*r.Product.PO)
			}
			row = append(row, po)
		}
		for _, m := range products.Measures {
			row = append(row, textfmt.FmtPtr(l, r.Value(m.Key), 2))
		}
		t.Add(row...)
	}
	total := []string{i18n.T("Total")}
	if d.Features.PO {
		total = append(total, "")
	}
	for _, m := range products.Measures {
		total = append(total, textfmt.FmtPtr(l, d.Total(m.Key), 2))
	}
	t.Add(total...)
	if d.Available != nil && d.ActiveCount() > 0 {
		frozen := ""
		if d.PlanFrozen {
			frozen = " (" + i18n.P("frozen") + ")"
		}
		t.Caption = i18n.P("Standard = {basis}{frozen} {available} / {count} products",
			"basis", basis, "frozen", frozen, "available", textfmt.FmtPtr(l, d.Available, 2), "count", d.ActiveCount())
	}
	return t
}

// askProductValues asks for a value (preplanned, planned or done) per product.
func (e *Env) askProductValues(data *storage.TeamData, fc *forecast.Forecast, s *model.Sprint, measure string) error {
	entry := fc.Entry(s.ID)
	if len(data.Products) == 0 || entry == nil {
		return nil
	}
	d := products.Distribute(fc, entry)
	if len(d.Rows) == 0 {
		return nil
	}
	unit := cliUnitAt(data, entry.Sprint.Start)
	distributionTable(&d, unit).Render(e.Out)
	e.explain(measure)
	if s.Products == nil {
		s.Products = map[string]model.ProductValues{}
	}
	for _, r := range d.Rows {
		values := s.Products[r.Product.ID]
		var field **float64
		switch measure {
		case "preplanned":
			field = &values.Preplanned
		case "planned":
			field = &values.Planned
		default:
			field = &values.Done
		}
		answer, err := e.AskNumber(textfmt.BlankControls(r.Product.Name)+" – "+products.MeasureLabel(measure)+" ("+unit+")", *field, true, 0)
		if err != nil {
			return err
		}
		*field = answer
		if values.IsEmpty() {
			delete(s.Products, r.Product.ID)
		} else {
			s.Products[r.Product.ID] = values
		}
	}
	return nil
}

func planningCommand(env *Env) *cobra.Command {
	var doCommit bool
	cmd := &cobra.Command{
		Use: "planning TEAM [SPRINT]",
		Short: i18n.T("Guided sprint planning: 1. absences, 2. Forecast PLAN and scheduling per product, " +
			"3. commitment (default: next planning)."),
		Args: cobra.RangeArgs(1, 2),
		RunE: func(cmd *cobra.Command, args []string) error {
			id := ""
			if len(args) > 1 {
				id = args[1]
			}
			return runPlanning(env, args[0], id, doCommit)
		},
	}
	teamArg(env, cmd)
	commitFlag(cmd, &doCommit)
	return cmd
}

func runPlanning(env *Env, key, sprintID string, doCommit bool) error {
	data, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	s, err := findOrCreateSprint(data, env, sprintID, forecast.PurposePlanning)
	if err != nil {
		return err
	}
	before := cloneData(data)
	var paths []string
	env.rule(i18n.P("Planning {id} – step 1: absences", "id", s.ID))
	recorded := data.SprintByID(s.ID) != nil
	asked := false
	if len(data.People) > 0 {
		asked, err = env.Confirm(i18n.P("Record or check the known absences for the sprint?"), !recorded)
		if err != nil {
			return err
		}
	}
	if asked {
		path, err := env.askAbsences(data, s)
		if err != nil {
			return err
		}
		paths = append(paths, path)
		capacityTable(data, s).Render(env.Out)
	} else if !recorded {
		env.Println(i18n.P("Without confirmed absences the capacity is only estimated (calendar and history)."))
	}
	if len(paths) > 0 {
		if data, err = env.LoadTeam(key); err != nil {
			return err
		}
	}
	fc, err := forecast.Build(data, env.Today)
	if err != nil {
		return asFail(err)
	}
	var copied model.Sprint
	if stored := data.SprintByID(s.ID); stored != nil {
		copied = stored.Clone()
	} else {
		copied = s.Clone()
	}
	s = &copied
	env.rule(i18n.P("Planning {id} – step 2: Forecast PLAN and planning", "id", s.ID))
	if data.SprintByID(s.ID) != nil {
		if err := env.showSprintForecast(key, s.ID); err != nil {
			return err
		}
	}
	if data.Team.Features.Products && len(data.Products) > 0 {
		ok, err := env.Confirm(i18n.P("Record planning per product?"), true)
		if err != nil {
			return err
		}
		if ok {
			if err := env.askProductValues(data, fc, s, "planned"); err != nil {
				return err
			}
		}
	}
	env.rule(i18n.P("Planning {id} – step 3: commitment", "id", s.ID))
	unit := cliUnitAt(data, s.Start)
	var planValues *model.Planning
	ok, err := env.Confirm(i18n.P("Record the cross-check (carry-over, backlog, corrections)? Optional – only "+
		"affects the planning delta"), s.Planning != nil)
	if err != nil {
		return err
	}
	if ok {
		p := model.Planning{}
		if s.Planning != nil {
			p = *s.Planning
		}
		env.explain("carryover")
		carry, err := env.AskNumber(i18n.P("Carry-over ({unit})", "unit", unit), &p.Carryover, false, 0)
		if err != nil {
			return err
		}
		env.explain("backlog")
		backlog, err := env.AskNumber("Backlog ("+unit+")", &p.Backlog, false, 0)
		if err != nil {
			return err
		}
		env.explain("corrections")
		corrections, err := env.AskNumbers(i18n.P("Corrections ({unit})", "unit", unit), p.Corrections)
		if err != nil {
			return err
		}
		planValues = &model.Planning{Carryover: *carry, Backlog: *backlog, Corrections: corrections}
	}
	env.explain("forecast_ist")
	def := s.Commitment
	if def == nil && planValues != nil && planValues.Committed() != 0 {
		def = model.Ptr(planValues.Committed())
		env.Println(i18n.P("Prefilled with carry-over + backlog."))
	}
	commitment, err := env.AskNumber(i18n.P("Commitment ({unit})", "unit", unit), def, true, 0)
	if err != nil {
		return err
	}
	forecast.ApplyPlanning(s, commitment, planValues)
	refreeze := false
	if frozen, current, offer := forecast.RefreezeOffer(s, fc.Entry(s.ID)); offer {
		refreeze, err = env.Confirm(i18n.P("The frozen Forecast PLAN ({frozen}) differs from the current one "+
			"({current}). Freeze again?", "frozen", report.Fmt(&frozen, report.PlanDigits(fc), ""), "current", report.Fmt(&current, report.PlanDigits(fc), "")), false)
		if err != nil {
			return err
		}
	}
	forecast.FreezePlan(s, fc.Entry(s.ID), env.Today, refreeze)
	if err := env.refuseInvalid(before, withSprint(data, s), "sprints/"); err != nil {
		return err
	}
	path, err := env.Repo().SaveSprint(key, s)
	if err != nil {
		return asFail(err)
	}
	env.saved(path)
	fresh, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	if fc, err = forecast.Build(fresh, env.Today); err != nil {
		return asFail(err)
	}
	if e := fc.Entry(s.ID); e != nil && e.Result.PlanningTotal != nil {
		delta := 0.0
		if e.Result.PlanningDelta != nil {
			delta = *e.Result.PlanningDelta
		}
		env.Println(i18n.P("Planning total {total} {unit} · Forecast PLAN {plan} {unit} · "+
			"[{colour}]delta {delta} {unit}[/{colour}]",
			"total", report.Fmt(e.Result.PlanningTotal, 2, ""), "plan", report.Fmt(e.Result.Plan, report.PlanDigits(fc), ""),
			"delta", report.Fmt(&delta, 2, ""), "unit", unit, "colour", "green"))
	}
	return env.maybeCommit(key, []string{path}, i18n.T("{team} {id}: planning recorded", "team", data.Team.Name, "id", s.ID), "", doCommit)
}

func reviewCommand(env *Env) *cobra.Command {
	var doCommit bool
	cmd := &cobra.Command{
		Use:   "review TEAM [SPRINT]",
		Short: i18n.T("Record the sprint review: velocity, scope creep; freezes the capacity."),
		Args:  cobra.RangeArgs(1, 2),
		RunE: func(cmd *cobra.Command, args []string) error {
			id := ""
			if len(args) > 1 {
				id = args[1]
			}
			return runReview(env, args[0], id, doCommit)
		},
	}
	teamArg(env, cmd)
	cmd.Flags().BoolVar(&doCommit, "commit", false, i18n.T("Commit and set tag TEAM/SPRINT."))
	return cmd
}

func runReview(env *Env, key, sprintID string, doCommit bool) error {
	data, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	s, err := findOrCreateSprint(data, env, sprintID, forecast.PurposeReview)
	if err != nil {
		return err
	}
	fc, err := forecast.Build(data, env.Today)
	if err != nil {
		return asFail(err)
	}
	before := cloneData(data)
	unit := cliUnitAt(data, s.Start)
	env.Println("Review Sprint " + s.ID + " (" + s.Start.Format("02.01.") + " – " + s.End.Format("02.01.2006") + ")")
	if s.Capacity == nil {
		var frozen *float64
		if len(data.People) > 0 {
			value := capacity.Sprint(&data.Team, data.People, *s, 0).Rounded()
			env.Println(i18n.P("Capacity according to people list and absences: [bold]{capacity} PT[/bold]",
				"capacity", textfmt.FmtCapacity(i18n.Language(), &value, data.Team.Capacity.Rounding)))
			frozen = &value
			ok, err := env.Confirm(i18n.P("Is that correct (otherwise correct the absences)?"), true)
			if err != nil {
				return err
			}
			if !ok {
				if frozen, err = env.AskNumber(i18n.P("Actual capacity (PT)"), frozen, false, 0); err != nil {
					return err
				}
			}
		} else {
			env.explain("capacity")
			if frozen, err = env.AskNumber(i18n.P("Capacity (PT)"), nil, false, 0); err != nil {
				return err
			}
		}
		s.Capacity = frozen
	}
	env.explain("velocity")
	if s.Velocity, err = env.AskNumber("Velocity ("+unit+")", s.Velocity, true, 0); err != nil {
		return err
	}
	env.explain("scope_creep")
	if s.ScopeCreep, err = env.AskNumber(i18n.P("Scope creep (share 0–1)"), s.ScopeCreep, true, 0); err != nil {
		return err
	}
	if data.Team.Features.Products && len(data.Products) > 0 {
		ok, err := env.Confirm(i18n.P("Record done per product?"), true)
		if err != nil {
			return err
		}
		if ok {
			if err := env.askProductValues(data, fc, s, "done"); err != nil {
				return err
			}
		}
	}
	if err := env.refuseInvalid(before, withSprint(data, s), "sprints/"); err != nil {
		return err
	}
	path, err := env.Repo().SaveSprint(key, s)
	if err != nil {
		return asFail(err)
	}
	env.saved(path)
	return env.maybeCommit(key, []string{path}, i18n.T("{team} {id}: review recorded", "team", data.Team.Name, "id", s.ID),
		key+"/"+s.ID, doCommit)
}

// cliUnitAt is the estimation unit valid in a sprint that starts at the given time.
func cliUnitAt(data *storage.TeamData, start time.Time) string {
	u, _ := forecast.UnitAt(data, start)
	return string(u)
}
