// Package app is the interface between the window and the Go core. Every exported method of
// API is callable from the frontend (Wails binds them; frontend/src/lib/api.ts has the same
// methods with types). The package has no window code, so it builds and is tested without
// CGO or a web view.
//
// Rules for methods:
//   - Arguments and results are plain structs, slices, maps, strings and numbers (JSON).
//   - An error becomes a rejected promise; its text is for users and already translated.
//   - A method must not block for long: start work in the background and report it in Status.
//   - New areas add their methods in their own file (api_<area>.go) and their types in
//     types_<area>.go, so that pages do not collide.
package app

import (
	"errors"
	"os"
	"runtime"
	"sort"
	"sync"
	"time"

	"github.com/swallat/foresprint/internal/config"
	"github.com/swallat/foresprint/internal/datasvc"
	"github.com/swallat/foresprint/internal/holidays"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
)

// API is the object bound to the window.
type API struct {
	Version string

	// ChooseFolder opens the folder dialog of the system and returns the chosen path ("" if
	// cancelled). Set by the window shell; nil in tests.
	ChooseFolder func(title string) (string, error)
	// ChooseFile opens the file dialog for an Excel workbook and returns the chosen path ("" if
	// cancelled). Set by the window shell; nil in tests.
	ChooseFile func(title string) (string, error)
	// OpenPath opens a file with the program of the system; nil = the default of the platform.
	OpenPath func(path string) error

	// Now is the clock; nil = the system clock (set in tests).
	Now func() time.Time

	mu      sync.Mutex
	dataDir string
	run     trackerRun
	undo    []projectSnapshot
	// data is the storage of the data folder (area Data, api_data.go).
	data *datasvc.Store
	// tagMu guards tags: the tags the next Save sets (asked for in the Review).
	tagMu sync.Mutex
	tags  []string
	// sprintTags remembers the tag each Review asked for, by team/sprint, so that reopening can
	// take back the right one.
	sprintTags map[string]string
}

// New returns the API for a data folder; "" takes the remembered one.
func New(version, dataDir string) *API {
	config.Install()
	if dataDir == "" {
		dataDir, _ = config.DataDir()
	}
	return &API{Version: version, dataDir: dataDir, data: datasvc.New(dataDir)}
}

// Info describes the program and the machine.
type Info struct {
	Version         string `json:"version"`
	OS              string `json:"os"`
	Arch            string `json:"arch"`
	DataDir         string `json:"dataDir"`
	HolidaysVersion string `json:"holidaysVersion"`
}

// Info returns the version and the data folder in use.
func (a *API) Info() Info {
	return Info{
		Version:         a.Version,
		OS:              runtime.GOOS,
		Arch:            runtime.GOARCH,
		DataDir:         a.DataDir(),
		HolidaysVersion: holidays.Info().HolidaysVersion,
	}
}

// DataDir is the data folder in use.
func (a *API) DataDir() string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.dataDir
}

// Choice is one entry of a list the user picks from.
type Choice struct {
	Code  string `json:"code"`
	Label string `json:"label"`
}

// Prefs are the personal settings of this machine (settings.json), not team data.
type Prefs struct {
	Language       string   `json:"language"`
	Languages      []Choice `json:"languages"`
	Theme          string   `json:"theme"`
	Themes         []Choice `json:"themes"`
	Density        string   `json:"density"` // "compact", "normal" or "roomy"
	DataDir        string   `json:"dataDir"`
	RecentDataDirs []string `json:"recentDataDirs"`
}

// Prefs returns the language, theme and data folders. Labels of themes are translated.
func (a *API) Prefs() Prefs {
	p := Prefs{
		Language:       savedLanguage(),
		Theme:          config.Theme(),
		Density:        config.Density(),
		DataDir:        a.DataDir(),
		RecentDataDirs: config.RecentDataDirs(),
	}
	for _, l := range i18n.Languages() {
		p.Languages = append(p.Languages, Choice{Code: l.Code, Label: l.Name})
	}
	for _, t := range config.Themes {
		p.Themes = append(p.Themes, Choice{Code: t.Code, Label: i18n.T(t.Label)})
	}
	return p
}

// SetLanguage saves the interface language ("de", "en").
func (a *API) SetLanguage(code string) error { return config.SaveLanguage(code) }

