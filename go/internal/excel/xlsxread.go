package excel

import (
	"archive/zip"
	"bytes"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"math"
	"math/big"
	"path"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/yamlx"
)

// This file reads the cached values of a workbook the way openpyxl does (load_workbook with
// data_only=True), because the import was written against it: numbers are int or float, a
// number whose cell has a date format is a date and time, text is text, errors are their text.
//
// A cell value is one of: nil, string, int64, float64, bool, time.Time (a date and time),
// timeOfDay and duration.

type timeOfDay struct{ Hour, Minute, Second, Micro int }

type duration struct{ Days, Seconds, Micro int64 }

// workbook is a workbook read from a file.
type workbook struct {
	names      []string
	sheets     map[string]*worksheet
	properties map[string]string // custom document properties as Python's str()
}

type worksheet struct {
	rows map[int]map[int]any // 1-based row, 0-based column
	last int                 // highest row number
}

func (wb *workbook) rename(from, to string) {
	for i, n := range wb.names {
		if n == from {
			wb.names[i] = to
		}
	}
	wb.sheets[to] = wb.sheets[from]
	delete(wb.sheets, from)
}

func (wb *workbook) has(name string) bool {
	_, ok := wb.sheets[name]
	return ok
}

type zipFiles map[string][]byte

func readZip(data []byte) (zipFiles, error) {
	r, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		if errors.Is(err, zip.ErrFormat) {
			return nil, errors.New("File is not a zip file") //nolint:staticcheck // Python text
		}
		return nil, err
	}
	files := zipFiles{}
	for _, f := range r.File {
		rc, err := f.Open()
		if err != nil {
			return nil, err
		}
		b, err := io.ReadAll(rc)
		_ = rc.Close()
		if err != nil {
			return nil, err
		}
		files[f.Name] = b
	}
	return files, nil
}

func (z zipFiles) xml(name string, v any) error {
	b, ok := z[name]
	if !ok {
		return fmt.Errorf("There is no item named %q in the archive", name) //nolint:staticcheck // Python text
	}
	if err := xml.Unmarshal(b, v); err != nil {
		return fmt.Errorf("%s: %w", name, err)
	}
	return nil
}

type relation struct {
	ID, Type, Target string
}

func (z zipFiles) relations(part string) (map[string]relation, error) {
	rels := map[string]relation{}
	name := path.Join(path.Dir(part), "_rels", path.Base(part)+".rels")
	if _, ok := z[name]; !ok {
		return rels, nil
	}
	var doc struct {
		Rels []struct {
			ID     string `xml:"Id,attr"`
			Type   string `xml:"Type,attr"`
			Target string `xml:"Target,attr"`
		} `xml:"Relationship"`
	}
	if err := z.xml(name, &doc); err != nil {
		return nil, err
	}
	for _, r := range doc.Rels {
		rels[r.ID] = relation{r.ID, r.Type, r.Target}
	}
	return rels, nil
}

func resolvePart(base, target string) string {
	if strings.HasPrefix(target, "/") {
		return strings.TrimPrefix(target, "/")
	}
	return path.Clean(path.Join(path.Dir(base), target))
}

// builtinFormats are openpyxl's number formats by index.
var builtinFormats = map[int]string{
	0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00",
	5: `"$"#,##0_);("$"#,##0)`, 6: `"$"#,##0_);[Red]("$"#,##0)`,
	7: `"$"#,##0.00_);("$"#,##0.00)`, 8: `"$"#,##0.00_);[Red]("$"#,##0.00)`,
	9: "0%", 10: "0.00%", 11: "0.00E+00", 12: "# ?/?", 13: "# ??/??",
	14: "mm-dd-yy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 18: "h:mm AM/PM",
	19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "m/d/yy h:mm",
	37: "#,##0_);(#,##0)", 38: "#,##0_);[Red](#,##0)", 39: "#,##0.00_);(#,##0.00)",
	40: "#,##0.00_);[Red](#,##0.00)",
	41: `_(* #,##0_);_(* \(#,##0\);_(* "-"_);_(@_)`,
	42: `_("$"* #,##0_);_("$"* \(#,##0\);_("$"* "-"_);_(@_)`,
	43: `_(* #,##0.00_);_(* \(#,##0.00\);_(* "-"??_);_(@_)`,
	44: `_("$"* #,##0.00_)_("$"* \(#,##0.00\)_("$"* "-"??_)_(@_)`,
	45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0", 48: "##0.0E+0", 49: "@",
}

