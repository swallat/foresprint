package sources

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unicode/utf8"
)

// csvHeaders are Jira's standard column names, English and German.
var csvHeaders = map[string][]string{
	"key":        {"Issue key", "Vorgangsschlüssel"},
	"title":      {"Summary", "Zusammenfassung"},
	"status":     {"Status"},
	"issue_type": {"Issue Type", "Vorgangstyp"},
	"priority":   {"Priority", "Priorität"},
	"labels":     {"Labels", "Stichwörter"},
	"components": {"Component/s", "Komponente/n"},
	"sprint":     {"Sprint"},
	"rank":       {"Custom field (Rank)", "Benutzerdefiniertes Feld (Rang)", "Rank", "Rang"},
	"resolution": {"Resolution", "Lösung"},
	// Inward link of the type "Blocks" = "is blocked by": the tickets that must be finished first.
	"blocked_by": {"Inward issue link (Blocks)", "Eingehende Vorgangsverknüpfung (Blocks)"},
	// Epic without a configured field name: the parent of the issue.
	"parent": {"Parent", "Übergeordnet"},
}

// csvFieldOrder is the order in which the Python dictionary of the accepted headers is filled;
// the columns of a header are assigned in this order.
var csvFieldOrder = []string{
	"key", "title", "status", "issue_type", "priority", "labels", "components", "sprint", "rank",
	"resolution", "blocked_by", "parent",
}

const csvExtraPrefix = "rule:"

// csvRequired are the columns without which the file is useless.
var csvRequired = []string{"key", "title", "estimate"}

// CustomFieldHeaders are the headers under which a custom field with this display name appears
// in the export.
func CustomFieldHeaders(name string) []string {
	return []string{"Custom field (" + name + ")", "Benutzerdefiniertes Feld (" + name + ")", name}
}

// SniffDelimiter is ';' when the header line contains more semicolons than commas, else ','.
func SniffDelimiter(headerLine string) rune {
	if strings.Count(headerLine, ";") > strings.Count(headerLine, ",") {
		return ';'
	}
	return ','
}

// ParseNumber reads a number with decimal point or decimal comma. Empty text gives nil; other
// text that is not a finite number gives an error.
func ParseNumber(value string) (*float64, error) {
	text := pyStrip(value)
	if text == "" {
		return nil, nil //nolint:nilnil // nil means "no value"
	}
	if strings.Contains(text, ",") {
		if strings.Contains(text, ".") {
			// Both present: the last one is the decimal separator, the other groups thousands.
			if strings.LastIndex(text, ",") > strings.LastIndex(text, ".") {
				text = strings.ReplaceAll(strings.ReplaceAll(text, ".", ""), ",", ".")
			} else {
				text = strings.ReplaceAll(text, ",", "")
			}
		} else {
			text = strings.ReplaceAll(text, ",", ".")
		}
	}
	number, ok := pyFloat(text)
	if !ok {
		return nil, fmt.Errorf("not a finite number: %q", value)
	}
	return &number, nil
}

// CSVSource reads the tickets of a CSV export of Jira.
type CSVSource struct {
	Path       string
	Fields     Fields
	RuleFields []RuleField
}

// NewCSVSource returns the source of the file.
func NewCSVSource(path string, fields Fields, ruleFields []RuleField) *CSVSource {
	return &CSVSource{Path: path, Fields: fields, RuleFields: ruleFields}
}

// Kind is "csv".
func (s *CSVSource) Kind() string { return "csv" }

// Name is the name of the source as stored in tickets.yaml.
func (s *CSVSource) Name() string { return filepath.Base(s.Path) }

// headers returns the accepted headers per column, including the configured custom fields, in
// the order of the columns.
func (s *CSVSource) headers() (order []string, wanted map[string][]string) {
	wanted = make(map[string][]string, len(csvHeaders)+8)
	for _, name := range csvFieldOrder {
		if name == "parent" {
			continue
		}
		order = append(order, name)
		wanted[name] = csvHeaders[name]
	}
	if s.Fields.Estimate != "" {
		order = append(order, "estimate")
		wanted["estimate"] = CustomFieldHeaders(s.Fields.Estimate)
	}
	if s.Fields.Remaining != "" {
		order = append(order, "remaining")
		wanted["remaining"] = CustomFieldHeaders(s.Fields.Remaining)
	}
	order = append(order, "epic")
	if s.Fields.Epic != "" {
		wanted["epic"] = CustomFieldHeaders(s.Fields.Epic)
	} else {
		wanted["epic"] = csvHeaders["parent"]
	}
	for _, rf := range s.RuleFields {
		key := csvExtraPrefix + rf.Name
		if _, dup := wanted[key]; !dup {
			order = append(order, key)
		}
		wanted[key] = CustomFieldHeaders(rf.Display)
	}
	return order, wanted
}

