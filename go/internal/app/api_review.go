package app

import (
	"context"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/protocol"
	"github.com/swallat/foresprint/internal/report"
	"github.com/swallat/foresprint/internal/storage"
)

// The area Review and minutes: closing a sprint (velocity from commitment, not done and
// additionally done; done per product; the person days frozen; carry-over; a tag at the next
// Save) and the minutes files of a sprint. The numbers are the model's: Velocity = Commitment -
// NotDone + AdditionalDone.

func (a *API) pendingTags() []string {
	a.tagMu.Lock()
	defer a.tagMu.Unlock()
	return append([]string(nil), a.tags...)
}

// tagRoot is the Git repository of the data folder; "" if there is none.
func (a *API) tagRoot() string {
	root, err := gitsync.Root(context.Background(), a.DataDir())
	if err != nil {
		return ""
	}
	return root
}

// usableTags are the pending tags that can be set now: a valid name that does not exist yet.
func (a *API) usableTags() []string {
	pending := a.pendingTags()
	if len(pending) == 0 {
		return nil
	}
	root := a.tagRoot()
	if root == "" {
		return nil
	}
	var out []string
	for _, tag := range pending {
		if git.ValidTagName(context.Background(), root, tag) != nil {
			continue
		}
		if c, err := git.TagCommit(context.Background(), root, tag); err == nil && c == "" {
			out = append(out, tag)
		}
	}
	return out
}

// dropSetTags forgets the pending tags that exist now or can never be set (invalid name).
func (a *API) dropSetTags() {
	pending := a.pendingTags()
	root := a.tagRoot()
	var done []string
	for _, tag := range pending {
		if root == "" || git.ValidTagName(context.Background(), root, tag) != nil {
			done = append(done, tag)
		} else if c, err := git.TagCommit(context.Background(), root, tag); err == nil && c != "" {
			done = append(done, tag)
		}
	}
	a.dropTags(done)
}

func (a *API) dropTags(done []string) {
	a.tagMu.Lock()
	defer a.tagMu.Unlock()
	keep := a.tags[:0]
	for _, t := range a.tags {
		if !contains(done, t) {
			keep = append(keep, t)
		}
	}
	a.tags = keep
}

// addTag asks for a tag at the next Save; a Review asks for one tag only.
func (a *API) addTag(team, sprint, tag string) {
	a.tagMu.Lock()
	defer a.tagMu.Unlock()
	a.takeBack(team, sprint)
	if a.sprintTags == nil {
		a.sprintTags = map[string]string{}
	}
	a.sprintTags[team+"/"+sprint] = tag
	if !contains(a.tags, tag) {
		a.tags = append(a.tags, tag)
	}
}

// takeBack drops the tag the Review of the sprint asked for (tagMu is held).
func (a *API) takeBack(team, sprint string) {
	key := team + "/" + sprint
	old, ok := a.sprintTags[key]
	if !ok {
		return
	}
	delete(a.sprintTags, key)
	keep := a.tags[:0]
	for _, t := range a.tags {
		if t != old {
			keep = append(keep, t)
		}
	}
	a.tags = keep
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

func val(p *float64) float64 {
	if p == nil {
		return 0
	}
	return *p
}

func (a *API) loadReviewSprint(team, sprintID string) (*storage.TeamData, *forecast.Forecast, *model.Sprint, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return nil, nil, nil, err
	}
	fc, err := forecast.Build(data, today())
	if err != nil {
		return nil, nil, nil, err
	}
	s, err := fc.LookupSprint(sprintID, forecast.DefaultLookupAhead)
	if err != nil {
		return nil, nil, nil, err
	}
	if s == nil {
		return nil, nil, nil, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", sprintID))
	}
	return data, fc, s, nil
}

// reviewTargets are the places the rest of a ticket can continue: the next sprints and the
// backlog.
func reviewTargets(fc *forecast.Forecast, s model.Sprint) []ReviewTarget {
	out := []ReviewTarget{}
	n := 0
	for i := range fc.Entries {
		e := fc.Entries[i].Sprint
		if !e.Start.After(s.Start) {
			continue
		}
		id := e.ID
		if n == 0 {
			id = ""
		}
		out = append(out, ReviewTarget{ID: id, Name: sprintName(e)})
		if n++; n == 4 {
			break
		}
	}
	return append(out, ReviewTarget{ID: model.CarryBacklog})
}

