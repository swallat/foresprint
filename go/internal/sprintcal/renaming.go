package sprintcal

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/protocol"
	"github.com/swallat/foresprint/internal/storage"
)

// Rename gives a sprint a new ID.
type Rename struct{ Old, New string }

func dataError(text string, values ...any) error {
	return &storage.DataError{Msg: i18n.T(text, values...)}
}

// PlanRenames are the renames that follow from "sprintID is now called newID": the sprint itself
// and all saved sprints after it, counted on by the team's numbering. Sprints whose ID stays the
// same are missing from the list. A *storage.DataError is returned for an unknown sprint, an
// invalid ID, or a new ID that would collide with an earlier sprint.
func PlanRenames(data *storage.TeamData, sprintID, newID string) ([]Rename, error) {
	newID = strings.TrimSpace(newID)
	sprint := data.SprintByID(sprintID)
	if sprint == nil {
		known := make([]string, len(data.Sprints))
		for i, s := range data.Sprints {
			known[i] = s.ID
		}
		list := strings.Join(known, ", ")
		if list == "" {
			list = i18n.T("none")
		}
		return nil, dataError("Sprint {id!r} is not saved (existing: {known}).", "id", sprintID, "known", list)
	}
	if newID == "" {
		return nil, dataError("Please enter a new sprint ID.")
	}
	if problem := storage.FileNameProblem(newID, false); problem != "" {
		return nil, dataError("ID not allowed as a file name ({problem}).", "problem", problem)
	}
	numbering := data.Team.Sprint.Numbering
	if !calendar.MatchesNaming(data.Team.Sprint.Naming, newID) && !calendar.IDFitsNumbering(newID, sprint.End, numbering) {
		return nil, dataError("Sprint ID {id!r} does not match the numbering (expected {expected}).",
			"id", newID, "expected", calendar.ExpectedIDForm(i18n.Language(), numbering))
	}
	position := slices.IndexFunc(data.Sprints, func(s model.Sprint) bool { return s.ID == sprintID })
	untouched := map[string]bool{}
	for _, s := range data.Sprints[:position] {
		untouched[s.ID] = true
	}
	var renames []Rename
	previous := newID
	// With a naming rule the later IDs are names from the pattern, counted on from the order of
	// the sprints; without one they count on from the previous ID.
	named := len(data.Team.Sprint.Naming) > 0
	history := append([]model.Sprint(nil), data.Sprints[:position]...)
	for i, s := range data.Sprints[position:] {
		target := newID
		if i > 0 {
			var err error
			if named {
				var created model.Sprint
				last := history[len(history)-1]
				if created, err = calendar.NewChain(&data.Team, history).After(&last); err != nil {
					return nil, err
				}
				target = created.ID
			} else if target, err = calendar.NextID(previous, s.Start, numbering); err != nil {
				return nil, err
			}
		}
		renamed := s.Clone()
		renamed.ID = target
		history = append(history, renamed)
		if untouched[target] {
			return nil, dataError("Sprint ID {id!r} is already taken (by an earlier sprint).", "id", target)
		}
		if target != s.ID {
			renames = append(renames, Rename{s.ID, target})
		}
		previous = target
	}
	return renames, nil
}

// Applied is the result of ApplyRenames: the new sprint files and all touched paths (old and new
// names of sprint files and minutes, for committing).
type Applied struct{ Files, Touched []string }

func accessError(text string, path string, err error) error {
	return &storage.FileAccessError{Msg: i18n.T(text, "path", path, "reason", storage.Reason(err)), Err: err}
}

func replace(src, dst string) error {
	if err := os.Rename(src, dst); err != nil {
		return accessError("{path}: not renamed ({reason})", src, err)
	}
	return nil
}

