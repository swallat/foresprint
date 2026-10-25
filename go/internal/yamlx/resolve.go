package yamlx

import "regexp"

// The implicit resolvers of PyYAML (resolver.py) that decide whether a string must be quoted
// when written: a plain string that the reader would resolve to another type is quoted. Every
// resolver applies to the whole text.
var implicitResolvers = []*regexp.Regexp{
	// bool
	regexp.MustCompile(`^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$`),
	// float
	regexp.MustCompile(`^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?` +
		`|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?` +
		`|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*` +
		`|[-+]?\.(?:inf|Inf|INF)` +
		`|\.(?:nan|NaN|NAN))$`),
	// int
	regexp.MustCompile(`^(?:[-+]?0b[0-1_]+` +
		`|[-+]?0[0-7_]+` +
		`|[-+]?(?:0|[1-9][0-9_]*)` +
		`|[-+]?0x[0-9a-fA-F_]+` +
		`|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$`),
	// merge, null (also the empty string), value
	regexp.MustCompile(`^(?:<<|~|null|Null|NULL|=|)$`),
	// timestamp
	regexp.MustCompile(`^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]` +
		`|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?` +
		`(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?` +
		`(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$`),
}

// resolvesToNonString reports whether the reader would not read the plain text s as a string.
// (The resolver for "!", "&" and "*" can never match a plain scalar and is left out.)
func resolvesToNonString(s string) bool {
	for _, re := range implicitResolvers {
		if re.MatchString(s) {
			return true
		}
	}
	return false
}