func hasTarget(list []ReviewTarget, id string) bool {
	for _, t := range list {
		if t.ID == id {
			return true
		}
	}
	return false
}

func buildReview(team string, data *storage.TeamData, fc *forecast.Forecast, s model.Sprint) SprintReview {
	col := column(data, fc, s)
	out := SprintReview{
		Sprint:      col,
		Unit:        string(data.Team.Unit),
		Started:     !s.Start.After(fc.Today),
		Reviewed:    s.Velocity != nil,
		Tickets:     data.Team.Features.Tickets && len(s.CommittedTickets) > 0,
		PlannedDays: col.Capacity,
		FrozenDays:  col.Capacity,
		Targets:     reviewTargets(fc, s),
		List:        []ReviewTicket{},
		Products:    []ReviewProduct{},
		Tag:         team + "/" + s.ID,
	}
	if s.Capacity != nil {
		out.FrozenDays = *s.Capacity
	}
	out.ProductionOn = data.Team.Features.Production
	out.Commitment = val(s.Commitment)
	if out.Tickets {
		carried := map[string]model.CarryItem{}
		for _, c := range s.Carry {
			if c.Ticket != nil {
				carried[*c.Ticket] = c
			}
		}
		sum := 0.0
		for _, key := range s.CommittedTickets {
			row := ReviewTicket{Key: key, Title: key}
			if t := data.TicketByKey(key); t != nil {
				row.Title = t.Title
				row.Estimate = val(t.Estimate)
				row.Done = t.Done
				row.Rest = row.Estimate
				if t.Remaining != nil {
					row.Rest = *t.Remaining
				}
			}
			if c, ok := carried[key]; ok {
				row.Done, row.Rest, row.Target = false, c.Rest, c.Target
			} else if out.Reviewed {
				row.Done = true
			}
			out.List = append(out.List, row)
			sum += row.Estimate
		}
		if s.Commitment == nil {
			out.Commitment = sum
		}
		for _, r := range out.List {
			if !r.Done {
				out.NotDone += r.Estimate
			}
		}
		// A target that is not among the offered places stays selectable.
		for _, r := range out.List {
			if !r.Done && !hasTarget(out.Targets, r.Target) {
				out.Targets = append(out.Targets, ReviewTarget{ID: r.Target, Name: r.Target})
			}
		}
	} else {
		out.RestNext = val(s.RestNext)
	}
	out.CommitmentSet = s.Commitment != nil || out.Tickets
	out.AdditionalDone = val(s.AdditionalDone)
	if out.Reviewed {
		// A closed Review shows what was stored, whatever the tickets say today.
		out.NotDone = val(s.NotDone)
		out.Velocity = *s.Velocity
	} else {
		if !out.Tickets {
			out.NotDone = val(s.NotDone)
		}
		out.Velocity = out.Commitment - out.NotDone + out.AdditionalDone
	}
	if out.FrozenDays > 0 {
		r := out.Velocity / out.FrozenDays
		out.Rate = &r
	}
	if data.Team.Features.Products {
		out.ProductsOn = true
		for _, p := range data.Products {
			if !p.ActiveBetween(s.Start, s.End) {
				continue
			}
			v := s.Products[p.ID]
			planned := val(v.Planned)
			if v.Planned == nil {
				planned = val(v.Preplanned)
			}
			out.Products = append(out.Products, ReviewProduct{ID: p.ID, Name: p.Name, Planned: planned,
				Done: val(v.Done), ProdDone: val(v.ProductionDone)})
		}
	} else {
		out.Production = val(s.ProductionDone)
	}
	if out.Reviewed {
		out.Reopenable = true
		for _, later := range data.Sprints {
			if later.Start.After(s.Start) && later.Velocity != nil {
				out.Reopenable = false
			}
		}
	}
	return out
}

// SprintReview reads the Review of a sprint: the recorded values, or the suggestion from the
// planning (commitment, committed tickets with their tracker state).
func (a *API) SprintReview(team, sprintID string) (SprintReview, error) {
	data, fc, s, err := a.loadReviewSprint(team, sprintID)
	if err != nil {
		return SprintReview{}, err
	}
	return buildReview(team, data, fc, *s), nil
}

