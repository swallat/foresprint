package excel

import (
	"fmt"

	"github.com/swallat/foresprint/internal/model"
)

func isNumber(ref string) string { return "ISNUMBER(" + ref + ")" }

func known(refAvg, refTrend string) string {
	return fmt.Sprintf(`IF(ISNUMBER(%s),%s,IF(ISNUMBER(%s),%s,""))`, refAvg, refAvg, refTrend, refTrend)
}

// TrendFormula is the Excel formula of the extrapolation for row i (0 = first sprint); it mirrors
// the engine's trend. r(col, offset) returns the reference of column col in row i-offset. The
// formula only matters where the average is missing.
func TrendFormula(mode model.TrendMode, thinRef string, r func(col string, offset int) string, i int) string {
	has := func(off int) bool { return i-off >= 0 }
	ref := func(col string, off int) string {
		if has(off) {
			return r(col, off)
		}
		return `""`
	}
	k1 := ref("known", 1)
	k2 := ref("known", 2)
	fallback := `""`
	if has(1) {
		fallback = fmt.Sprintf(`IF(%s,%s,"")`, isNumber(k1), k1)
	}
	flat := fallback
	linear := fallback
	if has(2) {
		linear = fmt.Sprintf(`IF(AND(%s,%s),MAX(0,%s+(%s-%s)),%s)`, isNumber(k1), isNumber(k2), k1, k1, k2, fallback)
	}
	var body string
	switch mode {
	case model.TrendFlat:
		body = flat
	case model.TrendLinear:
		body = linear
	default: // classic
		a1, a2, a3 := ref("avg", 1), ref("avg", 2), ref("avg", 3)
		t1, t2 := ref("trend", 1), ref("trend", 2)
		parts := linear
		if i >= 2 {
			ratioBranch := fallback
			if has(3) {
				ratio := fmt.Sprintf("%s/%s*%s", a2, a3, t1)
				ratioBranch = fmt.Sprintf(`IF(AND(%s,%s,%s),MAX(0,%s),%s)`, isNumber(a2), isNumber(a3), isNumber(t1), ratio, fallback)
			}
			parts = fmt.Sprintf(`IF(%s,%s,%s)`, isNumber(t2), linear, ratioBranch)
		}
		if i >= 1 {
			if has(2) {
				body = fmt.Sprintf(`IF(%s,IF(%s,MAX(0,%s+(%s-%s)),%s),%s)`, isNumber(a1), isNumber(a2), a1, a1, a2, fallback, parts)
			} else {
				body = fmt.Sprintf(`IF(%s,%s,%s)`, isNumber(a1), fallback, parts)
			}
		} else {
			body = parts
		}
	}
	return fmt.Sprintf("IF(%s,%s,%s)", thinRef, flat, body)
}
