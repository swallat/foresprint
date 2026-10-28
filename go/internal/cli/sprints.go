package cli

import (
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sprintcal"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/validate"
)

func init() {
	Register(sprintsCommand)
	Register(renameSprintCommand)
}

func sprintsCommand(env *Env) *cobra.Command {
	var count int
	var create, doCommit bool
	var ends []string
	cmd := &cobra.Command{
		Use:   "sprints TEAM",
		Short: i18n.T("Sprint calendar: show and create upcoming sprints and adjust end dates."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if count < 1 || count > 60 {
				return Failf("Number of sprints starting with the current one.")
			}
			return runSprints(env, args[0], count, create, ends, doCommit)
		},
	}
	teamArg(env, cmd)
	cmd.Flags().IntVar(&count, "count", 6, i18n.T("Number of sprints starting with the current one."))
	cmd.Flags().BoolVar(&create, "create", false, i18n.T("Create missing sprint files."))
	cmd.Flags().StringArrayVar(&ends, "end", nil, i18n.T("Different last day, e.g. --end 2026.25=2027-01-12 (repeatable); following "+
		"sprints shift accordingly."))
	commitFlag(cmd, &doCommit)
	return cmd
}

func runSprints(env *Env, key string, count int, create bool, ends []string, doCommit bool) error {
	data, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	fc, err := forecast.Build(data, env.TodayFor(data))
	if err != nil {
		return asFail(err)
	}
	planned, err := sprintcal.AbsenceSprints(data, fc, count, 0)
	if err != nil {
		return asFail(err)
	}
	rows := sprintcal.Table(data, planned, env.TodayFor(data))
	for _, raw := range ends {
		id, date, _ := strings.Cut(raw, "=")
		last, perr := time.Parse("2006-01-02", strings.TrimSpace(date))
		idx := -1
		for i, r := range rows {
			if r.Sprint == strings.TrimSpace(id) {
				idx = i
			}
		}
		if idx < 0 || perr != nil {
			return Failf("--end {value}: expected SPRINT=YYYY-MM-DD of a sprint shown", "value", raw)
		}
		rows[idx].Last = last
	}
	after, problems, err := sprintcal.Apply(data, planned, rows)
	if err != nil {
		return asFail(err)
	}
	if len(problems) > 0 {
		for _, p := range problems {
			env.Warnf("%s", p)
		}
		return errExit1
	}
	shown := sprintcal.Table(data, after, env.TodayFor(data))
	l := i18n.Language()
	t := &Table{
		Title:  i18n.P("Sprint calendar {team}", "team", textfmt.BlankControls(data.Team.Name)),
		Header: []string{i18n.T("Sprint"), i18n.T("Start"), i18n.T("Last day"), i18n.T("Working days"), i18n.T("Status")},
		Right:  []bool{false, false, false, true, false},
	}
	for _, r := range shown {
		t.Add(textfmt.BlankControls(r.Sprint), calendar.DayLabel(l, r.Start), calendar.DayLabel(l, r.Last),
			strconv.Itoa(r.WorkingDays), i18n.T(r.Status))
	}
	t.Caption = i18n.P("Working days: {week} from the start up to and including the last day (holidays "+
		"are only deducted in the capacity). The next sprint starts the day after the last "+
		"day.", "week", calendar.WorkweekLabel(l, &data.Team))
	t.Render(env.Out)
	changed := sprintcal.ToSave(data, planned, after, create)
	var blocking []validate.Issue
	for _, i := range validate.CheckTeam(sprintcal.WithSprints(data, changed), env.TodayFor(data)) {
		if i.Level == validate.Error && strings.HasPrefix(i.Where, "sprints/") {
			blocking = append(blocking, i)
		}
	}
	if len(blocking) > 0 {
		for _, i := range blocking {
			env.Warnf("%s: %s", textfmt.BlankControls(i.Where), textfmt.BlankControls(i.Message))
		}
		return errExit1
	}
	if len(changed) == 0 {
		if !create {
			env.Println(i18n.P("Create missing sprint files with --create."))
		}
		return nil
	}
	return saveSprints(env, key, data, changed, doCommit)
}

// saveSprints writes the sprints and offers the commit.
func saveSprints(env *Env, key string, data *storage.TeamData, sprints []model.Sprint, doCommit bool) error {
	var paths, names []string
	for i := range sprints {
		path, err := env.Repo().SaveSprint(key, &sprints[i])
		if err != nil {
			return asFail(err)
		}
		paths = append(paths, path)
		names = append(names, baseName(path))
	}
	env.Println(i18n.P("Saved: {path}", "path", strings.Join(names, ", ")))
	return env.maybeCommit(key, paths, i18n.T("{team}: sprint calendar", "team", data.Team.Name), "", doCommit)
}

func renameSprintCommand(env *Env) *cobra.Command {
	var doCommit bool
	cmd := &cobra.Command{
		Use:   "rename-sprint TEAM SPRINT NEW",
		Short: i18n.T("Change a sprint ID; the saved sprints after it count on from the new ID."),
		Args:  cobra.ExactArgs(3),
		RunE: func(cmd *cobra.Command, args []string) error {
			data, err := env.LoadTeam(args[0])
			if err != nil {
				return err
			}
			renames, err := sprintcal.PlanRenames(data, args[1], args[2])
			if err != nil {
				return asFail(err)
			}
			if len(renames) == 0 {
				env.Println(i18n.P("Nothing to change: sprint {id} already has that ID.", "id", textfmt.BlankControls(args[1])))
				return nil
			}
			t := &Table{Title: i18n.P("Sprint IDs {team}", "team", textfmt.BlankControls(data.Team.Name)),
				Header: []string{i18n.T("before"), i18n.T("new"), i18n.T("Start")}}
			l := i18n.Language()
			for _, r := range renames {
				t.Add(textfmt.BlankControls(r.Old), textfmt.BlankControls(r.New), calendar.DayLabel(l, data.SprintByID(r.Old).Start))
			}
			t.Render(env.Out)
			applied, err := sprintcal.ApplyRenames(env.Repo(), data, renames)
			if err != nil {
				return asFail(err)
			}
			names := make([]string, len(applied.Files))
			for i, f := range applied.Files {
				names[i] = baseName(f)
			}
			env.Println(i18n.P("Saved: {path}", "path", strings.Join(names, ", ")))
			return env.maybeCommit(args[0], applied.Touched,
				i18n.T("{team}: sprint {old} is now {new}", "team", data.Team.Name, "old", args[1], "new", args[2]), "", doCommit)
		},
	}
	teamArg(env, cmd)
	commitFlag(cmd, &doCommit)
	return cmd
}