func nonNegative(v float64) error {
	if v < 0 || math.IsNaN(v) || math.IsInf(v, 0) {
		return fmt.Errorf("%s", i18n.T("Numbers in the Review must not be negative."))
	}
	return nil
}

func (a *API) minutes(team string) *protocol.Store {
	return &protocol.Store{Dir: storage.NewRepository(a.DataDir()).TeamDir(team)}
}

// CloseReview records the Review: velocity, carry-over, done per product and the frozen person
// days, writes the Review minutes and asks for the tag at the next Save. Capacity and the
// absences of the sprint are frozen with it.
func (a *API) CloseReview(team, sprintID string, in ReviewInput) (ReviewClosed, error) {
	editMu.Lock()
	defer editMu.Unlock()
	repo := storage.NewRepository(a.DataDir())
	data, fc, found, err := a.loadReviewSprint(team, sprintID)
	if err != nil {
		return ReviewClosed{}, err
	}
	if found.Start.After(fc.Today) {
		return ReviewClosed{}, fmt.Errorf("%s", i18n.T("Sprint {id} has not begun; it cannot be reviewed yet.", "id", sprintID))
	}
	for _, v := range []float64{in.NotDone, in.AdditionalDone, in.RestNext, in.FrozenDays, in.Production} {
		if err := nonNegative(v); err != nil {
			return ReviewClosed{}, err
		}
	}
	s := found.Clone()
	view := buildReview(team, data, fc, s)
	if view.Reviewed && !view.Reopenable {
		return ReviewClosed{}, fmt.Errorf("%s", i18n.T("Only the latest reviewed sprint can be reopened."))
	}
	if tag := strings.TrimSpace(in.Tag); tag != "" {
		if err := git.CheckName(tag); err != nil {
			return ReviewClosed{}, err
		}
		if root := a.tagRoot(); root != "" {
			if err := git.ValidTagName(context.Background(), root, tag); err != nil {
				return ReviewClosed{}, err
			}
		}
	}
	commitment := view.Commitment
	if !view.CommitmentSet && in.Commitment != nil {
		if err := nonNegative(*in.Commitment); err != nil {
			return ReviewClosed{}, err
		}
		commitment = *in.Commitment
	}
	s.Commitment = model.Ptr(commitment)
	s.Carry, s.RestNext = nil, nil
	notDone := in.NotDone
	if view.Tickets {
		byKey := map[string]ReviewTicket{}
		for _, r := range in.List {
			byKey[r.Key] = r
		}
		notDone = 0
		for _, row := range view.List {
			got, ok := byKey[row.Key]
			if !ok {
				got = row
			}
			if got.Done {
				continue
			}
			if err := nonNegative(got.Rest); err != nil {
				return ReviewClosed{}, err
			}
			if !knownTarget(data, fc, got.Target) {
				return ReviewClosed{}, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", got.Target))
			}
			notDone += row.Estimate
			key := row.Key
			s.Carry = append(s.Carry, model.CarryItem{Ticket: &key, Rest: got.Rest, Target: got.Target})
		}
	} else if in.RestNext > 0 {
		if in.RestNext > notDone {
			return ReviewClosed{}, fmt.Errorf("%s", i18n.T("The rest that continues cannot be more than what was not done."))
		}
		s.RestNext = model.Ptr(in.RestNext)
	}
	if notDone > commitment {
		return ReviewClosed{}, fmt.Errorf("%s", i18n.T("Not done cannot be more than the commitment."))
	}
	s.NotDone, s.AdditionalDone = model.Ptr(notDone), model.Ptr(in.AdditionalDone)
	s.Velocity = model.Ptr(commitment - notDone + in.AdditionalDone)
	s.ScopeCreep = nil
	if commitment > 0 && in.AdditionalDone > 0 {
		s.ScopeCreep = model.Ptr(math.Round(in.AdditionalDone/commitment*10000) / 10000)
	}
	frozen := in.FrozenDays
	if frozen == 0 {
		frozen = view.FrozenDays
	}
	s.Capacity = model.Ptr(frozen)
	s.Freeze()
	if view.ProductsOn {
		if s.Products == nil {
			s.Products = map[string]model.ProductValues{}
		}
		for _, p := range in.Products {
			if err := nonNegative(p.Done); err != nil {
				return ReviewClosed{}, err
			}
			if err := nonNegative(p.ProdDone); err != nil {
				return ReviewClosed{}, err
			}
			if data.Team.Features.Products && !hasProduct(data, p.ID) {
				continue
			}
			v := s.Products[p.ID]
			v.Done = model.Ptr(p.Done)
			if data.Team.Features.Production {
				v.ProductionDone = model.Ptr(p.ProdDone)
			}
			s.Products[p.ID] = v
		}
	} else if data.Team.Features.Production {
		s.ProductionDone = model.Ptr(in.Production)
	}

	done := buildReview(team, withSprint(data, s), fc, s)
	text := reviewMinutes(data, done, time.Now())
	_, err = a.minutes(team).SaveWithProtocol(sprintID, protocol.Review, text, nil, func() ([]string, error) {
		path, serr := repo.SaveSprint(team, &s)
		return []string{path}, serr
	})
	if err != nil {
		return ReviewClosed{}, err
	}
	out := ReviewClosed{Review: done}
	if entries, lerr := a.minutes(team).List(sprintID); lerr == nil {
		for _, e := range entries {
			if e.Kind == protocol.Review && !e.Obsolete {
				out.Minutes = relTo(repo.TeamDir(team), e.Path)
				break
			}
		}
	}
	if tag := strings.TrimSpace(in.Tag); tag != "" {
		a.addTag(team, sprintID, tag)
		out.Tag = tag
	}
	return out, nil
}

