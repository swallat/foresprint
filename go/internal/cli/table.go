package cli

import (
	"fmt"
	"io"
	"strings"
	"unicode/utf8"
)

// Table is a plain text table: a title, a header, rows and an optional note below. Columns are
// separated by two spaces; the columns marked right are aligned to the right edge.
type Table struct {
	Title   string
	Header  []string
	Right   []bool
	Rows    [][]string
	Caption string
}

// Add appends a row.
func (t *Table) Add(cells ...string) { t.Rows = append(t.Rows, cells) }

// Render writes the table.
func (t *Table) Render(w io.Writer) {
	widths := make([]int, len(t.Header))
	measure := func(row []string) {
		for i, c := range row {
			if n := utf8.RuneCountInString(c); i < len(widths) && n > widths[i] {
				widths[i] = n
			}
		}
	}
	measure(t.Header)
	for _, r := range t.Rows {
		measure(r)
	}
	line := func(row []string) {
		parts := make([]string, len(widths))
		for i := range widths {
			cell := ""
			if i < len(row) {
				cell = row[i]
			}
			pad := strings.Repeat(" ", widths[i]-utf8.RuneCountInString(cell))
			if i < len(t.Right) && t.Right[i] {
				parts[i] = pad + cell
			} else {
				parts[i] = cell + pad
			}
		}
		_, _ = fmt.Fprintln(w, strings.TrimRight(strings.Join(parts, "  "), " "))
	}
	if t.Title != "" {
		_, _ = fmt.Fprintln(w, t.Title)
	}
	line(t.Header)
	total := 2 * (len(widths) - 1)
	for _, n := range widths {
		total += n
	}
	_, _ = fmt.Fprintln(w, strings.Repeat("─", total))
	for _, r := range t.Rows {
		line(r)
	}
	if t.Caption != "" {
		_, _ = fmt.Fprintln(w, t.Caption)
	}
}
