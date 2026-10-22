package validate

import (
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/swallat/foresprint/internal/yamlx"
)

// Silent assumptions when loading: a duplicate key still counts as "the last one wins", an
// empty value as 0. The check only makes this visible. Empty values are reported only where a
// number is expected and the program silently reads the empty value as 0.

var emptyAsZero = [][]string{
	{"people", "*", "memberships", "*", "fte"},
	{"planning", "carryover"},
	{"planning", "backlog"},
	{"planning", "corrections", "*"},
	{"absences", "*"},
	{"expected_absences", "*"},
	{"prognoses", "*", "preplanned", "*"},
	{"projects", "*", "priority"},
}

// Mappings whose keys the program reads with str(): there 1 and "1" are the same key.
var strKeyed = [][]string{
	{"products"},
	{"absences"},
	{"expected_absences"},
	{"prognoses", "*", "preplanned"},
	{"tracker", "sprint_names"},
}

const (
	maxVisits = 50_000 // protects against anchor bombs
	maxTime   = 2 * time.Second
	maxIssues = 50
	maxPlaces = 10
)

// part is one step of a path: an index of a list or the text of a key.
type part struct {
	index int
	text  string
	isIdx bool
}

func (p part) String() string {
	if p.isIdx {
		return strconv.Itoa(p.index)
	}
	return p.text
}

// cell is a path as a linked list: depth costs nothing when creating it.
type cell struct {
	parent *cell
	part   part
}

func materialize(c *cell) []part {
	var parts []part
	for ; c != nil; c = c.parent {
		parts = append(parts, c.part)
	}
	for i, j := 0, len(parts)-1; i < j; i, j = i+1, j-1 {
		parts[i], parts[j] = parts[j], parts[i]
	}
	return parts
}

func formatPath(path []part) string {
	var b strings.Builder
	for _, p := range path {
		switch {
		case p.isIdx:
			b.WriteString("[" + strconv.Itoa(p.index) + "]")
		case b.Len() > 0:
			b.WriteString("." + p.text)
		default:
			b.WriteString(p.text)
		}
	}
	return b.String()
}

func matches(path []part, pattern []string) bool {
	if len(path) != len(pattern) {
		return false
	}
	for i, want := range pattern {
		if want != "*" && want != path[i].String() {
			return false
		}
	}
	return true
}

func anyMatches(path []part, patterns [][]string) bool {
	for _, p := range patterns {
		if matches(path, p) {
			return true
		}
	}
	return false
}

func target(n *yaml.Node) *yaml.Node {
	for n.Kind == yaml.AliasNode {
		n = n.Alias
	}
	return n
}

func isEmptyValue(n *yaml.Node) bool {
	if n.Kind != yaml.ScalarNode {
		return false
	}
	tag := yamlx.ScalarTag(n)
	return tag == "!!null" || (tag == "!!str" && n.Value == "")
}

type keyInfo struct {
	shown   string
	compare string
}

// keyOf is the display text and comparison key of a mapping key. With asText (mappings the
// program reads with str()) the text counts, otherwise the type too (1 is not "1"). canon
// belongs to the surrounding mapping: it remembers the text of the first entry per key object.
func keyOf(n *yaml.Node, asText bool, canon map[string]string) keyInfo {
	n = target(n)
	if n.Kind != yaml.ScalarNode {
		id := fmt.Sprintf("%p", n)
		return keyInfo{id, "node" + id}
	}
	var value any
	if yamlx.ScalarTag(n) == "!!str" {
		value = n.Value
	} else if v, err := yamlx.Scalar(n); err == nil {
		value = v
	} else {
		value = n.Value // unusual key: the text is enough
	}
	shown := blankControls(yamlx.PyStr(value))
	c := yamlx.CanonicalKey(value)
	if asText {
		first, ok := canon[c]
		if !ok {
			first = yamlx.PyStr(value)
			canon[c] = first
		}
		return keyInfo{shown, "t" + first}
	}
	return keyInfo{shown, "v" + c}
}

type node2 struct{ key, value *yaml.Node }

