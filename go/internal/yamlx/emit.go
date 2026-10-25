package yamlx

import (
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"
	"time"
)

// Width is the line width of the writer (PyYAML: width=100); text is folded at single spaces
// once the column has passed it.
const Width = 100

const bestIndent = 2

// Dump writes v the way yaml.safe_dump(v, allow_unicode=True, sort_keys=False, width=100) does,
// byte for byte, for the values that Foresprint writes: nil, bool, int, int64, *big.Int,
// float64, string, Date, time.Time, []any, *Map and Map.
//
// A time.Time in UTC is written as a timestamp without a zone (Python's naive datetime), any
// other location with its offset. Values that Python would write with an anchor (the same list
// or mapping object twice) are written twice. A scalar at the top level is not supported.
func Dump(v any) (string, error) {
	e := &emitter{whitespace: true, indention: true}
	switch v.(type) {
	case []any, *Map, Map:
	default:
		return "", fmt.Errorf("yamlx: Dump needs a mapping or a list at the top level, got %T", v)
	}
	if err := e.node(v, ctx{root: true}); err != nil {
		return "", err
	}
	e.writeIndent()
	return e.sb.String(), nil
}

// MustDump is Dump for values that are built by the program itself; it panics on a type error.
func MustDump(v any) string {
	s, err := Dump(v)
	if err != nil {
		panic(err)
	}
	return s
}

type ctx struct {
	root, sequence, mapping, simpleKey bool
}

type emitter struct {
	sb         strings.Builder
	column     int
	whitespace bool
	indention  bool
	indent     int
	hasIndent  bool
	indents    []indentSave
	flowLevel  int
	c          ctx
}

type indentSave struct {
	indent int
	has    bool
}

func (e *emitter) increaseIndent(flow, indentless bool) {
	e.indents = append(e.indents, indentSave{e.indent, e.hasIndent})
	if !e.hasIndent {
		e.hasIndent = true
		if flow {
			e.indent = bestIndent
		} else {
			e.indent = 0
		}
	} else if !indentless {
		e.indent += bestIndent
	}
}

func (e *emitter) popIndent() {
	last := e.indents[len(e.indents)-1]
	e.indents = e.indents[:len(e.indents)-1]
	e.indent, e.hasIndent = last.indent, last.has
}

func (e *emitter) node(v any, c ctx) error {
	e.c = c
	switch x := v.(type) {
	case []any:
		if e.flowLevel > 0 || len(x) == 0 {
			return e.flowSequence(x)
		}
		return e.blockSequence(x)
	case *Map:
		if x == nil {
			return e.flowMapping(nil)
		}
		return e.mapping(x)
	case Map:
		return e.mapping(&x)
	}
	sc, err := scalarOf(v)
	if err != nil {
		return err
	}
	e.increaseIndent(true, false)
	e.processScalar(sc)
	e.popIndent()
	return nil
}

func (e *emitter) mapping(m *Map) error {
	if e.flowLevel > 0 || len(m.Entries) == 0 {
		return e.flowMapping(m)
	}
	e.increaseIndent(false, false)
	for _, en := range m.Entries {
		e.writeIndent()
		simple, err := checkSimpleKey(en.Key)
		if err != nil {
			return err
		}
		if simple {
			if err := e.node(en.Key, ctx{mapping: true, simpleKey: true}); err != nil {
				return err
			}
			e.writeIndicator(":", false, false, false)
			if err := e.node(en.Value, ctx{mapping: true}); err != nil {
				return err
			}
			continue
		}
		e.writeIndicator("?", true, false, true)
		if err := e.node(en.Key, ctx{mapping: true}); err != nil {
			return err
		}
		e.writeIndent()
		e.writeIndicator(":", true, false, true)
		if err := e.node(en.Value, ctx{mapping: true}); err != nil {
			return err
		}
	}
	e.popIndent()
	return nil
}

