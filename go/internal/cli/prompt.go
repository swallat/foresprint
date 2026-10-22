package cli

import (
	"bufio"
	"errors"
	"io"
	"math"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/i18n"
)

// errAborted ends a command whose input stream is closed while it still asks.
func errAborted() error { return &Fail{Msg: i18n.T("Aborted.")} }

// readLine reads one line of the input without the line end; io.EOF at the end of the input
// when nothing was read.
func (e *Env) readLine() (string, error) {
	if e.input == nil {
		e.input = bufio.NewReader(e.In)
	}
	line, err := e.input.ReadString('\n')
	if err != nil && (err != io.EOF || line == "") {
		return "", err
	}
	line = strings.TrimRight(line, "\r\n")
	if !e.interactive() {
		e.Println(line) // a terminal shows what is typed; a pipe does not
	}
	return line, nil
}

// interactive reports whether the input is a terminal.
func (e *Env) interactive() bool {
	f, ok := e.In.(*os.File)
	if !ok {
		return false
	}
	info, err := f.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}

// Ask prints the question with the default in parentheses and returns the answer; an empty
// answer is the default.
func (e *Env) Ask(label, def string) (string, error) {
	prompt := label
	if def != "" {
		prompt += " (" + def + ")"
	}
	e.Printf("%s: ", prompt)
	line, err := e.readLine()
	if err != nil {
		e.Println()
		return "", errAborted()
	}
	if strings.TrimSpace(line) == "" {
		return def, nil
	}
	return line, nil
}

// Confirm asks a yes/no question; an empty answer is the default.
func (e *Env) Confirm(label string, def bool) (bool, error) {
	hint, short := "[y/n]", "n"
	if def {
		short = "y"
	}
	for {
		e.Printf("%s %s (%s): ", label, hint, short)
		line, err := e.readLine()
		if err != nil {
			e.Println()
			return false, errAborted()
		}
		switch strings.ToLower(strings.TrimSpace(line)) {
		case "":
			return def, nil
		case "y", "yes", "j", "ja":
			return true, nil
		case "n", "no", "nein":
			return false, nil
		}
		e.Println(i18n.P("Please enter y or n."))
	}
}

// parseNumber reads a number with comma or point as decimal separator.
func parseNumber(raw string) (float64, error) {
	return strconv.ParseFloat(strings.ReplaceAll(strings.TrimSpace(raw), ",", "."), 64)
}

// AskNumber asks for a number >= minimum; nil for an empty answer if allowEmpty.
func (e *Env) AskNumber(label string, def *float64, allowEmpty bool, minimum float64) (*float64, error) {
	hint := ""
	if allowEmpty {
		hint = " (" + i18n.P("empty = not specified") + ")"
	}
	shown := ""
	if def != nil {
		shown = plainNumber(*def)
	}
	for {
		raw, err := e.Ask(label+hint, shown)
		if err != nil {
			return nil, err
		}
		raw = strings.TrimSpace(raw)
		if raw == "" {
			if allowEmpty {
				return nil, nil
			}
			e.Println(i18n.P("Please enter a value."))
			continue
		}
		v, err := parseNumber(raw)
		var numErr *strconv.NumError
		if errors.As(err, &numErr) && !errors.Is(err, strconv.ErrRange) {
			e.Println(i18n.P("Please enter a number (decimal separator , or .)."))
			continue
		}
		if math.IsNaN(v) || math.IsInf(v, 0) {
			e.Println(i18n.P("Please enter a finite number."))
			continue
		}
		if v < minimum {
			e.Println(i18n.P("The value must be ≥ {value}.", "value", plainNumber(minimum)))
			continue
		}
		return &v, nil
	}
}

// AskNumbers asks for numbers separated by spaces.
func (e *Env) AskNumbers(label string, def []float64) ([]float64, error) {
	parts := make([]string, len(def))
	for i, v := range def {
		parts[i] = plainNumber(v)
	}
	for {
		raw, err := e.Ask(label, strings.Join(parts, " "))
		if err != nil {
			return nil, err
		}
		var values []float64
		ok := true
		for _, f := range strings.Fields(raw) {
			v, err := parseNumber(f)
			if err != nil && !errors.Is(err, strconv.ErrRange) {
				ok = false
				break
			}
			values = append(values, v)
		}
		if !ok {
			e.Println(i18n.P("Please enter numbers separated by spaces."))
			continue
		}
		finite := true
		for _, v := range values {
			finite = finite && !math.IsInf(v, 0) && !math.IsNaN(v)
		}
		if !finite {
			e.Println(i18n.P("Please enter a finite number."))
			continue
		}
		return values, nil
	}
}

// AskDate asks for a date as YYYY-MM-DD.
func (e *Env) AskDate(label string, def *time.Time) (time.Time, error) {
	shown := ""
	if def != nil {
		shown = def.Format("2006-01-02")
	}
	for {
		raw, err := e.Ask(label+" ("+i18n.P("YYYY-MM-DD")+")", shown)
		if err != nil {
			return time.Time{}, err
		}
		d, err := time.Parse("2006-01-02", strings.TrimSpace(raw))
		if err == nil {
			return d, nil
		}
		e.Println(i18n.P("Please enter the date as YYYY-MM-DD."))
	}
}