// inherited are the entries that n inherits via "<<" and that the loader keeps (PyYAML rules:
// explicit keys always win; with several "<<" in the same mapping the later one, with a list
// "<<: [a, b]" the earlier source; within a source its own keys before those it inherited).
// taken are the keys already assigned.
func inherited(n *yaml.Node, asText bool, canon map[string]string, taken map[string]bool, visiting map[*yaml.Node]bool) []node2 {
	var result []node2
	var merges []*yaml.Node
	for i := 0; i+1 < len(n.Content); i += 2 {
		if yamlx.IsMergeKey(n.Content[i]) {
			merges = append(merges, n.Content[i+1])
		}
	}
	for mi := len(merges) - 1; mi >= 0; mi-- {
		valueNode := target(merges[mi])
		sources := []*yaml.Node{valueNode}
		if valueNode.Kind == yaml.SequenceNode {
			sources = valueNode.Content
		}
		for _, source := range sources {
			source = target(source)
			if source.Kind != yaml.MappingNode || visiting[source] {
				continue
			}
			type own struct {
				node2
				c string
			}
			var fresh []own
			for i := 0; i+1 < len(source.Content); i += 2 {
				if yamlx.IsMergeKey(source.Content[i]) {
					continue
				}
				c := keyOf(source.Content[i], asText, canon).compare
				if !taken[c] {
					fresh = append(fresh, own{node2{source.Content[i], source.Content[i+1]}, c})
				}
			}
			// The original computes the comparison keys of all own entries first, then marks the
			// fresh ones as taken.
			for _, f := range fresh {
				taken[f.c] = true
				result = append(result, f.node2)
			}
			next := map[*yaml.Node]bool{source: true}
			for k := range visiting {
				next[k] = true
			}
			result = append(result, inherited(source, asText, canon, taken, next)...)
		}
	}
	return result
}

type place struct{ line, col int }

func position(found []place) (lines, last string) {
	same := true
	for _, p := range found {
		if p.line != found[0].line {
			same = false
		}
	}
	if same {
		cols := make([]int, len(found))
		for i, p := range found {
			cols[i] = p.col
		}
		return msg("all in line {line}, columns {cols}", "line", strconv.Itoa(found[0].line), "cols", listed(cols)),
			msg("line {line}, column {col}", "line", strconv.Itoa(found[0].line), "col", strconv.Itoa(found[len(found)-1].col))
	}
	nums := make([]int, len(found))
	for i, p := range found {
		nums[i] = p.line
	}
	return msg("lines {lines}", "lines", listed(nums)), msg("line {line}", "line", strconv.Itoa(found[len(found)-1].line))
}

// listed writes numbers as a list, shortened if there are very many.
func listed(numbers []int) string {
	shown := make([]string, 0, maxPlaces)
	for i, n := range numbers {
		if i == maxPlaces {
			break
		}
		shown = append(shown, strconv.Itoa(n))
	}
	s := strings.Join(shown, ", ")
	if len(numbers) > maxPlaces {
		s += msg(" … and {n} more", "n", strconv.Itoa(len(numbers)-maxPlaces))
	}
	return s
}

type step struct {
	node     *yaml.Node
	cell     *cell
	entering bool
}