func (e *emitter) blockSequence(s []any) error {
	indentless := e.c.mapping && !e.indention
	e.increaseIndent(false, indentless)
	for _, item := range s {
		e.writeIndent()
		e.writeIndicator("-", true, false, true)
		if err := e.node(item, ctx{sequence: true}); err != nil {
			return err
		}
	}
	e.popIndent()
	return nil
}

// flowSequence and flowMapping are only used for empty collections (the writer has no flow
// style for the others, like safe_dump with the default flow style).
func (e *emitter) flowSequence(s []any) error {
	if len(s) > 0 {
		return fmt.Errorf("yamlx: non-empty flow sequence inside a flow collection")
	}
	e.writeIndicator("[", true, true, false)
	e.flowLevel++
	e.increaseIndent(true, false)
	e.popIndent()
	e.flowLevel--
	e.writeIndicator("]", false, false, false)
	return nil
}

func (e *emitter) flowMapping(m *Map) error {
	if m != nil && len(m.Entries) > 0 {
		return fmt.Errorf("yamlx: non-empty flow mapping inside a flow collection")
	}
	e.writeIndicator("{", true, true, false)
	e.flowLevel++
	e.increaseIndent(true, false)
	e.popIndent()
	e.flowLevel--
	e.writeIndicator("}", false, false, false)
	return nil
}

// checkSimpleKey: a key may be written on the line of its value when it is a short single-line
// scalar or an empty collection; anything else uses the "? key" form.
func checkSimpleKey(k any) (bool, error) {
	switch x := k.(type) {
	case []any:
		return len(x) == 0, nil
	case *Map:
		return x == nil || len(x.Entries) == 0, nil
	case Map:
		return len(x.Entries) == 0, nil
	}
	sc, err := scalarOf(k)
	if err != nil {
		return false, err
	}
	a := analyze(sc.text)
	// PyYAML also counts the length of the explicit tag ("!!str") that it prepares for the key.
	return len([]rune(sc.text))+len(tagName(k)) < 128 && !a.empty && !a.multiline, nil
}

// scalar is the text of a scalar and whether it may be written without quotes ("implicit"): the
// reader would resolve the plain text to the same type.
type scalar struct {
	text          string
	plainImplicit bool
}

func scalarOf(v any) (scalar, error) {
	switch x := v.(type) {
	case nil:
		return scalar{"null", true}, nil
	case bool:
		if x {
			return scalar{"true", true}, nil
		}
		return scalar{"false", true}, nil
	case int:
		return scalar{strconv.Itoa(x), true}, nil
	case int64:
		return scalar{strconv.FormatInt(x, 10), true}, nil
	case *big.Int:
		return scalar{x.String(), true}, nil
	case float64:
		return scalar{floatText(x), true}, nil
	case string:
		return scalar{x, !resolvesToNonString(x)}, nil
	case Date:
		return scalar{time.Time(x).Format("2006-01-02"), true}, nil
	case time.Time:
		return scalar{timestampText(x), true}, nil
	}
	return scalar{}, fmt.Errorf("yamlx: cannot write a value of type %T", v)
}

// timestampText is Python's datetime.isoformat(" ").
func timestampText(t time.Time) string {
	s := t.Format("2006-01-02 15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += fmt.Sprintf(".%06d", us)
	}
	if t.Location() != time.UTC {
		s += t.Format("-07:00")
	}
	return s
}

// floatText is PyYAML's representation of a float: Python's repr, lower case, with ".0" before
// the exponent when there is no decimal point; ".nan", ".inf", "-.inf".
func floatText(f float64) string {
	switch {
	case math.IsNaN(f):
		return ".nan"
	case math.IsInf(f, 1):
		return ".inf"
	case math.IsInf(f, -1):
		return "-.inf"
	}
	s := pyFloatRepr(f)
	if !strings.Contains(s, ".") && strings.Contains(s, "e") {
		s = strings.Replace(s, "e", ".0e", 1)
	}
	return s
}

