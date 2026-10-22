package excel

import (
	"archive/zip"
	"bytes"
	"encoding/xml"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/xuri/excelize/v2"
)

// Format is the look of a cell (the xlsxwriter formats of the Python version).
type Format struct {
	Bold  bool
	Wrap  bool // text wrap, vertical alignment top
	Size  float64
	BG    string // background colour, "RRGGBB"
	Color string // font colour, "RRGGBB"
	Num   string // number format; empty = General
}

type errNA struct{}

// NA is the cached value of a formula that results in #N/A.
var NA = errNA{}

// colPad is the padding xlsxwriter adds to a column width (the width Excel shows is the width
// of the characters plus this padding).
const colPad = 0.7109375

// book wraps excelize with the few operations the workbook needs and remembers the types of the
// cached results of formulas: excelize can only store them as text, the file is corrected in
// finish.
type book struct {
	f      *excelize.File
	styles map[Format]int
	cached map[string]map[string]any // sheet -> ref -> cached value (number, bool, NA)
	sheets []*sheet
}

type sheet struct {
	b    *book
	name string
}

func newBook() *book {
	f := excelize.NewFile()
	// Excel calculates the formulas when it opens the file (the cached results are for previews).
	full := true
	if err := f.SetCalcProps(&excelize.CalcPropsOptions{FullCalcOnLoad: &full}); err != nil {
		panic(err)
	}
	return &book{f: f, styles: map[Format]int{}, cached: map[string]map[string]any{}}
}

func (b *book) addSheet(name string) *sheet {
	if len(b.sheets) == 0 {
		// excelize starts with "Sheet1".
		if err := b.f.SetSheetName("Sheet1", name); err != nil {
			panic(err)
		}
	} else if _, err := b.f.NewSheet(name); err != nil {
		panic(err)
	}
	s := &sheet{b: b, name: name}
	b.sheets = append(b.sheets, s)
	return s
}

func (b *book) style(f Format) int {
	if f == (Format{}) {
		return 0
	}
	if id, ok := b.styles[f]; ok {
		return id
	}
	st := excelize.Style{}
	if f.Bold || f.Size != 0 || f.Color != "" {
		st.Font = &excelize.Font{Bold: f.Bold, Size: f.Size, Color: f.Color}
	}
	if f.BG != "" {
		st.Fill = excelize.Fill{Type: "pattern", Pattern: 1, Color: []string{f.BG}}
	}
	if f.Wrap {
		st.Alignment = &excelize.Alignment{WrapText: true, Vertical: "top"}
	}
	if f.Num != "" {
		n := f.Num
		st.CustomNumFmt = &n
	}
	id, err := b.f.NewStyle(&st)
	if err != nil {
		panic(err)
	}
	b.styles[f] = id
	return id
}

// ref is the A1 reference of a cell; row and col are 0-based.
func ref(row, col int, absRow, absCol bool) string {
	name, err := excelize.CoordinatesToCellName(col+1, row+1, absRow || absCol)
	if err != nil {
		panic(err)
	}
	if absRow && absCol {
		return name
	}
	if absRow || absCol {
		// CoordinatesToCellName makes both parts absolute; strip the one that is not.
		colName, _ := excelize.ColumnNumberToName(col + 1)
		var b strings.Builder
		if absCol {
			b.WriteByte('$')
		}
		b.WriteString(colName)
		if absRow {
			b.WriteByte('$')
		}
		b.WriteString(strconv.Itoa(row + 1))
		return b.String()
	}
	return name
}

func (s *sheet) cell(row, col int) string { return ref(row, col, false, false) }

func (s *sheet) must(err error) {
	if err != nil {
		panic(fmt.Sprintf("excel: sheet %s: %v", s.name, err))
	}
}

// styleAt applies the format to the cell.
func (s *sheet) styleAt(row, col int, f Format) {
	if id := s.b.style(f); id != 0 {
		s.must(s.b.f.SetCellStyle(s.name, s.cell(row, col), s.cell(row, col), id))
	}
}

