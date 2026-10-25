package i18n

import "regexp"

// Texts written for the Python version carry markup of the rich library ("[bold]x[/bold]").
// The command line of the Go core prints plain text: Plain removes the tags. A tag is "[" and
// a letter, "#", "/" or "@" up to "]"; backslashes in front of "[" count (two make one, an odd
// number escapes the bracket), like rich.markup.escape.
var tag = regexp.MustCompile(`(\\*)\[([a-z#/@][^\[]*?\])`)

// Plain removes rich markup tags from a text.
func Plain(text string) string {
	return tag.ReplaceAllStringFunc(text, func(m string) string {
		parts := tag.FindStringSubmatch(m)
		slashes := parts[1]
		if len(slashes)%2 == 1 { // escaped: the bracket stays, one backslash goes
			return slashes[:len(slashes)-1] + "[" + parts[2]
		}
		return slashes[:len(slashes)/2]
	})
}
