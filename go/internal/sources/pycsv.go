package sources

import (
	"fmt"
	"strings"
)

// csvReader reads CSV like Python's csv.reader with the default dialect ("excel") and
// strict=True. It is a port of the state machine of _csv.c, because the error cases and the
// treatment of line ends differ from encoding/csv.

const csvFieldLimit = 131072

type csvState int

const (
	csvStartRecord csvState = iota
	csvStartField
	csvInField
	csvInQuotedField
	csvQuoteInQuotedField
	csvEatCRNL
)

type csvError struct{ msg string }

func (e *csvError) Error() string { return e.msg }

type csvReader struct {
	lines     []string // the lines of the text, each with its "\n" (io.StringIO splits at "\n" only)
	next      int
	delimiter rune

	// LineNum is the number of lines read so far.
	LineNum int

	state  csvState
	field  []rune
	record []string
}

func newCSVReader(text string, delimiter rune) *csvReader {
	var lines []string
	for text != "" {
		i := strings.IndexByte(text, '\n')
		if i < 0 {
			lines = append(lines, text)
			break
		}
		lines = append(lines, text[:i+1])
		text = text[i+1:]
	}
	return &csvReader{lines: lines, delimiter: delimiter}
}

func (r *csvReader) saveField() {
	r.record = append(r.record, string(r.field))
	r.field = r.field[:0]
}

func (r *csvReader) addChar(c rune) error {
	if len(r.field) >= csvFieldLimit {
		return &csvError{fmt.Sprintf("field larger than field limit (%d)", csvFieldLimit)}
	}
	r.field = append(r.field, c)
	return nil
}

func isCRNL(c rune) bool { return c == '\n' || c == '\r' }

const endOfLine rune = -2

// process handles one character (or the end of a line); it mirrors parse_process_char.
func (r *csvReader) process(c rune) error {
	switch r.state {
	case csvStartRecord:
		if c == endOfLine {
			return nil // an empty line
		}
		if isCRNL(c) {
			r.state = csvEatCRNL
			return nil
		}
		r.state = csvStartField
		return r.process(c)
	case csvStartField:
		switch {
		case c == endOfLine:
			r.saveField()
			r.state = csvStartRecord
		case isCRNL(c):
			r.saveField()
			r.state = csvEatCRNL
		case c == '"':
			r.state = csvInQuotedField
		case c == r.delimiter:
			r.saveField()
		default:
			if err := r.addChar(c); err != nil {
				return err
			}
			r.state = csvInField
		}
	case csvInField:
		switch {
		case c == endOfLine:
			r.saveField()
			r.state = csvStartRecord
		case isCRNL(c):
			r.saveField()
			r.state = csvEatCRNL
		case c == r.delimiter:
			r.saveField()
			r.state = csvStartField
		default:
			return r.addChar(c)
		}
	case csvInQuotedField:
		switch c {
		case endOfLine:
		case '"':
			r.state = csvQuoteInQuotedField
		default:
			return r.addChar(c)
		}
	case csvQuoteInQuotedField:
		switch {
		case c == '"':
			if err := r.addChar(c); err != nil {
				return err
			}
			r.state = csvInQuotedField
		case c == r.delimiter:
			r.saveField()
			r.state = csvStartField
		case c == endOfLine:
			r.saveField()
			r.state = csvStartRecord
		case isCRNL(c):
			r.saveField()
			r.state = csvEatCRNL
		default:
			return &csvError{fmt.Sprintf("'%c' expected after '\"'", r.delimiter)}
		}
	case csvEatCRNL:
		switch {
		case isCRNL(c):
		case c == endOfLine:
			r.state = csvStartRecord
		default:
			return &csvError{"new-line character seen in unquoted field - do you need to open " +
				"the file with newline=''?"}
		}
	}
	return nil
}

// Read returns the next record, or (nil, false, nil) at the end of the text. An empty line gives
// an empty record.
func (r *csvReader) Read() ([]string, bool, error) {
	r.record = nil
	r.field = r.field[:0]
	r.state = csvStartRecord
	for {
		if r.next >= len(r.lines) {
			if r.state != csvStartRecord {
				return nil, false, &csvError{"unexpected end of data"}
			}
			return nil, false, nil
		}
		line := r.lines[r.next]
		r.next++
		r.LineNum++
		for _, c := range line {
			if err := r.process(c); err != nil {
				return nil, false, err
			}
		}
		if err := r.process(endOfLine); err != nil {
			return nil, false, err
		}
		if r.state == csvStartRecord {
			rec := r.record
			if rec == nil {
				rec = []string{}
			}
			return rec, true, nil
		}
	}
}
