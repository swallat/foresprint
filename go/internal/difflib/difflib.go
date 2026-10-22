// Package difflib ports the parts of Python's difflib that the core uses: SequenceMatcher (with
// autojunk and without a junk function), grouped opcodes and unified_diff. The result is the
// same as Python's, line for line, because the algorithm is not a minimal diff: it looks for the
// longest matching block and recurses on both sides.
package difflib

import (
	"sort"
	"strconv"
	"strings"
)

// Match is a block of equal lines: a[A:A+Size] == b[B:B+Size].
type Match struct{ A, B, Size int }

// Opcode describes how to turn a[I1:I2] into b[J1:J2]. Tag is "equal", "replace", "delete" or
// "insert".
type Opcode struct {
	Tag            string
	I1, I2, J1, J2 int
}

// Matcher is difflib.SequenceMatcher(None, a, b) with autojunk.
type Matcher struct {
	a, b    []string
	b2j     map[string][]int
	matches []Match
}

// NewMatcher prepares the comparison of a and b.
func NewMatcher(a, b []string) *Matcher {
	m := &Matcher{a: a, b: b, b2j: map[string][]int{}}
	m.chainB()
	return m
}

func (m *Matcher) chainB() {
	for i, elt := range m.b {
		m.b2j[elt] = append(m.b2j[elt], i)
	}
	// Purge elements that appear often (autojunk).
	if n := len(m.b); n >= 200 {
		ntest := n/100 + 1
		for elt, idxs := range m.b2j {
			if len(idxs) > ntest {
				delete(m.b2j, elt)
			}
		}
	}
}

// findLongestMatch returns the longest matching block in a[alo:ahi] and b[blo:bhi]; of several
// of the same length, the one that starts earliest in a, and of those the one that starts
// earliest in b.
func (m *Matcher) findLongestMatch(alo, ahi, blo, bhi int) Match {
	besti, bestj, bestsize := alo, blo, 0
	j2len := map[int]int{}
	for i := alo; i < ahi; i++ {
		newj2len := map[int]int{}
		for _, j := range m.b2j[m.a[i]] {
			if j < blo {
				continue
			}
			if j >= bhi {
				break
			}
			k := j2len[j-1] + 1
			newj2len[j] = k
			if k > bestsize {
				besti, bestj, bestsize = i-k+1, j-k+1, k
			}
		}
		j2len = newj2len
	}
	// Extend the match with equal lines on both sides (also popular ones that autojunk dropped).
	for besti > alo && bestj > blo && m.a[besti-1] == m.b[bestj-1] {
		besti, bestj, bestsize = besti-1, bestj-1, bestsize+1
	}
	for besti+bestsize < ahi && bestj+bestsize < bhi && m.a[besti+bestsize] == m.b[bestj+bestsize] {
		bestsize++
	}
	return Match{besti, bestj, bestsize}
}

// MatchingBlocks returns the blocks of equal lines, increasing in both sequences, adjacent
// blocks joined; the last one is the sentinel (len(a), len(b), 0).
func (m *Matcher) MatchingBlocks() []Match {
	if m.matches != nil {
		return m.matches
	}
	la, lb := len(m.a), len(m.b)
	type span struct{ alo, ahi, blo, bhi int }
	queue := []span{{0, la, 0, lb}}
	var blocks []Match
	for len(queue) > 0 {
		s := queue[len(queue)-1]
		queue = queue[:len(queue)-1]
		x := m.findLongestMatch(s.alo, s.ahi, s.blo, s.bhi)
		if x.Size == 0 {
			continue
		}
		blocks = append(blocks, x)
		if s.alo < x.A && s.blo < x.B {
			queue = append(queue, span{s.alo, x.A, s.blo, x.B})
		}
		if x.A+x.Size < s.ahi && x.B+x.Size < s.bhi {
			queue = append(queue, span{x.A + x.Size, s.ahi, x.B + x.Size, s.bhi})
		}
	}
	sort.Slice(blocks, func(i, j int) bool {
		if blocks[i].A != blocks[j].A {
			return blocks[i].A < blocks[j].A
		}
		if blocks[i].B != blocks[j].B {
			return blocks[i].B < blocks[j].B
		}
		return blocks[i].Size < blocks[j].Size
	})
	var joined []Match
	cur := Match{}
	for _, blk := range blocks {
		if cur.A+cur.Size == blk.A && cur.B+cur.Size == blk.B {
			cur.Size += blk.Size
			continue
		}
		if cur.Size > 0 {
			joined = append(joined, cur)
		}
		cur = blk
	}
	if cur.Size > 0 {
		joined = append(joined, cur)
	}
	joined = append(joined, Match{la, lb, 0})
	m.matches = joined
	return joined
}

