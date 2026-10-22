// Package workpackages handles the work packages a team keeps in Foresprint instead of tickets
// from a tracker (decision 15b of the design, arbeitspakete.yaml): new keys like AP-424, ranks,
// and the import of packages from a CSV or Excel table. New in 1.0, there is no Python original.
package workpackages

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"

	"golang.org/x/text/encoding/charmap"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/sources"
)

// Prefix is the key prefix of the team's work packages.
func Prefix(t model.TrackerSettings) string {
	if p := strings.TrimSpace(t.PackagePrefix); p != "" {
		return p
	}
	return model.DefaultPackagePrefix
}

// number is the numeric part of a key with the prefix, or false.
func number(key, prefix string) (int, bool) {
	rest, ok := strings.CutPrefix(key, prefix+"-")
	if !ok {
		return 0, false
	}
	n, err := strconv.Atoi(rest)
	return n, err == nil && n > 0
}

// NextKey is the next free key: one more than the highest number used with the prefix.
func NextKey(existing []model.Ticket, prefix string) string {
	highest := 0
	for _, t := range existing {
		if n, ok := number(t.Key, prefix); ok && n > highest {
			highest = n
		}
	}
	return fmt.Sprintf("%s-%d", prefix, highest+1)
}

// rankWidth is the width of the numbers in a rank, so that ranks sort as text.
const rankWidth = 8

// RankAfter is a rank that sorts after all ranks of the tickets (the end of the backlog).
func RankAfter(existing []model.Ticket) string {
	highest := 0
	for _, t := range existing {
		if t.Rank == nil {
			continue
		}
		if n, err := strconv.Atoi(strings.TrimLeft(*t.Rank, "0")); err == nil && n > highest {
			highest = n
		}
	}
	return fmt.Sprintf("%0*d", rankWidth, highest+10)
}

// Columns are the header names (lower case) that mean a field, in English and German.
var Columns = map[string][]string{
	"key":         {"key", "id", "schlüssel", "nummer", "nr"},
	"title":       {"title", "summary", "name", "titel", "zusammenfassung", "bezeichnung"},
	"status":      {"status"},
	"type":        {"type", "issue type", "typ", "vorgangstyp", "art"},
	"priority":    {"priority", "priorität", "prio"},
	"assignee":    {"assignee", "bearbeiter", "zugewiesen an", "verantwortlich"},
	"product":     {"product", "produkt"},
	"project":     {"project", "projekt"},
	"estimate":    {"estimate", "story points", "points", "punkte", "schätzung", "aufwand"},
	"refined":     {"refined", "verfeinert", "ready", "bereit"},
	"labels":      {"labels", "label", "schlagworte"},
	"description": {"description", "beschreibung"},
	"acceptance":  {"acceptance criteria", "acceptance", "akzeptanzkriterien", "abnahmekriterien"},
	"depends":     {"depends on", "blocked by", "abhängig von", "blockiert durch"},
	"done":        {"done", "erledigt", "fertig"},
}

// Problem is a row of the table that could not be read.
type Problem struct {
	// Row is the row number in the table (1 = header).
	Row int
	Msg string
}

// Options tell how a table is read.
type Options struct {
	// Tracker supplies the refined label and the prefix of new keys.
	Tracker model.TrackerSettings
	// Existing are the work packages already there (for new keys and ranks).
	Existing []model.Ticket
	// DoneStatuses are status values (lower case) that mean the package is done.
	DoneStatuses []string
}

// DefaultDoneStatuses are the status words that count as done when none are configured.
var DefaultDoneStatuses = []string{"done", "closed", "resolved", "erledigt", "fertig", "abgeschlossen"}

// Result is what a table gives.
type Result struct {
	Packages []model.Ticket
	Problems []Problem
	// Unmapped are header names no field was found for (shown so the user can correct the file).
	Unmapped []string
}

