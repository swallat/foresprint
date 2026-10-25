// Package ticketimport turns the raw tickets of a source (package sources) into the tickets of
// the model and reconciles them with the last import and the earmarks of the PO. It is the Go
// port of src/foresprint/ticket_import.py and label_writeback.py (comparison:
// golden/expected/ticketimport).
//
// Like the Excel import it has two stages: PlanImport compares and writes nothing; Plan.Apply
// writes tickets.yaml and, when it changed, preplan.yaml. Manual estimates of the PO are not
// applied here; the distribution does that.
package ticketimport

import (
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

// Kinds of a Change, in the order the preview shows them.
const (
	KindNew              = "new"                // key not in the last import
	KindChanged          = "changed"            // estimate or remaining differs (Note = field, Old/New = numbers)
	KindDone             = "done"               // resolved now (was open or unknown before)
	KindMissing          = "missing"            // key no longer delivered: removed from tickets.yaml
	KindUnassigned       = "unassigned"         // no project, or several via the same source (New = candidates)
	KindUnknownEpic      = "unknown_epic"       // epic no project rule refers to (Key = epic, New = ticket keys)
	KindRefinedUnclear   = "refined_unclear"    // refined only via refined_also_if (Note "rule") or label without estimate
	KindEarmarkDropped   = "earmark_dropped"    // real sprint wins (Old/New = sprints), ticket done, or its sprint is over (Note "ended")
	KindSprintUnresolved = "sprint_unresolved"  // sprint name of the tracker unknown to the tool (Note = name)
	KindEarmarkLabel     = "earmark_from_label" // earmark taken from the label planned_for_<sprint_id> (New = sprint)
)

// Kinds lists the kinds in the order of the preview.
var Kinds = []string{
	KindNew, KindChanged, KindDone, KindMissing, KindUnassigned, KindUnknownEpic,
	KindRefinedUnclear, KindEarmarkDropped, KindSprintUnresolved, KindEarmarkLabel,
}

// Notes of a refined_unclear change and of an earmark_dropped change.
const (
	UnclearRule       = "rule"
	UnclearNoEstimate = "no_estimate"
	// DroppedEnded: the sprint of the earmark is over (an open ticket cannot be put into the past).
	DroppedEnded = "ended"
)

// Change is one line of the preview.
type Change struct {
	Kind  string
	Key   string
	Title string
	// Old and New are a number (or nil), a sprint id, or a list of strings, depending on the kind.
	Old  any
	New  any
	Note *string
}

// Sprints answers what the tool knows about a sprint id: recorded, in the forecast, or generated
// from the calendar up to 52 sprints beyond the last recorded one.
type Sprints interface {
	// End returns the end of the sprint; ok is false for an unknown sprint.
	End(id string) (end time.Time, ok bool)
}

// Lister is implemented by Sprints that can also list their ids; the name of a tracker sprint is
// then matched against ids that only contain its sprint number ("TEAM - 2026.20").
type Lister interface {
	IDs() []string
}

// Env is what the import needs to know about the team.
type Env struct {
	Tracker  model.TrackerSettings
	Projects []model.Project
	// Products are matched by id or name when the product comes from a tracker field.
	Products []model.Product
	// Tickets are the tickets of the last import (tickets.yaml).
	Tickets []model.Ticket
	Preplan model.Preplan
	Sprints Sprints
	Today   time.Time
	// KeepOrder keeps the PO's own order of tracker tickets (preplan.yaml order); otherwise a
	// fetch takes over the order of the tracker again.
	KeepOrder bool
}

// Plan is the result of the preview: the tickets to write, the reconciled preplan and what
// changed.
type Plan struct {
	Tickets []model.Ticket
	Preplan model.Preplan
	// PreplanChanged is true when the reconciliation dropped or took an earmark: preplan.yaml is
	// written as well.
	PreplanChanged bool
	Changes        []Change
	// Warnings are hints that do not belong to one ticket of the import (translated texts).
	Warnings []string
	// Source is the name of the source (file name or query) stored in tickets.yaml.
	Source *string
}

// OfKind returns the changes of one kind.
func (p Plan) OfKind(kind string) []Change {
	var out []Change
	for _, c := range p.Changes {
		if c.Kind == kind {
			out = append(out, c)
		}
	}
	return out
}

// Unchanged says whether applying the plan would leave the stored files as they are (apart from
// the time stamp). Then nothing is written (a new source name counts as a change). Changes is
// not the measure: it also lists hints that stay as long as the data does.
func (p Plan) Unchanged(storedTickets []model.Ticket, storedSource *string) bool {
	return !p.PreplanChanged && ticketsEqual(p.Tickets, storedTickets) && stringPtrEqual(p.Source, storedSource)
}

// Saver writes the files of a team (the storage package).
type Saver interface {
	SaveTickets(team string, tickets []model.Ticket, now time.Time, source *string) (path string, err error)
	SavePreplan(team string, preplan model.Preplan) (path string, err error)
}

// Apply writes tickets.yaml (time stamp now, source of the plan) and, only when the
// reconciliation changed it, preplan.yaml. It returns the paths written.
func (p Plan) Apply(saver Saver, team string, now time.Time) ([]string, error) {
	path, err := saver.SaveTickets(team, p.Tickets, now, p.Source)
	if err != nil {
		return nil, err
	}
	paths := []string{path}
	if p.PreplanChanged {
		path, err = saver.SavePreplan(team, p.Preplan)
		if err != nil {
			return paths, err
		}
		paths = append(paths, path)
	}
	return paths, nil
}

// --- Single ticket -----------------------------------------------------------------------

// IsRefined returns (refined, unclear) of a ticket with these facts and this estimate (spec
// section 6.3). The label with an estimate is a clear refinement. Without the label,
// refined_also_if counts as refined but unclear (the label is sometimes forgotten). The label
// without an estimate is unclear and not refined: there is nothing to calculate with.
func IsRefined(facts model.Facts, estimate *float64, tracker model.TrackerSettings) (refined, unclear bool) {
	if tracker.Fields.Refined != nil {
		if mapped, ok := RefinedFromField(facts[MapRefined]); ok { // the mapped field decides
			return mapped && estimate != nil, mapped && estimate == nil
		}
	}
	label := ""
	if tracker.RefinedLabel != nil {
		label = *tracker.RefinedLabel
	}
	if label != "" && containsString(facts["label"], label) {
		if estimate != nil {
			return true, false
		}
		return false, true
	}
	if tracker.RefinedAlsoIf != nil && tracker.RefinedAlsoIf.Matches(facts) {
		return true, true
	}
	return false, false
}

// AssignProject returns the project id of a ticket with these facts and the candidates (spec
// section 6.4). Of all projects whose rule matches, the one matching via the source earliest in
// order wins; sources outside the order rank last. Several projects matching via the same best
// source contradict each other: no project (nil), all of them as candidates (in file order).
func AssignProject(facts model.Facts, projects []model.Project, order []string) (project *string, candidates []string) {
	rank := func(sourceSet []string) int {
		best := len(order)
		for _, s := range sourceSet {
			for i, o := range order {
				if o == s && i < best {
					best = i
				}
			}
		}
		return best
	}
	type match struct {
		id   string
		rank int
	}
	var matching []match
	for _, p := range projects {
		if p.Match != nil && p.Match.Matches(facts) {
			matching = append(matching, match{p.ID, rank(p.Match.MatchedSources(facts))})
		}
	}
	if len(matching) == 0 {
		return nil, nil
	}
	best := matching[0].rank
	for _, m := range matching {
		if m.rank < best {
			best = m.rank
		}
	}
	var winners []string
	for _, m := range matching {
		if m.rank == best {
			winners = append(winners, m.id)
		}
	}
	if len(winners) == 1 {
		return &winners[0], nil
	}
	return nil, winners
}

func containsString(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// ResolveSprint returns the tool's sprint id for a sprint name of the tracker: the name itself
// when it is a known id (recorded, in the forecast or in the calendar ahead), else
// tracker.sprint_names, else the one known id with a separator (2026.20) the name contains as a
// word, else nil (the raw name stays on the ticket). A name mapped to model.CarryBacklog counts
// as resolved: its tickets are backlog (Convert leaves InSprint empty), without a warning.
func ResolveSprint(name string, tracker model.TrackerSettings, sprints Sprints) *string {
	if name == "" {
		return nil
	}
	if _, ok := sprints.End(name); ok {
		return &name
	}
	if id, ok := tracker.SprintNames.Get(name); ok {
		return &id
	}
	if id := sprintWord(name, sprints); id != nil {
		return id
	}
	if id := sprintByNumber(name, sprints); id != nil {
		return id
	}
	return sprintAfterWord(name, sprints)
}

// ResolveSprintExact is ResolveSprint without the guesses by number: the name itself when it is a
// known id, tracker.sprint_names, or the one yearly id (2026.20) the name contains as a word.
// For sprints of a board that other teams may share: "Other Team Sprint 3" is nobody's sprint 3.
func ResolveSprintExact(name string, tracker model.TrackerSettings, sprints Sprints) *string {
	if name == "" {
		return nil
	}
	if _, ok := sprints.End(name); ok {
		return &name
	}
	if id, ok := tracker.SprintNames.Get(name); ok {
		return &id
	}
	return sprintWord(name, sprints)
}

var sprintNumber = regexp.MustCompile(`(?i)\bsprint\s+(\d+)\b([._-]\d)?`)

// sprintAfterWord finds a bare number after the word "Sprint" ("Team Sprint 17") when it is a
// known id; any other bare number may be anything ("Release 45").
func sprintAfterWord(name string, sprints Sprints) *string {
	m := sprintNumber.FindAllStringSubmatch(name, -1)
	if len(m) != 1 || m[0][2] != "" { // "Sprint 17.1" is not sprint 17
		return nil
	}
	if _, ok := sprints.End(m[0][1]); !ok {
		return nil
	}
	id := m[0][1]
	return &id
}

// sprintByNumber finds the one known id that contains a yearly number of the name (2026.20) as a
// word, for ids with a prefix. More than one such id is ambiguous and gives nil.
func sprintByNumber(name string, sprints Sprints) *string {
	lister, ok := sprints.(Lister)
	if !ok {
		return nil
	}
	var found *string
	for _, w := range sprintWords.FindAllString(name, -1) {
		if !strings.ContainsAny(w, "._-") || !strings.ContainsAny(w, "0123456789") {
			continue
		}
		for _, id := range lister.IDs() {
			if id == w || !slices.Contains(sprintWords.FindAllString(id, -1), w) {
				continue
			}
			if found != nil && *found != id {
				return nil
			}
			id := id
			found = &id
		}
	}
	return found
}

var sprintWords = regexp.MustCompile(`[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*`)

// sprintWord finds a sprint id inside a longer tracker name ("Team Sprint 2026.20"): the one
// word of the name that is a known id. More than one such word is ambiguous and gives nil.
func sprintWord(name string, sprints Sprints) *string {
	var found *string
	for _, w := range sprintWords.FindAllString(name, -1) {
		if _, ok := sprints.End(w); !ok || !strings.ContainsAny(w, "._-") {
			continue // a bare number may be anything ("Release 45"): only yearly ids count
		}
		if found != nil && *found != w {
			return nil
		}
		w := w
		found = &w
	}
	return found
}

func ptrOrNil(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func copyFloat(f *float64) *float64 {
	if f == nil {
		return nil
	}
	v := *f
	return &v
}

func cloneStrings(s []string) []string {
	return append([]string{}, s...)
}

// Reresolve resolves the sprint names of stored tickets again (the sprint table of the tracker
// settings changed) and returns the tickets with the new sprints and the preplan without the
// earmarks the real sprint of a ticket now overrules (as an import does), and whether any
// changed.
func Reresolve(tickets []model.Ticket, preplan model.Preplan, env Env) ([]model.Ticket, model.Preplan, bool) {
	out := slices.Clone(tickets)
	preplan.Earmarks = slices.Clone(preplan.Earmarks)
	changed := false
	for i, tk := range out {
		if tk.SprintName == nil || *tk.SprintName == "" {
			continue
		}
		in := ResolveSprint(*tk.SprintName, env.Tracker, env.Sprints)
		if in != nil && (*in == model.CarryBacklog || sprintEnded(*in, env)) {
			in = nil
		}
		if str := func(p *string) string {
			if p == nil {
				return ""
			}
			return *p
		}; str(in) != str(tk.InSprint) {
			out[i].InSprint = in
			changed = true
		}
		if in != nil && sprintOpen(*in, env) {
			if e := preplan.EarmarkFor(tk.Key); e != nil && e.Sprint != *in {
				removeEarmark(&preplan, tk.Key)
				changed = true
			}
		}
	}
	return out, preplan, changed
}

// Convert returns a raw ticket as the tool stores it: sprint resolved, refined state and project
// derived.
//
// Jira keeps closed sprints in the Sprint field of an open ticket (carried over): such a sprint
// is resolved but does not count as the ticket's sprint (InSprint stays nil, SprintName keeps
// the name for display).
func Convert(raw sources.RawTicket, env Env) model.Ticket {
	tracker := env.Tracker
	inSprint := ResolveSprint(raw.SprintName, tracker, env.Sprints)
	if inSprint != nil && (*inSprint == model.CarryBacklog || sprintEnded(*inSprint, env)) {
		inSprint = nil
	}
	ticket := model.Ticket{
		Key:        raw.Key,
		Title:      raw.Title,
		Status:     ptrOrNil(raw.Status),
		IssueType:  ptrOrNil(raw.IssueType),
		Priority:   ptrOrNil(raw.Priority),
		Estimate:   copyFloat(raw.Estimate),
		Remaining:  copyFloat(raw.Remaining),
		InSprint:   inSprint,
		SprintName: ptrOrNil(raw.SprintName),
		Rank:       ptrOrNil(raw.Rank),
		Epic:       ptrOrNil(raw.Epic),
		Labels:     cloneStrings(raw.Labels),
		Components: cloneStrings(raw.Components),
		DependsOn:  cloneStrings(raw.BlockedBy),
		Done:       raw.Resolved,
	}
	for _, name := range tracker.RuleFields.Keys() {
		if values, ok := raw.Extra[name]; ok {
			ticket.Extra.Set(name, cloneStrings(values))
		}
	}
	for _, m := range mappedFields(tracker) {
		if values, ok := raw.Extra[m.Name]; ok {
			ticket.Extra.Set(m.Name, cloneStrings(values))
		}
	}
	facts := ticket.Facts()
	// The size the distribution calculates with (remaining if filled, else the estimate).
	size := ticket.Size(tracker.PlanningUses)
	refined, unclear := IsRefined(facts, size, tracker)
	ticket.RefinedUnclear = unclear
	switch {
	case size == nil:
		ticket.EstimateSource = model.EstimateNone
	case refined && !unclear:
		ticket.EstimateSource = model.EstimateRefined
	default:
		ticket.EstimateSource = model.EstimateRough
	}
	ticket.Project, ticket.ProjectCandidates = AssignProject(facts, env.Projects, tracker.ProjectMatchOrder)
	if ticket.ProjectCandidates == nil {
		ticket.ProjectCandidates = []string{}
	}
	applyMappedAssignment(&ticket, env)
	return ticket
}

// KnownEpics returns the epics some project rule refers to (lower-cased: rules ignore case).
func KnownEpics(projects []model.Project) map[string]bool {
	found := map[string]bool{}
	for _, p := range projects {
		if p.Match == nil {
			continue
		}
		for _, leaf := range p.Match.Leaves() {
			if leaf.Source == "epic" && !leaf.Contains {
				for _, v := range leaf.Values {
					found[strings.ToLower(v)] = true
				}
			}
		}
	}
	return found
}

// sprintEnded says whether the sprint is known and already over (its end is not after today).
func sprintEnded(id string, env Env) bool {
	end, ok := env.Sprints.End(id)
	return ok && !end.After(env.Today)
}

// sprintOpen says whether the sprint is known and current or in the future (its end after today).
func sprintOpen(id string, env Env) bool {
	end, ok := env.Sprints.End(id)
	return ok && end.After(env.Today)
}

// --- Preview -----------------------------------------------------------------------------

func note(s string) *string { return &s }

func clonePreplan(p model.Preplan) model.Preplan {
	// Everything beside earmarks and estimates is the PO's own and must survive a fetch.
	out := model.Preplan{
		Production: slices.Clone(p.Production), Overrides: slices.Clone(p.Overrides),
		ProForma: slices.Clone(p.ProForma), Order: slices.Clone(p.Order),
	}
	for _, e := range p.Earmarks {
		c := e
		c.Note = cloneStringPtr(e.Note)
		out.Earmarks = append(out.Earmarks, c)
	}
	for _, e := range p.Estimates {
		c := e
		c.Estimate = copyFloat(e.Estimate)
		c.Note = cloneStringPtr(e.Note)
		out.Estimates = append(out.Estimates, c)
	}
	return out
}

func cloneStringPtr(s *string) *string {
	if s == nil {
		return nil
	}
	v := *s
	return &v
}

// removeEarmark drops the earmark of the ticket from the preplan.
func removeEarmark(p *model.Preplan, ticket string) {
	for i, e := range p.Earmarks {
		if e.Ticket == ticket {
			p.Earmarks = append(p.Earmarks[:i:i], p.Earmarks[i+1:]...)
			return
		}
	}
}

// splitSubtasks takes the sub-tasks out of the raw tickets unless the tracker settings keep
// them, and counts them per parent (a parent that is not part of the fetch counts nothing).
func splitSubtasks(raws []sources.RawTicket, tracker model.TrackerSettings) ([]sources.RawTicket, map[string]int) {
	counts := map[string]int{}
	if tracker.IncludeSubtasks {
		return raws, counts
	}
	kept := make([]sources.RawTicket, 0, len(raws))
	for _, r := range raws {
		if r.Subtask {
			if r.Parent != "" {
				counts[r.Parent]++
			}
			continue
		}
		kept = append(kept, r)
	}
	return kept, counts
}

// PlanImport converts the raw tickets and reconciles them with the last import and the earmarks
// (spec section 6.5); nothing is written. With adoptLabels false the planned_for_* labels stay
// unread (the label write-back plans against the earmarks of the tool only).
func PlanImport(env Env, raws []sources.RawTicket, source *string, adoptLabels bool) Plan {
	old := map[string]model.Ticket{}
	var oldOrder []string
	for _, tk := range env.Tickets {
		if _, seen := old[tk.Key]; !seen {
			oldOrder = append(oldOrder, tk.Key)
		}
		old[tk.Key] = tk
	}
	preplan := clonePreplan(env.Preplan)
	if !env.KeepOrder {
		preplan.Order = nil // a fetch takes over the order of the tracker again
	}
	plan := Plan{Source: source}
	epicsKnown := KnownEpics(env.Projects)
	unknown := map[string][]string{}
	var unknownOrder []string

	seen := map[string]model.Ticket{}
	var order []string
	raws, subtasks := splitSubtasks(raws, env.Tracker)
	for _, raw := range raws {
		if _, dup := seen[raw.Key]; dup {
			plan.Warnings = append(plan.Warnings,
				sources.T("Ticket {key} occurs more than once; the last entry counts", "key", raw.Key))
		} else {
			order = append(order, raw.Key)
		}
		seen[raw.Key] = Convert(raw, env)
	}
	plan.Tickets = make([]model.Ticket, len(order))
	for i, key := range order {
		plan.Tickets[i] = seen[key]
		plan.Tickets[i].SubtaskCount = subtasks[key]
	}

	add := func(c Change) { plan.Changes = append(plan.Changes, c) }
	for _, tk := range plan.Tickets {
		prev, hadPrev := old[tk.Key]
		if !hadPrev && !tk.Done {
			add(Change{Kind: KindNew, Key: tk.Key, Title: tk.Title})
		}
		if hadPrev {
			if !floatPtrEqual(prev.Estimate, tk.Estimate) {
				add(Change{KindChanged, tk.Key, tk.Title, floatOrNil(prev.Estimate), floatOrNil(tk.Estimate), note("estimate")})
			}
			if !floatPtrEqual(prev.Remaining, tk.Remaining) {
				add(Change{KindChanged, tk.Key, tk.Title, floatOrNil(prev.Remaining), floatOrNil(tk.Remaining), note("remaining")})
			}
		}
		earmark := preplan.EarmarkFor(tk.Key)
		if tk.Done {
			if !hadPrev || !prev.Done {
				add(Change{Kind: KindDone, Key: tk.Key, Title: tk.Title})
			}
			if earmark != nil {
				sprint := earmark.Sprint
				removeEarmark(&preplan, tk.Key)
				add(Change{Kind: KindEarmarkDropped, Key: tk.Key, Title: tk.Title, Old: sprint})
			}
			continue
		}
		if earmark != nil && sprintEnded(earmark.Sprint, env) {
			sprint := earmark.Sprint
			removeEarmark(&preplan, tk.Key)
			add(Change{Kind: KindEarmarkDropped, Key: tk.Key, Title: tk.Title, Old: sprint, Note: note(DroppedEnded)})
			earmark = nil
		}
		switch {
		case tk.InSprint == nil:
			// A closed sprint is resolved but not the ticket's sprint; only names the tool
			// cannot resolve are reported.
			if tk.SprintName != nil && *tk.SprintName != "" && ResolveSprint(*tk.SprintName, env.Tracker, env.Sprints) == nil {
				add(Change{Kind: KindSprintUnresolved, Key: tk.Key, Title: tk.Title, Note: tk.SprintName})
			}
		case earmark != nil && earmark.Sprint != *tk.InSprint && sprintOpen(*tk.InSprint, env):
			// The real sprint of the tracker wins over the earmark of the tool.
			sprint := earmark.Sprint
			removeEarmark(&preplan, tk.Key)
			add(Change{Kind: KindEarmarkDropped, Key: tk.Key, Title: tk.Title, Old: sprint, New: *tk.InSprint})
			earmark = nil
		}
		if adoptLabels && env.Tracker.WriteLabels && tk.InSprint == nil && earmark == nil {
			var known []string
			if hadPrev {
				known = prev.Labels
			}
			earmarkFromLabel(&plan, &preplan, tk, env, known)
		}
		if tk.Project == nil {
			add(Change{Kind: KindUnassigned, Key: tk.Key, Title: tk.Title, New: cloneStrings(tk.ProjectCandidates)})
		}
		if tk.Epic != nil && *tk.Epic != "" && !epicsKnown[strings.ToLower(*tk.Epic)] {
			if _, ok := unknown[*tk.Epic]; !ok {
				unknownOrder = append(unknownOrder, *tk.Epic)
			}
			unknown[*tk.Epic] = append(unknown[*tk.Epic], tk.Key)
		}
		if tk.RefinedUnclear {
			// With the label the only way to be unclear is a missing size; without it the
			// ticket counts as refined only via refined_also_if.
			why := UnclearRule
			if label := env.Tracker.RefinedLabel; label != nil && *label != "" && containsString(tk.Labels, *label) {
				why = UnclearNoEstimate
			}
			add(Change{Kind: KindRefinedUnclear, Key: tk.Key, Title: tk.Title, Note: note(why)})
		}
	}

	for _, epic := range unknownOrder {
		add(Change{Kind: KindUnknownEpic, Key: epic, New: unknown[epic]})
	}

	for _, key := range oldOrder {
		if _, ok := seen[key]; ok {
			continue
		}
		prev := old[key]
		earmark := preplan.EarmarkFor(key)
		if earmark != nil && sprintEnded(earmark.Sprint, env) {
			sprint := earmark.Sprint
			removeEarmark(&preplan, key)
			add(Change{Kind: KindEarmarkDropped, Key: key, Title: prev.Title, Old: sprint, Note: note(DroppedEnded)})
			earmark = nil
		}
		var missingNote *string
		if earmark != nil {
			missingNote = note(earmark.Sprint)
		}
		add(Change{Kind: KindMissing, Key: key, Title: prev.Title, Note: missingNote})
		switch {
		case earmark != nil:
			plan.Warnings = append(plan.Warnings, sources.T(
				"Ticket {key} is no longer in the import; the earmark for sprint {sprint} stays",
				"key", key, "sprint", earmark.Sprint))
		case preplan.EstimateFor(key) != nil:
			plan.Warnings = append(plan.Warnings, sources.T(
				"Ticket {key} is no longer in the import; the own estimate stays", "key", key))
		}
	}

	// Earmarks of tickets that left an earlier import: nothing else drops them, so they go once
	// their sprint is over.
	for _, earmark := range append([]model.Earmark(nil), preplan.Earmarks...) {
		_, inNew := seen[earmark.Ticket]
		_, inOld := old[earmark.Ticket]
		if inNew || inOld {
			continue
		}
		if sprintEnded(earmark.Sprint, env) {
			removeEarmark(&preplan, earmark.Ticket)
			add(Change{Kind: KindEarmarkDropped, Key: earmark.Ticket, Old: earmark.Sprint, Note: note(DroppedEnded)})
		}
	}

	for _, cycle := range FindCycles(plan.Tickets) {
		plan.Warnings = append(plan.Warnings, sources.T("Circular dependencies: {cycle}",
			"cycle", strings.Join(append(append([]string{}, cycle...), cycle[0]), " → ")))
	}
	sortChanges(plan.Changes)
	plan.Preplan = preplan
	plan.PreplanChanged = !preplanEqual(preplan, env.Preplan)
	return plan
}

func sortChanges(changes []Change) {
	rank := map[string]int{}
	for i, k := range Kinds {
		rank[k] = i
	}
	sort.SliceStable(changes, func(i, j int) bool { return rank[changes[i].Kind] < rank[changes[j].Kind] })
}

func floatOrNil(f *float64) any {
	if f == nil {
		return nil
	}
	return *f
}

// earmarkFromLabel takes the earmark of a ticket without sprint and earmark from its
// planned_for_* label (spec section 6.6, the weakest source). A label of a sprint that is
// unknown or over, or several labels, are reported; the next label write removes them. A label
// the last import already knew is no news: without an earmark it was released in the tool.
func earmarkFromLabel(plan *Plan, preplan *model.Preplan, tk model.Ticket, env Env, known []string) {
	knownSprints := sources.LabelSprints(known)
	var sprints []string
	for _, s := range sources.LabelSprints(tk.Labels) {
		if !containsString(knownSprints, s) {
			sprints = append(sprints, s)
		}
	}
	if len(sprints) == 0 {
		return
	}
	sprint := sprints[0]
	if len(sprints) == 1 && sprintOpen(sprint, env) {
		preplan.Earmarks = append(preplan.Earmarks, model.Earmark{Ticket: tk.Key, Sprint: sprint})
		plan.Changes = append(plan.Changes, Change{Kind: KindEarmarkLabel, Key: tk.Key, Title: tk.Title, New: sprint})
		return
	}
	labels := make([]string, len(sprints))
	for i, s := range sprints {
		labels[i] = sources.PlannedLabel(s)
	}
	plan.Warnings = append(plan.Warnings, sources.T(
		"Ticket {key}: the label {labels} does not point to exactly one future sprint and is not taken as an earmark",
		"key", tk.Key, "labels", strings.Join(labels, ", ")))
}

// FindCycles returns the cycles in DependsOn (keys in dependency order), each reported once.
// Dependencies on keys outside the list are ignored.
func FindCycles(tickets []model.Ticket) [][]string {
	graph := map[string][]string{}
	var keys []string
	for _, tk := range tickets {
		if _, ok := graph[tk.Key]; !ok {
			keys = append(keys, tk.Key)
		}
		graph[tk.Key] = nil
	}
	for _, tk := range tickets {
		var deps []string
		for _, d := range tk.DependsOn {
			if _, ok := graph[d]; ok {
				deps = append(deps, d)
			}
		}
		graph[tk.Key] = deps
	}
	state := map[string]int{} // 1 = on the current path, 2 = finished
	seen := map[string]bool{}
	var cycles [][]string
	type frame struct {
		key  string
		next int
	}
	for _, start := range keys {
		if state[start] != 0 {
			continue
		}
		state[start] = 1
		path := []string{start}
		stack := []frame{{start, 0}}
		for len(stack) > 0 {
			top := &stack[len(stack)-1]
			deps := graph[top.key]
			advanced := false
			for top.next < len(deps) {
				nxt := deps[top.next]
				top.next++
				switch state[nxt] {
				case 1: // back edge: the path from nxt onwards is a cycle
					at := indexOf(path, nxt)
					cycle := path[at:]
					first := 0
					for i, k := range cycle {
						if k < cycle[first] {
							first = i
						}
					}
					canon := append(append([]string{}, cycle[first:]...), cycle[:first]...)
					if id := strings.Join(canon, "\x00"); !seen[id] {
						seen[id] = true
						cycles = append(cycles, canon)
					}
				case 0:
					state[nxt] = 1
					path = append(path, nxt)
					stack = append(stack, frame{nxt, 0})
					advanced = true
				}
				if advanced {
					break
				}
			}
			if !advanced {
				state[path[len(path)-1]] = 2
				path = path[:len(path)-1]
				stack = stack[:len(stack)-1]
			}
		}
	}
	return cycles
}

func indexOf(list []string, s string) int {
	for i, v := range list {
		if v == s {
			return i
		}
	}
	return -1
}
