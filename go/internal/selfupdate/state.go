package selfupdate

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/config"
)

// ModeEnv overrides the saved mode.
const ModeEnv = "FORESPRINT_AUTOUPDATE"

// CheckInterval is the time between two automatic checks.
const CheckInterval = 24 * time.Hour

// Mode says what happens when a newer version exists.
type Mode string

// The modes: on and notice look once a day and only report (nothing is installed by itself), off does not even look.
const (
	On     Mode = "on"
	Notice Mode = "notice"
	Off    Mode = "off"
)

// ParseMode reads a mode name ("1", "true", "0" and "false" are accepted too).
func ParseMode(raw string) (Mode, bool) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "on", "1", "true":
		return On, true
	case "notice":
		return Notice, true
	case "off", "0", "false":
		return Off, true
	}
	return "", false
}

// State is what is remembered between two runs (update.json in the settings folder).
type State struct {
	Mode      string    `json:"mode,omitempty"`
	LastCheck time.Time `json:"last_check,omitempty"`
	Latest    string    `json:"latest,omitempty"`
}

// StateFile is the path of the state file.
func StateFile() string { return filepath.Join(config.Dir(), "update.json") }

// LoadState reads the state; a missing or damaged file is an empty state.
func LoadState() State {
	var s State
	if data, err := os.ReadFile(StateFile()); err == nil {
		_ = json.Unmarshal(data, &s)
	}
	return s
}

// Save writes the state.
func (s State) Save() error {
	if err := os.MkdirAll(filepath.Dir(StateFile()), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(StateFile(), append(data, '\n'), 0o644)
}

// CurrentMode is the environment variable before the saved setting; default on.
func CurrentMode() Mode {
	for _, raw := range []string{os.Getenv(ModeEnv), LoadState().Mode} {
		if m, ok := ParseMode(raw); ok {
			return m
		}
	}
	return On
}

// Due reports whether the last check is older than CheckInterval.
func (s State) Due(now time.Time) bool { return now.Sub(s.LastCheck) >= CheckInterval }
