package rules

// closeMatch is difflib.get_close_matches(word, candidates, n=1) with the default cutoff 0.6:
// the candidate that is most similar to word, ties going to the larger text; "" for none.
func closeMatch(word string, candidates []string) string {
	best, bestScore := "", -1.0
	w := []rune(word)
	for _, c := range candidates {
		score := ratio([]rune(c), w)
		if score < 0.6 {
			continue
		}
		if score > bestScore || (score == bestScore && c > best) {
			best, bestScore = c, score
		}
	}
	return best
}

// ratio is SequenceMatcher(None, a, b).ratio() for short sequences (without the "popular
// element" shortcut that difflib applies from 200 elements on).
func ratio(a, b []rune) float64 {
	total := len(a) + len(b)
	if total == 0 {
		return 1
	}
	return 2 * float64(matchCount(a, b, 0, len(a), 0, len(b))) / float64(total)
}

func matchCount(a, b []rune, alo, ahi, blo, bhi int) int {
	i, j, k := longestMatch(a, b, alo, ahi, blo, bhi)
	if k == 0 {
		return 0
	}
	n := k
	if alo < i && blo < j {
		n += matchCount(a, b, alo, i, blo, j)
	}
	if i+k < ahi && j+k < bhi {
		n += matchCount(a, b, i+k, ahi, j+k, bhi)
	}
	return n
}

// longestMatch finds the longest matching block; of equal ones the first in a, then in b.
func longestMatch(a, b []rune, alo, ahi, blo, bhi int) (besti, bestj, bestsize int) {
	besti, bestj = alo, blo
	prev := map[int]int{}
	for i := alo; i < ahi; i++ {
		cur := map[int]int{}
		for j := blo; j < bhi; j++ {
			if a[i] != b[j] {
				continue
			}
			k := prev[j-1] + 1
			cur[j] = k
			if k > bestsize {
				besti, bestj, bestsize = i-k+1, j-k+1, k
			}
		}
		prev = cur
	}
	return besti, bestj, bestsize
}