// Fetch reads all tickets of the file.
func (s *CSVSource) Fetch() ([]RawTicket, error) {
	text, err := s.read()
	if err != nil {
		return nil, err
	}
	firstLine, _, _ := strings.Cut(text, "\n")
	reader := newCSVReader(text, SniffDelimiter(firstLine))
	header, ok, err := reader.Read()
	if err != nil {
		return nil, s.csvError(err, 1)
	}
	if !ok {
		return nil, errorf("{path}: The file is empty", "path", filepath.Clean(s.Path))
	}
	columns, err := s.columns(header)
	if err != nil {
		return nil, err
	}
	var tickets []RawTicket
	for {
		start := reader.LineNum + 1
		row, ok, err := reader.Read()
		if err != nil {
			return nil, s.csvError(err, start)
		}
		if !ok {
			break
		}
		blank := true
		for _, cell := range row {
			if pyStrip(cell) != "" {
				blank = false
				break
			}
		}
		if blank {
			continue
		}
		ticket, err := s.ticket(row, columns, reader.LineNum)
		if err != nil {
			return nil, err
		}
		tickets = append(tickets, ticket)
	}
	return tickets, nil
}

func (s *CSVSource) csvError(err error, line int) error {
	return errorf("{path}, line {line}: The file is not valid CSV ({error})",
		"path", filepath.Clean(s.Path), "line", line, "error", err)
}

// read returns the file as text; a UTF-8 byte order mark is dropped like Python's utf-8-sig.
func (s *CSVSource) read() (string, error) {
	raw, err := os.ReadFile(s.Path)
	if err != nil {
		return "", errorf("{path}: file not readable: {error}", "path", filepath.Clean(s.Path), "error", osErrorText(err))
	}
	raw = bytes.TrimPrefix(raw, []byte{0xEF, 0xBB, 0xBF})
	if !utf8.Valid(raw) {
		return "", errorf("{path}: The file is not UTF-8 encoded ({error})",
			"path", filepath.Clean(s.Path), "error", decodeErrorText(raw))
	}
	// Python reads the file in text mode: a line end is "\n" whatever the file uses.
	text := strings.ReplaceAll(strings.ReplaceAll(string(raw), "\r\n", "\n"), "\r", "\n")
	return text, nil
}

// osErrorText is the text of an operating system error without the Go prefix, capitalised like
// the C library does.
func osErrorText(err error) string {
	var errno syscall.Errno
	if errors.As(err, &errno) {
		return upperFirst(errno.Error())
	}
	var pe *fs.PathError
	if errors.As(err, &pe) {
		return upperFirst(pe.Err.Error())
	}
	return err.Error()
}