// str writes text (an empty text is an empty cell, like xlsxwriter's write).
func (s *sheet) str(row, col int, v string, f Format) {
	if v == "" {
		s.blank(row, col, f)
		return
	}
	s.must(s.b.f.SetCellStr(s.name, s.cell(row, col), v))
	s.styleAt(row, col, f)
}

func (s *sheet) num(row, col int, v float64, f Format) {
	s.must(s.b.f.SetCellFloat(s.name, s.cell(row, col), v, -1, 64))
	s.styleAt(row, col, f)
}

func (s *sheet) boolean(row, col int, v bool, f Format) {
	s.must(s.b.f.SetCellBool(s.name, s.cell(row, col), v))
	s.styleAt(row, col, f)
}

// blank is an empty cell with a format; without a format nothing is written.
func (s *sheet) blank(row, col int, f Format) {
	if s.b.style(f) == 0 {
		return
	}
	s.must(s.b.f.SetCellValue(s.name, s.cell(row, col), nil))
	s.styleAt(row, col, f)
}

// date writes a date or a date with a time as an Excel serial number.
func (s *sheet) date(row, col int, t time.Time, f Format) {
	s.num(row, col, serial(t), f)
}

// serial is the Excel serial number of a time without time zone (1900 date system).
func serial(t time.Time) float64 {
	epoch := time.Date(1899, 12, 30, 0, 0, 0, 0, time.UTC)
	wall := time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), t.Minute(), t.Second(), t.Nanosecond(), time.UTC)
	return wall.Sub(epoch).Seconds() / 86400
}

// formula writes a formula (without "=") with its cached result: a number, a text, a bool or NA.
func (s *sheet) formula(row, col int, formula string, f Format, cached any) {
	cell := s.cell(row, col)
	switch v := cached.(type) {
	case float64:
		s.must(s.b.f.SetCellFloat(s.name, cell, v, -1, 64))
		s.b.remember(s.name, cell, v)
	case int:
		s.must(s.b.f.SetCellInt(s.name, cell, int64(v)))
		s.b.remember(s.name, cell, float64(v))
	case bool:
		s.must(s.b.f.SetCellBool(s.name, cell, v))
		s.b.remember(s.name, cell, v)
	case errNA:
		s.must(s.b.f.SetCellStr(s.name, cell, "#N/A"))
		s.b.remember(s.name, cell, NA)
	case string:
		s.must(s.b.f.SetCellStr(s.name, cell, v))
		// excelize evaluates the formula itself and may replace the value; the file is
		// corrected in finish.
		s.b.remember(s.name, cell, v)
	default:
		panic(fmt.Sprintf("excel: cached value of type %T", cached))
	}
	s.must(s.b.f.SetCellFormula(s.name, cell, formula))
	s.styleAt(row, col, f)
}

func (b *book) remember(sheet, cell string, v any) {
	if b.cached[sheet] == nil {
		b.cached[sheet] = map[string]any{}
	}
	b.cached[sheet][cell] = v
}

// column sets the width of columns first..last (0-based, inclusive) in characters.
func (s *sheet) column(first, last int, width float64) {
	a, _ := excelize.ColumnNumberToName(first + 1)
	z, _ := excelize.ColumnNumberToName(last + 1)
	s.must(s.b.f.SetColWidth(s.name, a, z, width+colPad))
}

func (s *sheet) rowHeight(row int, height float64) {
	s.must(s.b.f.SetRowHeight(s.name, row+1, height))
}

// freeze fixes the rows above and the columns left of the cell (row, col).
func (s *sheet) freeze(row, col int) {
	panes := &excelize.Panes{Freeze: true, TopLeftCell: s.cell(row, col)}
	switch {
	case row > 0 && col > 0:
		panes.XSplit, panes.YSplit, panes.ActivePane = col, row, "bottomRight"
	case row > 0:
		panes.YSplit, panes.ActivePane = row, "bottomLeft"
	default:
		panes.XSplit, panes.ActivePane = col, "topRight"
	}
	s.must(s.b.f.SetPanes(s.name, panes))
}