// pyFloatRepr is repr(float) of Python: the shortest digits that round-trip, positional for
// decimal exponents -4 to 15, otherwise d.ddde+XX with at least two exponent digits.
func pyFloatRepr(f float64) string {
	if f == 0 {
		if math.Signbit(f) {
			return "-0.0"
		}
		return "0.0"
	}
	s := strconv.FormatFloat(f, 'e', -1, 64) // -d.ddde+XX
	sign := ""
	if s[0] == '-' {
		sign, s = "-", s[1:]
	}
	mant, expText, _ := strings.Cut(s, "e")
	exp, _ := strconv.Atoi(expText)
	digits := strings.Replace(mant, ".", "", 1)
	if exp < -4 || exp >= 16 {
		out := digits[:1]
		if len(digits) > 1 {
			out += "." + digits[1:]
		}
		esign := "+"
		if exp < 0 {
			esign, exp = "-", -exp
		}
		return fmt.Sprintf("%s%se%s%02d", sign, out, esign, exp)
	}
	switch {
	case exp < 0:
		return sign + "0." + strings.Repeat("0", -exp-1) + digits
	case exp+1 >= len(digits):
		return sign + digits + strings.Repeat("0", exp+1-len(digits)) + ".0"
	}
	return sign + digits[:exp+1] + "." + digits[exp+1:]
}

// --- scalar analysis and styles ---------------------------------------------------------

type analysis struct {
	empty, multiline, allowFlowPlain, allowBlockPlain, allowSingle bool
}

func isBreak(r rune) bool { return r == '\n' || r == 0x85 || r == 0x2028 || r == 0x2029 }

func isSpaceLike(r rune) bool {
	return r == 0 || r == ' ' || r == '\t' || r == '\r' || isBreak(r)
}

func analyze(text string) analysis {
	s := []rune(text)
	if len(s) == 0 {
		return analysis{empty: true, allowBlockPlain: true, allowSingle: true}
	}
	var blockInd, flowInd, lineBreaks, special bool
	var leadingSpace, leadingBreak, trailingSpace, trailingBreak, breakSpace, spaceBreak bool
	if strings.HasPrefix(text, "---") || strings.HasPrefix(text, "...") {
		blockInd, flowInd = true, true
	}
	precededByWS := true
	followedByWS := len(s) == 1 || isSpaceLike(s[1])
	var prevSpace, prevBreak bool
	for i := 0; i < len(s); i++ {
		ch := s[i]
		if i == 0 {
			if strings.ContainsRune("#,[]{}&*!|>'\"%@`", ch) {
				flowInd, blockInd = true, true
			}
			if ch == '?' || ch == ':' {
				flowInd = true
				if followedByWS {
					blockInd = true
				}
			}
			if ch == '-' && followedByWS {
				flowInd, blockInd = true, true
			}
		} else {
			if strings.ContainsRune(",?[]{}", ch) {
				flowInd = true
			}
			if ch == ':' {
				flowInd = true
				if followedByWS {
					blockInd = true
				}
			}
			if ch == '#' && precededByWS {
				flowInd, blockInd = true, true
			}
		}
		if isBreak(ch) {
			lineBreaks = true
		}
		if ch != '\n' && (ch < 0x20 || ch > 0x7E) {
			ok := ch == 0x85 || (ch >= 0xA0 && ch <= 0xD7FF) || (ch >= 0xE000 && ch <= 0xFFFD) ||
				(ch >= 0x10000 && ch < 0x10ffff)
			if !ok || ch == 0xFEFF {
				special = true
			}
		}
		switch {
		case ch == ' ':
			if i == 0 {
				leadingSpace = true
			}
			if i == len(s)-1 {
				trailingSpace = true
			}
			if prevBreak {
				breakSpace = true
			}
			prevSpace, prevBreak = true, false
		case isBreak(ch):
			if i == 0 {
				leadingBreak = true
			}
			if i == len(s)-1 {
				trailingBreak = true
			}
			if prevSpace {
				spaceBreak = true
			}
			prevSpace, prevBreak = false, true
		default:
			prevSpace, prevBreak = false, false
		}
		precededByWS = isSpaceLike(ch)
		followedByWS = i+2 >= len(s) || isSpaceLike(s[i+2])
	}
	a := analysis{multiline: lineBreaks, allowFlowPlain: true, allowBlockPlain: true, allowSingle: true}
	if leadingSpace || leadingBreak || trailingSpace || trailingBreak {
		a.allowFlowPlain, a.allowBlockPlain = false, false
	}
	if breakSpace {
		a.allowFlowPlain, a.allowBlockPlain, a.allowSingle = false, false, false
	}
	if spaceBreak || special {
		a.allowFlowPlain, a.allowBlockPlain, a.allowSingle = false, false, false
	}
	if lineBreaks {
		a.allowFlowPlain, a.allowBlockPlain = false, false
	}
	if flowInd {
		a.allowFlowPlain = false
	}
	if blockInd {
		a.allowBlockPlain = false
	}
	return a
}