// Opcodes returns the steps that turn a into b.
func (m *Matcher) Opcodes() []Opcode {
	i, j := 0, 0
	var answer []Opcode
	for _, blk := range m.MatchingBlocks() {
		tag := ""
		switch {
		case i < blk.A && j < blk.B:
			tag = "replace"
		case i < blk.A:
			tag = "delete"
		case j < blk.B:
			tag = "insert"
		}
		if tag != "" {
			answer = append(answer, Opcode{tag, i, blk.A, j, blk.B})
		}
		i, j = blk.A+blk.Size, blk.B+blk.Size
		if blk.Size > 0 {
			answer = append(answer, Opcode{"equal", i - blk.Size, i, j - blk.Size, j})
		}
	}
	return answer
}

// GroupedOpcodes returns the opcodes in groups with n lines of context around the changes.
func (m *Matcher) GroupedOpcodes(n int) [][]Opcode {
	codes := m.Opcodes()
	if len(codes) == 0 {
		codes = []Opcode{{"equal", 0, 1, 0, 1}}
	}
	// Fixup leading and trailing groups if they show no changes.
	if c := codes[0]; c.Tag == "equal" {
		codes[0] = Opcode{c.Tag, max(c.I1, c.I2-n), c.I2, max(c.J1, c.J2-n), c.J2}
	}
	if c := codes[len(codes)-1]; c.Tag == "equal" {
		codes[len(codes)-1] = Opcode{c.Tag, c.I1, min(c.I2, c.I1+n), c.J1, min(c.J2, c.J1+n)}
	}
	nn := n + n
	var groups [][]Opcode
	var group []Opcode
	for _, c := range codes {
		// End the current group and start a new one whenever there is a large range with no
		// changes.
		if c.Tag == "equal" && c.I2-c.I1 > nn {
			group = append(group, Opcode{c.Tag, c.I1, min(c.I2, c.I1+n), c.J1, min(c.J2, c.J1+n)})
			groups = append(groups, group)
			group = nil
			c.I1, c.J1 = max(c.I1, c.I2-n), max(c.J1, c.J2-n)
		}
		group = append(group, c)
	}
	if len(group) > 0 && (len(group) != 1 || group[0].Tag != "equal") {
		groups = append(groups, group)
	}
	return groups
}

func formatRange(start, stop int) string {
	beginning := start + 1
	length := stop - start
	if length == 1 {
		return strconv.Itoa(beginning)
	}
	if length == 0 {
		beginning--
	}
	return strconv.Itoa(beginning) + "," + strconv.Itoa(length)
}

// UnifiedDiff is difflib.unified_diff(a, b, fromfile, tofile, lineterm="", n=n): the lines of the
// difference in unified format (without line terminators).
func UnifiedDiff(a, b []string, fromfile, tofile string, n int) []string {
	var out []string
	started := false
	for _, group := range NewMatcher(a, b).GroupedOpcodes(n) {
		if !started {
			started = true
			out = append(out, "--- "+fromfile, "+++ "+tofile)
		}
		first, last := group[0], group[len(group)-1]
		out = append(out, "@@ -"+formatRange(first.I1, last.I2)+" +"+formatRange(first.J1, last.J2)+" @@")
		for _, c := range group {
			if c.Tag == "equal" {
				for _, line := range a[c.I1:c.I2] {
					out = append(out, " "+line)
				}
				continue
			}
			if c.Tag == "replace" || c.Tag == "delete" {
				for _, line := range a[c.I1:c.I2] {
					out = append(out, "-"+line)
				}
			}
			if c.Tag == "replace" || c.Tag == "insert" {
				for _, line := range b[c.J1:c.J2] {
					out = append(out, "+"+line)
				}
			}
		}
	}
	return out
}

// Join is "\n".join for the lines of a diff.
func Join(lines []string) string { return strings.Join(lines, "\n") }
