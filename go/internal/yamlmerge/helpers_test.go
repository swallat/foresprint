package yamlmerge_test

import "math"

func nan() float64         { return math.NaN() }
func inf(sign int) float64 { return math.Inf(sign) }
