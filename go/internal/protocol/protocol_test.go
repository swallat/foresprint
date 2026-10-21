package protocol

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
)

type cases struct {
	KindTitles map[string]string `json:"kind_titles"`
	Cell       []struct {
		Text *string `json:"text"`
		Cell string  `json:"cell"`
	} `json:"cell"`
	MDItem []struct {
		Text string `json:"text"`
		Item string `json:"item"`
	} `json:"md_item"`
	Rendering    []renderCase `json:"rendering"`
	Planning     []planCase   `json:"planning"`
	Fingerprints []struct {
		Text          string   `json:"text"`
		DocumentsYAML []string `json:"documents_yaml"`
		Fingerprint   string   `json:"fingerprint"`
	} `json:"fingerprints"`
	Scenario struct {
		Operations []op `json:"operations"`
	} `json:"scenario"`
}

type renderCase struct {
	Kind         string      `json:"kind"`
	Team         string      `json:"team"`
	Sprint       string      `json:"sprint"`
	Facts        [][2]string `json:"facts"`
	Notes        [][]any     `json:"notes"`
	Comment      string      `json:"comment"`
	ShowPO       bool        `json:"show_po"`
	Text         string      `json:"text"`
	PlanningLine []string    `json:"planning_lines"`
	Distribution *struct {
		Rows []struct {
			Name              string   `json:"name"`
			PO                string   `json:"po"`
			Active            bool     `json:"active"`
			Standard          *float64 `json:"standard"`
			Preplanned        *float64 `json:"preplanned"`
			Planned           *float64 `json:"planned"`
			Done              *float64 `json:"done"`
			ProductionPlanned *float64 `json:"production_planned"`
			ProductionDone    *float64 `json:"production_done"`
		} `json:"rows"`
		ByPO []struct {
			PO     string              `json:"po"`
			Totals map[string]*float64 `json:"totals"`
		} `json:"by_po"`
	} `json:"distribution"`
}

type planCase struct {
	Text     string            `json:"text"`
	Parts    map[string][2]any `json:"parts"`
	Previous map[string][2]any `json:"previous"`
}

type op struct {
	Op      string      `json:"op"`
	Sprint  string      `json:"sprint"`
	Kind    string      `json:"kind"`
	Text    string      `json:"text"`
	Now     string      `json:"now"`
	State   *string     `json:"state"`
	Path    string      `json:"path"`
	Created bool        `json:"created"`
	Content string      `json:"content"`
	Folder  []string    `json:"folder"`
	Found   [][4]any    `json:"found"`
	Renamed []string    `json:"renamed"`
	Renames [][2]string `json:"renames"`
}

var noon = time.Date(2026, 7, 8, 9, 5, 0, 0, time.UTC)

func parts(m map[string][2]any) map[string]SectionPart {
	out := map[string]SectionPart{}
	for k, v := range m {
		var lines []string
		for _, l := range v[1].([]any) {
			lines = append(lines, l.(string))
		}
		if lines == nil {
			lines = []string{}
		}
		out[k] = SectionPart{AsOf: v[0].(string), Lines: lines}
	}
	return out
}

func asMap(m map[string]SectionPart) map[string][2]any {
	out := map[string][2]any{}
	for k, v := range m {
		lines := make([]any, 0, len(v.Lines))
		for _, l := range v.Lines {
			lines = append(lines, l)
		}
		out[k] = [2]any{v.AsOf, lines}
	}
	return out
}

func load(t *testing.T) cases {
	var c cases
	golden.Load(t, &c, "protocol", "cases.json")
	return c
}

func TestSmall(t *testing.T) {
	c := load(t)
	for k, want := range c.KindTitles {
		if got := KindTitle(k); got != want {
			t.Errorf("KindTitle(%s) = %q, want %q", k, got, want)
		}
	}
	for _, x := range c.Cell {
		text := ""
		if x.Text != nil {
			text = *x.Text
		}
		if got := Cell(text); got != x.Cell {
			t.Errorf("Cell(%q) = %q, want %q", text, got, x.Cell)
		}
	}
	for _, x := range c.MDItem {
		if got := MDItem(x.Text); got != x.Item {
			t.Errorf("MDItem(%q) = %q, want %q", x.Text, got, x.Item)
		}
	}
	for _, f := range c.Fingerprints {
		if got := Fingerprint(f.Text, f.DocumentsYAML...); got != f.Fingerprint {
			t.Errorf("Fingerprint(%q) = %s, want %s", f.Text, got, f.Fingerprint)
		}
	}
}

