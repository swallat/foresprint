// Package protocol writes the minutes of the sprint meetings (PO pre-planning, Planning, Review)
// as Markdown files; port of protocol.py. A save creates a new file in the "protokolle" folder
// of the team; older versions stay readable, obsolete ones are renamed.
package protocol

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/report"
)

// Meetings.
const (
	Preplanning = "vorplanung"
	Planning    = "planning"
	Review      = "review"
)

// Kinds lists the meetings in the order of the Python port.
var Kinds = []string{Preplanning, Planning, Review}

// Folder is the name of the minutes folder inside a team folder.
const Folder = "protokolle"

// Markers in the minutes.
const (
	SectionMarker = "<!-- sprintforecast-section: "
	StateMarker   = "<!-- sprintforecast-state: "
)

// Translate maps an English source text to the configured language (the text catalog replaces
// it); placeholders are {name}, filled from pairs of name and value.
var Translate = func(text string) string { return text }

func msg(text string, pairs ...string) string {
	text = Translate(text)
	if len(pairs) == 0 {
		return text
	}
	var b strings.Builder
	for i := 0; i < len(text); {
		if text[i] == '{' {
			if end := strings.IndexByte(text[i:], '}'); end > 0 {
				name := text[i+1 : i+end]
				found := false
				for j := 0; j+1 < len(pairs); j += 2 {
					if pairs[j] == name {
						b.WriteString(pairs[j+1])
						found = true
						break
					}
				}
				if found {
					i += end + 1
					continue
				}
			}
		}
		b.WriteByte(text[i])
		i++
	}
	return b.String()
}

// Columns of the product table per meeting.
var kindMeasures = map[string][]string{
	Preplanning: {"standard", "preplanned"},
	Planning:    {"standard", "preplanned", "planned"},
	Review:      {"planned", "done"},
}

var measureLabels = map[string]string{
	"standard":           "Standard",
	"preplanned":         "PO pre-planning",
	"planned":            "Planning",
	"done":               "Done",
	"production_planned": "of which production access (planning)",
	"production_done":    "of which production access (done)",
}

// Measures are the columns that are summed per PO, in report order.
var Measures = []string{"standard", "preplanned", "planned", "done"}

// MeasureLabel is the display name of a measure in the configured language.
func MeasureLabel(measure string) string { return msg(measureLabels[measure]) }

// Row is the part of a product row the minutes use.
type Row struct {
	Name, PO          string
	Active            bool
	Standard          *float64
	Preplanned        *float64
	Planned           *float64
	Done              *float64
	ProductionPlanned *float64
	ProductionDone    *float64
}

// Value returns the value of a measure (nil if there is none).
func (r Row) Value(measure string) *float64 {
	switch measure {
	case "standard":
		return r.Standard
	case "preplanned":
		return r.Preplanned
	case "planned":
		return r.Planned
	case "done":
		return r.Done
	case "production_planned":
		return r.ProductionPlanned
	case "production_done":
		return r.ProductionDone
	}
	return nil
}

// Distribution is the part of a distribution the minutes use.
type Distribution struct{ Rows []Row }

// POTotals are the totals of one PO.
type POTotals struct {
	PO     string
	Totals map[string]*float64
}

// ByPO sums the measures per PO in order of first appearance; empty unless at least one
// product has a PO.
func ByPO(d Distribution) []POTotals {
	any := false
	for _, r := range d.Rows {
		if r.PO != "" {
			any = true
		}
	}
	if !any {
		return nil
	}
	var order []string
	groups := map[string][]Row{}
	for _, r := range d.Rows {
		po := r.PO
		if po == "" {
			po = msg("(no PO)")
		}
		if _, ok := groups[po]; !ok {
			order = append(order, po)
		}
		groups[po] = append(groups[po], r)
	}
	result := make([]POTotals, 0, len(order))
	for _, po := range order {
		totals := map[string]*float64{}
		for _, m := range Measures {
			sum, seen := 0.0, false
			for _, r := range groups[po] {
				if v := r.Value(m); v != nil {
					sum += *v
					seen = true
				}
			}
			if seen {
				s := sum
				totals[m] = &s
			} else {
				totals[m] = nil
			}
		}
		result = append(result, POTotals{PO: po, Totals: totals})
	}
	return result
}