// knownTarget says whether a carry target is the next sprint, the backlog, a pro-forma sprint or a
// sprint of the team.
func knownTarget(data *storage.TeamData, fc *forecast.Forecast, id string) bool {
	if id == "" || id == model.CarryBacklog || strings.HasPrefix(id, model.CarryProForma) {
		return true
	}
	if data.SprintByID(id) != nil {
		return true
	}
	return fc.Entry(id) != nil
}

func hasProduct(data *storage.TeamData, id string) bool {
	for _, p := range data.Products {
		if p.ID == id {
			return true
		}
	}
	return false
}

// withSprint is the data with the sprint replaced by the changed one.
func withSprint(data *storage.TeamData, s model.Sprint) *storage.TeamData {
	copied := *data
	copied.Sprints = append([]model.Sprint(nil), data.Sprints...)
	for i := range copied.Sprints {
		if copied.Sprints[i].ID == s.ID {
			copied.Sprints[i] = s
			return &copied
		}
	}
	copied.Sprints = append(copied.Sprints, s)
	return &copied
}

func relTo(base, path string) string {
	if rel, err := filepath.Rel(base, path); err == nil {
		return filepath.ToSlash(rel)
	}
	return path
}

// ReopenReview takes the Review back: the sprint is unreviewed again and its Review minutes are
// marked obsolete (they stay as files). Only the latest reviewed sprint can be reopened.
func (a *API) ReopenReview(team, sprintID string) (ReviewClosed, error) {
	editMu.Lock()
	defer editMu.Unlock()
	repo := storage.NewRepository(a.DataDir())
	data, fc, found, err := a.loadReviewSprint(team, sprintID)
	if err != nil {
		return ReviewClosed{}, err
	}
	if !buildReview(team, data, fc, *found).Reopenable {
		return ReviewClosed{}, fmt.Errorf("%s", i18n.T("Only the latest reviewed sprint can be reopened."))
	}
	s := found.Clone()
	s.Velocity, s.NotDone, s.AdditionalDone, s.ScopeCreep = nil, nil, nil, nil
	// The frozen capacity and absences stay: they are what planning froze, too.
	s.Carry, s.RestNext, s.ProductionDone = nil, nil, nil
	for id, v := range s.Products {
		v.Done, v.ProductionDone = nil, nil
		s.Products[id] = v
	}
	_, err = a.minutes(team).ObsoleteWithSave(sprintID, protocol.Review, func() ([]string, error) {
		path, serr := repo.SaveSprint(team, &s)
		return []string{path}, serr
	})
	if err != nil {
		return ReviewClosed{}, err
	}
	a.tagMu.Lock()
	a.takeBack(team, sprintID)
	a.tagMu.Unlock()
	data, err = repo.Load(team)
	if err != nil {
		return ReviewClosed{}, err
	}
	if fc, err = forecast.Build(data, today()); err != nil {
		return ReviewClosed{}, err
	}
	saved := data.SprintByID(sprintID)
	if saved == nil {
		saved = &s
	}
	return ReviewClosed{Review: buildReview(team, data, fc, *saved)}, nil
}

