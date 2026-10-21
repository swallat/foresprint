// Package config holds the settings of the user and the machine, outside the team data: the
// language, the theme, the remembered data folders. They are kept in settings.json in
// %APPDATA%\foresprint (Windows) or ~/.config/foresprint, the same file the Python version
// wrote, so a user keeps the settings when switching over.
//
// A folder named "sprintforecast" (from before the rename) is copied on first use and left in
// place.
package config

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/i18n"
)

const (
	name           = "foresprint"
	legacyName     = "sprintforecast"
	migratedMarker = ".migrated"
	fileName       = "settings.json"
	damagedSuffix  = ".defekt"
)

// Error means that the settings cannot be saved (folder not writable, ...). The message is
// meant for users.
type Error struct {
	msg string
	err error
}

func (e *Error) Error() string { return e.msg }
func (e *Error) Unwrap() error { return e.err }

// Dir is the settings folder. XDG_CONFIG_HOME and APPDATA are looked at on every call.
func Dir() string {
	var base string
	switch appdata := os.Getenv("APPDATA"); {
	case runtime.GOOS == "windows" && appdata != "":
		base = appdata
	case os.Getenv("XDG_CONFIG_HOME") != "":
		base = os.Getenv("XDG_CONFIG_HOME")
	default:
		home, err := os.UserHomeDir()
		if err != nil {
			home = "."
		}
		base = filepath.Join(home, ".config")
	}
	folder, legacy := filepath.Join(base, name), filepath.Join(base, legacyName)
	if isDir(legacy) && !failed[folder] && !exists(filepath.Join(folder, migratedMarker)) {
		if err := copyMissing(legacy, folder); err != nil {
			failed[folder] = true
			return legacy // keep using the old folder rather than a half copy
		}
	}
	return folder
}

var failed = map[string]bool{} // folders whose migration failed: not retried in this process

func isDir(p string) bool {
	info, err := os.Stat(p)
	return err == nil && info.IsDir()
}

func exists(p string) bool {
	_, err := os.Lstat(p)
	return err == nil
}

// copyMissing copies what target does not have yet, then marks the folder as migrated. Lock
// files ("sperren") are not copied: a lock in the old folder never excludes one in the new.
func copyMissing(source, target string) error {
	if err := os.MkdirAll(target, 0o755); err != nil {
		return err
	}
	err := filepath.WalkDir(source, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(source, path)
		if err != nil || rel == "." {
			return err
		}
		for _, part := range strings.Split(rel, string(filepath.Separator)) {
			if part == "sperren" {
				if d.IsDir() {
					return filepath.SkipDir
				}
				return nil
			}
		}
		dest := filepath.Join(target, rel)
		if d.IsDir() {
			return os.MkdirAll(dest, 0o755)
		}
		if exists(dest) {
			return nil
		}
		return copyFile(path, dest)
	})
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(target, migratedMarker), []byte("copied from the folder 'sprintforecast'\n"), 0o644)
}

// copyFile writes through a temporary name and links it into place, so that a process
// starting at the same time never sees a half-written file.
func copyFile(source, dest string) error {
	data, err := os.ReadFile(source)
	if err != nil {
		return err
	}
	tmp := fmt.Sprintf("%s.%d.tmp", dest, os.Getpid())
	defer func() { _ = os.Remove(tmp) }()
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	if err := os.Link(tmp, dest); err != nil && !errors.Is(err, fs.ErrExist) {
		if !exists(dest) { // no hard links on this file system
			return os.Rename(tmp, dest)
		}
	}
	return nil
}

// Path is the settings file.
func Path() string { return filepath.Join(Dir(), fileName) }

// Load reads the settings; an unreadable or damaged file counts as empty.
func Load() map[string]any {
	raw, err := os.ReadFile(Path())
	if err != nil {
		return map[string]any{}
	}
	var out map[string]any
	if json.Unmarshal(raw, &out) != nil || out == nil {
		return map[string]any{}
	}
	return out
}

// keepDamaged backs up an unreadable settings file before it is overwritten. An older backup
// stays; the new one gets a time stamp.
func keepDamaged(path string) error {
	raw, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err == nil {
		var obj map[string]any
		if json.Unmarshal(raw, &obj) == nil && obj != nil {
			return nil
		}
	}
	target := path + damagedSuffix
	stamp := time.Now().Format("20060102-150405")
	for n := 1; exists(target); n++ {
		target = fmt.Sprintf("%s%s-%s", path, damagedSuffix, stamp)
		if n > 1 {
			target += "-" + strconv.Itoa(n)
		}
	}
	if err != nil {
		return err
	}
	return os.WriteFile(target, raw, 0o644)
}

// Update saves settings atomically (through a temporary file, never half-written); a damaged
// file is backed up first. Errors are *Error with an understandable message.
func Update(changes map[string]any) error {
	path := Path()
	tmp := ""
	err := func() error {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return err
		}
		if err := keepDamaged(path); err != nil {
			return err
		}
		merged := Load()
		for k, v := range changes {
			merged[k] = v
		}
		text, err := Marshal(merged)
		if err != nil {
			return err
		}
		f, err := os.CreateTemp(filepath.Dir(path), "*.tmp")
		if err != nil {
			return err
		}
		tmp = f.Name()
		_, werr := f.Write(text)
		if cerr := f.Close(); werr == nil {
			werr = cerr
		}
		if werr != nil {
			return werr
		}
		if err := os.Rename(tmp, path); err != nil {
			return err
		}
		tmp = ""
		return nil
	}()
	if tmp != "" {
		_ = os.Remove(tmp)
	}
	if err != nil {
		reason := err.Error()
		var pe *fs.PathError
		if errors.As(err, &pe) {
			reason = pe.Err.Error()
		}
		return &Error{msg: i18n.T("The settings could not be saved ({path}): {error}", "path", path, "error", reason), err: err}
	}
	return nil
}

// Marshal writes settings like Python's json.dumps(indent=2, sort_keys=True): sorted keys,
// two spaces, non-ASCII characters as \u escapes.
func Marshal(settings map[string]any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(settings); err != nil { // map keys are sorted by encoding/json
		return nil, err
	}
	return asciiEscape(bytes.TrimRight(buf.Bytes(), "\n")), nil
}

func asciiEscape(in []byte) []byte {
	var out bytes.Buffer
	for len(in) > 0 {
		r, size := utf8.DecodeRune(in)
		switch {
		case r < 0x80:
			out.WriteByte(in[0])
		case r >= 0x10000:
			r -= 0x10000
			fmt.Fprintf(&out, `\u%04x\u%04x`, 0xd800+(r>>10), 0xdc00+(r&0x3ff))
		default:
			fmt.Fprintf(&out, `\u%04x`, r)
		}
		in = in[size:]
	}
	return out.Bytes()
}

// String is a text setting ("" if missing or not a text).
func String(key string) string {
	s, _ := Load()[key].(string)
	return s
}

// Strings is a list-of-text setting; entries that are not non-empty texts are skipped.
func Strings(key string) []string {
	list, _ := Load()[key].([]any)
	var out []string
	for _, v := range list {
		if s, ok := v.(string); ok && strings.TrimSpace(s) != "" {
			out = append(out, s)
		}
	}
	return out
}