var timedeltaFormat = regexp.MustCompile(`(?i)\[hh?\](:mm(:ss(\.0*)?)?)?|\[mm?\](:ss(\.0*)?)?|\[ss?\](\.0*)?`)

// stripFormat removes the quoted texts and the bracketed parts except [h], [m] and [s] (openpyxl's
// STRIP_RE).
func stripFormat(f string) string {
	var b strings.Builder
	for i := 0; i < len(f); {
		switch f[i] {
		case '"':
			if end := strings.IndexByte(f[i+1:], '"'); end >= 0 {
				i += end + 2
				continue
			}
		case '[':
			if end := strings.IndexByte(f[i+1:], ']'); end >= 0 {
				switch f[i+1 : i+1+end] {
				case "h", "hh", "m", "mm", "s", "ss":
				default:
					i += end + 2
					continue
				}
			}
		}
		b.WriteByte(f[i])
		i++
	}
	return b.String()
}

// isDateFormat is openpyxl's is_date_format.
func isDateFormat(f string) bool {
	f, _, _ = strings.Cut(f, ";")
	f = stripFormat(f)
	for i := 0; i < len(f); i++ {
		if strings.IndexByte("dmhysDMHYS", f[i]) >= 0 && (i == 0 || (f[i-1] != '_' && f[i-1] != '\\')) {
			return true
		}
	}
	return false
}

func isTimedeltaFormat(f string) bool {
	f, _, _ = strings.Cut(f, ";")
	return timedeltaFormat.MatchString(f)
}

type styleKind int

const (
	plainStyle styleKind = iota
	dateStyle
	durationStyle
)

func readStyles(z zipFiles) ([]styleKind, error) {
	if _, ok := z["xl/styles.xml"]; !ok {
		return nil, nil
	}
	var doc struct {
		NumFmts []struct {
			ID   int    `xml:"numFmtId,attr"`
			Code string `xml:"formatCode,attr"`
		} `xml:"numFmts>numFmt"`
		XFs []struct {
			NumFmt int `xml:"numFmtId,attr"`
		} `xml:"cellXfs>xf"`
	}
	if err := z.xml("xl/styles.xml", &doc); err != nil {
		return nil, err
	}
	custom := map[int]string{}
	for _, n := range doc.NumFmts {
		custom[n.ID] = n.Code
	}
	kinds := make([]styleKind, len(doc.XFs))
	for i, xf := range doc.XFs {
		code, ok := custom[xf.NumFmt]
		if !ok {
			code, ok = builtinFormats[xf.NumFmt]
		}
		switch {
		case !ok:
		case isDateFormat(code):
			kinds[i] = dateStyle
			if isTimedeltaFormat(code) {
				kinds[i] = durationStyle
			}
		case isTimedeltaFormat(code):
			kinds[i] = durationStyle
		}
	}
	return kinds, nil
}

type cellText struct {
	T *string `xml:"t"`
	R []struct {
		T *string `xml:"t"`
	} `xml:"r"`
}

// content is openpyxl's Text.content: the plain text followed by the runs.
func (t cellText) content() string {
	var b strings.Builder
	if t.T != nil {
		b.WriteString(*t.T)
	}
	for _, r := range t.R {
		if r.T != nil {
			b.WriteString(*r.T)
		}
	}
	return b.String()
}

func readShared(z zipFiles) ([]string, error) {
	if _, ok := z["xl/sharedStrings.xml"]; !ok {
		return nil, nil
	}
	var doc struct {
		Items []cellText `xml:"si"`
	}
	if err := z.xml("xl/sharedStrings.xml", &doc); err != nil {
		return nil, err
	}
	out := make([]string, len(doc.Items))
	for i, it := range doc.Items {
		out[i] = strings.ReplaceAll(it.content(), "x005F_", "")
	}
	return out, nil
}

// pyInt parses what Python's int() accepts for the digits of a sheet value.
func pyInt(s string) (any, bool) {
	if n, err := strconv.ParseInt(s, 10, 64); err == nil {
		return n, true
	}
	b, ok := new(big.Int).SetString(strings.TrimSpace(s), 10)
	if !ok {
		return nil, false
	}
	f, _ := new(big.Float).SetInt(b).Float64()
	return f, true
}