func (e *emitter) processScalar(sc scalar) {
	a := analyze(sc.text)
	split := !e.c.simpleKey
	plain := sc.plainImplicit &&
		(!e.c.simpleKey || (!a.empty && !a.multiline)) &&
		((e.flowLevel > 0 && a.allowFlowPlain) || (e.flowLevel == 0 && a.allowBlockPlain))
	switch {
	case plain:
		e.writePlain(sc.text, split)
	case a.allowSingle && (!e.c.simpleKey || !a.multiline):
		e.writeSingleQuoted(sc.text, split)
	default:
		e.writeDoubleQuoted(sc.text, split)
	}
}

// --- writers ----------------------------------------------------------------------------

func (e *emitter) write(s string) { e.sb.WriteString(s) }

func (e *emitter) writeIndicator(indicator string, needWhitespace, whitespace, indention bool) {
	data := indicator
	if !e.whitespace && needWhitespace {
		data = " " + indicator
	}
	e.whitespace = whitespace
	e.indention = e.indention && indention
	e.column += len([]rune(data))
	e.write(data)
}

func (e *emitter) writeIndent() {
	indent := 0
	if e.hasIndent {
		indent = e.indent
	}
	if !e.indention || e.column > indent || (e.column == indent && !e.whitespace) {
		e.writeLineBreak("\n")
	}
	if e.column < indent {
		e.whitespace = true
		e.write(strings.Repeat(" ", indent-e.column))
		e.column = indent
	}
}

func (e *emitter) writeLineBreak(data string) {
	e.whitespace = true
	e.indention = true
	e.column = 0
	e.write(data)
}

func (e *emitter) writeRunes(r []rune) {
	e.column += len(r)
	e.write(string(r))
}

func (e *emitter) writePlain(text string, split bool) {
	if text == "" {
		return
	}
	t := []rune(text)
	if !e.whitespace {
		e.column++
		e.write(" ")
	}
	e.whitespace = false
	e.indention = false
	spaces, breaks := false, false
	start, end := 0, 0
	for end <= len(t) {
		var ch rune
		has := end < len(t)
		if has {
			ch = t[end]
		}
		switch {
		case spaces:
			if !has || ch != ' ' {
				if start+1 == end && e.column > Width && split {
					e.writeIndent()
					e.whitespace = false
					e.indention = false
				} else {
					e.writeRunes(t[start:end])
				}
				start = end
			}
		case breaks:
			if !has || !isBreak(ch) {
				if t[start] == '\n' {
					e.writeLineBreak("\n")
				}
				for _, br := range t[start:end] {
					e.writeLineBreak(string(br))
				}
				e.writeIndent()
				e.whitespace = false
				e.indention = false
				start = end
			}
		default:
			if !has || ch == ' ' || isBreak(ch) {
				e.writeRunes(t[start:end])
				start = end
			}
		}
		if has {
			spaces = ch == ' '
			breaks = isBreak(ch)
		}
		end++
	}
}

