package sources

import "sort"

// A port of Python's difflib.SequenceMatcher (without junk, with autojunk) and
// get_close_matches, used to suggest similar field names. The ratio of two names must be the same
// number as in Python, because the order of the suggestions depends on it.

type matchBlock struct{ a, b, size int }

type sequenceMatcher struct {
	a, b []rune
	b2j  map[rune][]int
}

// newSequenceMatcher compares a with b (Python: set_seq1(a), set_seq2(b)).
func newSequenceMatcher(a, b []rune) *sequenceMatcher {
	m := &sequenceMatcher{a: a, b: b, b2j: map[rune][]int{}}
	for i, elt := range b {
		m.b2j[elt] = append(m.b2j[elt], i)
	}
	// autojunk: elements that make up more than 1% of a sequence of 200 or more are ignored
	if n := len(b); n >= 200 {
		ntest := n/100 + 1
		for elt, idxs := range m.b2j {
			if len(idxs) > ntest {
				delete(m.b2j, elt)
			}
		}
	}
	return m
}

func (m *sequenceMatcher) findLongestMatch(alo, ahi, blo, bhi int) matchBlock {
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
	// Extend the match; this also takes in the elements that were ignored as popular.
	for besti > alo && bestj > blo && m.a[besti-1] == m.b[bestj-1] {
		besti, bestj, bestsize = besti-1, bestj-1, bestsize+1
	}
	for besti+bestsize < ahi && bestj+bestsize < bhi &&
		m.a[besti+bestsize] == m.b[bestj+bestsize] {
		bestsize++
	}
	return matchBlock{besti, bestj, bestsize}
}

func (m *sequenceMatcher) matchingBlocks() []matchBlock {
	type span struct{ alo, ahi, blo, bhi int }
	queue := []span{{0, len(m.a), 0, len(m.b)}}
	var found []matchBlock
	for len(queue) > 0 {
		q := queue[len(queue)-1]
		queue = queue[:len(queue)-1]
		x := m.findLongestMatch(q.alo, q.ahi, q.blo, q.bhi)
		if x.size == 0 {
			continue
		}
		found = append(found, x)
		if q.alo < x.a && q.blo < x.b {
			queue = append(queue, span{q.alo, x.a, q.blo, x.b})
		}
		if x.a+x.size < q.ahi && x.b+x.size < q.bhi {
			queue = append(queue, span{x.a + x.size, q.ahi, x.b + x.size, q.bhi})
		}
	}
	sort.Slice(found, func(i, j int) bool {
		if found[i].a != found[j].a {
			return found[i].a < found[j].a
		}
		if found[i].b != found[j].b {
			return found[i].b < found[j].b
		}
		return found[i].size < found[j].size
	})
	return found
}

// ratio is 2*M/T like SequenceMatcher.ratio (1.0 for two empty sequences).
func (m *sequenceMatcher) ratio() float64 {
	total := len(m.a) + len(m.b)
	if total == 0 {
		return 1.0
	}
	matches := 0
	for _, blk := range m.matchingBlocks() {
		matches += blk.size
	}
	return 2.0 * float64(matches) / float64(total)
}

// closeMatches is difflib.get_close_matches(word, possibilities, n, cutoff): the best matches,
// best first. A name that occurs twice in the possibilities is returned twice, as in Python.
func closeMatches(word string, possibilities []string, n int, cutoff float64) []string {
	type scored struct {
		score float64
		text  string
	}
	var result []scored
	for _, x := range possibilities {
		if score := newSequenceMatcher([]rune(x), []rune(word)).ratio(); score >= cutoff {
			result = append(result, scored{score, x})
		}
	}
	// heapq.nlargest orders by the tuple (score, text), largest first
	sort.SliceStable(result, func(i, j int) bool {
		if result[i].score != result[j].score {
			return result[i].score > result[j].score
		}
		return result[i].text > result[j].text
	})
	if len(result) > n {
		result = result[:n]
	}
	out := make([]string, len(result))
	for i, r := range result {
		out[i] = r.text
	}
	return out
}
