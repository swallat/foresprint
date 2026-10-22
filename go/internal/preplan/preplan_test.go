package preplan

import (
	"encoding/json"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/storage"
)

var midnight = regexp.MustCompile(`^(\d{4}-\d\d-\d\d)T00:00:00Z$`)

// plain converts v to JSON values, dates as YYYY-MM-DD.
func plain(t *testing.T, v any) any {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var out any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	return dates(out)
}

func dates(v any) any {
	switch x := v.(type) {
	case map[string]any:
		for k, e := range x {
			x[k] = dates(e)
		}
	case []any:
		for i, e := range x {
			x[i] = dates(e)
		}
	case string:
		if m := midnight.FindStringSubmatch(x); m != nil {
			return m[1]
		}
	}
	return v
}

func variantMap(v *Variants) map[string]*Distribution {
	out := map[string]*Distribution{}
	for _, it := range v.Items() {
		out[string(it.Variant)] = it.Dist
	}
	return out
}

// export is what scripts/golden.py export_preplan records.
func export(t *testing.T, data *storage.TeamData, today time.Time) map[string]any {
	t.Helper()
	variants, err := DistributeVariants(data, today, 26)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]any{
		"samples":   variants.Samples,
		"available": variants.Available(),
		"variants":  plain(t, variantMap(variants)),
	}
	ranges := map[string]any{}
	for _, p := range data.Projects {
		r, err := ProjectRangeOf(variants, p.ID)
		if err != nil {
			t.Fatal(err)
		}
		m := map[string]any{}
		m["project"], m["available"] = r.Project, r.Available
		m["last_sprint"], m["light"] = plain(t, r.LastSprint), plain(t, r.Light)
		m["earliest"], m["latest"] = r.Earliest, r.Latest
		m["best_light"], m["worst_light"], m["complete"] = r.BestLight, r.WorstLight, r.Complete
		m["light_range"] = []string{r.BestLight, r.WorstLight}
		m["uniform"], m["on_track"] = r.Uniform(), r.OnTrack()
		ranges[p.ID] = m
	}
	got["project_ranges"] = ranges
	tickets := map[string]any{}
	for _, tk := range data.Tickets {
		r := TicketRangeOf(variants, tk.Key)
		if r == nil {
			tickets[tk.Key] = nil
			continue
		}
		tickets[tk.Key] = map[string]any{
			"ticket": r.Ticket, "sprints": plain(t, r.Sprints), "earliest": r.Earliest,
			"latest": r.Latest, "complete": r.Complete, "fixed": r.Fixed(),
		}
	}
	got["ticket_ranges"] = tickets
	rows := []any{}
	for _, r := range HandoverRows(data, variants.Median, 6) {
		rows = append(rows, map[string]any{
			"sprint": r.Sprint, "product": r.Product, "proposed": r.Proposed, "current": r.Current,
			"action": r.Action(false), "action_overwrite": r.Action(true),
			"writes": r.Writes(false), "writes_overwrite": r.Writes(true),
		})
	}
	got["handover"] = rows
	sums := map[string]any{}
	for name, d := range variantMap(variants) {
		per := map[string]any{}
		for _, s := range d.Sprints {
			cells := map[string]any{}
			for _, e := range SprintSums(d, s, data) {
				key := "(none)"
				if e.Product != nil {
					key = *e.Product
				}
				cells[key] = e.Amount
			}
			per[s] = cells
		}
		sums[name] = per
	}
	got["sprint_sums"] = sums
	return got
}

func load(t *testing.T, root, team string) *storage.TeamData {
	t.Helper()
	data, err := storage.NewRepository(root).Load(team)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestPreplanGolden(t *testing.T) {
	ran := 0
	for _, c := range golden.Cases(t) {
		var want map[string]any
		if !c.LoadExpected(t, &want, "preplan.json") {
			continue
		}
		ran++
		t.Run(c.Name, func(t *testing.T) {
			data := load(t, filepath.Join(golden.RepoRoot(t), filepath.FromSlash(c.Root)), c.Team)
			golden.Compare(t, want, export(t, data, coretest.Today(t, c)))
		})
	}
	if ran == 0 {
		t.Fatal("no case with a ticket distribution")
	}
}

// TestPreplanVariations runs the altered copies of tickets-products (cycles, earmarks, bases ...).
func TestPreplanVariations(t *testing.T) {
	var ref struct {
		Cases []struct {
			Name      string         `json:"name"`
			Base      string         `json:"base"`
			Team      string         `json:"team"`
			Today     string         `json:"today"`
			Overrides []string       `json:"overrides"`
			LoadError string         `json:"load_error"`
			Preplan   map[string]any `json:"preplan"`
		} `json:"cases"`
	}
	golden.Load(t, &ref, "preplan", "cases.json")
	bases := map[string]golden.Case{}
	for _, c := range golden.Cases(t) {
		bases[c.Name] = c
	}
	for _, rc := range ref.Cases {
		t.Run(rc.Name, func(t *testing.T) {
			base := bases[rc.Base]
			root := t.TempDir()
			folder := filepath.Join(root, rc.Team)
			copyYAML(t, base.TeamDir(t), folder)
			copyYAML(t, filepath.Join(golden.RepoRoot(t), "golden", "inputs", "preplan", rc.Name), folder)
			if rc.LoadError != "" {
				if _, err := storage.NewRepository(root).Load(rc.Team); err == nil {
					t.Fatal("the team should not load")
				}
				return
			}
			today, err := time.Parse("2006-01-02", rc.Today)
			if err != nil {
				t.Fatal(err)
			}
			golden.Compare(t, rc.Preplan, export(t, load(t, root, rc.Team), today))
		})
	}
}

func copyYAML(t *testing.T, from, to string) {
	t.Helper()
	err := filepath.WalkDir(from, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(path, ".yaml") {
			return err
		}
		rel, _ := filepath.Rel(from, path)
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		dest := filepath.Join(to, rel)
		if err := os.MkdirAll(filepath.Dir(dest), 0o777); err != nil {
			return err
		}
		return os.WriteFile(dest, b, 0o666)
	})
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
}
