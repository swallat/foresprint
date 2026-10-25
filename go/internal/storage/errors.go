// Package storage reads and writes the YAML files of a team (port of storage.py): team.yaml,
// people.yaml, products.yaml, sprints/<id>.yaml and the files of the ticket pre-planning. The
// files are written byte for byte like the Python core wrote them, so that Git sees no change
// when only the program was swapped.
//
//	<data>/<team>/team.yaml          Team configuration
//	<data>/<team>/people.yaml        People list with memberships
//	<data>/<team>/products.yaml      Product list (optional)
//	<data>/<team>/sprints/<id>.yaml  One sprint per file
//	<data>/<team>/projects.yaml      Projects of the ticket pre-planning (features.tickets)
//	<data>/<team>/tickets.yaml       Last ticket import (features.tickets)
//	<data>/<team>/preplan.yaml       Earmarks and own estimates (features.tickets)
package storage

import (
	"errors"
	"strings"
)

// Translate turns a message template into the language of the user. The templates are the
// English texts of the Python core (placeholders in braces); the texts catalog sets this.
var Translate = func(s string) string { return s }

// tr fills the placeholders {name} of a template with the values given as name, value pairs, in
// one pass (like str.format: a value that itself contains "{name}" stays as it is).
func tr(template string, kv ...string) string {
	t := Translate(template)
	values := map[string]string{}
	for i := 0; i+1 < len(kv); i += 2 {
		values[kv[i]] = kv[i+1]
	}
	var b strings.Builder
	for i := 0; i < len(t); {
		if t[i] == '{' {
			if end := strings.IndexByte(t[i:], '}'); end > 0 {
				if v, ok := values[t[i+1:i+end]]; ok {
					b.WriteString(v)
					i += end + 1
					continue
				}
			}
		}
		b.WriteByte(t[i])
		i++
	}
	return b.String()
}

// DataError says that a file is missing or not readable. The message is meant for users.
type DataError struct{ Msg string }

func (e *DataError) Error() string { return e.Msg }

// FileAccessError says that a file cannot be read, written or deleted (missing permissions, open
// in another program, disk full). It is a data error too (see IsDataError).
type FileAccessError struct {
	Msg string
	Err error
}

func (e *FileAccessError) Error() string { return e.Msg }
func (e *FileAccessError) Unwrap() error { return e.Err }

// ConflictError says that a file contains the conflict markers of an incomplete merge. This is
// detected before the YAML is loaded: editing the team is blocked until the conflict is
// resolved.
type ConflictError struct{ Files []string }

func (e *ConflictError) Error() string {
	return tr("Merge conflict in: {files}. Editing is locked until the conflict is resolved.",
		"files", strings.Join(e.Files, ", "))
}

// IsDataError reports whether err is a DataError, FileAccessError or ConflictError.
func IsDataError(err error) bool {
	var d *DataError
	var f *FileAccessError
	var c *ConflictError
	return errors.As(err, &d) || errors.As(err, &f) || errors.As(err, &c)
}

func dataErr(template string, kv ...string) error { return &DataError{Msg: tr(template, kv...)} }