// finish saves the workbook and corrects the types of cached results.
func (b *book) finish() ([]byte, error) {
	var buf bytes.Buffer
	if err := b.f.Write(&buf); err != nil {
		return nil, err
	}
	return patch(buf.Bytes(), b)
}

var sheetPart = regexp.MustCompile(`^xl/worksheets/sheet(\d+)\.xml$`)

// patch rewrites the cells with a cached number, bool or error: excelize marks every formula
// cell as text.
func patch(zipped []byte, b *book) ([]byte, error) {
	r, err := zip.NewReader(bytes.NewReader(zipped), int64(len(zipped)))
	if err != nil {
		return nil, err
	}
	var out bytes.Buffer
	w := zip.NewWriter(&out)
	for _, zf := range r.File {
		rc, err := zf.Open()
		if err != nil {
			return nil, err
		}
		data, err := io.ReadAll(rc)
		_ = rc.Close()
		if err != nil {
			return nil, err
		}
		if chartPart.MatchString(zf.Name) {
			data = patchChart(data)
		}
		if m := sheetPart.FindStringSubmatch(zf.Name); m != nil {
			index, _ := strconv.Atoi(m[1])
			if index >= 1 && index <= len(b.sheets) {
				data = patchSheet(data, b.cached[b.sheets[index-1].name])
			}
		}
		fw, err := w.CreateHeader(&zip.FileHeader{Name: zf.Name, Method: zip.Deflate, Modified: zf.Modified})
		if err != nil {
			return nil, err
		}
		if _, err := fw.Write(data); err != nil {
			return nil, err
		}
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

var chartPart = regexp.MustCompile(`^xl/charts/chart\d+\.xml$`)

// naAsBlank is the extension that makes Excel draw #N/A as a gap.
const naAsBlank = `<extLst><ext uri="{56B9EC1D-385E-4148-901F-78D8002777C0}" xmlns:c16r3="http://schemas.microsoft.com/office/drawing/2017/03/chart"><c16r3:dataDisplayOptions16><c16r3:dispNaAsBlank val="1"/></c16r3:dataDisplayOptions16></ext></extLst>`

func patchChart(data []byte) []byte {
	return bytes.Replace(data, []byte("</chart>"), []byte(naAsBlank+"</chart>"), 1)
}

var strCell = regexp.MustCompile(`<c r="([A-Z]+[0-9]+)"((?: s="[0-9]+")?) t="str">(<f>.*?</f>)<v>.*?</v>`)

func patchSheet(data []byte, cached map[string]any) []byte {
	if len(cached) == 0 {
		return data
	}
	return strCell.ReplaceAllFunc(data, func(m []byte) []byte {
		parts := strCell.FindSubmatch(m)
		cell, style, formula := string(parts[1]), string(parts[2]), string(parts[3])
		switch v := cached[cell].(type) {
		case float64:
			return []byte(fmt.Sprintf(`<c r="%s"%s>%s<v>%s</v>`, cell, style, formula, strconv.FormatFloat(v, 'g', -1, 64)))
		case bool:
			return []byte(fmt.Sprintf(`<c r="%s"%s t="b">%s<v>%d</v>`, cell, style, formula, boolInt(v)))
		case errNA:
			return []byte(fmt.Sprintf(`<c r="%s"%s t="e">%s<v>#N/A</v>`, cell, style, formula))
		case string:
			return []byte(fmt.Sprintf(`<c r="%s"%s t="str">%s<v>%s</v>`, cell, style, formula, xmlText(v)))
		}
		return m
	})
}

func boolInt(v bool) int {
	if v {
		return 1
	}
	return 0
}

func xmlText(s string) string {
	var b bytes.Buffer
	_ = xml.EscapeText(&b, []byte(s))
	return b.String()
}