// ParseTable turns a table (header row first) into work packages. Rows without a title are
// problems; a row without a key gets the next free key. Keys of the table must be unique.
func ParseTable(rows [][]string, opts Options) Result {
	var res Result
	if len(rows) == 0 {
		return res
	}
	columns := map[string]int{}
	for i, h := range rows[0] {
		name := pytext.Casefold(pytext.Strip(h))
		matched := false
		for field, aliases := range Columns {
			for _, a := range aliases {
				if a == name {
					if _, taken := columns[field]; !taken {
						columns[field] = i
					}
					matched = true
				}
			}
		}
		if !matched && name != "" {
			res.Unmapped = append(res.Unmapped, pytext.Strip(h))
		}
	}
	if _, ok := columns["title"]; !ok {
		res.Problems = append(res.Problems, Problem{Row: 1, Msg: sources.T("The table has no column for the title (expected one of: {names}).",
			"names", strings.Join(Columns["title"], ", "))})
		return res
	}
	done := opts.DoneStatuses
	if len(done) == 0 {
		done = DefaultDoneStatuses
	}
	prefix := Prefix(opts.Tracker)
	all := append([]model.Ticket(nil), opts.Existing...)
	seen := map[string]int{}
	ranked := append([]model.Ticket(nil), opts.Existing...)
	// Keys the table names itself are reserved first, so a generated key never takes one.
	for _, row := range rows[1:] {
		if i, ok := columns["key"]; ok && i < len(row) {
			if k := pytext.Strip(row[i]); k != "" {
				all = append(all, model.Ticket{Key: k})
			}
		}
	}
	cell := func(row []string, field string) string {
		if i, ok := columns[field]; ok && i < len(row) {
			return pytext.Strip(row[i])
		}
		return ""
	}
	for n, row := range rows[1:] {
		line := n + 2
		if rowBlank(row) {
			continue
		}
		title := cell(row, "title")
		if title == "" {
			res.Problems = append(res.Problems, Problem{Row: line, Msg: sources.T("No title")})
			continue
		}
		t := model.Ticket{Title: title}
		t.Key = cell(row, "key")
		if t.Key != "" {
			if first, dup := seen[t.Key]; dup {
				res.Problems = append(res.Problems, Problem{Row: line, Msg: sources.T("Key {key} is already used in row {row}",
					"key", t.Key, "row", first)})
				continue
			}
			seen[t.Key] = line
		}
		if s := cell(row, "estimate"); s != "" {
			f, err := sources.ParseNumber(s)
			if err != nil || f == nil || *f < 0 {
				res.Problems = append(res.Problems, Problem{Row: line, Msg: sources.T("The estimate {value} is not a non-negative number", "value", s)})
				continue
			}
			t.Estimate = f
		}
		set := func(dst **string, field string) {
			if v := cell(row, field); v != "" {
				*dst = &v
			}
		}
		set(&t.Status, "status")
		set(&t.IssueType, "type")
		set(&t.Priority, "priority")
		set(&t.Assignee, "assignee")
		set(&t.Product, "product")
		set(&t.Project, "project")
		set(&t.Description, "description")
		set(&t.Acceptance, "acceptance")
		t.Labels = splitList(cell(row, "labels"))
		t.DependsOn = splitList(cell(row, "depends"))
		if truthy(cell(row, "refined")) {
			label := "refined"
			if opts.Tracker.RefinedLabel != nil && *opts.Tracker.RefinedLabel != "" {
				label = *opts.Tracker.RefinedLabel
			}
			if !slices.Contains(t.Labels, label) {
				t.Labels = append(t.Labels, label)
			}
		}
		t.Done = truthy(cell(row, "done"))
		if t.Status != nil {
			for _, d := range done {
				if pytext.Casefold(*t.Status) == d {
					t.Done = true
				}
			}
		}
		if t.Key == "" {
			t.Key = NextKey(all, prefix)
			all = append(all, model.Ticket{Key: t.Key})
		}
		rank := RankAfter(ranked)
		t.Rank = &rank
		ranked = append(ranked, t)
		res.Packages = append(res.Packages, t)
	}
	return res
}