func TestRender(t *testing.T) {
	for i, r := range load(t).Rendering {
		var facts []Fact
		for _, f := range r.Facts {
			facts = append(facts, Fact{f[0], f[1]})
		}
		var notes []Note
		for _, n := range r.Notes {
			note := Note{Title: n[0].(string)}
			for _, it := range n[1].([]any) {
				note.Items = append(note.Items, it.(string))
			}
			notes = append(notes, note)
		}
		var d *Distribution
		if r.Distribution != nil {
			d = &Distribution{}
			for _, row := range r.Distribution.Rows {
				d.Rows = append(d.Rows, Row{row.Name, row.PO, row.Active, row.Standard, row.Preplanned, row.Planned, row.Done, row.ProductionPlanned, row.ProductionDone})
			}
			got := ByPO(*d)
			if len(got) != len(r.Distribution.ByPO) {
				t.Fatalf("case %d: ByPO has %d groups, want %d", i, len(got), len(r.Distribution.ByPO))
			}
			for j, want := range r.Distribution.ByPO {
				golden.Compare(t, want.Totals, got[j].Totals)
				if got[j].PO != want.PO {
					t.Errorf("case %d: PO %q, want %q", i, got[j].PO, want.PO)
				}
			}
			if lines := PlanningDistributionLines(*d, r.ShowPO); !same(lines, r.PlanningLine) {
				t.Errorf("case %d: planning lines differ:\n%q\nwant\n%q", i, lines, r.PlanningLine)
			}
		}
		if got := Render(r.Kind, r.Team, r.Sprint, noon, facts, d, notes, r.Comment, r.ShowPO); got != r.Text {
			t.Errorf("case %d (%s %s): text differs:\n%s\nwant\n%s", i, r.Kind, r.Sprint, got, r.Text)
		}
	}
}

func same(a, b []string) bool {
	if len(a) == 0 && len(b) == 0 {
		return true
	}
	return equal(a, b)
}

func TestPlanning(t *testing.T) {
	c := load(t)
	facts := []Fact{{"Capacity", "40 PT"}, {"Commitment", "34 | 35"}, {"Note", "two\nlines  here"}}
	sections := []Section{
		{"absences", "Absences", []string{"- anna: 2", "", "- ben: 1"}, true},
		{"scheduling", "Scheduling", []string{"Tickets: 12"}, false},
		{"commitment", "Commitment", []string{"34"}, true},
	}
	first := RenderPlanning("Team A", "2026.7", noon, facts, sections, map[string]SectionPart{})
	if first != c.Planning[0].Text {
		t.Errorf("first differs:\n%s\nwant\n%s", first, c.Planning[0].Text)
	}
	golden.Compare(t, c.Planning[0].Parts, asMap(SectionParts(first)))
	changed := []Section{sections[0], sections[1], {"commitment", "Commitment", []string{"35"}, true}}
	later := time.Date(2026, 7, 9, 10, 30, 0, 0, time.UTC)
	second := RenderPlanning("Team A", "2026.7", later, facts, changed, parts(c.Planning[1].Previous))
	if second != c.Planning[1].Text {
		t.Errorf("second differs:\n%s\nwant\n%s", second, c.Planning[1].Text)
	}
	golden.Compare(t, c.Planning[1].Parts, asMap(SectionParts(second)))
	golden.Compare(t, c.Planning[2].Parts, asMap(SectionParts(c.Planning[2].Text)))
}

