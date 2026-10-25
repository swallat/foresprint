package ticketimport

import (
	"encoding/json"
	"errors"
	"sort"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

// The comparison with golden/expected/ticketimport, frozen from version 0.8
// from the Python implementation.

// --- JSON to model ---

type obj = map[string]any

func jstr(v any) *string {
	s, ok := v.(string)
	if !ok {
		return nil
	}
	return &s
}

func jstrs(v any) []string {
	list, _ := v.([]any)
	out := make([]string, 0, len(list))
	for _, x := range list {
		s, _ := x.(string)
		out = append(out, s)
	}
	return out
}

func jfloat(v any) *float64 {
	n, ok := v.(json.Number)
	if !ok {
		return nil
	}
	f, err := n.Float64()
	if err != nil {
		return nil
	}
	return &f
}

func jint(v any) int {
	n, _ := v.(json.Number)
	i, _ := n.Int64()
	return int(i)
}

func jbool(v any) bool { b, _ := v.(bool); return b }

func jdate(v any) time.Time {
	t, err := time.Parse("2006-01-02", v.(string))
	if err != nil {
		panic(err)
	}
	return t
}

func ordered[V any](m obj, conv func(any) V) model.OrderedMap[V] {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var out model.OrderedMap[V]
	for _, k := range keys {
		out.Set(k, conv(m[k]))
	}
	return out
}

func ruleFrom(v any) *model.Rule {
	m, ok := v.(obj)
	if !ok {
		return nil
	}
	r := &model.Rule{Op: m["op"].(string), Values: jstrs(m["values"]), Short: jbool(m["short"]), Contains: jbool(m["contains"])}
	if s := jstr(m["source"]); s != nil {
		r.Source = *s
	}
	for _, c := range m["children"].([]any) {
		r.Children = append(r.Children, ruleFrom(c))
	}
	return r
}

func trackerFrom(m obj) model.TrackerSettings {
	t := model.NewTrackerSettings()
	t.Kind = m["kind"].(string)
	f := m["fields"].(obj)
	t.Fields = model.TrackerFields{Estimate: jstr(f["estimate"]), Remaining: jstr(f["remaining"]), Epic: jstr(f["epic"])}
	t.PlanningUses = model.PlanningUses(m["planning_uses"].(string))
	t.RefinedLabel = jstr(m["refined_label"])
	t.RefinedAlsoIf = ruleFrom(m["refined_also_if"])
	t.ProjectMatchOrder = jstrs(m["project_match_order"])
	t.WriteLabels = jbool(m["write_labels"])
	t.SprintNames = ordered(m["sprint_names"].(obj), func(v any) string { return v.(string) })
	t.RuleFields = ordered(m["rule_fields"].(obj), func(v any) string { return v.(string) })
	return t
}

func projectsFrom(v any) []model.Project {
	var out []model.Project
	for _, x := range v.([]any) {
		m := x.(obj)
		out = append(out, model.Project{ID: m["id"].(string), Name: m["name"].(string), Match: ruleFrom(m["match"])})
	}
	return out
}

func ticketFrom(m obj) model.Ticket {
	return model.Ticket{
		Key: m["key"].(string), Title: m["title"].(string), Status: jstr(m["status"]),
		IssueType: jstr(m["issue_type"]), Priority: jstr(m["priority"]),
		Extra:    ordered(m["extra"].(obj), jstrs),
		Estimate: jfloat(m["estimate"]), Remaining: jfloat(m["remaining"]),
		EstimateSource: model.EstimateSource(m["estimate_source"].(string)),
		RefinedUnclear: jbool(m["refined_unclear"]), InSprint: jstr(m["in_sprint"]),
		SprintName: jstr(m["sprint_name"]), Rank: jstr(m["rank"]), Epic: jstr(m["epic"]),
		Labels: jstrs(m["labels"]), Components: jstrs(m["components"]), DependsOn: jstrs(m["depends_on"]),
		Project: jstr(m["project"]), ProjectCandidates: jstrs(m["project_candidates"]), Done: jbool(m["done"]),
	}
}

func ticketsFrom(v any) []model.Ticket {
	out := []model.Ticket{}
	for _, x := range v.([]any) {
		out = append(out, ticketFrom(x.(obj)))
	}
	return out
}

func preplanFrom(m obj) model.Preplan {
	var p model.Preplan
	for _, x := range m["earmarks"].([]any) {
		e := x.(obj)
		p.Earmarks = append(p.Earmarks, model.Earmark{Ticket: e["ticket"].(string), Sprint: e["sprint"].(string), Note: jstr(e["note"])})
	}
	for _, x := range m["estimates"].([]any) {
		e := x.(obj)
		p.Estimates = append(p.Estimates, model.ManualEstimate{Ticket: e["ticket"].(string), Estimate: jfloat(e["estimate"]), Note: jstr(e["note"])})
	}
	return p
}

func rawFrom(m obj) sources.RawTicket {
	val := func(k string) string { s, _ := m[k].(string); return s }
	extra := map[string][]string{}
	for k, v := range m["extra"].(obj) {
		extra[k] = jstrs(v)
	}
	return sources.RawTicket{
		Key: val("key"), Title: val("title"), Status: val("status"), IssueType: val("issue_type"),
		Priority: val("priority"), Extra: extra, Estimate: jfloat(m["estimate"]), Remaining: jfloat(m["remaining"]),
		SprintName: val("sprint_name"), Rank: val("rank"), Epic: val("epic"),
		Labels: jstrs(m["labels"]), Components: jstrs(m["components"]), BlockedBy: jstrs(m["blocked_by"]),
		Resolved: jbool(m["resolved"]),
	}
}

// --- model to JSON ---

func ptr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func ticketJSON(t model.Ticket) obj {
	extra := obj{}
	for _, e := range t.Extra.Entries {
		extra[e.Key] = e.Value
	}
	return obj{
		"key": t.Key, "title": t.Title, "status": ptr(t.Status), "issue_type": ptr(t.IssueType),
		"priority": ptr(t.Priority), "extra": extra, "estimate": t.Estimate, "remaining": t.Remaining,
		"estimate_source": string(t.EstimateSource), "refined_unclear": t.RefinedUnclear,
		"in_sprint": ptr(t.InSprint), "sprint_name": ptr(t.SprintName), "rank": ptr(t.Rank),
		"epic": ptr(t.Epic), "labels": nn(t.Labels), "components": nn(t.Components),
		"depends_on": nn(t.DependsOn), "project": ptr(t.Project),
		"project_candidates": nn(t.ProjectCandidates), "done": t.Done,
	}
}

func nn(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

func preplanJSON(p model.Preplan) obj {
	earmarks := []any{}
	for _, e := range p.Earmarks {
		earmarks = append(earmarks, obj{"ticket": e.Ticket, "sprint": e.Sprint, "note": ptr(e.Note)})
	}
	estimates := []any{}
	for _, e := range p.Estimates {
		estimates = append(estimates, obj{"ticket": e.Ticket, "estimate": e.Estimate, "note": ptr(e.Note)})
	}
	return obj{"earmarks": earmarks, "estimates": estimates}
}

func planJSON(p Plan, stored []model.Ticket, storedSource *string) obj {
	tickets := []any{}
	for _, t := range p.Tickets {
		tickets = append(tickets, ticketJSON(t))
	}
	changes := []any{}
	for _, c := range p.Changes {
		changes = append(changes, obj{"kind": c.Kind, "key": c.Key, "title": c.Title, "old": c.Old, "new": c.New, "note": ptr(c.Note)})
	}
	warnings := p.Warnings
	if warnings == nil {
		warnings = []string{}
	}
	return obj{
		"tickets": tickets, "preplan": preplanJSON(p.Preplan), "preplan_changed": p.PreplanChanged,
		"changes": changes, "warnings": warnings, "source": ptr(p.Source),
		"unchanged": p.Unchanged(stored, storedSource),
	}
}

// tableSprints stands in for the forecast: the ids the Python calendar knew, with their end.
type tableSprints map[string]time.Time

func (t tableSprints) End(id string) (time.Time, bool) { e, ok := t[id]; return e, ok }

func sprintsFrom(v any) tableSprints {
	out := tableSprints{}
	for id, end := range v.(obj) {
		out[id] = jdate(end)
	}
	return out
}

// --- Tests ---

func TestImportGolden(t *testing.T) {
	var names []string
	golden.Load(t, &names, "ticketimport", "import", "index.json")
	if len(names) < 10 {
		t.Fatalf("only %d import scenarios", len(names))
	}
	for _, name := range names {
		t.Run(name, func(t *testing.T) {
			var want obj
			golden.Load(t, &want, "ticketimport", "import", name+".json")
			env := Env{
				Tracker:  trackerFrom(want["tracker"].(obj)),
				Projects: projectsFrom(want["projects"]),
				Tickets:  ticketsFrom(want["tickets"]),
				Preplan:  preplanFrom(want["preplan"].(obj)),
				Sprints:  sprintsFrom(want["sprints"]),
				Today:    jdate(want["today"]),
			}
			var raws []sources.RawTicket
			for _, r := range want["raws"].([]any) {
				raws = append(raws, rawFrom(r.(obj)))
			}
			storedSource := jstr(want["tickets_source"])
			plan := PlanImport(env, raws, jstr(want["source"]), jbool(want["adopt_labels"]))
			golden.Compare(t, want["plan"], planJSON(plan, env.Tickets, storedSource))
		})
	}
}

func TestFunctionsGolden(t *testing.T) {
	var want obj
	golden.Load(t, &want, "ticketimport", "functions.json")

	trackers := map[string]model.TrackerSettings{}
	for name, v := range want["trackers"].(obj) {
		m := v.(obj)
		tr := model.NewTrackerSettings()
		tr.RefinedLabel = jstr(m["label"])
		tr.RefinedAlsoIf = ruleFrom(m["rule"])
		trackers[name] = tr
	}
	for _, c := range want["is_refined"].([]any) {
		m := c.(obj)
		facts := model.Facts{}
		for k, v := range m["facts"].(obj) {
			facts[k] = jstrs(v)
		}
		refined, unclear := IsRefined(facts, jfloat(m["estimate"]), trackers[m["tracker"].(string)])
		golden.Compare(t, m["ok"], []bool{refined, unclear})
	}

	all := projectsFrom(want["projects"])
	for _, c := range want["assign_project"].([]any) {
		m := c.(obj)
		facts := model.Facts{}
		for k, v := range m["facts"].(obj) {
			facts[k] = jstrs(v)
		}
		subset := all
		switch m["projects"] {
		case "first-two":
			subset = all[:2]
		case "none":
			subset = nil
		}
		project, candidates := AssignProject(facts, subset, jstrs(m["order"]))
		golden.Compare(t, m["ok"], []any{ptr(project), nn(candidates)})
	}

	tr := model.NewTrackerSettings()
	tr.SprintNames = model.NewOrderedMap(
		model.Entry[string]{Key: "Sprint 22", Value: "2026.22"},
		model.Entry[string]{Key: "Sprint 23", Value: "2026.23"},
	)
	sprints := sprintsFrom(want["sprints"])
	for _, c := range want["resolve_sprint"].([]any) {
		m := c.(obj)
		name, _ := m["name"].(string)
		golden.Compare(t, m["ok"], ptr(ResolveSprint(name, tr, sprints)))
	}

	for _, c := range want["find_cycles"].([]any) {
		m := c.(obj)
		var tickets []model.Ticket
		for _, x := range m["tickets"].([]any) {
			pair := x.([]any)
			tickets = append(tickets, model.Ticket{Key: pair[0].(string), DependsOn: jstrs(pair[1])})
		}
		got := FindCycles(tickets)
		if got == nil {
			got = [][]string{}
		}
		golden.Compare(t, m["ok"], got)
	}
}

type recorder struct {
	calls  [][]any
	failAt *int
}

func (r *recorder) SetLabels(key string, add, remove []string) error {
	if r.failAt != nil && len(r.calls) == *r.failAt {
		return &sources.Error{Msg: "Jira refuses the write (403)"}
	}
	r.calls = append(r.calls, []any{key, nn(add), nn(remove)})
	return nil
}

func TestLabelsGolden(t *testing.T) {
	var want []obj
	golden.Load(t, &want, "ticketimport", "labels.json")
	if len(want) < 5 {
		t.Fatal("too few label cases")
	}
	for _, c := range want {
		t.Run(c["name"].(string), func(t *testing.T) {
			tickets := ticketsFrom(c["tickets"])
			plan := PlanLabelWrites(tickets, preplanFrom(c["preplan"].(obj)))
			writes := []any{}
			for _, w := range plan.Writes {
				writes = append(writes, obj{"key": w.Key, "title": w.Title, "add": nn(w.Add), "remove": nn(w.Remove)})
			}
			golden.Compare(t, c["plan"], obj{"writes": writes, "warnings": nn(plan.Warnings)})
			for _, a := range c["apply"].([]any) {
				ap := a.(obj)
				rec := &recorder{}
				if f, ok := ap["fail_at"].(json.Number); ok {
					n := jint(f)
					rec.failAt = &n
				}
				done, err := ApplyLabelWrites(rec, plan)
				got := obj{"fail_at": ap["fail_at"], "calls": append([][]any{}, rec.calls...)}
				var se *sources.Error
				if errors.As(err, &se) {
					got["error"] = se.Msg
				} else {
					got["ok"] = done
				}
				golden.Compare(t, ap, got)
			}
		})
	}
}
