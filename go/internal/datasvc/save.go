package datasvc

import (
	"regexp"
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/yamlmerge"
	"github.com/swallat/foresprint/internal/yamlx"
)

// protectedRe recognises the answers of servers that do not accept a direct upload to the main
// branch (D4).
var protectedRe = regexp.MustCompile(`(?i)protected branch|GH006|not allowed to push|pre-receive hook declined|` +
	`push to .* is not allowed|branch protection`)

// Save makes the work visible to the team: it commits, takes over what others did meanwhile and
// uploads, in one step (D2). If the server only takes merge requests, the work goes to a branch of
// the person's own and the result carries the link (D4).
func (s *Store) Save(opts SaveOptions) Result {
	return s.share(gitsync.SyncOptions{Message: s.messageOf(opts.Message), AllowInvalid: opts.SaveAnyway})
}

// Refresh takes over what others have saved, without uploading anything (D2).
func (s *Store) Refresh() Result {
	return s.share(gitsync.SyncOptions{PullOnly: true})
}

func (s *Store) messageOf(message string) string {
	if m := strings.TrimSpace(message); m != "" {
		return m
	}
	return i18n.T("Save from Foresprint")
}

func (s *Store) share(opts gitsync.SyncOptions) Result {
	dir := s.Folder()
	if dir == "" {
		return s.failed(git.New(i18n.T("No data folder chosen."), "path", ""))
	}
	opts.Today = s.today()
	ctx := s.ctx()
	before := s.Status()
	res, err := gitsync.Sync(ctx, dir, opts)
	if err != nil {
		return s.failed(err)
	}
	// D4: a server that refuses the direct upload gets the work on an own branch instead.
	if e := res.Error; e != nil && e.Kind == "denied" && !opts.PullOnly && protectedRe.MatchString(e.Error()) {
		if root, rerr := gitsync.Root(ctx, dir); rerr == nil {
			if mode, _ := gitsync.ShareMode(ctx, root); mode != gitsync.ShareMergeRequest {
				if gitsync.SetShareMode(ctx, root, gitsync.ShareMergeRequest) == nil {
					if res, err = gitsync.Sync(ctx, dir, opts); err != nil {
						return s.failed(err)
					}
				}
			}
		}
	}
	return s.resultOf(res, before.Unsaved == 0 && before.Pending == 0 && before.Incoming == 0)
}

func (s *Store) failed(err error) Result {
	return Result{Outcome: OutcomeProblem, Problem: problemOf(err), Taken: []Change{}, Status: s.Status()}
}

// resultOf maps the result of the sync; idle says there was nothing to save, share or take over.
func (s *Store) resultOf(res *gitsync.SyncResult, idle bool) Result {
	out := Result{Taken: changes(res.Pulled), Notes: res.Notes, Findings: res.Validation}
	if res.MergeRequestURL != "" {
		s.setReview(res.MergeRequestURL)
	}
	out.Link = res.MergeRequestURL
	out.Conflicts = countOpen(res.Conflicts)
	switch e := res.Error; {
	case e == nil && res.MergeRequestBranch != "":
		out.Outcome = OutcomeWaitingForReview
		if out.Link == "" {
			out.Link = s.Status().Link
		}
	case e == nil && idle && res.Committed == "" && !res.Merged && len(res.Pulled) == 0:
		out.Outcome = OutcomeNothing
	case e == nil:
		out.Outcome = OutcomeSaved
	case e.Kind == "conflict" || out.Conflicts > 0:
		out.Outcome = OutcomeConflict
	case e.Kind == "invalid":
		out.Outcome = OutcomeFindings
	case e.Kind == "offline" && res.Committed != "":
		out.Outcome = OutcomeOffline
	case e.Kind == "not_writable":
		out.Outcome = OutcomeReadOnly
		out.Problem = problemOf(e)
	default:
		out.Outcome = OutcomeProblem
		out.Problem = problemOf(e)
	}
	if out.Outcome == OutcomeOffline {
		out.Problem = problemOf(res.Error)
	}
	if out.Taken == nil {
		out.Taken = []Change{}
	}
	out.Status = s.Status()
	return out
}