// CheckYAMLText finds duplicate keys and empty values that are silently read as 0 in a YAML
// file (as notices). name is the file name in the findings.
func CheckYAMLText(text, name string) []Issue {
	root, ok := compose(text)
	if !ok {
		return nil // loading reports invalid YAML as an error
	}
	var issues []Issue
	omitted := 0
	report := func(message string) {
		if len(issues) < maxIssues {
			issues = append(issues, Issue{Warning, name, message})
		} else {
			omitted++
		}
	}
	var stack []step
	if root != nil {
		stack = append(stack, step{root, nil, true})
	}
	active := map[*yaml.Node]bool{}
	visited := map[*yaml.Node]bool{}
	dupDone := map[*yaml.Node]bool{}
	visits, repeats := 0, 0
	stopped := ""
	deadline := time.Now().Add(maxTime)
	for len(stack) > 0 {
		st := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		node := target(st.node)
		if !st.entering {
			delete(active, node)
			continue
		}
		visits++
		if visited[node] {
			repeats++
		}
		visited[node] = true
		if visits > maxVisits || (visits%1024 == 0 && time.Now().After(deadline)) {
			if repeats*2 > visits {
				stopped = msg("The file refers to the same parts (anchors) so often that it was not checked completely.")
			} else {
				stopped = msg("The file is too large or too deeply nested to be checked completely.")
			}
			break
		}
		if node.Kind == yaml.ScalarNode {
			path := materialize(st.cell)
			if isEmptyValue(node) && anyMatches(path, emptyAsZero) {
				report(msg("The value of '{where}' (line {line}) is empty. The program silently counts it as 0. Please enter a number (0 if it really is zero).",
					"where", formatPath(path), "line", strconv.Itoa(node.Line)))
			}
			continue
		}
		if active[node] { // reference to a parent node: do not repeat endlessly
			continue
		}
		active[node] = true
		stack = append(stack, step{node, nil, false})
		var children []step
		if node.Kind == yaml.SequenceNode {
			for i, item := range node.Content {
				children = append(children, step{item, &cell{st.cell, part{index: i, isIdx: true}}, true})
			}
		} else {
			path := materialize(st.cell)
			asText := anyMatches(path, strKeyed)
			canon := map[string]string{}
			type kept struct {
				value *yaml.Node
				text  string
			}
			var order []string
			found := map[string][]place{}
			shown := map[string]string{}
			last := map[string]kept{}
			for i := 0; i+1 < len(node.Content); i += 2 {
				kn := node.Content[i]
				if yamlx.IsMergeKey(kn) {
					continue
				}
				k := keyOf(kn, asText, canon)
				tk := target(kn)
				if _, seen := found[k.compare]; !seen {
					order = append(order, k.compare)
				}
				found[k.compare] = append(found[k.compare], place{tk.Line, tk.Column})
				shown[k.compare] = k.shown
				last[k.compare] = kept{node.Content[i+1], k.shown}
			}
			for _, c := range order {
				children = append(children, step{last[c].value, &cell{st.cell, part{text: last[c].text}}, true})
			}
			taken := map[string]bool{}
			for c := range found {
				taken[c] = true
			}
			for _, e := range inherited(node, asText, canon, taken, map[*yaml.Node]bool{node: true}) {
				children = append(children, step{e.value, &cell{st.cell, part{text: keyOf(e.key, asText, canon).shown}}, true})
			}
			first := !dupDone[node] // references: report only once
			dupDone[node] = true
			for _, c := range order {
				places := found[c]
				if len(places) > 1 && first {
					where := formatPath(append(append([]part{}, path...), part{text: shown[c]}))
					lines, lastPos := position(places)
					report(msg("The key '{where}' appears more than once in the file ({lines}). The program reads only the last entry ({last}); the others are silently ignored. Please delete the extra lines and keep the correct value.",
						"where", where, "lines", lines, "last", lastPos))
				}
			}
		}
		for i := len(children) - 1; i >= 0; i-- {
			stack = append(stack, children[i])
		}
	}
	if omitted > 0 {
		issues = append(issues, Issue{Warning, name, msg("… and {n} more notes in this file", "n", strconv.Itoa(omitted))})
	}
	if stopped != "" {
		issues = append(issues, Issue{Warning, name, stopped})
	}
	return issues
}

// compose parses text into a node tree; ok is false for invalid YAML (and for a stream of several
// documents, which PyYAML's compose refuses). A text without a document gives (nil, true).
func compose(text string) (*yaml.Node, bool) {
	dec := yaml.NewDecoder(strings.NewReader(yamlx.NormalizeDirective(text)))
	var doc yaml.Node
	if err := dec.Decode(&doc); err != nil {
		return nil, errors.Is(err, io.EOF)
	}
	var extra yaml.Node
	if err := dec.Decode(&extra); !errors.Is(err, io.EOF) {
		return nil, false
	}
	if doc.Kind != yaml.DocumentNode || len(doc.Content) == 0 {
		return nil, true
	}
	return doc.Content[0], true
}