func (e *emitter) writeSingleQuoted(text string, split bool) {
	e.writeIndicator("'", true, false, false)
	t := []rune(text)
	spaces, breaks := false, false
	start, end := 0, 0
	for end <= len(t) {
		var ch rune
		has := end < len(t)
		if has {
			ch = t[end]
		}
		switch {
		case spaces:
			if !has || ch != ' ' {
				if start+1 == end && e.column > Width && split && start != 0 && end != len(t) {
					e.writeIndent()
				} else {
					e.writeRunes(t[start:end])
				}
				start = end
			}
		case breaks:
			if !has || !isBreak(ch) {
				if t[start] == '\n' {
					e.writeLineBreak("\n")
				}
				for _, br := range t[start:end] {
					e.writeLineBreak(string(br))
				}
				e.writeIndent()
				start = end
			}
		default:
			if !has || ch == ' ' || isBreak(ch) || ch == '\'' {
				if start < end {
					e.writeRunes(t[start:end])
					start = end
				}
			}
		}
		if has && ch == '\'' {
			e.column += 2
			e.write("''")
			start = end + 1
		}
		if has {
			spaces = ch == ' '
			breaks = isBreak(ch)
		}
		end++
	}
	e.writeIndicator("'", false, false, false)
}

var escapes = map[rune]string{
	0: "0", 7: "a", 8: "b", 9: "t", 10: "n", 11: "v", 12: "f", 13: "r", 0x1B: "e",
	'"': "\"", '\\': "\\", 0x85: "N", 0xA0: "_", 0x2028: "L", 0x2029: "P",
}

func (e *emitter) writeDoubleQuoted(text string, split bool) {
	e.writeIndicator("\"", true, false, false)
	t := []rune(text)
	start, end := 0, 0
	for end <= len(t) {
		var ch rune
		has := end < len(t)
		if has {
			ch = t[end]
		}
		printable := (ch >= 0x20 && ch <= 0x7E) || (ch >= 0xA0 && ch <= 0xD7FF) || (ch >= 0xE000 && ch <= 0xFFFD)
		if !has || ch == '"' || ch == '\\' || ch == 0x85 || ch == 0x2028 || ch == 0x2029 || ch == 0xFEFF || !printable {
			if start < end {
				e.writeRunes(t[start:end])
				start = end
			}
			if has {
				var data string
				r, ok := escapes[ch]
				switch {
				case ok:
					data = "\\" + r
				case ch <= 0xFF:
					data = fmt.Sprintf("\\x%02X", ch)
				case ch <= 0xFFFF:
					data = fmt.Sprintf("\\u%04X", ch)
				default:
					data = fmt.Sprintf("\\U%08X", ch)
				}
				e.column += len([]rune(data))
				e.write(data)
				start = end + 1
			}
		}
		if 0 < end && end < len(t)-1 && (ch == ' ' || start >= end) && e.column+(end-start) > Width && split {
			data := "\\"
			if start < end {
				data = string(t[start:end]) + data
				start = end
			}
			e.column += len([]rune(data))
			e.write(data)
			e.writeIndent()
			e.whitespace = false
			e.indention = false
			if t[start] == ' ' {
				e.column++
				e.write("\\")
			}
		}
		end++
	}
	e.writeIndicator("\"", false, false, false)
}

// tagName is the short tag PyYAML writes for the type of a scalar ("!!str"); it only counts
// towards the length of a simple key.
func tagName(v any) string {
	switch v.(type) {
	case nil:
		return "!!null"
	case bool:
		return "!!bool"
	case int, int64, *big.Int:
		return "!!int"
	case float64:
		return "!!float"
	case Date, time.Time:
		return "!!timestamp"
	}
	return "!!str"
}
