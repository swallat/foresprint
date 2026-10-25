package git

import (
	"regexp"
	"strings"
	"unicode"

	"github.com/swallat/foresprint/internal/pytext"
)

var (
	schemeRe      = regexp.MustCompile(`^([A-Za-z][A-Za-z0-9+.-]*)://`)
	nameStartRe   = regexp.MustCompile(`^[A-Za-z0-9._~-]+`)
	scpPasswordRe = regexp.MustCompile(`^([^@/\\\s:]+):[^@/\\\s]*@`) // user:password@host:path
	urlInTextRe   = regexp.MustCompile(`(?i)[a-z][a-z0-9+.-]*://[^\s'"<>]+`)
)

// PublicURL is the address without credentials and without anything after ? or # (for display
// only). It never fails and is idempotent. For ssh the user name is kept and the password
// dropped; local paths and every address accepted by ParseRemoteURL stay unchanged.
func PublicURL(url string) string {
	if m := schemeRe.FindStringSubmatchIndex(url); m != nil {
		scheme, end := url[m[2]:m[3]], m[1]
		rest := url[end:]
		if at := strings.LastIndex(rest, "@"); at >= 0 { // everything up to the last "@" goes
			removed := rest[:at]
			rest = rest[at+1:]
			if strings.EqualFold(scheme, "ssh") {
				if user := nameStartRe.FindString(removed); user != "" {
					rest = user + "@" + rest
				}
			}
		}
		if cut := strings.IndexAny(rest, "?#"); cut >= 0 {
			rest = rest[:cut]
		}
		return url[:end] + rest
	}
	if m := scpPasswordRe.FindStringSubmatchIndex(url); m != nil { // user:password@host:path
		return url[m[2]:m[3]] + "@" + url[m[1]:]
	}
	return url
}

// HasCredentials says whether the address contains anything that PublicURL would remove.
func HasCredentials(text string) bool {
	text = pytext.Strip(text)
	return PublicURL(text) != text
}

func schemeChar(b byte) bool {
	return b >= 'a' && b <= 'z' || b >= 'A' && b <= 'Z' || b >= '0' && b <= '9' || b == '+' || b == '.' || b == '-'
}

// Scrub replaces every address (scheme://...) in the text with its display form.
func Scrub(text string) string {
	var out strings.Builder
	pos := 0  // text before pos has been written
	from := 0 // where to search on
	for from < len(text) {
		loc := urlInTextRe.FindStringIndex(text[from:])
		if loc == nil {
			break
		}
		start, end := from+loc[0], from+loc[1]
		// A match only counts at the beginning of a word of scheme characters, not after every dot
		// or hyphen (Python: negative look-behind). After a rejected match the search goes on
		// behind its "://".
		if start > 0 && schemeChar(text[start-1]) {
			from = start + strings.Index(text[start:end], "://") + 3
			continue
		}
		out.WriteString(text[pos:start])
		out.WriteString(PublicURL(text[start:end]))
		pos, from = end, end
	}
	out.WriteString(text[pos:])
	return out.String()
}

// Characters that MDCode replaces with a space: control characters (Cc), line and paragraph
// separators (Zl, Zp) and the writing-direction control characters. They make text appear
// different from how it is written (reordering, line break). The remaining format characters
// (Cf) stay: the zero-width joiner (U+200D) holds emoji sequences together, the zero-width
// non-joiner (U+200C) is part of the spelling of, for example, Persian and Indian names.
func blanked(r rune) bool {
	switch r {
	case 0x061c, 0x200e, 0x200f, // Arabic Letter Mark, Left-to-Right Mark, Right-to-Left Mark
		0x202a, 0x202b, 0x202c, 0x202d, 0x202e, // Embedding, Pop, Override
		0x2066, 0x2067, 0x2068, 0x2069: // Isolate
		return true
	}
	return unicode.Is(unicode.Cc, r) || unicode.Is(unicode.Zl, r) || unicode.Is(unicode.Zp, r)
}

// BlankControls turns control characters, line breaks and writing-direction characters into
// spaces (external text for output without Markdown, e.g. the command line).
func BlankControls(text string) string {
	return strings.Map(func(r rune) rune {
		if blanked(r) {
			return ' '
		}
		return r
	}, text)
}

var asciiPunctuationRe = regexp.MustCompile("([!-/:-@\\[-`{-~])")

// MDPlain is plain text that never acts as Markdown: every ASCII punctuation character gets a
// backslash (as CommonMark requires), so that neither emphasis, links, images nor web addresses
// such as www.example.com or http://... have any effect. Control characters and line breaks
// become spaces, as with MDCode. For messages that contain names from files and cannot have each
// name set as code individually.
func MDPlain(text string) string {
	return asciiPunctuationRe.ReplaceAllString(BlankControls(text), `\$1`)
}

// MDCode is text as a code span for Markdown. Names and addresses that come from outside (server,
// configuration) never belong in the interface as plain text: emphasis would take effect there
// and web addresses such as www.example.com/x would become links. Backticks in the text do not
// end the span; control characters, line breaks and writing-direction characters become spaces.
// The remaining invisible characters (emoji sequences, Persian names) stay.
func MDCode(text string) string {
	text = BlankControls(text)
	if text == "" {
		return ""
	}
	longest, run := 0, 0
	for i := 0; i < len(text); i++ {
		if text[i] == '`' {
			run++
			longest = max(longest, run)
		} else {
			run = 0
		}
	}
	fence := strings.Repeat("`", longest+1)
	pad := ""
	if strings.ContainsAny(text[:1], "` ") || strings.ContainsAny(text[len(text)-1:], "` ") {
		pad = " "
	}
	return fence + pad + text + pad + fence
}

// MDCodeLines is like MDCode, but line by line (hard line breaks in Markdown): the multi-line
// output of Git stays readable. Empty lines are dropped, as is whitespace at the end of a line
// (the server pads its "remote:" lines with it).
func MDCodeLines(text string) string {
	var parts []string
	for _, line := range pytext.SplitLines(text, false) {
		if pytext.Strip(line) == "" {
			continue
		}
		parts = append(parts, MDCode(strings.TrimRightFunc(line, unicode.IsSpace)))
	}
	return strings.Join(parts, "  \n")
}
