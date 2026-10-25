package yamlx

import (
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"
	"time"
)

// PyStr is str() of a loaded YAML value in Python.
func PyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case int64:
		return strconv.FormatInt(x, 10)
	case *big.Int:
		return x.String()
	case float64:
		return PyFloatRepr(x)
	case string:
		return x
	case Date:
		return time.Time(x).Format("2006-01-02")
	case time.Time:
		s := x.Format("2006-01-02 15:04:05")
		if x.Nanosecond() != 0 {
			s += fmt.Sprintf(".%06d", x.Nanosecond()/1000)
		}
		if x.Location() != time.UTC {
			_, off := x.Zone()
			sign := "+"
			if off < 0 {
				sign, off = "-", -off
			}
			s += fmt.Sprintf("%s%02d:%02d", sign, off/3600, off%3600/60)
			if off%60 != 0 {
				s += fmt.Sprintf(":%02d", off%60)
			}
		}
		return s
	}
	return fmt.Sprint(v)
}

// PyFloatRepr is repr() of a float in Python.
func PyFloatRepr(f float64) string {
	switch {
	case math.IsNaN(f):
		return "nan"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	case f == 0:
		if math.Signbit(f) {
			return "-0.0"
		}
		return "0.0"
	}
	e := strconv.FormatFloat(math.Abs(f), 'e', -1, 64) // d.ddde+XX
	mant, exp, _ := strings.Cut(e, "e")
	digits := strings.Replace(mant, ".", "", 1)
	exp10, _ := strconv.Atoi(exp)
	decpt := exp10 + 1
	var s string
	switch {
	case decpt > 16 || decpt < -3:
		s = digits[:1]
		if len(digits) > 1 {
			s += "." + digits[1:]
		}
		sign := "+"
		if exp10 < 0 {
			sign = "-"
		}
		a := exp10
		if a < 0 {
			a = -a
		}
		s += fmt.Sprintf("e%s%02d", sign, a)
	case decpt <= 0:
		s = "0." + strings.Repeat("0", -decpt) + digits
	case decpt >= len(digits):
		s = digits + strings.Repeat("0", decpt-len(digits)) + ".0"
	default:
		s = digits[:decpt] + "." + digits[decpt:]
	}
	if f < 0 {
		s = "-" + s
	}
	return s
}