func upperFirst(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

// decodeErrorText describes the first invalid byte the way Python's UnicodeDecodeError does.
func decodeErrorText(raw []byte) string {
	for i := 0; i < len(raw); {
		r, size := utf8.DecodeRune(raw[i:])
		if r != utf8.RuneError || size > 1 {
			i += size
			continue
		}
		b := raw[i]
		reason := "invalid start byte"
		if b >= 0xC2 && b <= 0xF4 {
			need := 2
			if b >= 0xE0 {
				need = 3
			}
			if b >= 0xF0 {
				need = 4
			}
			if i+need > len(raw) && !utf8.FullRune(raw[i:]) {
				reason = "unexpected end of data"
			} else {
				reason = "invalid continuation byte"
			}
		}
		return fmt.Sprintf("'utf-8' codec can't decode byte 0x%02x in position %d: %s", b, i, reason)
	}
	return "'utf-8' codec can't decode"
}

// columns returns the column indexes per field (several for repeated headers); missing required
// columns raise with the headers that would have been accepted.
func (s *CSVSource) columns(header []string) (map[string][]int, error) {
	if s.Fields.Estimate == "" {
		return nil, errorf("{path}: The field name of the estimate is not configured "+
			"(tracker.fields.estimate in team.yaml)", "path", filepath.Clean(s.Path))
	}
	order, wanted := s.headers()
	positions := map[string][]int{}
	for index, cell := range header {
		name := casefold(pyStrip(cell))
		for _, field := range order {
			for _, alias := range wanted[field] {
				if casefold(pyStrip(alias)) == name {
					positions[field] = append(positions[field], index)
					break
				}
			}
		}
	}
	for _, rf := range s.RuleFields {
		if len(positions[csvExtraPrefix+rf.Name]) == 0 {
			return nil, errorf("{path}: column for the rule field '{name}' missing – expected {names}",
				"path", filepath.Clean(s.Path), "name", rf.Name, "names", quotedAliases(wanted[csvExtraPrefix+rf.Name]))
		}
	}
	var missing []string
	for _, name := range csvRequired {
		if len(positions[name]) == 0 {
			missing = append(missing, name)
		}
	}
	if len(missing) > 0 {
		lines := make([]string, len(missing))
		for i, name := range missing {
			lines[i] = T("{path}: column missing – expected {names}",
				"path", filepath.Clean(s.Path), "names", quotedAliases(wanted[name]))
		}
		return nil, &Error{Msg: strings.Join(lines, "\n")}
	}
	return positions, nil
}

func quotedAliases(aliases []string) string {
	quoted := make([]string, len(aliases))
	for i, a := range aliases {
		quoted[i] = "„" + a + "“"
	}
	return strings.Join(quoted, " / ")
}

func (s *CSVSource) ticket(row []string, columns map[string][]int, line int) (RawTicket, error) {
	values := func(name string) []string {
		var found []string
		for _, i := range columns[name] {
			if i < len(row) {
				if v := pyStrip(row[i]); v != "" {
					found = append(found, v)
				}
			}
		}
		return found
	}
	single := func(name string) string {
		if found := values(name); len(found) > 0 {
			return found[0]
		}
		return ""
	}
	number := func(name string) (*float64, error) {
		found := values(name)
		if len(found) == 0 {
			return nil, nil //nolint:nilnil // nil means "no value"
		}
		_, wanted := s.headers()
		column := wanted[name][0]
		value, err := ParseNumber(found[0])
		if err != nil {
			return nil, errorf("{path}, line {line}: '{value}' in column “{column}” is not a number",
				"path", filepath.Clean(s.Path), "line", line, "value", found[0], "column", column)
		}
		if *value == 0 {
			zero := 0.0 // "-0" is stored as 0
			value = &zero
		}
		if *value < 0 {
			return nil, errorf("{path}, line {line}: '{value}' in column “{column}” is negative",
				"path", filepath.Clean(s.Path), "line", line, "value", found[0], "column", column)
		}
		return value, nil
	}

	key := single("key")
	if key == "" {
		return RawTicket{}, errorf("{path}, line {line}: key is missing", "path", filepath.Clean(s.Path), "line", line)
	}
	sprints := values("sprint")
	ticket := RawTicket{
		Key:        key,
		Title:      collapse(single("title")),
		Status:     single("status"),
		IssueType:  single("issue_type"),
		Priority:   single("priority"),
		Rank:       single("rank"),
		Epic:       single("epic"),
		Labels:     dedupe(values("labels")),
		Components: dedupe(values("components")),
		BlockedBy:  dedupe(values("blocked_by")),
		Resolved:   len(values("resolution")) > 0,
		Extra:      map[string][]string{},
	}
	for _, rf := range s.RuleFields {
		if found := values(csvExtraPrefix + rf.Name); len(found) > 0 {
			ticket.Extra[rf.Name] = dedupe(found)
		}
	}
	var err error
	if ticket.Estimate, err = number("estimate"); err != nil {
		return RawTicket{}, err
	}
	if ticket.Remaining, err = number("remaining"); err != nil {
		return RawTicket{}, err
	}
	// Jira lists the sprints of a ticket chronologically: the last one is the current.
	if len(sprints) > 0 {
		ticket.SprintName = sprints[len(sprints)-1]
	}
	return ticket, nil
}