// castNumber is openpyxl's _cast_number.
func castNumber(s string) (any, error) {
	if strings.ContainsAny(s, ".Ee") {
		f, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
		if err != nil {
			var ne *strconv.NumError
			if errors.As(err, &ne) && errors.Is(ne.Err, strconv.ErrRange) {
				return f, nil
			}
			return nil, fmt.Errorf("could not convert string to float: %q", s)
		}
		return f, nil
	}
	v, ok := pyInt(s)
	if !ok {
		return nil, fmt.Errorf("invalid literal for int() with base 10: %q", s)
	}
	return v, nil
}

var (
	windowsEpoch = time.Date(1899, 12, 30, 0, 0, 0, 0, time.UTC)
	macEpoch     = time.Date(1904, 1, 1, 0, 0, 0, 0, time.UTC)
)

// fromExcel is openpyxl's from_excel; ok is false where Python raises OverflowError or
// ValueError.
func fromExcel(value any, epoch time.Time, asDuration bool) (any, bool) {
	var f float64
	switch v := value.(type) {
	case int64:
		f = float64(v)
	case float64:
		f = v
	default:
		return nil, false
	}
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return nil, false
	}
	if asDuration {
		days := math.Floor(f)
		micros := math.RoundToEven((f - days) * 86400 * 1e6)
		// timedelta(days=value) rounds to microseconds; then the microseconds go to milliseconds.
		secs := math.Floor(micros / 1e6)
		micro := int64(micros - secs*1e6)
		micro = int64(math.RoundToEven(float64(micro)/1000)) * 1000
		d := duration{Days: int64(days), Seconds: int64(secs), Micro: micro}
		if d.Micro >= 1_000_000 {
			d.Micro -= 1_000_000
			d.Seconds++
		}
		return d, true
	}
	day := math.Floor(f)
	fraction := f - day
	diffMs := int64(math.RoundToEven(fraction * 86400 * 1000))
	if f >= 0 && f < 1 && diffMs < 86400*1000 {
		secs := diffMs / 1000
		return timeOfDay{Hour: int(secs / 3600), Minute: int(secs % 3600 / 60), Second: int(secs % 60), Micro: int(diffMs % 1000 * 1000)}, true
	}
	if f > 0 && f < 60 && epoch.Equal(windowsEpoch) {
		day++
	}
	if math.Abs(day) > 3_652_059 {
		return nil, false
	}
	t := epoch.AddDate(0, 0, int(day)).Add(time.Duration(diffMs) * time.Millisecond)
	if t.Year() < 1 || t.Year() > 9999 {
		return nil, false
	}
	return t, true
}

func colIndex(ref string) (row, col int) {
	i := 0
	for i < len(ref) && ref[i] >= 'A' && ref[i] <= 'Z' {
		col = col*26 + int(ref[i]-'A') + 1
		i++
	}
	row, _ = strconv.Atoi(ref[i:])
	return row, col - 1
}

type xmlSheetCell struct {
	R string    `xml:"r,attr"`
	S int       `xml:"s,attr"`
	T string    `xml:"t,attr"`
	V *string   `xml:"v"`
	I *cellText `xml:"is"`
}

type xmlSheetRow struct {
	R     int            `xml:"r,attr"`
	Cells []xmlSheetCell `xml:"c"`
}

func readSheet(z zipFiles, part string, shared []string, styles []styleKind, epoch time.Time) (*worksheet, error) {
	var doc struct {
		Rows []xmlSheetRow `xml:"sheetData>row"`
	}
	if err := z.xml(part, &doc); err != nil {
		return nil, err
	}
	ws := &worksheet{rows: map[int]map[int]any{}}
	rowCounter := 0
	for _, row := range doc.Rows {
		rowCounter++
		if row.R > 0 {
			rowCounter = row.R
		}
		colCounter := -1
		for _, c := range row.Cells {
			r, col := rowCounter, colCounter+1
			if c.R != "" {
				r, col = colIndex(c.R)
			}
			colCounter = col
			kind := c.T
			if kind == "" {
				kind = "n"
			}
			var text string
			if c.V != nil {
				text = *c.V
			}
			var value any
			switch {
			case kind == "inlineStr":
				if c.I != nil {
					value = c.I.content()
				}
			case text == "":
			case kind == "n":
				n, err := castNumber(text)
				if err != nil {
					return nil, err
				}
				value = n
				if c.S > 0 && c.S < len(styles) && styles[c.S] != plainStyle {
					if d, ok := fromExcel(n, epoch, styles[c.S] == durationStyle); ok {
						value = d
					} else {
						value = "#VALUE!"
					}
				}
			case kind == "s":
				i, err := strconv.Atoi(text)
				if err != nil || i < 0 || i >= len(shared) {
					return nil, fmt.Errorf("list index out of range")
				}
				value = shared[i]
			case kind == "b":
				n, err := strconv.Atoi(text)
				if err != nil {
					return nil, fmt.Errorf("invalid literal for int() with base 10: %q", text)
				}
				value = n != 0
			case kind == "d":
				t, err := parseISO8601(text)
				if err != nil {
					return nil, err
				}
				value = t
			default: // str, e
				value = text
			}
			if value == nil {
				continue
			}
			if ws.rows[r] == nil {
				ws.rows[r] = map[int]any{}
			}
			ws.rows[r][col] = value
			if r > ws.last {
				ws.last = r
			}
		}
	}
	return ws, nil
}

