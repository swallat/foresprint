// Package git runs the git program for Foresprint (port of git.py): finding Git, running calls
// with a time limit and the possibility to abort them, turning Git's messages into errors with a
// kind and a next step, checking server addresses, and the small everyday operations on the data
// folder (changes, commit, tags, create, clone).
//
// Errors of Git calls are *Error. Texts are English source texts for the catalog of package
// i18n; texts that contain names from outside (branches, addresses, files) can be rendered with
// a quoting function for Markdown (Error.Render, Error.HintMD).
package git

import (
	"errors"
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
)

// Error is an error from a Git call. Kind names the type (see Classify), the hint is the next
// step in everyday language; Error() stays the short message. Message and hint never contain
// credentials from an address (Scrub). Raw means: the message is the output of Git and the
// server (Classify), not a text of our own. It contains names and lines that others determine
// ("remote:" lines, hooks, tags, branches).
type Error struct {
	msg    string
	Kind   string
	hint   string
	hintMD string
	Raw    bool
	// Detail carries what a kind knows beyond the message (for example NewBranchDetail).
	Detail any
	render func(quote func(string) string) string
}

// New returns an error of the given kind with the next step (may be empty).
func New(message, kind, hint string) *Error {
	if kind == "" {
		kind = "error"
	}
	return &Error{msg: Scrub(message), Kind: kind, hint: Scrub(hint)}
}

// Newf is New with an English source text and its placeholder values (see i18n.T).
func Newf(kind, hint, text string, values ...any) *Error {
	return New(i18n.T(text, values...), kind, hint)
}

// WithRaw marks the message as the output of Git.
func (e *Error) WithRaw(raw bool) *Error {
	e.Raw = raw
	return e
}

// WithHintMD sets the hint for Markdown, for hints that contain names from outside.
func (e *Error) WithHintMD(hint string) *Error {
	e.hintMD = Scrub(hint)
	return e
}

// Error is the short message.
func (e *Error) Error() string { return e.msg }

// Hint is the next step in everyday language (may be empty).
func (e *Error) Hint() string { return e.hint }

// HintMD is the hint for Markdown if it contains names from outside, otherwise Hint.
func (e *Error) HintMD() string {
	if e.hintMD != "" {
		return e.hintMD
	}
	return e.hint
}

// SetHint replaces the hint (also the one for Markdown).
func (e *Error) SetHint(hint string) {
	e.hint = hint
	e.hintMD = ""
}

// Render is the message for the interface: the output of Git (Raw) goes through quote (e.g.
// MDCodeLines for Markdown), our own texts stay as they are. A nil quote leaves the text alone.
func (e *Error) Render(quote func(string) string) string {
	if quote == nil {
		quote = identity
	}
	if e.render != nil {
		return e.render(quote)
	}
	if e.Raw {
		return quote(e.msg)
	}
	return e.msg
}

// Full is the message including the next step, for places without a heading (TitleFor). For a
// login error the cause comes first: the hint (AuthHelp) starts right with the next step,
// because the heading would otherwise name it. As with Render, quote applies only to the
// message, never to cause and hint.
func (e *Error) Full(quote func(string) string) string {
	var parts []string
	if e.Kind == "auth" && e.hint != "" {
		parts = append(parts, TitleFor(e.Kind)+".")
	}
	parts = append(parts, e.Render(quote), e.hint)
	var kept []string
	for _, p := range parts {
		if p != "" {
			kept = append(kept, p)
		}
	}
	return strings.TrimSpace(strings.Join(kept, " "))
}

func identity(s string) string { return s }

// As returns err as a *Error, or nil if it is none.
func As(err error) *Error {
	var e *Error
	if errors.As(err, &e) {
		return e
	}
	return nil
}

// KindOf returns the kind of a Git error ("" for any other error).
func KindOf(err error) string {
	if e := As(err); e != nil {
		return e.Kind
	}
	return ""
}

// IsKind reports whether err is a Git error of one of the kinds.
func IsKind(err error, kinds ...string) bool {
	kind := KindOf(err)
	if kind == "" {
		return false
	}
	for _, k := range kinds {
		if k == kind {
			return true
		}
	}
	return false
}