// ApplyRenames renames the sprint files and the minutes; all or nothing.
func ApplyRenames(repo *storage.Repository, data *storage.TeamData, renames []Rename) (Applied, error) {
	if len(renames) == 0 {
		return Applied{}, nil
	}
	key := data.Team.Key
	type move struct {
		old, new string
		sprint   model.Sprint
	}
	var moves []move
	for _, r := range renames {
		sprint := data.SprintByID(r.Old)
		if sprint == nil {
			return Applied{}, fmt.Errorf("sprint %s not found", r.Old)
		}
		renamed := sprint.Clone()
		renamed.ID = r.New
		oldPath, err := repo.SprintPath(key, r.Old)
		if err != nil {
			return Applied{}, err
		}
		newPath, err := repo.SprintPath(key, r.New)
		if err != nil {
			return Applied{}, err
		}
		moves = append(moves, move{oldPath, newPath, renamed})
	}
	// Collect the minutes before the first rename: otherwise a later sprint would find the
	// just-renamed files of its predecessor.
	pairs := make([][2]string, len(renames))
	for i, r := range renames {
		pairs[i] = [2]string{r.Old, r.New}
	}
	store := &protocol.Store{Dir: repo.TeamDir(key)}
	protocols, err := store.Renames(pairs)
	if err != nil {
		return Applied{}, err
	}
	sources := map[string]bool{}
	for _, m := range moves {
		sources[m.old] = true
	}
	for _, p := range protocols {
		sources[p[0]] = true
	}
	targets := make([]string, 0, len(moves)+len(protocols))
	for _, m := range moves {
		targets = append(targets, m.new)
	}
	for _, p := range protocols {
		targets = append(targets, p[1])
	}
	for _, target := range targets {
		if _, err := os.Stat(target); err == nil && !sources[target] {
			return Applied{}, dataError("{path} already exists.", "path", target)
		}
	}
	backup := map[string][]byte{}
	for _, m := range moves {
		b, err := os.ReadFile(m.old)
		if err != nil {
			return Applied{}, storage.NotReadable(m.old, err)
		}
		backup[m.old] = b
	}
	var written []string
	type step struct{ from, to string }
	var done []step
	rollback := func() {
		for _, p := range written {
			_ = os.Remove(p)
		}
		for old, text := range backup {
			_ = os.WriteFile(old, text, 0o644)
		}
		for i := len(done) - 1; i >= 0; i-- {
			_ = os.Rename(done[i].to, done[i].from)
		}
		storage.ClearTeamCache()
	}
	// Minutes in two steps: first all to an intermediate name, then to the new name. If the chain
	// overlaps (2026.20 → 2026.21, 2026.21 → 2026.22), a direct rename would overwrite the
	// successor's minutes.
	stamp := fmt.Sprintf("%x", time.Now().UnixNano())
	type staged struct{ src, tmp, dst string }
	var stages []staged
	for _, p := range protocols {
		stages = append(stages, staged{p[0], p[0] + ".renaming-" + stamp, p[1]})
	}
	fail := func(err error) (Applied, error) {
		rollback()
		return Applied{}, err
	}
	for _, m := range moves {
		if err := os.Remove(m.old); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return fail(accessError("{path}: not deleted ({reason}). Is the file read-only or open in another "+
				"program?", m.old, err))
		}
	}
	for i := range moves {
		path, err := repo.SaveSprint(key, &moves[i].sprint)
		if err != nil {
			return fail(err)
		}
		written = append(written, path)
	}
	for _, st := range stages {
		if err := replace(st.src, st.tmp); err != nil {
			return fail(err)
		}
		done = append(done, step{st.src, st.tmp})
	}
	for _, st := range stages {
		if err := replace(st.tmp, st.dst); err != nil {
			return fail(err)
		}
		done = append(done, step{st.tmp, st.dst})
	}
	storage.ClearTeamCache()
	var touched []string
	for _, m := range moves {
		touched = append(touched, m.old)
	}
	touched = append(touched, written...)
	for _, p := range protocols {
		touched = append(touched, p[0])
	}
	for _, p := range protocols {
		touched = append(touched, p[1])
	}
	unique := touched[:0:0]
	seen := map[string]bool{}
	for _, p := range touched {
		if !seen[p] {
			seen[p] = true
			unique = append(unique, filepath.Clean(p))
		}
	}
	return Applied{Files: written, Touched: unique}, nil
}