var listSeparator = regexp.MustCompile(`[,;\n]+`)

func splitList(s string) []string {
	var out []string
	for _, part := range listSeparator.Split(s, -1) {
		if p := pytext.Strip(part); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func rowBlank(row []string) bool {
	for _, c := range row {
		if pytext.Strip(c) != "" {
			return false
		}
	}
	return true
}

func truthy(s string) bool {
	switch pytext.Casefold(pytext.Strip(s)) {
	case "1", "y", "yes", "ja", "j", "true", "wahr", "x":
		return true
	}
	return false
}

// ReadCSV reads a CSV table; the delimiter (comma, semicolon or tab) is guessed from the header
// line, a byte order mark is dropped and text that is not UTF-8 is read as Windows-1252 (what
// German Excel writes as "CSV").
func ReadCSV(raw []byte) ([][]string, error) {
	raw = bytes.TrimPrefix(raw, []byte("\xef\xbb\xbf"))
	if !utf8.Valid(raw) {
		if decoded, err := charmap.Windows1252.NewDecoder().Bytes(raw); err == nil {
			raw = decoded
		}
	}
	first, _, _ := bytes.Cut(raw, []byte("\n"))
	r := csv.NewReader(bytes.NewReader(raw))
	r.Comma = delimiter(string(first))
	r.FieldsPerRecord = -1
	r.LazyQuotes = true
	var rows [][]string
	for {
		rec, err := r.Read()
		if err == io.EOF {
			return rows, nil
		}
		if err != nil {
			return nil, &sources.Error{Msg: sources.T("The CSV file cannot be read: {error}", "error", err.Error())}
		}
		rows = append(rows, rec)
	}
}

// Change says what an import does to the existing packages.
type Change struct {
	Package model.Ticket
	// Update is true when a package with this key exists and is replaced; otherwise it is new.
	Update bool
}

// Merge combines imported packages with the existing ones: a key that exists is updated (the
// fields of the table win, what the table does not carry stays), a new key is added at the end.
// It returns the new list of packages and the changes for the preview.
func Merge(existing, imported []model.Ticket) ([]model.Ticket, []Change) {
	out := append([]model.Ticket(nil), existing...)
	index := map[string]int{}
	for i, t := range out {
		index[t.Key] = i
	}
	var changes []Change
	for _, p := range imported {
		if i, ok := index[p.Key]; ok {
			merged := mergeOne(out[i], p)
			out[i] = merged
			changes = append(changes, Change{Package: merged, Update: true})
			continue
		}
		index[p.Key] = len(out)
		out = append(out, p)
		changes = append(changes, Change{Package: p})
	}
	return out, changes
}

// mergeOne lets the imported fields that have a value win and keeps the others (and the rank).
func mergeOne(old, in model.Ticket) model.Ticket {
	out := old
	out.Title = in.Title
	for _, f := range []struct{ dst, src **string }{
		{&out.Status, &in.Status}, {&out.IssueType, &in.IssueType}, {&out.Priority, &in.Priority},
		{&out.Assignee, &in.Assignee}, {&out.Product, &in.Product}, {&out.Project, &in.Project},
		{&out.Description, &in.Description}, {&out.Acceptance, &in.Acceptance},
	} {
		if *f.src != nil {
			*f.dst = *f.src
		}
	}
	if in.Estimate != nil {
		out.Estimate = in.Estimate
	}
	if len(in.Labels) > 0 {
		out.Labels = in.Labels
	}
	if len(in.DependsOn) > 0 {
		out.DependsOn = in.DependsOn
	}
	out.Done = in.Done || old.Done && in.Status == nil
	return out
}

// delimiter is the separator that occurs most in the header line: semicolon, tab or comma.
func delimiter(header string) rune {
	best, count := ',', strings.Count(header, ",")
	for _, c := range []rune{';', '\t'} {
		if n := strings.Count(header, string(c)); n > count {
			best, count = c, n
		}
	}
	return best
}
