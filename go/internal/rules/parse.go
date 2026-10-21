package rules

import (
	"fmt"
	"strings"
	"unicode"
)

// SyntaxError is an invalid expression; Position is the offset of the problem in characters
// (not bytes), like the Python core reports it.
type SyntaxError struct {
	Message  string
	Position int
}

func (e *SyntaxError) Error() string { return e.Message }

// Translate turns an English message into the language of the user; the catalog of the texts
// replaces it. Placeholders are {name}, filled from pairs of name and value.
var Translate = func(text string) string { return text }

func msg(text string, pairs ...string) string {
	text = Translate(text)
	if len(pairs) == 0 {
		return text
	}
	// One pass like str.format: inserted text is never expanded again.
	var b strings.Builder
	for i := 0; i < len(text); {
		if text[i] == '{' {
			if end := strings.IndexByte(text[i:], '}'); end > 0 {
				name := text[i+1 : i+end]
				if v, ok := lookup(pairs, name); ok {
					b.WriteString(v)
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

func lookup(pairs []string, name string) (string, bool) {
	for i := 0; i+1 < len(pairs); i += 2 {
		if pairs[i] == name {
			return pairs[i+1], true
		}
	}
	return "", false
}

// lower is str.lower() of Python; Go's ToLower keeps U+0130 as a plain "i".
func lower(s string) string {
	return strings.ToLower(strings.ReplaceAll(s, "\u0130", "i\u0307"))
}

// isSpace is str.isspace() of Python, which also decides \s of its regular expressions: Go's
// unicode.IsSpace lacks the information separators 0x1c to 0x1f.
func isSpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

const (
	tokStr  = "str"
	tokOp   = "op"
	tokWord = "word"
	tokEnd  = "end"
)

type token struct {
	kind string
	text string
	pos  int
}

func (t token) keyword() string {
	if t.kind != tokWord {
		return ""
	}
	switch l := lower(t.text); l {
	case "and", "or", "not", "in":
		return l
	}
	return ""
}

func isKeyword(s string) bool {
	switch lower(s) {
	case "and", "or", "not", "in":
		return true
	}
	return false
}

func isWordRune(r rune) bool {
	return !isSpace(r) && !strings.ContainsRune(`=!~(),"`, r)
}

func tokenize(text string) ([]token, error) {
	rs := []rune(text)
	var tokens []token
	pos := 0
	for {
		start := pos
		for start < len(rs) && isSpace(rs[start]) {
			start++
		}
		if start == len(rs) {
			break
		}
		r := rs[start]
		switch r {
		case '"':
			end, ok := scanString(rs, start)
			if !ok {
				return nil, &SyntaxError{msg("Unterminated quote or unexpected character"), start}
			}
			tokens = append(tokens, token{tokStr, unescape(rs[start+1 : end-1]), start})
			pos = end
		case '!', '=', '~', '(', ')', ',':
			op := string(r)
			if (r == '!') && start+1 < len(rs) && (rs[start+1] == '=' || rs[start+1] == '~') {
				op = string(rs[start : start+2])
			} else if r == '!' {
				return nil, &SyntaxError{msg("Unterminated quote or unexpected character"), start}
			}
			tokens = append(tokens, token{tokOp, op, start})
			pos = start + len([]rune(op))
		default:
			end := start
			for end < len(rs) && isWordRune(rs[end]) {
				end++
			}
			tokens = append(tokens, token{tokWord, string(rs[start:end]), start})
			pos = end
		}
	}
	tokens = append(tokens, token{tokEnd, "", len(rs)})
	return tokens, nil
}

// scanString matches "(?:[^"\\]|\\.)*" at rs[start]; "." does not match a line feed.
func scanString(rs []rune, start int) (end int, ok bool) {
	i := start + 1
	for i < len(rs) {
		switch rs[i] {
		case '"':
			return i + 1, true
		case '\\':
			if i+1 >= len(rs) || rs[i+1] == '\n' {
				return 0, false
			}
			i += 2
		default:
			i++
		}
	}
	return 0, false
}

// unescape is re.sub(r"\\(.)", r"\1", ...): a backslash and the next character (but a line
// feed) become that character.
func unescape(rs []rune) string {
	var b strings.Builder
	for i := 0; i < len(rs); i++ {
		if rs[i] == '\\' && i+1 < len(rs) && rs[i+1] != '\n' {
			i++
		}
		b.WriteRune(rs[i])
	}
	return b.String()
}

type parser struct {
	sources []string
	tokens  []token
	i       int
}

func (p *parser) cur() token { return p.tokens[p.i] }

func (p *parser) next() token {
	t := p.cur()
	p.i++
	return t
}

func (p *parser) isOp(op string) bool { return p.cur().kind == tokOp && p.cur().text == op }

func (p *parser) fail(message string) error { return &SyntaxError{message, p.cur().pos} }

// ParseRule is the rule of an expression; sources are the fields it may name (the fixed ones and
// the configured rule fields, see Sources). The grammar, keywords case-insensitive:
//
//	expr  := and (OR and)*
//	and   := not (AND not)*
//	not   := NOT not | '(' expr ')' | cond
//	cond  := source '=' value | source '!=' value
//	       | source '~' value (contains) | source '!~' value
//	       | source IN '(' value (',' value)* ')' | source NOT IN '(' ... ')'
//	value := word | "quoted text"
//
// A *SyntaxError carries a readable message and the position.
func ParseRule(text string, sources []string) (*Rule, error) {
	tokens, err := tokenize(text)
	if err != nil {
		return nil, err
	}
	p := &parser{sources: sources, tokens: tokens}
	return p.parse()
}

func (p *parser) parse() (*Rule, error) {
	if p.cur().kind == tokEnd {
		return nil, p.fail(msg("The expression is empty"))
	}
	rule, err := p.or()
	if err != nil {
		return nil, err
	}
	if p.cur().kind != tokEnd {
		if p.isOp(")") {
			return nil, p.fail(msg("Closing parenthesis without an opening one"))
		}
		return nil, p.fail(msg("Expected AND, OR or the end, found '{found}'", "found", p.cur().text))
	}
	return rule, nil
}

func (p *parser) or() (*Rule, error) {
	first, err := p.and()
	if err != nil {
		return nil, err
	}
	parts := []*Rule{first}
	for p.cur().keyword() == "or" {
		p.next()
		part, err := p.and()
		if err != nil {
			return nil, err
		}
		parts = append(parts, part)
	}
	return combine(OpAny, parts), nil
}

func (p *parser) and() (*Rule, error) {
	first, err := p.not()
	if err != nil {
		return nil, err
	}
	parts := []*Rule{first}
	for p.cur().keyword() == "and" {
		p.next()
		part, err := p.not()
		if err != nil {
			return nil, err
		}
		parts = append(parts, part)
	}
	return combine(OpAll, parts), nil
}

func (p *parser) not() (*Rule, error) {
	if p.cur().keyword() == "not" {
		p.next()
		inner, err := p.not()
		if err != nil {
			return nil, err
		}
		return &Rule{Op: OpNone, Children: []*Rule{inner}}, nil
	}
	if p.isOp("(") {
		p.next()
		rule, err := p.or()
		if err != nil {
			return nil, err
		}
		if !p.isOp(")") {
			return nil, p.fail(msg("Missing closing parenthesis"))
		}
		p.next()
		return rule, nil
	}
	return p.condition()
}

func (p *parser) condition() (*Rule, error) {
	tok := p.cur()
	if tok.kind != tokWord || tok.keyword() != "" {
		found := tok.text
		if found == "" {
			found = msg("end")
		}
		return nil, p.fail(msg("Expected a field ({fields}), found '{found}'",
			"fields", strings.Join(p.sources, ", "), "found", found))
	}
	source := lower(tok.text)
	if !contains(p.sources, source) {
		if close := closeMatch(source, p.sources); close != "" {
			return nil, p.fail(msg("Unknown field '{source}', did you mean '{close}'?",
				"source", tok.text, "close", close))
		}
		return nil, p.fail(msg("Unknown field '{source}' (allowed: {allowed})",
			"source", tok.text, "allowed", strings.Join(p.sources, ", ")))
	}
	p.next()
	negate := false
	if p.cur().keyword() == "not" {
		p.next()
		negate = true
		if p.cur().keyword() != "in" {
			return nil, p.fail(msg("Expected IN after NOT"))
		}
	}
	contains := false
	var values []string
	switch {
	case p.isOp("=") || p.isOp("!=") || p.isOp("~") || p.isOp("!~"):
		op := p.next().text
		negate = strings.HasPrefix(op, "!")
		contains = strings.HasSuffix(op, "~")
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		values = []string{v}
	case p.cur().keyword() == "in":
		p.next()
		var err error
		if values, err = p.valueList(); err != nil {
			return nil, err
		}
	default:
		return nil, p.fail(msg("Expected =, !=, ~, !~, IN or NOT IN after '{source}'", "source", tok.text))
	}
	if source == "in_sprint" { // the facts carry "true"/"false" in lower case
		for i, v := range values {
			if l := lower(v); l == "true" || l == "false" {
				values[i] = l
			}
		}
	}
	leaf := &Rule{Op: OpLeaf, Source: source, Values: values, Contains: contains}
	if negate {
		return &Rule{Op: OpNone, Children: []*Rule{leaf}}, nil
	}
	return leaf, nil
}

func (p *parser) value() (string, error) {
	tok := p.cur()
	if (tok.kind != tokWord && tok.kind != tokStr) || (tok.kind == tokWord && tok.keyword() != "") {
		found := tok.text
		if found == "" {
			found = msg("end")
		}
		return "", p.fail(msg("Expected a value, found '{found}'", "found", found))
	}
	p.next()
	return tok.text, nil
}

func (p *parser) valueList() ([]string, error) {
	if !p.isOp("(") {
		return nil, p.fail(msg("Expected '(' after IN"))
	}
	p.next()
	v, err := p.value()
	if err != nil {
		return nil, err
	}
	values := []string{v}
	for p.isOp(",") {
		p.next()
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		values = append(values, v)
	}
	if !p.isOp(")") {
		return nil, p.fail(msg("Missing closing parenthesis"))
	}
	p.next()
	return values, nil
}

func combine(op string, parts []*Rule) *Rule {
	if len(parts) == 1 {
		return parts[0]
	}
	var flat []*Rule
	for _, part := range parts {
		if part.Op == op && !part.Short {
			flat = append(flat, part.Children...)
		} else {
			flat = append(flat, part)
		}
	}
	return &Rule{Op: op, Children: flat}
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// MustParse is ParseRule for expressions that are known to be valid (tests, built-in rules).
func MustParse(text string) *Rule {
	r, err := ParseRule(text, Sources)
	if err != nil {
		panic(fmt.Sprintf("rules: %q: %v", text, err))
	}
	return r
}
