package cli

import (
	"strconv"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/formulas"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() { Register(capacityCommand) }

func capacityCommand(env *Env) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "capacity TEAM [SPRINT]",
		Short: i18n.T("Show the capacity calculation of a sprint in detail (default: next sprint)."),
		Args:  cobra.RangeArgs(1, 2),
		RunE: func(cmd *cobra.Command, args []string) error {
			data, err := env.LoadTeam(args[0])
			if err != nil {
				return err
			}
			id := ""
			if len(args) > 1 {
				id = args[1]
			}
			s, err := findOrCreateSprint(data, env, id, forecast.PurposeNext)
			if err != nil {
				return err
			}
			capacityTable(data, s).Render(env.Out)
			digits := data.Team.Capacity.Rounding
			l := i18n.Language()
			if s.Capacity != nil {
				env.Println(i18n.P("Recorded/frozen in the sprint file: {capacity} PT",
					"capacity", textfmt.FmtCapacity(l, s.Capacity, digits)))
			}
			if data.SprintByID(s.ID) == nil {
				if len(data.People) > 0 {
					env.Println(i18n.P("No sprint file yet – until then the forecast uses the calendar and the " +
						"people list; the unknown absences are estimated from the history (without " +
						"history, no deduction)."))
				} else {
					env.Println(i18n.P("No sprint file yet – until then the forecast uses the capacity trend."))
				}
			}
			return nil
		},
	}
	teamArg(env, cmd)
	return cmd
}

// findOrCreateSprint is the sprint from the store or, without a file, from the calendar; with
// no ID, the default sprint of the purpose.
func findOrCreateSprint(data *storage.TeamData, env *Env, id string, purpose forecast.Purpose) (*model.Sprint, error) {
	if id == "" {
		fc, err := forecast.Build(data, env.Today)
		if err != nil {
			return nil, asFail(err)
		}
		entry, err := fc.DefaultEntry(purpose)
		if err != nil {
			return nil, asFail(err)
		}
		if entry == nil {
			return nil, Failf("No matching sprint found – please specify a sprint ID.")
		}
		id = entry.Sprint.ID
	}
	sprint, err := forecast.FindSprint(data, id, forecast.DefaultFindAhead)
	if err != nil {
		return nil, asFail(err)
	}
	if sprint == nil {
		return nil, Failf("Sprint {id} is not part of the team's sprint sequence.", "id", id)
	}
	return sprint, nil
}

// plainNumber is a number without trailing zeros ("2", "0.5").
func plainNumber(v float64) string { return pymath.General(v) }

func capacityTable(data *storage.TeamData, s *model.Sprint) *Table {
	l := i18n.Language()
	b := capacity.Sprint(&data.Team, data.People, *s, 0)
	digits := b.Rounding
	t := &Table{
		Title: i18n.P("Capacity sprint {id} ({start} – {end})", "id", s.ID,
			"start", s.Start.Format("02.01."), "end", s.End.Format("02.01.2006")),
		Header: []string{i18n.T("Person"), i18n.T("Working days"), i18n.T("Holidays"), i18n.T("Absences"), i18n.T("PT")},
		Right:  []bool{false, true, true, true, true},
	}
	for _, pc := range b.People {
		cap := pc.Capacity
		t.Add(pc.Person.Name, strconv.Itoa(pc.Workdays), strconv.Itoa(pc.Holidays),
			plainNumber(pc.AbsenceDays), textfmt.FmtCapacity(l, &cap, digits))
	}
	deduction := func(label string, part float64) {
		p := part
		t.Add(label, "", "", "", "−"+textfmt.FmtCapacity(l, &p, digits))
	}
	if b.OverheadDaysPart != 0 {
		deduction(i18n.P("Scrum events deduction ({days} PT per person × FTE)",
			"days", plainNumber(data.Team.Capacity.OverheadDays)), b.OverheadDaysPart)
	}
	if b.OverheadSharePart != 0 {
		deduction(i18n.P("Scrum events deduction ({share})",
			"share", textfmt.Pct(l, data.Team.Capacity.OverheadShare)), b.OverheadSharePart)
	}
	if approx := b.Approximated(); len(approx) > 0 {
		names := make([]string, len(approx))
		for i, p := range approx {
			names[i] = p.Person.Name
		}
		t.Caption = formulas.New(l).FTEChangeNote(names)
	}
	total := b.Capacity
	t.Add(i18n.T("Total"), "", "", "", textfmt.FmtCapacity(l, &total, digits))
	return t
}
