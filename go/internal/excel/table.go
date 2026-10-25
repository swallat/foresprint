package excel

import (
	"fmt"
	"math"
	"strconv"
	"time"
)

// Limits of a table: a cell far away from the others must not make a huge grid.
const (
	maxTableWidth = 1024
	maxTableRows  = 200000
)

// Table reads one sheet of a workbook as rows of text (cached values, as a user sees them):
// the first sheet when name is empty. Empty rows at the end are dropped, rows are padded to the
// same width. The names of the sheets are returned too, for a choice.
func Table(source []byte, name string) (rows [][]string, sheets []string, err error) {
	wb, err := openWorkbook(source)
	if err != nil {
		return nil, nil, dataErr("The file is not a readable Excel workbook: {error}", "error", err.Error())
	}
	sheets = append(sheets, wb.names...)
	if name == "" && len(wb.names) > 0 {
		name = wb.names[0]
	}
	ws := wb.sheets[name]
	if ws == nil {
		return nil, sheets, dataErr("The workbook has no sheet {name}.", "name", name)
	}
	width := 0
	for _, cols := range ws.rows {
		for c := range cols {
			width = max(width, c+1)
		}
	}
	if width > maxTableWidth || ws.last > maxTableRows {
		return nil, sheets, dataErr("The sheet is too large for a table (at most {cols} columns and {rows} rows).",
			"cols", maxTableWidth, "rows", maxTableRows)
	}
	for r := 1; r <= ws.last; r++ {
		row := make([]string, width)
		for c, v := range ws.rows[r] {
			row[c] = tableText(v)
		}
		rows = append(rows, row)
	}
	for len(rows) > 0 && rowEmpty(rows[len(rows)-1]) {
		rows = rows[:len(rows)-1]
	}
	return rows, sheets, nil
}

func rowEmpty(row []string) bool {
	for _, c := range row {
		if c != "" {
			return false
		}
	}
	return true
}

// tableText is the text of a cell value: whole numbers without decimals, dates as ISO dates.
func tableText(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		if x == math.Trunc(x) && math.Abs(x) < 1e15 {
			return strconv.FormatInt(int64(x), 10)
		}
		f, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'g', 15, 64), 64) // Excel shows 15 digits
		return strconv.FormatFloat(f, 'f', -1, 64)
	case bool:
		if x {
			return "TRUE"
		}
		return "FALSE"
	case time.Time:
		if x.Hour() == 0 && x.Minute() == 0 && x.Second() == 0 {
			return x.Format("2006-01-02")
		}
		return x.Format("2006-01-02 15:04:05")
	}
	return fmt.Sprint(v)
}
