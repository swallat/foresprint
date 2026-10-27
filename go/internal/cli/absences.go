package cli

import (
	"fmt"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/report"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() { Register(absencesCommand) }

func absencesCommand(env *Env) *cobra.Command {
	var doCommit bool
	var period periodOptions
	cmd := &cobra.Command{
		Use:   "absences TEAM [SPRINT]",
		Short: i18n.T("Record planned absences per person for a sprint (default: next sprint)."),
		Args:  cobra.RangeArgs(1, 2),
		RunE: func(cmd *cobra.Command, args []string) error {
			key := args[0]
			data, err := env.LoadTeam(key)
			if err != nil {
				return err
			}
			if period.used() {
				return runAbsencePeriods(env, key, data, period, doCommit)
			}
			if len(data.People) == 0 {
				return Failf("No people recorded. First: {command}", "command", "foresprint people "+key)
			}
			id := ""
			if len(args) > 1 {
				id = args[1]
			}
			s, err := findOrCreateSprint(data, env, id, forecast.PurposeNext)
			if err != nil {
				return err
			}
			path, err := env.askAbsences(data, s)
			if err != nil {
				return err
			}
			capacityTable(data, s).Render(env.Out)
			env.saved(path)
			if err := env.showSprintForecast(key, s.ID); err != nil {
				return err
			}
			return env.maybeCommit(key, []string{path},
				i18n.T("{team} {id}: absences recorded", "team", data.Team.Name, "id", s.ID), "", doCommit)
		},
	}
	teamArg(env, cmd)
	commitFlag(cmd, &doCommit)
	period.flags(cmd)
	return cmd
}

// sprintSummary describes the sprint: its days, working week and holidays.
func sprintSummary(data *storage.TeamData, s *model.Sprint) string {
	l := i18n.Language()
	days := calendar.TeamWorkdays(&data.Team, s.Start, s.End)
	region, country := "", data.Team.Capacity.Country
	if data.Team.Capacity.Region != nil {
		region = *data.Team.Capacity.Region
	}
	var holidays []string
	for _, d := range days {
		if name := calendar.HolidayName(l, d, region, country); name != "" {
			holidays = append(holidays, d.Format("02.01.")+" "+name)
		}
	}
	last := s.End
	if len(days) > 0 {
		last = days[len(days)-1]
	}
	text := i18n.P("Sprint [bold]{id}[/bold]: {start} – {last} (last working day; the next sprint "+
		"starts on {next}), {days} working days ({week})",
		"id", s.ID, "start", day(s.Start), "last", day(last), "next", s.End.Format("02.01."),
		"days", len(days), "week", calendar.WorkweekLabel(l, &data.Team))
	if len(holidays) > 0 {
		where := i18n.P("nationwide")
		if region != "" {
			where = region
		}
		text += "\n" + i18n.P("including holidays ({region}): {holidays}", "region", where, "holidays", strings.Join(holidays, ", "))
	}
	return text
}

// withSprint is a copy of the data with the (new or changed) sprint.
func withSprint(data *storage.TeamData, s *model.Sprint) *storage.TeamData {
	c := *data
	c.Sprints = nil
	for _, x := range data.Sprints {
		if x.ID != s.ID {
			c.Sprints = append(c.Sprints, x)
		}
	}
	c.Sprints = append(c.Sprints, *s)
	sort.SliceStable(c.Sprints, func(i, j int) bool { return c.Sprints[i].Start.Before(c.Sprints[j].Start) })
	return &c
}

// askAbsences asks for the absences of every active person and saves the sprint.
func (e *Env) askAbsences(data *storage.TeamData, s *model.Sprint) (string, error) {
	before := cloneData(data)
	days := calendar.TeamWorkdays(&data.Team, s.Start, s.End)
	e.Println(sprintSummary(data, s))
	e.explain("absences")
	for _, p := range data.People {
		if !p.ActiveBetween(s.Start, s.End) {
			continue
		}
		current := s.CellDays(p.ID)
		value, err := e.AskNumber(textfmt.BlankControls(p.Name), &current, false, 0)
		if err != nil {
			return "", err
		}
		if v := *value; v != 0 {
			if limit := float64(len(days)); v > limit {
				v = limit
			}
			s.SetCell(p.ID, v, model.AbsencesConfirmed)
		} else {
			s.SetCell(p.ID, 0, model.AbsencesConfirmed)
		}
	}
	s.Freeze() // all people were asked, including "0": the allocation is confirmed
	if s.Capacity != nil {
		ok, err := e.Confirm(i18n.P("A fixed capacity ({capacity}) is recorded for the sprint. Remove it so it is "+
			"calculated from the absences?", "capacity", textfmt.FmtCapacity(i18n.Language(), s.Capacity, data.Team.Capacity.Rounding)),
			s.End.After(e.Today))
		if err != nil {
			return "", err
		}
		if ok {
			s.Capacity = nil
		}
	}
	if err := e.refuseInvalid(before, withSprint(data, s), "sprints/"); err != nil {
		return "", err
	}
	path, err := e.Repo().SaveSprint(data.Team.Key, s)
	return path, asFail(err)
}

// showSprintForecast prints capacity and Forecast PLAN of a sprint after a change.
func (e *Env) showSprintForecast(key, id string) error {
	data, err := e.LoadTeam(key)
	if err != nil {
		return err
	}
	fc, err := forecast.Build(data, e.Today)
	if err != nil {
		return asFail(err)
	}
	entry := fc.Entry(id)
	if entry == nil {
		return nil
	}
	r := entry.Result
	e.Println(i18n.P("Forecast sprint {id}", "id", id))
	e.Println(fmt.Sprintf("  %s: %s PT", i18n.P("Capacity"), report.CapacityLabel(entry)))
	e.Println(fmt.Sprintf("  %s: %s", i18n.P("norm. velocity trend"), report.Fmt(r.NormalizedVelocity.Trend, 2, "")))
	e.Println(fmt.Sprintf("  Forecast PLAN: %s %s  (%s %s · %s %s)", report.Fmt(r.Plan, report.PlanDigits(fc), ""), cliUnitAt(data, entry.Sprint.Start),
		i18n.P("Plannable"), report.Fmt(r.Roadmap, report.SplitDigits(fc), ""), i18n.P("Small items"), report.Fmt(r.SmallStuff, report.SplitDigits(fc), "")))
	return nil
}