func TestScenario(t *testing.T) {
	root := t.TempDir()
	ConfigDir = func() string { return filepath.Join(root, "config") }
	team := filepath.Join(root, "t")
	if err := os.MkdirAll(team, 0o777); err != nil {
		t.Fatal(err)
	}
	var clock time.Time
	changes := 0
	s := &Store{Dir: team, Now: func() time.Time { return clock }, OnChange: func() { changes++ }}
	listing := func() []string {
		entries, err := os.ReadDir(filepath.Join(team, Folder))
		if err != nil {
			return []string{}
		}
		names := []string{}
		for _, e := range entries {
			names = append(names, e.Name())
		}
		return names
	}
	parse := func(v string) time.Time {
		at, err := time.Parse("2006-01-02T15:04:05", v)
		if err != nil {
			t.Fatal(err)
		}
		return at
	}
	for i, o := range load(t).Scenario.Operations {
		if o.Now != "" {
			clock = parse(o.Now)
		}
		switch o.Op {
		case "write":
			path, created, err := s.WriteNew(o.Sprint, o.Kind, o.Text, o.State)
			if err != nil {
				t.Fatalf("op %d: %v", i, err)
			}
			if filepath.Base(path) != o.Path || created != o.Created {
				t.Errorf("op %d: got %s created=%v, want %s created=%v", i, filepath.Base(path), created, o.Path, o.Created)
			}
			if got, _ := readText(path); got != o.Content { // the reference read it in text mode
				t.Errorf("op %d: content %q, want %q", i, got, o.Content)
			}
		case "list":
			entries, err := s.List(o.Sprint)
			if err != nil {
				t.Fatal(err)
			}
			if len(entries) != len(o.Found) {
				t.Fatalf("op %d: %d entries, want %d", i, len(entries), len(o.Found))
			}
			for j, want := range o.Found {
				e := entries[j]
				if e.At.Format("2006-01-02T15:04:05") != want[0] || e.Kind != want[1] || e.Obsolete != want[2].(bool) || filepath.Base(e.Path) != want[3] {
					t.Errorf("op %d entry %d: got %v, want %v", i, j, e, want)
				}
			}
		case "obsolete":
			renamed, err := s.MarkObsolete(o.Sprint, o.Kind)
			if err != nil {
				t.Fatal(err)
			}
			got := []string{}
			for _, p := range renamed {
				got = append(got, filepath.Base(p))
			}
			if !same(got, o.Renamed) {
				t.Errorf("op %d: renamed %v, want %v", i, got, o.Renamed)
			}
		case "renames":
			got, err := s.Renames([][2]string{{"2026.7", "2026.07"}, {"2026.8", "A"}})
			if err != nil {
				t.Fatal(err)
			}
			if len(got) != len(o.Renames) {
				t.Fatalf("op %d: %d renames, want %d", i, len(got), len(o.Renames))
			}
			for j, w := range o.Renames {
				if filepath.Base(got[j][0]) != w[0] || filepath.Base(got[j][1]) != w[1] {
					t.Errorf("op %d rename %d: got %v, want %v", i, j, got[j], w)
				}
			}
			// The reference then adds names that do not belong or are impossible.
			folder := filepath.Join(team, Folder)
			for _, name := range []string{
				"2026.7-planning-20261340-250000.md",
				"2026.7-planning-20260101-000000.txt",
				"2026.7-other-20260101-000000.md",
				"2026.7-planning-20260101-000000-ZZZZ.md",
				"2026.7-planning-20260101-000000-abcd_obsolet_20260102-000000.md",
				"2026.7-planning-20260101-000000-abcd_obsolet_20260102-000000.md.bak",
			} {
				if err := os.WriteFile(filepath.Join(folder, name), []byte("x"), 0o666); err != nil {
					t.Fatal(err)
				}
			}
			if err := os.Mkdir(filepath.Join(folder, "2026.7-review-20260102-000000"), 0o777); err != nil {
				t.Fatal(err)
			}
			o.Folder = nil
		}
		if o.Op == "renames" {
			continue // the folder is checked by the following listing
		}
		if got := listing(); !same(got, o.Folder) {
			t.Errorf("op %d (%s): folder %v, want %v", i, o.Op, got, o.Folder)
		}
	}
	if changes == 0 {
		t.Error("OnChange was never called")
	}
}

func TestSaveRollsBack(t *testing.T) {
	root := t.TempDir()
	ConfigDir = func() string { return filepath.Join(root, "config") }
	s := &Store{Dir: root, Now: func() time.Time { return noon }}
	failure := os.ErrInvalid
	_, err := s.SaveWithProtocol("2026.7", Planning, "# P\n\nAs of: x\n\n- a: 1\n", []string{"id: 1\n"},
		func() ([]string, error) { return nil, failure })
	if err == nil || !os.IsNotExist(statErr(filepath.Join(root, Folder))) && len(entriesOf(t, s)) != 0 {
		t.Fatalf("err = %v, entries = %v", err, entriesOf(t, s))
	}
	saved, err := s.SaveWithProtocol("2026.7", Planning, "# P\n\nAs of: x\n\n- a: 1\n", []string{"id: 1\n"},
		func() ([]string, error) { return []string{"f"}, nil })
	if err != nil || len(saved) != 1 || len(entriesOf(t, s)) != 1 {
		t.Fatalf("saved = %v, err = %v, entries = %v", saved, err, entriesOf(t, s))
	}
}

func statErr(path string) error { _, err := os.Stat(path); return err }

func entriesOf(t *testing.T, s *Store) []Entry {
	t.Helper()
	e, err := s.List("2026.7")
	if err != nil {
		t.Fatal(err)
	}
	return e
}

func TestLockContention(t *testing.T) {
	root := t.TempDir()
	ConfigDir = func() string { return filepath.Join(root, "config") }
	old := LockWait
	LockWait = 200 * time.Millisecond
	defer func() { LockWait = old }()
	s := &Store{Dir: root, Now: func() time.Time { return noon }}
	folder, err := s.makeFolder()
	if err != nil {
		t.Fatal(err)
	}
	err = s.locked(folder, "2026.7", Planning, func() error {
		_, _, inner := s.WriteNew("2026.7", Planning, "x\n\ny\n", nil)
		var access *AccessError
		if !errors.As(inner, &access) {
			t.Errorf("second writer got %v, want an AccessError", inner)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestPySum(t *testing.T) {
	for _, c := range []struct {
		xs   []float64
		want float64
	}{
		{[]float64{17.355, 5.8, 6.8, 23.8, 28.3, 7.65}, 89.705},
		{[]float64{1e16, 1, -1e16}, 1},
	} {
		if got := pySum(c.xs); got != c.want {
			t.Errorf("pySum(%v) = %v, want %v", c.xs, got, c.want)
		}
	}
}