func num(v float64) string { return report.FmtValue(v, 2) }

func reviewMinutes(data *storage.TeamData, r SprintReview, now time.Time) string {
	facts := []protocol.Fact{
		{Label: i18n.T("Commitment of the sprint"), Value: num(r.Commitment) + " " + r.Unit},
		{Label: i18n.T("Not done"), Value: num(r.NotDone)},
		{Label: i18n.T("Done in addition"), Value: num(r.AdditionalDone)},
		{Label: i18n.T("Velocity"), Value: num(r.Velocity) + " " + r.Unit},
		{Label: i18n.T("Person days (frozen)"), Value: num(r.FrozenDays)},
	}
	if r.Rate != nil {
		facts = append(facts, protocol.Fact{Label: i18n.T("Rate per person day"), Value: num(*r.Rate)})
	}
	var notes []protocol.Note
	if r.Tickets {
		var done, left []string
		for _, t := range r.List {
			line := t.Key + " " + t.Title
			if t.Done {
				done = append(done, line)
			} else {
				left = append(left, fmt.Sprintf("%s (%s)", line, i18n.T("rest {rest}", "rest", num(t.Rest))))
			}
		}
		notes = append(notes, protocol.Note{Title: i18n.T("Done tickets"), Items: done},
			protocol.Note{Title: i18n.T("Carried over"), Items: left})
	}
	var d *protocol.Distribution
	if r.ProductsOn {
		d = &protocol.Distribution{}
		for _, p := range r.Products {
			pl, dn, pd := p.Planned, p.Done, p.ProdDone
			row := protocol.Row{Name: p.Name, Active: true, Planned: &pl, Done: &dn}
			if r.ProductionOn {
				row.ProductionDone = &pd
			}
			d.Rows = append(d.Rows, row)
		}
	}
	return protocol.Render(protocol.Review, data.Team.Name, r.Sprint.ID, now, facts, d, notes, "", false)
}

func minutesRow(dir string, sprintID string, e protocol.Entry) MinutesRow {
	return MinutesRow{Sprint: sprintID, Kind: e.Kind, At: e.At.Format("2006-01-02 15:04"),
		File: relTo(dir, e.Path), Obsolete: e.Obsolete}
}

// SprintMinutes lists the minutes files of a sprint, newest first; an empty sprint lists those
// of all sprints.
func (a *API) SprintMinutes(team, sprintID string) ([]MinutesRow, error) {
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return nil, err
	}
	ids := []string{sprintID}
	if sprintID == "" {
		ids = nil
		for _, s := range data.Sprints {
			ids = append(ids, s.ID)
		}
	}
	dir := repo.TeamDir(team)
	rows := []MinutesRow{}
	for _, id := range ids {
		entries, err := a.minutes(team).List(id)
		if err != nil {
			return nil, err
		}
		for _, e := range entries {
			rows = append(rows, minutesRow(dir, id, e))
		}
	}
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].At > rows[j].At })
	return rows, nil
}

// MinutesText reads one minutes file (a path relative to the team folder, as SprintMinutes
// lists it).
func (a *API) MinutesText(team, file string) (MinutesText, error) {
	repo := storage.NewRepository(a.DataDir())
	dir := repo.TeamDir(team)
	clean := filepath.Clean(filepath.FromSlash(file))
	if filepath.IsAbs(clean) || strings.HasPrefix(clean, "..") || filepath.Dir(clean) != protocol.Folder {
		return MinutesText{}, fmt.Errorf("%s", i18n.T("This is not a minutes file."))
	}
	path := filepath.Join(dir, clean)
	b, err := os.ReadFile(path)
	if err != nil {
		return MinutesText{}, err
	}
	return MinutesText{Text: string(b), Path: path}, nil
}