// Cell neutralizes pipes and line breaks for a Markdown cell or line.
func Cell(text string) string {
	return strings.Join(pytext.Fields(strings.ReplaceAll(text, "|", `\|`)), " ")
}

// KindTitle is the heading of a meeting.
func KindTitle(kind string) string {
	switch kind {
	case Preplanning:
		return msg("PO pre-planning")
	case Planning:
		return msg("Sprint Planning")
	case Review:
		return msg("Sprint Review")
	}
	return ""
}

// MDItem is a bullet line with neutralized pipes and line breaks.
func MDItem(text string) string { return "- " + Cell(text) }

func distributionLines(d Distribution, measures []string, showPO bool, heading string) []string {
	var lines []string
	if len(d.Rows) == 0 {
		return lines
	}
	header := []string{msg("Product")}
	if showPO {
		header = append(header, "PO")
	}
	for _, m := range measures {
		header = append(header, MeasureLabel(m))
	}
	lines = append(lines, "", heading+" "+msg("Per product"), "")
	lines = append(lines, "| "+strings.Join(header, " | ")+" |", "|"+strings.Repeat("---|", len(header)))
	for _, r := range d.Rows {
		show := r.Active
		for _, m := range measures {
			if r.Value(m) != nil {
				show = true
			}
		}
		if !show {
			continue
		}
		cells := []string{Cell(r.Name)}
		if showPO {
			cells = append(cells, Cell(r.PO))
		}
		for _, m := range measures {
			cells = append(cells, report.Fmt(r.Value(m), 2, ""))
		}
		lines = append(lines, "| "+strings.Join(cells, " | ")+" |")
	}
	if rows := ByPO(d); showPO && len(rows) > 0 {
		header = []string{"PO"}
		for _, m := range measures {
			header = append(header, MeasureLabel(m))
		}
		lines = append(lines, "", heading+" "+msg("Per PO"), "", "| "+strings.Join(header, " | ")+" |")
		lines = append(lines, "|"+strings.Repeat("---|", len(header)))
		for _, po := range rows {
			cells := []string{Cell(po.PO)}
			for _, m := range measures {
				cells = append(cells, report.Fmt(po.Totals[m], 2, ""))
			}
			lines = append(lines, "| "+strings.Join(cells, " | ")+" |")
		}
	}
	return lines
}

// Fact is a key figure line of the minutes.
type Fact struct{ Label, Value string }

// Note is a section with bullet items.
type Note struct {
	Title string
	Items []string
}

const stamp = "20060102-150405"

func asOf(now time.Time) string {
	return msg("As of: {at}", "at", now.Format("02.01.2006 15:04"))
}

func header(kind, team, sprintID string, now time.Time, facts []Fact) []string {
	lines := []string{
		"# " + KindTitle(kind) + " " + Cell(team) + " – " + msg("Sprint {id}", "id", sprintID),
		"",
		asOf(now),
		"",
	}
	for _, f := range facts {
		lines = append(lines, "- "+f.Label+": "+Cell(f.Value))
	}
	return lines
}

// Render is the Markdown text of a meeting: header, key figures, sections and, with d, the
// distribution per product (and per PO).
func Render(kind, team, sprintID string, now time.Time, facts []Fact, d *Distribution, notes []Note, comment string, showPO bool) string {
	lines := header(kind, team, sprintID, now, facts)
	if pytext.Strip(comment) != "" {
		lines = append(lines, "", "**"+msg("Comment")+":** "+Cell(comment))
	}
	for _, n := range notes {
		if len(n.Items) == 0 {
			continue
		}
		lines = append(lines, "", "## "+n.Title, "")
		for _, i := range n.Items {
			lines = append(lines, "- "+Cell(i))
		}
	}
	if d != nil {
		lines = append(lines, distributionLines(*d, kindMeasures[kind], showPO, "##")...)
	}
	return strings.Join(lines, "\n") + "\n"
}

