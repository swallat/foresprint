// Package pymath has the small pieces of Python's arithmetic that the calculation core relies on
// and that Go does not have in the same form: the compensated sum of the built-in sum() (Python
// 3.12 and later), math.fsum, statistics.median and fmean, round() and the number formatting of
// str.format. A result that has to match the Python core digit for digit is calculated with
// these and not with a plain loop.
package pymath

import (
	"math"
	"sort"
	"strconv"
	"strings"
)

// Sum is Python's sum() of floats: Neumaier summation, so the result is not the plain left to
// right sum. An empty list gives 0.
func Sum(xs []float64) float64 {
	result, c := 0.0, 0.0
	for _, x := range xs {
		t := result + x
		switch {
		case math.IsInf(t, 0) || math.IsNaN(t):
			// Like CPython: from here on the plain sum, the compensation is meaningless.
			c = 0
		case math.Abs(result) >= math.Abs(x):
			c += (result - t) + x
		default:
			c += (x - t) + result
		}
		result = t
	}
	if c != 0 && !math.IsInf(c, 0) && !math.IsNaN(c) {
		result += c
	}
	return result
}

// Fsum is math.fsum: the exactly rounded sum (Shewchuk's algorithm).
func Fsum(xs []float64) float64 {
	var partials []float64
	for _, x := range xs {
		i := 0
		for _, y := range partials {
			if math.Abs(x) < math.Abs(y) {
				x, y = y, x
			}
			hi := x + y
			lo := y - (hi - x)
			if lo != 0 {
				partials[i] = lo
				i++
			}
			x = hi
		}
		partials = append(partials[:i], x)
	}
	if len(partials) == 0 {
		return 0
	}
	n := len(partials)
	hi := partials[n-1]
	n--
	var lo float64
	for n > 0 {
		x := hi
		y := partials[n-1]
		n--
		hi = x + y
		lo = y - (hi - x)
		if lo != 0 {
			break
		}
	}
	// Round half to even when the remaining partials are exactly half an ulp.
	if n > 0 && ((lo < 0 && partials[n-1] < 0) || (lo > 0 && partials[n-1] > 0)) {
		y := lo * 2
		x := hi + y
		if y == x-hi {
			hi = x
		}
	}
	return hi
}

// FMean is statistics.fmean: the exactly rounded sum divided by the count. The list must not
// be empty.
func FMean(xs []float64) float64 { return Fsum(xs) / float64(len(xs)) }

// Median is statistics.median. The list must not be empty.
func Median(xs []float64) float64 {
	s := append([]float64(nil), xs...)
	sort.Float64s(s)
	n := len(s)
	if n%2 == 1 {
		return s[n/2]
	}
	return (s[n/2-1] + s[n/2]) / 2
}

// Round is Python's round(x, digits) for a float: the correctly rounded decimal, ties to even
// (judged on the exact binary value, so round(2.675, 2) is 2.67).
func Round(x float64, digits int) float64 {
	if math.IsInf(x, 0) || math.IsNaN(x) {
		return x
	}
	if digits >= 0 {
		v, err := strconv.ParseFloat(strconv.FormatFloat(x, 'f', digits, 64), 64)
		if err != nil {
			return x
		}
		return v
	}
	scale := math.Pow(10, float64(-digits))
	return math.RoundToEven(x/scale) * scale
}

// Fixed is f"{x:.{digits}f}", with the thousands separator "," when grouped is true
// (f"{x:,.{digits}f}"). Negative zero keeps its sign like in Python.
func Fixed(x float64, digits int, grouped bool) string {
	text := strconv.FormatFloat(x, 'f', digits, 64)
	if !grouped {
		return text
	}
	sign := ""
	if strings.HasPrefix(text, "-") {
		sign, text = "-", text[1:]
	}
	whole, frac, hasFrac := strings.Cut(text, ".")
	var b strings.Builder
	for i, r := range whole {
		if i > 0 && (len(whole)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(r)
	}
	out := sign + b.String()
	if hasFrac {
		out += "." + frac
	}
	return out
}

// General is f"{x:g}": six significant digits, no trailing zeros.
func General(x float64) string {
	text := strconv.FormatFloat(x, 'g', 6, 64)
	if strings.ContainsAny(text, "e") {
		// Go and Python agree on the exponent form ("1e+06"); drop trailing zeros of the
		// mantissa like Python does.
		mant, exp, _ := strings.Cut(text, "e")
		if strings.Contains(mant, ".") {
			mant = strings.TrimRight(strings.TrimRight(mant, "0"), ".")
		}
		return mant + "e" + exp
	}
	if strings.Contains(text, ".") {
		text = strings.TrimRight(strings.TrimRight(text, "0"), ".")
	}
	if text == "-0" {
		return "-0"
	}
	return text
}