func countOpen(files []gitsync.ConflictFile) int {
	n := 0
	for _, f := range files {
		if f.Open() {
			n++
		}
	}
	return n
}

// Conflicts lists what two people changed in different ways and needs a decision (D3). It is
// empty when no merge waits.
func (s *Store) Conflicts() []Conflict {
	dir := s.Folder()
	if dir == "" {
		return []Conflict{}
	}
	ctx := s.ctx()
	files, err := gitsync.PendingConflicts(ctx, dir)
	if err != nil {
		return []Conflict{}
	}
	out := []Conflict{}
	for _, f := range files {
		if !f.Open() {
			continue
		}
		c := Conflict{File: f.File, Whole: f.Whole, MineDeleted: f.OursDeleted, TheirsDeleted: f.TheirsDeleted,
			Entries: []ConflictEntry{}}
		if f.Whole {
			mine, theirs, _ := gitsync.ConflictTextDiffs(ctx, dir, f.File)
			c.Entries = append(c.Entries, ConflictEntry{Path: []string{}, Label: f.File, Mine: mine, Theirs: theirs,
				MineMissing: f.OursDeleted, TheirsMissing: f.TheirsDeleted})
		}
		for _, k := range f.Keys {
			e := ConflictEntry{Path: append([]string{}, k.Path...), Label: k.Label(),
				MineMissing: yamlmerge.IsMissing(k.Ours), TheirsMissing: yamlmerge.IsMissing(k.Theirs)}
			e.Mine, e.Theirs = show(k.Ours), show(k.Theirs)
			e.Before, e.HasBefore = show(k.Base), !yamlmerge.IsMissing(k.Base)
			c.Entries = append(c.Entries, e)
		}
		out = append(out, c)
	}
	return out
}

// show writes a value of the data as text.
func show(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case *yamlx.Map, []any:
		text, err := yamlx.Dump(x)
		if err != nil {
			return ""
		}
		return strings.TrimRight(text, "\n")
	}
	if yamlmerge.IsMissing(v) {
		return ""
	}
	return yamlx.PyStr(v)
}

// ResolveConflicts records the decisions. Entries without a decision stay open; the result says
// how many files still wait. When none do, Save finishes the merge (D3).
func (s *Store) ResolveConflicts(decisions []Decision) Result {
	dir := s.Folder()
	choices := gitsync.Choices{}
	for _, d := range decisions {
		if d.Choice != Mine && d.Choice != Theirs {
			continue
		}
		if choices[d.File] == nil {
			choices[d.File] = yamlmerge.Choices{}
		}
		choices[d.File].Choose(yamlmerge.Path(d.Path), d.Choice)
	}
	remaining, err := gitsync.ResolveConflicts(s.ctx(), dir, choices)
	if err != nil {
		return s.failed(err)
	}
	git.InvalidateStatus()
	out := Result{Outcome: OutcomeSaved, Taken: []Change{}, Conflicts: countOpen(remaining)}
	if out.Conflicts > 0 {
		out.Outcome = OutcomeConflict
	}
	out.Status = s.Status()
	return out
}

// TakeTheirs decides every open conflict for the other side ("Discard mine", D3). What is lost
// is the person's own change to the contested values only.
func (s *Store) TakeTheirs() Result {
	var decisions []Decision
	for _, c := range s.Conflicts() {
		for _, e := range c.Entries {
			decisions = append(decisions, Decision{File: c.File, Path: e.Path, Choice: Theirs})
		}
	}
	return s.ResolveConflicts(decisions)
}

// AbortMerge gives up an unfinished merge from outside the app and returns to the state before
// it; the own work stays.
func (s *Store) AbortMerge() Status {
	_ = gitsync.AbortUnfinished(s.ctx(), s.Folder())
	git.InvalidateStatus()
	return s.Status()
}