// PlanningDistributionLines are the product tables of the Planning minutes (headings one level
// below the section).
func PlanningDistributionLines(d Distribution, showPO bool) []string {
	return distributionLines(d, kindMeasures[Planning], showPO, "###")
}

// Section is a section of the Planning minutes; without Recorded it says "not yet recorded".
type Section struct {
	Key, Title string
	Lines      []string
	Recorded   bool
}

// SectionPart is a parsed section: its as-of text and the lines below it.
type SectionPart struct {
	AsOf  string
	Lines []string
}

// SectionParts parses the sections of Planning minutes.
func SectionParts(text string) map[string]SectionPart {
	parts := map[string]SectionPart{}
	key, open := "", false
	var body []string
	closeSection := func() {
		if !open {
			return
		}
		asOf, rest := "", body
		if len(body) > 0 && strings.HasPrefix(body[0], "_") && strings.HasSuffix(body[0], "_") {
			if len(body[0]) >= 2 {
				asOf = body[0][1 : len(body[0])-1]
			}
			rest = body[1:]
		}
		kept := []string{}
		for _, ln := range rest {
			if pytext.Strip(ln) != "" {
				kept = append(kept, ln)
			}
		}
		parts[key] = SectionPart{AsOf: asOf, Lines: kept}
	}
	for _, line := range strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n") {
		switch {
		case strings.HasPrefix(line, SectionMarker):
			closeSection()
			key = pytext.Strip(strings.TrimSuffix(line[len(SectionMarker):], " -->"))
			open, body = true, nil
		case strings.HasPrefix(line, StateMarker):
			closeSection()
			open = false
		case open && pytext.Strip(line) != "" && !strings.HasPrefix(line, "## "):
			body = append(body, line)
		}
	}
	closeSection()
	return parts
}

// RenderPlanning is the complete Planning minutes with all sections. A recorded section keeps
// the as-of time of previous when its lines are unchanged, otherwise now applies.
func RenderPlanning(team, sprintID string, now time.Time, facts []Fact, sections []Section, previous map[string]SectionPart) string {
	lines := header(Planning, team, sprintID, now, facts)
	for _, s := range sections {
		lines = append(lines, "", "## "+s.Title, SectionMarker+s.Key+" -->", "")
		if !s.Recorded {
			lines = append(lines, "_"+msg("not yet recorded")+"_")
			continue
		}
		old := previous[s.Key]
		oldAsOf := old.AsOf
		if oldAsOf == msg("not yet recorded") { // the placeholder is not an as-of time
			oldAsOf = ""
		}
		body := []string{}
		for _, ln := range s.Lines {
			if pytext.Strip(ln) != "" {
				body = append(body, ln)
			}
		}
		at := asOf(now)
		if oldAsOf != "" && equal(old.Lines, body) {
			at = oldAsOf
		}
		lines = append(lines, "_"+at+"_", "")
		lines = append(lines, s.Lines...)
	}
	return strings.Join(lines, "\n") + "\n"
}

func equal(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// BodyOf is the text without the "As of: …" line (third line).
func BodyOf(text string) []string {
	lines := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	head := lines
	if len(head) > 2 {
		head = head[:2]
	}
	out := append([]string{}, head...)
	if len(lines) > 3 {
		out = append(out, lines[3:]...)
	}
	return out
}

// Fingerprint is the short fingerprint of the saved state: the text without the as-of line plus
// the YAML texts of all saved sprint files.
func Fingerprint(text string, documents ...string) string {
	h := sha256.New()
	h.Write([]byte(strings.Join(BodyOf(text), "\n")))
	for _, d := range documents {
		h.Write([]byte(d))
	}
	return hex.EncodeToString(h.Sum(nil))[:16]
}