func parseISO8601(s string) (time.Time, error) {
	for _, layout := range []string{"2006-01-02T15:04:05.999999999Z", "2006-01-02T15:04:05.999999999", "2006-01-02T15:04:05Z", "2006-01-02T15:04:05", "2006-01-02"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("Invalid ISO 8601 date: %q", s) //nolint:staticcheck // Python text
}

// readCustomProperties returns the custom document properties as text (Python's str of the
// value).
func readCustomProperties(z zipFiles) (map[string]string, error) {
	out := map[string]string{}
	if _, ok := z["docProps/custom.xml"]; !ok {
		return out, nil
	}
	var doc struct {
		Props []struct {
			Name  string `xml:"name,attr"`
			Inner struct {
				XMLName xml.Name
				Text    string `xml:",chardata"`
			} `xml:",any"`
		} `xml:"property"`
	}
	if err := z.xml("docProps/custom.xml", &doc); err != nil {
		return nil, err
	}
	for _, p := range doc.Props {
		text := p.Inner.Text
		switch p.Inner.XMLName.Local {
		case "i4", "i2", "i1", "i8", "int", "ui1", "ui2", "ui4", "ui8", "uint":
			if n, err := strconv.ParseInt(strings.TrimSpace(text), 10, 64); err == nil {
				text = strconv.FormatInt(n, 10)
			}
		case "r8", "r4":
			if f, err := strconv.ParseFloat(strings.TrimSpace(text), 64); err == nil {
				text = yamlx.PyFloatRepr(f)
			}
		case "bool":
			text = "False"
			if t := strings.TrimSpace(strings.ToLower(p.Inner.Text)); t == "true" || t == "1" {
				text = "True"
			}
		}
		out[p.Name] = text
	}
	return out, nil
}

// openWorkbook reads the sheets and properties of a workbook file.
func openWorkbook(data []byte) (*workbook, error) {
	z, err := readZip(data)
	if err != nil {
		return nil, err
	}
	var root struct {
		Pr struct {
			Date1904 string `xml:"date1904,attr"`
		} `xml:"workbookPr"`
		Sheets []struct {
			Name string `xml:"name,attr"`
			ID   string `xml:"id,attr"`
		} `xml:"sheets>sheet"`
	}
	if err := z.xml("xl/workbook.xml", &root); err != nil {
		return nil, err
	}
	epoch := windowsEpoch
	if root.Pr.Date1904 == "1" || root.Pr.Date1904 == "true" {
		epoch = macEpoch
	}
	rels, err := z.relations("xl/workbook.xml")
	if err != nil {
		return nil, err
	}
	shared, err := readShared(z)
	if err != nil {
		return nil, err
	}
	styles, err := readStyles(z)
	if err != nil {
		return nil, err
	}
	wb := &workbook{sheets: map[string]*worksheet{}}
	for _, s := range root.Sheets {
		rel, ok := rels[s.ID]
		if !ok {
			return nil, fmt.Errorf("sheet %q has no relationship", s.Name)
		}
		ws, err := readSheet(z, resolvePart("xl/workbook.xml", rel.Target), shared, styles, epoch)
		if err != nil {
			return nil, err
		}
		wb.names = append(wb.names, s.Name)
		wb.sheets[s.Name] = ws
	}
	if wb.properties, err = readCustomProperties(z); err != nil {
		return nil, err
	}
	return wb, nil
}