// SetTheme saves the theme ("system", "light", "dark").
func (a *API) SetTheme(code string) error { return config.SaveTheme(code) }

// SetDensity saves the density of tables ("compact", "normal", "roomy").
func (a *API) SetDensity(code string) error { return config.SaveDensity(code) }

// Texts returns the texts of the window for a language: English source text to translation.
// A text without entry is shown in English by the frontend.
func (a *API) Texts(lang string) map[string]string {
	if code := i18n.Normalize(lang); code != "" {
		lang = code
	}
	return i18n.UITexts(lang)
}

// SetDataDir remembers a folder as the data folder; it must exist.
func (a *API) SetDataDir(path string) error {
	info, err := os.Stat(path)
	if err != nil || !info.IsDir() {
		return errors.New(i18n.T("The folder {path} does not exist.", "path", path))
	}
	if err := config.SaveDataDir(path); err != nil {
		return err
	}
	a.mu.Lock()
	changed := a.dataDir != path
	a.dataDir = path
	a.mu.Unlock()
	if changed {
		// Tags a Review asked for belong to the data they were asked for.
		a.tagMu.Lock()
		a.tags, a.sprintTags = nil, nil
		a.tagMu.Unlock()
	}
	a.data.SetFolder(path)
	storage.ClearTeamCache()
	return nil
}

// PickDataDir asks the user for a folder and makes it the data folder. It returns the folder,
// or "" if the user cancelled.
func (a *API) PickDataDir() (string, error) {
	if a.ChooseFolder == nil {
		return "", errors.New(i18n.T("No folder dialog in this build."))
	}
	path, err := a.ChooseFolder(i18n.T("Choose the data folder"))
	if err != nil || path == "" {
		return "", err
	}
	return path, a.SetDataDir(path)
}

// TeamSummary is one team of the data folder, for the team selector and the start page.
type TeamSummary struct {
	Key      string `json:"key"`
	Name     string `json:"name"`
	People   int    `json:"people"`
	Sprints  int    `json:"sprints"`
	Problem  string `json:"problem,omitempty"`
	Tickets  bool   `json:"tickets"`
	Products int    `json:"products"`
}

// Teams lists the teams in the data folder. A team that cannot be read is listed with its
// problem, so that the window can show it instead of hiding the team.
func (a *API) Teams() []TeamSummary {
	repo := storage.NewRepository(a.DataDir())
	keys := repo.Teams()
	sort.Strings(keys)
	out := make([]TeamSummary, 0, len(keys))
	for _, key := range keys {
		data, err := repo.Load(key)
		if err != nil {
			out = append(out, TeamSummary{Key: key, Name: key, Problem: err.Error()})
			continue
		}
		out = append(out, TeamSummary{
			Key:      key,
			Name:     data.Team.Name,
			People:   len(data.People),
			Sprints:  len(data.Sprints),
			Products: len(data.Products),
			Tickets:  data.Team.Features.Tickets,
		})
	}
	return out
}

// SprintInfo is one sprint of a team, for the sprint selector and the timeline.
type SprintInfo struct {
	ID    string `json:"id"`
	Start string `json:"start"` // YYYY-MM-DD
	End   string `json:"end"`   // YYYY-MM-DD
	State string `json:"state"` // "past", "current" or "future", by today's date
}

// Sprints lists the sprints of a team in the order of the files (by start date).
func (a *API) Sprints(team string) ([]SprintInfo, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return nil, err
	}
	today := time.Now().Format("2006-01-02")
	out := make([]SprintInfo, 0, len(data.Sprints))
	for _, s := range data.Sprints {
		start, end := s.Start.Format("2006-01-02"), s.End.Format("2006-01-02")
		state := "future"
		switch {
		case end < today:
			state = "past"
		case start <= today:
			state = "current"
		}
		out = append(out, SprintInfo{ID: s.ID, Start: start, End: end, State: state})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Start < out[j].Start })
	return out, nil
}

// savedLanguage is the language the user chose, so that the selector shows the choice even when
// FORESPRINT_LANG overrides the language of texts in this process.
func savedLanguage() string {
	if code := config.Language(); code != "" {
		return code
	}
	return i18n.Language()
}
