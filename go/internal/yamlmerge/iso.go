package yamlmerge

import (
	"strconv"
	"strings"
	"time"
)

// ParseISO reads the ISO 8601 forms of Python's datetime.fromisoformat: a date, or a date and a
// time (separated by T, a space or any single character), with optional fraction of a second and
// a zone (Z, +HH, +HH:MM, +HHMM). ok is false for anything else.
func ParseISO(s string) (DateTime, bool) {
	date, rest := s, ""
	if len(s) >= 10 && s[4] == '-' {
		date, rest = s[:10], s[10:]
	} else if len(s) >= 8 && s[4] != '-' {
		date, rest = s[:8], s[8:]
	}
	var year, month, day int
	ok := false
	switch len(date) {
	case 10:
		var y, m, d bool
		year, y = atoi(date[0:4])
		month, m = atoi(date[5:7])
		day, d = atoi(date[8:10])
		ok = y && m && d && date[7] == '-'
	case 8:
		var y, m, d bool
		year, y = atoi(date[0:4])
		month, m = atoi(date[4:6])
		day, d = atoi(date[6:8])
		ok = y && m && d
	}
	if !ok || month < 1 || month > 12 || day < 1 || day > 31 {
		return DateTime{}, false
	}
	check := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
	if check.Day() != day || year < 1 {
		return DateTime{}, false
	}
	if rest == "" {
		return DateTime{Time: check}, true
	}
	rest = rest[1:] // the separator
	zone, aware := 0, false
	if i := strings.IndexAny(rest, "Zz+-"); i >= 0 {
		z := rest[i:]
		rest = rest[:i]
		aware = true
		if z != "Z" && z != "z" {
			sign := 1
			if z[0] == '-' {
				sign = -1
			}
			digits := strings.ReplaceAll(z[1:], ":", "")
			if len(digits) != 2 && len(digits) != 4 && len(digits) != 6 {
				return DateTime{}, false
			}
			h, okH := atoi(digits[0:2])
			mi, okM, se, okS := 0, true, 0, true
			if len(digits) >= 4 {
				mi, okM = atoi(digits[2:4])
			}
			if len(digits) == 6 {
				se, okS = atoi(digits[4:6])
			}
			if !okH || !okM || !okS || h > 23 || mi > 59 {
				return DateTime{}, false
			}
			zone = sign * (h*3600 + mi*60 + se)
		}
	}
	if rest == "" {
		return DateTime{}, false
	}
	clock, frac, _ := strings.Cut(rest, ".")
	if strings.ContainsAny(rest, ",") {
		clock, frac, _ = strings.Cut(rest, ",")
	}
	clock = strings.ReplaceAll(clock, ":", "")
	if len(clock) != 2 && len(clock) != 4 && len(clock) != 6 {
		return DateTime{}, false
	}
	hour, okH := atoi(clock[0:2])
	minute, okM, second, okS := 0, true, 0, true
	if len(clock) >= 4 {
		minute, okM = atoi(clock[2:4])
	}
	if len(clock) == 6 {
		second, okS = atoi(clock[4:6])
	}
	if frac != "" {
		if _, okF := atoi(frac); !okF {
			return DateTime{}, false
		}
	}
	if !okH || !okM || !okS || hour > 23 || minute > 59 || second > 59 {
		return DateTime{}, false
	}
	loc := time.UTC
	if aware {
		loc = time.FixedZone("", zone)
	}
	return DateTime{Time: time.Date(year, time.Month(month), day, hour, minute, second, 0, loc), Aware: aware}, true
}

func atoi(s string) (int, bool) {
	if s == "" {
		return 0, false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, false
		}
	}
	n, err := strconv.Atoi(s)
	return n, err == nil
}
