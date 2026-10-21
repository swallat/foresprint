package preplan

import (
	"fmt"
	"math"
	"slices"
	"sort"
	"time"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/coretypes"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

const day = 24 * time.Hour

// lastDay is the last day of a sprint (its end is exclusive); nil for an unknown sprint.
func lastDay(s *coretypes.Sprint) *time.Time {
	if s == nil {
		return nil
	}
	d := s.End.Add(-day)
	return &d
}

// laterPosition is the position in the timeline of a sprint after the horizon (size = length of
// the timeline = the target sprint when the target lies beyond the horizon): later than the
// target unless the sprint is known and ends by the target date.
func laterPosition(last, target *time.Time, size, lengthDays int) int {
	if last == nil || target == nil || last.After(*target) {
		return size + 1
	}
	// The target sprint is the last one ending on or before the target date.
	if target.Before(last.Add(time.Duration(lengthDays) * day)) {
		return size
	}
	return size - 1
}

// TargetSprint is the index of the last sprint of the timeline whose last day lies on or before
// target (the sprint end is exclusive); ok is false without target date or when no sprint ends by
// then. The timeline is the current sprint (when given) followed by the horizon sprints. A target
// inside the current sprint (and not yet over) is the current sprint itself. len(timeline) = the
// target sprint lies beyond the horizon.
func TargetSprint(target *time.Time, sprints []coretypes.Sprint, lengthDays int, current *coretypes.Sprint, today *time.Time) (int, bool) {
	timeline := timelineOf(sprints, current)
	if len(timeline) == 0 || target == nil {
		return 0, false
	}
	if current != nil && !current.Start.After(*target) && target.Before(current.End.Add(-day)) &&
		(today == nil || !target.Before(*today)) {
		return 0, true
	}
	if !timeline[len(timeline)-1].End.Add(time.Duration(lengthDays-1) * day).After(*target) {
		return len(timeline), true
	}
	last, ok := 0, false
	for i, s := range timeline {
		if !s.End.Add(-day).After(*target) {
			last, ok = i, true
		}
	}
	return last, ok
}

func timelineOf(sprints []coretypes.Sprint, current *coretypes.Sprint) []coretypes.Sprint {
	var timeline []coretypes.Sprint
	if current != nil {
		timeline = append(timeline, *current)
	}
	return append(timeline, sprints...)
}

// TrafficLight is the traffic light of a project from the placements of its tickets (spec
// section 5.3). lengthDays (sprint length of the team) tells whether a target date lies beyond
// the horizon; current is the running sprint: work placed in it counts as on time for a target
// date inside it. Tickets fixed or earmarked after the horizon (dist.Later) are compared with
// the target date by the last day of their sprint (an unknown sprint counts as later than the
// target).
func TrafficLight(project model.Project, dist *Distribution, sprints []coretypes.Sprint, lengthDays int, current *coretypes.Sprint, today *time.Time) ProjectStatus {
	var own []Placement
	for _, p := range dist.Placements {
		if p.Project != nil && *p.Project == project.ID {
			own = append(own, p)
		}
	}
	timeline := timelineOf(sprints, current)
	index := map[string]int{}
	for i, s := range timeline {
		index[s.ID] = i
	}
	target, hasTarget := TargetSprint(project.Target, sprints, lengthDays, current, today)
	var targetID *string
	if hasTarget && target < len(timeline) {
		targetID = strPtr(timeline[target].ID)
	}
	undistributed := 0
	for _, p := range own {
		if !p.Distributable() {
			undistributed++
		}
	}
	last, lastSet := 0, false
	var lastID *string
	for _, p := range own {
		if p.Sprint == nil {
			continue
		}
		// Not in the timeline: a sprint after the horizon (or unknown) or a past one.
		i, in := index[*p.Sprint]
		if !in {
			i = -1
			if l, later := dist.Later[*p.Sprint]; later {
				i = laterPosition(l, project.Target, len(timeline), lengthDays)
			}
		}
		if !lastSet || i > last {
			last, lastSet, lastID = i, true, p.Sprint
		}
	}
	var light string
	switch {
	case len(own) == 0:
		light = LightEmpty
	case undistributed > 0:
		light = LightMissed
	case project.Target == nil:
		light = LightOnTrack
	case !hasTarget:
		light = LightMissed // the target date lies before the first sprint of the timeline
	case !lastSet || last < target:
		light = LightOnTrack
	case last == target:
		light = LightTight
	default:
		light = LightMissed
	}
	return ProjectStatus{
		Project:          project.ID,
		Light:            light,
		TargetSprint:     targetID,
		LastSprint:       lastID,
		OpenTickets:      len(own),
		NotDistributable: undistributed,
	}
}

// refinementList is, per future sprint, the tickets whose estimate is rough or manual; the
// deadline is the planning of the sprint (spec section 5.4).
func refinementList(data *storage.TeamData, dist *Distribution, sprints []coretypes.Sprint) []RefinementItem {
	result := []RefinementItem{}
	for _, s := range sprints {
		for _, p := range dist.InSprint(s.ID) {
			if p.Source != model.EstimateRough && p.Source != model.EstimateManual {
				continue
			}
			unclear := false
			if t := data.TicketByKey(p.Ticket); t != nil {
				unclear = t.RefinedUnclear
			}
			result = append(result, RefinementItem{Ticket: p.Ticket, Sprint: s.ID, Deadline: s.Start, Source: p.Source, Unclear: unclear})
		}
	}
	return result
}

// Variants is the distribution under the three plans. Conservative and Optimistic are nil when
// the range is unavailable (fewer than two sprints with velocity).
type Variants struct {
	Median       *Distribution
	Conservative *Distribution
	Optimistic   *Distribution
	// Samples is the number of sprints with normalized velocity the range is calculated from.
	Samples int
}

// Available reports whether the range can be shown (all three variants exist).
func (v *Variants) Available() bool { return v.Conservative != nil && v.Optimistic != nil }

// Get returns the distribution of a variant, or nil.
func (v *Variants) Get(variant Variant) *Distribution {
	switch variant {
	case Conservative:
		return v.Conservative
	case Median:
		return v.Median
	case Optimistic:
		return v.Optimistic
	}
	return nil
}

// VariantDist is a variant with its distribution.
type VariantDist struct {
	Variant Variant
	Dist    *Distribution
}

// Items are the existing variants from optimistic to conservative.
func (v *Variants) Items() []VariantDist {
	var out []VariantDist
	for _, name := range []Variant{Optimistic, Median, Conservative} {
		if d := v.Get(name); d != nil {
			out = append(out, VariantDist{name, d})
		}
	}
	return out
}

// DistributeVariants is the distribution under the median (Forecast PLAN), conservative (lowest
// normalized velocity, rough estimates inflated by tracker.rough_factor) and optimistic plan.
// With fewer than two sprints with velocity there is no range: only the median is returned.
func DistributeVariants(data *storage.TeamData, today time.Time, maxSprints int) (*Variants, error) {
	core := data.Core()
	fc, err := analysis.HorizonForecast(core, today, maxSprints)
	if err != nil {
		return nil, err
	}
	horizon := analysis.HorizonEntries(fc, maxSprints)
	history := analysis.NormalizedHistory(fc)
	median, err := distribute(data, core, today, fc, horizon, Median, nil)
	if err != nil {
		return nil, err
	}
	v := &Variants{Median: median, Samples: len(history)}
	if len(history) < 2 {
		return v, nil
	}
	if v.Conservative, err = distribute(data, core, today, fc, horizon, Conservative, VariantVelocity(history, Conservative)); err != nil {
		return nil, err
	}
	if v.Optimistic, err = distribute(data, core, today, fc, horizon, Optimistic, VariantVelocity(history, Optimistic)); err != nil {
		return nil, err
	}
	return v, nil
}

// maxOrdinal is date.max.toordinal() of Python.
const maxOrdinal = 3652059

func ordinal(t time.Time) int { return int(t.Unix()/86400) + 719163 }

// SprintKey is the sort key of a sprint within a distribution: before the horizon (current or
// past sprint), the horizon sprints in order, then sprints after the horizon by their last day
// (an unknown sprint last).
func SprintKey(dist *Distribution, sprintID string) [2]int {
	if i := slices.Index(dist.Sprints, sprintID); i >= 0 {
		return [2]int{1, i}
	}
	if last, ok := dist.Later[sprintID]; ok {
		if last == nil {
			return [2]int{2, maxOrdinal}
		}
		return [2]int{2, ordinal(*last)}
	}
	return [2]int{0, 0}
}

func lessKey(a, b [2]int) bool { return a[0] < b[0] || (a[0] == b[0] && a[1] < b[1]) }

func lightRank(light string) int { return slices.Index(LightOrder, light) }

// ProjectRange is the traffic light and last sprint of a project under every variant.
type ProjectRange struct {
	Project string
	// Available is false when only the median exists (too little history).
	Available bool
	// LastSprint and Light per variant; only the variants that exist.
	LastSprint map[Variant]*string
	Light      map[Variant]string
	// Earliest and Latest last sprint over the variants (greedy placement is not monotone across
	// variants, so this is the minimum and maximum, not optimistic and conservative).
	Earliest, Latest *string
	// BestLight and WorstLight over the variants (on_track < tight < missed).
	BestLight, WorstLight string
	// Complete is false when in at least one variant a ticket of the project is not
	// distributable, so Latest is only the last sprint of the tickets that were placed.
	Complete bool
}

// Uniform reports whether all variants have the same traffic light.
func (r ProjectRange) Uniform() bool { return r.BestLight == r.WorstLight }

// OnTrack reports whether the project is on track in every variant.
func (r ProjectRange) OnTrack() bool { return r.WorstLight == LightOnTrack }

// ProjectRangeOf is the range of the project's last sprint and traffic light over the variants.
func ProjectRangeOf(v *Variants, projectID string) (ProjectRange, error) {
	type row struct {
		variant Variant
		dist    *Distribution
		status  *ProjectStatus
	}
	var rows []row
	for _, it := range v.Items() {
		st := it.Dist.Status(projectID)
		if st == nil {
			return ProjectRange{}, fmt.Errorf("unknown project %q", projectID)
		}
		rows = append(rows, row{it.Variant, it.Dist, st})
	}
	r := ProjectRange{
		Project:    projectID,
		Available:  v.Available(),
		LastSprint: map[Variant]*string{},
		Light:      map[Variant]string{},
		Complete:   true,
	}
	type placed struct {
		dist *Distribution
		id   string
	}
	var ps []placed
	for i, rw := range rows {
		r.LastSprint[rw.variant] = rw.status.LastSprint
		r.Light[rw.variant] = rw.status.Light
		if rw.status.LastSprint != nil {
			ps = append(ps, placed{rw.dist, *rw.status.LastSprint})
		}
		if rw.status.NotDistributable != 0 {
			r.Complete = false
		}
		if i == 0 || lightRank(rw.status.Light) < lightRank(r.BestLight) {
			r.BestLight = rw.status.Light
		}
		if i == 0 || lightRank(rw.status.Light) > lightRank(r.WorstLight) {
			r.WorstLight = rw.status.Light
		}
	}
	sort.SliceStable(ps, func(i, j int) bool { return lessKey(SprintKey(ps[i].dist, ps[i].id), SprintKey(ps[j].dist, ps[j].id)) })
	if len(ps) > 0 {
		r.Earliest, r.Latest = strPtr(ps[0].id), strPtr(ps[len(ps)-1].id)
	}
	return r, nil
}

// TicketRange is the sprint of one ticket under every variant.
type TicketRange struct {
	Ticket string
	// Sprints per variant; nil = not placed in that variant.
	Sprints map[Variant]*string
	// Earliest and Latest sprint over the variants that placed the ticket.
	Earliest, Latest *string
	// Complete is false when at least one variant did not place the ticket.
	Complete bool
}

// Fixed reports whether the ticket is in the same sprint in every variant.
func (r TicketRange) Fixed() bool { return r.Complete && samePtr(r.Earliest, r.Latest) }

// TicketRangeOf is the earliest and latest sprint of a ticket over the variants; nil for a
// ticket the distribution does not know (done or unknown).
func TicketRangeOf(v *Variants, key string) *TicketRange {
	if v.Median.Placement(key) == nil {
		return nil
	}
	r := &TicketRange{Ticket: key, Sprints: map[Variant]*string{}, Complete: true}
	type placed struct {
		dist *Distribution
		id   string
	}
	var ps []placed
	for _, it := range v.Items() {
		var sp *string
		if p := it.Dist.Placement(key); p != nil {
			sp = p.Sprint
		}
		r.Sprints[it.Variant] = sp
		if sp == nil {
			r.Complete = false
		} else {
			ps = append(ps, placed{it.Dist, *sp})
		}
	}
	sort.SliceStable(ps, func(i, j int) bool { return lessKey(SprintKey(ps[i].dist, ps[i].id), SprintKey(ps[j].dist, ps[j].id)) })
	if len(ps) > 0 {
		r.Earliest, r.Latest = strPtr(ps[0].id), strPtr(ps[len(ps)-1].id)
	}
	return r
}

// Handover actions.
const (
	ActionWrite     = "write"
	ActionSame      = "same"
	ActionOverwrite = "overwrite"
	ActionKeep      = "keep"
)

// HandoverRow is what the distribution proposes as preplanned for one sprint and product.
type HandoverRow struct {
	Sprint  string
	Product string
	// Proposed is the sum of the sizes of the tickets in the sprint, rounded to the team's
	// precision.
	Proposed float64
	// Current is the value the PO pre-planning holds today; nil = nothing entered (or no sprint
	// file).
	Current *float64
}

// Action says write (nothing entered yet), same (already equal), overwrite (a different value
// entered and overwrite) or keep (a different value entered: stays).
func (r HandoverRow) Action(overwrite bool) string {
	switch {
	case r.Current == nil:
		return ActionWrite
	case math.Abs(*r.Current-r.Proposed) < 1e-9:
		return ActionSame
	case overwrite:
		return ActionOverwrite
	}
	return ActionKeep
}

// Writes reports whether the row changes the PO pre-planning.
func (r HandoverRow) Writes(overwrite bool) bool {
	a := r.Action(overwrite)
	return a == ActionWrite || a == ActionOverwrite
}

// HandoverRows is, per future sprint (the first sprintCount of the horizon) and product, the sum
// of the sizes of the tickets placed there (distributed, earmarked and fixed by the tracker), as
// the distribution used them. Tickets without a known product are left out; sums that round to
// nothing are left out. Pure: nothing is written.
func HandoverRows(data *storage.TeamData, dist *Distribution, sprintCount int) []HandoverRow {
	known := map[string]int{}
	for i, p := range data.Products {
		known[p.ID] = i
	}
	shown := dist.Sprints
	if len(shown) > sprintCount {
		shown = shown[:sprintCount]
	}
	type cell struct{ sprint, product string }
	sums := map[cell]float64{}
	var cells []cell
	for _, p := range dist.Placements {
		if !placedReason(p.Reason) || p.Sprint == nil || !slices.Contains(shown, *p.Sprint) || p.Size == nil {
			continue
		}
		if p.Product == nil {
			continue
		}
		if _, ok := known[*p.Product]; !ok {
			continue
		}
		c := cell{*p.Sprint, *p.Product}
		if _, seen := sums[c]; !seen {
			cells = append(cells, c)
		}
		sums[c] += *p.Size
	}
	sort.SliceStable(cells, func(i, j int) bool {
		a, b := cells[i], cells[j]
		ai, bi := slices.Index(shown, a.sprint), slices.Index(shown, b.sprint)
		if ai != bi {
			return ai < bi
		}
		return known[a.product] < known[b.product]
	})
	digits := data.Team.Forecast.Rounding
	var rows []HandoverRow
	for _, c := range cells {
		proposed := engine.RoundHalfUp(sums[c], digits)
		if proposed <= 0 {
			continue
		}
		var current *float64
		if s := data.SprintByID(c.sprint); s != nil {
			if v, ok := s.Products[c.product]; ok {
				current = v.Preplanned
			}
		}
		rows = append(rows, HandoverRow{c.sprint, c.product, proposed, current})
	}
	return rows
}
