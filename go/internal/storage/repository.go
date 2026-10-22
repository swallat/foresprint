package storage

import (
	"bytes"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/yamlx"
)

// Environment variables.
const (
	// DataEnv names the data folder.
	DataEnv = "FORESPRINT_DATA"
	// AsOfEnv names the date that counts as "today" (for retrospectives and tests).
	AsOfEnv = "FORESPRINT_AS_OF"
)

// OnWrite is called after every write or delete of a team file, so that caches that depend on
// the files (the Git status) can be dropped. The default does nothing.
var OnWrite = func() {}

// ClearTeamCache tells the dependents that the files changed.
func ClearTeamCache() { OnWrite() }

// Git conflict markers at the start of a line (all three must occur). The "\r?" matters on
// Windows, where Git writes the markers with CRLF.
var markers = []*regexp.Regexp{
	regexp.MustCompile(`(?m)^<{7}( |\r?$)`),
	regexp.MustCompile(`(?m)^={7}\r?$`),
	regexp.MustCompile(`(?m)^>{7}( |\r?$)`),
}

// HasConflictMarkers reports whether text holds the markers of an incomplete merge.
func HasConflictMarkers(text string) bool {
	for _, m := range markers {
		if !m.MatchString(text) {
			return false
		}
	}
	return true
}

func reason(err error) string {
	var pe *fs.PathError
	var le *os.LinkError
	var se *os.SyscallError
	switch {
	case errors.As(err, &pe):
		err = pe.Err
	case errors.As(err, &le):
		err = le.Err
	case errors.As(err, &se):
		err = se.Err
	}
	s := err.Error()
	if s != "" {
		s = strings.ToUpper(s[:1]) + s[1:]
	}
	return s
}

func notReadable(path string, err error) error {
	return &FileAccessError{
		Msg: tr("{path}: cannot be read ({reason}). Check the permissions or close the file in any other program.",
			"path", path, "reason", reason(err)),
		Err: err,
	}
}

func notSaved(path string, err error) error {
	return &FileAccessError{
		Msg: tr("{path}: not saved ({reason}). The file was not changed. Is the folder writable, and is the file open in another program?",
			"path", path, "reason", reason(err)),
		Err: err,
	}
}

// ReadText reads a file as text, bytes that are not UTF-8 replaced; a failure is a
// FileAccessError.
func ReadText(path string) (string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return "", notReadable(path, err)
	}
	return strings.ToValidUTF8(string(b), "�"), nil
}

// read is _read: the content of a YAML file as a mapping.
func read(path string) (*yamlx.Map, error) {
	b, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, dataErr("File missing: {path}", "path", path)
	}
	if err != nil { // no read permission, folder instead of file, network drive unreachable
		return nil, notReadable(path, err)
	}
	if !utf8Valid(b) {
		return nil, dataErr("{path}: invalid YAML ({error})", "path", path, "error", "the file is not UTF-8")
	}
	text := string(b)
	if HasConflictMarkers(text) {
		return nil, &ConflictError{Files: []string{path}}
	}
	content, err := yamlx.Load(text)
	if err != nil { // e.g. an impossible date (2026-13-45)
		return nil, dataErr("{path}: invalid YAML ({error})", "path", path, "error", err.Error())
	}
	if content == nil {
		return &yamlx.Map{}, nil
	}
	m, ok := content.(*yamlx.Map)
	if !ok {
		return nil, dataErr("{path}: content must be a YAML mapping", "path", path)
	}
	return m, nil
}

// ReadFile is read for the packages that compare files with new content: a YAML file as a
// mapping.
func ReadFile(path string) (*yamlx.Map, error) { return read(path) }

func utf8Valid(b []byte) bool { return bytes.Equal([]byte(strings.ToValidUTF8(string(b), "�")), b) }

// DumpYAML writes a document the way all files are written (merging and saving write the
// same).
func DumpYAML(content *yamlx.Map) string { return yamlx.MustDump(content) }

// writeFile writes stably: always LF line endings, only if the content changed (no unnecessary
// changes for Git) and via a temporary file (never a half-written state). Write errors surface
// as FileAccessError with an understandable message.
func writeFile(path, header string, content *yamlx.Map) error {
	if err := writeAtomic(path, header, content); err != nil {
		var c *ConflictError
		if errors.As(err, &c) {
			return err
		}
		return notSaved(path, err)
	}
	return nil
}

func writeAtomic(path, header string, content *yamlx.Map) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	text := header + DumpYAML(content)
	if current, err := os.ReadFile(path); err == nil {
		if string(current) == text {
			return nil
		}
		if HasConflictMarkers(strings.ToValidUTF8(string(current), "�")) {
			// Never write over an incomplete merge: the markers would be lost.
			return &ConflictError{Files: []string{path}}
		}
	}
	if err := replaceWith(path, text); err != nil {
		return err
	}
	ClearTeamCache()
	return nil
}

// WriteText writes a text file (e.g. the report) via a temporary file; errors as with the data
// files. The text is written as it is (LF line endings).
func WriteText(path, text string) error {
	if err := replaceWith(path, text); err != nil {
		return notSaved(path, err)
	}
	return nil
}

// replaceWith writes text to a temporary file next to path and replaces path with it: the file
// is afterwards either completely new or unchanged, never half-written.
func replaceWith(path, text string) (err error) {
	tmp, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer func() {
		if err != nil { // write or rename error (e.g. locked): leave nothing behind
			_ = os.Remove(name)
		}
	}()
	if _, err = tmp.WriteString(text); err != nil {
		_ = tmp.Close()
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	// CreateTemp makes the file 0600; a data file is an ordinary file.
	if err = os.Chmod(name, 0o644); err != nil {
		return err
	}
	return os.Rename(name, path)
}

// TeamData is a team with everything that belongs to it.
type TeamData struct {
	Team     model.Team
	People   []model.Person
	Sprints  []model.Sprint
	Products []model.Product
	// The ticket pre-planning; empty unless features.tickets is on.
	Projects []model.Project
	Tickets  []model.Ticket
	Preplan  model.Preplan
	// AbsencePeriods are the planned absences as periods (abwesenheiten.yaml); read always.
	AbsencePeriods model.Absences
	// TicketsImported and TicketsSource are the time stamp and source (file name or query) of the
	// last ticket import.
	TicketsImported *time.Time
	TicketsSource   *string
}

// SprintByID returns the sprint, or nil.
func (d *TeamData) SprintByID(id string) *model.Sprint {
	for i := range d.Sprints {
		if d.Sprints[i].ID == id {
			return &d.Sprints[i]
		}
	}
	return nil
}

// TicketByKey returns the ticket, or nil.
func (d *TeamData) TicketByKey(key string) *model.Ticket {
	for i := range d.Tickets {
		if d.Tickets[i].Key == key {
			return &d.Tickets[i]
		}
	}
	return nil
}

// ProjectByID returns the project, or nil.
func (d *TeamData) ProjectByID(id string) *model.Project {
	for i := range d.Projects {
		if d.Projects[i].ID == id {
			return &d.Projects[i]
		}
	}
	return nil
}

// TeamFiles are the files of a team besides the sprint files.
var TeamFiles = []string{"team.yaml", "people.yaml", "products.yaml", "projects.yaml", "tickets.yaml", "preplan.yaml",
	"abwesenheiten.yaml", "arbeitspakete.yaml"}

// TicketFiles are the files of the ticket pre-planning; only read while features.tickets is on.
var TicketFiles = []string{"projects.yaml", "tickets.yaml", "preplan.yaml", "arbeitspakete.yaml"}

// FileVersion is one entry of TeamVersion.
type FileVersion struct {
	Name    string
	ModTime int64 // nanoseconds; 0 if the file is missing
	Size    int64
	Present bool
}

// TeamVersion is the file version of a team (changes whenever any of its files changes): name,
// modification time and size of all team files; new and deleted files change it.
func TeamVersion(base string) []FileVersion {
	names := append([]string(nil), TeamFiles...)
	paths := make([]string, len(names))
	for i, n := range names {
		paths[i] = filepath.Join(base, n)
	}
	sprints, _ := filepath.Glob(filepath.Join(base, "sprints", "*.yaml"))
	sort.Strings(sprints)
	for _, p := range sprints {
		names = append(names, filepath.Base(p))
		paths = append(paths, p)
	}
	out := make([]FileVersion, len(paths))
	for i, p := range paths {
		out[i] = FileVersion{Name: names[i]}
		if info, err := os.Stat(p); err == nil {
			out[i].ModTime, out[i].Size, out[i].Present = info.ModTime().UnixNano(), info.Size(), true
		}
	}
	return out
}

var teamKeyRe = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,63}$`)

// TeamKeyProblem says why key is not suitable as the key of a NEW team ("" = fine). Existing
// teams are not checked when loading, so that older folder names keep working. The key is the
// folder name: only these characters, so that neither a path separator nor ".." leads out of the
// data folder and the name stays the same on every file system (even case-insensitive ones); it
// starts with a letter or digit because a leading hyphen would be read as an option.
func TeamKeyProblem(key string) string {
	head, _, _ := strings.Cut(key, ".")
	if windowsDevices[strings.ToLower(head)] {
		return Translate("Key: these names are reserved for devices on Windows (CON, PRN, AUX, NUL, COM0 to COM9, LPT0 to LPT9).")
	}
	if !teamKeyRe.MatchString(key) {
		return Translate("Key: lower-case letters a–z (no umlauts), digits, hyphen and underscore (at most 64 characters; starting with a letter or digit)")
	}
	return ""
}

// Repository is a data folder with one folder per team.
type Repository struct{ Root string }

// NewRepository returns the repository of a data folder.
func NewRepository(root string) *Repository { return &Repository{Root: root} }

// TeamDir is the folder of a team.
func (r *Repository) TeamDir(key string) string { return filepath.Join(r.Root, key) }

// Teams are the keys of the teams, sorted.
func (r *Repository) Teams() []string {
	entries, err := os.ReadDir(r.Root)
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range entries {
		if fileExists(filepath.Join(r.Root, e.Name(), "team.yaml")) {
			out = append(out, e.Name())
		}
	}
	sort.Strings(out)
	return out
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

// ClashingTeam returns an existing team whose folder name equals key or differs only in case (on
// Windows and macOS they would be the same folder).
func (r *Repository) ClashingTeam(key string) (string, bool) {
	wanted := strings.ToLower(key)
	for _, name := range r.Teams() {
		if strings.ToLower(name) == wanted {
			return name, true
		}
	}
	return "", false
}

// Exists reports whether the team exists.
func (r *Repository) Exists(key string) bool {
	return fileExists(filepath.Join(r.TeamDir(key), "team.yaml"))
}

// Load reads a team.
func (r *Repository) Load(key string) (*TeamData, error) {
	base := r.TeamDir(key)
	if !fileExists(filepath.Join(base, "team.yaml")) {
		known := strings.Join(r.Teams(), ", ")
		if known == "" {
			known = Translate("none")
		}
		return nil, dataErr("Team '{key}' not found in {root} (available: {known})", "key", key, "root", r.Root, "known", known)
	}
	data := &TeamData{}
	teamFile := filepath.Join(base, "team.yaml")
	m, err := read(teamFile)
	if err != nil {
		return nil, err
	}
	if data.Team, err = TeamFromDict(key, m, teamFile); err != nil {
		return nil, err
	}
	if p := filepath.Join(base, "people.yaml"); fileExists(p) {
		if m, err = read(p); err != nil {
			return nil, err
		}
		if data.People, err = PeopleFromDict(m, p); err != nil {
			return nil, err
		}
	}
	if p := filepath.Join(base, "products.yaml"); fileExists(p) {
		if m, err = read(p); err != nil {
			return nil, err
		}
		if data.Products, err = ProductsFromDict(m, p); err != nil {
			return nil, err
		}
	}
	files, _ := filepath.Glob(filepath.Join(base, "sprints", "*.yaml"))
	sort.Strings(files)
	for _, f := range files {
		if m, err = read(f); err != nil {
			return nil, err
		}
		sprint, err := SprintFromDict(m, f)
		if err != nil {
			return nil, err
		}
		if stem := strings.TrimSuffix(filepath.Base(f), ".yaml"); sprint.ID != stem {
			return nil, dataErr("{file}: id '{id}' does not match the file name", "file", f, "id", sprint.ID)
		}
		data.Sprints = append(data.Sprints, sprint)
	}
	sort.SliceStable(data.Sprints, func(i, j int) bool { return data.Sprints[i].Start.Before(data.Sprints[j].Start) })
	if !data.Team.Features.Explicit { // older file: existing data stays visible
		f := model.Features{Products: len(data.Products) > 0}
		for _, p := range data.Products {
			f.PO = f.PO || (p.PO != nil && *p.PO != "")
		}
		for _, p := range data.People {
			f.Production = f.Production || p.ProductionAccess
		}
		data.Team.Features = f
	}
	if p := filepath.Join(base, "abwesenheiten.yaml"); fileExists(p) {
		if m, err = read(p); err != nil {
			return nil, err
		}
		if data.AbsencePeriods, err = AbsencesFromDict(m, p); err != nil {
			return nil, err
		}
	}
	if data.Team.Features.Tickets || data.Team.Features.Projects { // off: the files are not even read
		if p := filepath.Join(base, "projects.yaml"); fileExists(p) {
			if m, err = read(p); err != nil {
				return nil, err
			}
			if data.Projects, err = ProjectsFromDict(m, p); err != nil {
				return nil, err
			}
		}
	}
	if data.Team.Features.Tickets {
		if p := filepath.Join(base, TicketFileName(data.Team)); fileExists(p) {
			if m, err = read(p); err != nil {
				return nil, err
			}
			tf, err := TicketsFromDict(m, p)
			if err != nil {
				return nil, err
			}
			data.Tickets, data.TicketsImported, data.TicketsSource = tf.Tickets, tf.Imported, tf.Source
		}
		if p := filepath.Join(base, "preplan.yaml"); fileExists(p) {
			if m, err = read(p); err != nil {
				return nil, err
			}
			if data.Preplan, err = PreplanFromDict(m, p); err != nil {
				return nil, err
			}
		}
	}
	return data, nil
}

// SaveTeam writes team.yaml.
func (r *Repository) SaveTeam(team model.Team) (string, error) {
	path := filepath.Join(r.TeamDir(team.Key), "team.yaml")
	return path, writeFile(path, TeamHeader, TeamToDict(team))
}

// SavePeople writes people.yaml.
func (r *Repository) SavePeople(key string, people []model.Person) (string, error) {
	path := filepath.Join(r.TeamDir(key), "people.yaml")
	return path, writeFile(path, PeopleHeader, PeopleToDict(people))
}

// SaveProducts writes products.yaml.
func (r *Repository) SaveProducts(key string, products []model.Product) (string, error) {
	path := filepath.Join(r.TeamDir(key), "products.yaml")
	return path, writeFile(path, ProductsHeader, ProductsToDict(products))
}

// SaveProjects writes projects.yaml.
func (r *Repository) SaveProjects(key string, projects []model.Project) (string, error) {
	path := filepath.Join(r.TeamDir(key), "projects.yaml")
	return path, writeFile(path, ProjectsHeader, ProjectsToDict(projects))
}

// TicketFileName is the file that holds the tickets of the team: arbeitspakete.yaml for work
// packages kept in Foresprint, otherwise tickets.yaml.
func TicketFileName(team model.Team) string {
	if team.Source() == model.SourcePackages {
		return "arbeitspakete.yaml"
	}
	return "tickets.yaml"
}

// SaveTickets writes tickets.yaml.
func (r *Repository) SaveTickets(key string, f TicketsFile) (string, error) {
	path := filepath.Join(r.TeamDir(key), "tickets.yaml")
	return path, writeFile(path, TicketsHeader, TicketsToDict(f))
}

// SavePackages writes arbeitspakete.yaml, the work packages of a team whose work does not come
// from a tracker.
func (r *Repository) SavePackages(key string, f TicketsFile) (string, error) {
	path := filepath.Join(r.TeamDir(key), "arbeitspakete.yaml")
	return path, writeFile(path, PackagesHeader, TicketsToDict(f))
}

// SaveAbsences writes abwesenheiten.yaml.
func (r *Repository) SaveAbsences(key string, a model.Absences) (string, error) {
	path := filepath.Join(r.TeamDir(key), "abwesenheiten.yaml")
	return path, writeFile(path, AbsencesHeader, AbsencesToDict(a))
}

// SavePreplan writes preplan.yaml.
func (r *Repository) SavePreplan(key string, pp model.Preplan) (string, error) {
	path := filepath.Join(r.TeamDir(key), "preplan.yaml")
	return path, writeFile(path, PreplanHeader, PreplanToDict(pp))
}

// SprintPath is the file of a sprint; an id that would not be a safe file name is refused.
func (r *Repository) SprintPath(key, sprintID string) (string, error) {
	if problem := FileNameProblem(sprintID, false); problem != "" { // becomes the file name
		return "", dataErr("Sprint ID {id} is not allowed ({problem})", "id", yamlx.PyRepr(sprintID), "problem", problem)
	}
	return filepath.Join(r.TeamDir(key), "sprints", sprintID+".yaml"), nil
}

func (r *Repository) pinnedAbsenceState(path string, s model.Sprint) (model.AbsenceState, error) {
	if fileExists(path) {
		m, err := read(path)
		if err == nil {
			var old model.Sprint
			if old, err = SprintFromDict(m, path); err == nil {
				if old.AbsenceState != nil && *old.AbsenceState == model.AbsencesOpen {
					return model.AbsencesOpen, nil
				}
				return old.AbsenceStatus(), nil
			}
		}
		var fa *FileAccessError
		var ce *ConflictError
		if errors.As(err, &fa) || errors.As(err, &ce) {
			return "", err // unreadable is not "file broken": overwrite nothing
		}
	}
	if s.Velocity != nil { // sprint already evaluated (e.g. import)
		return model.AbsencesConfirmed, nil
	}
	return s.AbsenceStatus(), nil
}

// DeleteSprint removes a sprint file (the sprint is afterwards generated from the calendar
// again).
func (r *Repository) DeleteSprint(key, sprintID string) error {
	path, err := r.SprintPath(key, sprintID)
	if err != nil {
		return err
	}
	defer ClearTeamCache()
	if info, err := os.Stat(path); err == nil && info.IsDir() { // Python's unlink refuses a folder
		return &FileAccessError{Msg: tr("{path}: not deleted ({reason}). Is the file read-only or open in another program?",
			"path", path, "reason", "Is a directory")}
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return &FileAccessError{
			Msg: tr("{path}: not deleted ({reason}). Is the file read-only or open in another program?",
				"path", path, "reason", reason(err)),
			Err: err,
		}
	}
	return nil
}

// SaveSprint writes the sprint. If its absence state is not yet determined, it is determined now
// (from the existing file, for new files from the content), so that e.g. saving the Planning
// does not silently confirm absences. The state is set on sprint.
func (r *Repository) SaveSprint(key string, sprint *model.Sprint) (string, error) {
	path, err := r.SprintPath(key, sprint.ID)
	if err != nil {
		return "", err
	}
	if sprint.AbsenceState == nil {
		state, err := r.pinnedAbsenceState(path, *sprint)
		if err != nil {
			return "", err
		}
		sprint.AbsenceState = &state
	}
	return path, writeFile(path, strings.ReplaceAll(SprintHeader, "{id}", sprint.ID), SprintToDict(*sprint))
}

// SaveSprintsTogether writes several sprint files all or nothing: if one fails, those already
// written are reset to their previous state (new files removed).
func SaveSprintsTogether(repo *Repository, key string, sprints []*model.Sprint) ([]string, error) {
	before := map[string][]byte{}
	existed := map[string]bool{}
	for _, s := range sprints {
		path, err := repo.SprintPath(key, s.ID)
		if err != nil {
			return nil, err
		}
		if fileExists(path) {
			b, err := os.ReadFile(path)
			if err != nil {
				return nil, notReadable(path, err)
			}
			before[path], existed[path] = b, true
		}
	}
	var written []string
	for _, s := range sprints {
		path, err := repo.SaveSprint(key, s)
		if err != nil {
			for _, p := range written {
				if existed[p] {
					_ = os.WriteFile(p, before[p], 0o644)
				} else {
					_ = os.Remove(p)
				}
			}
			ClearTeamCache()
			return nil, err
		}
		written = append(written, path)
	}
	return written, nil
}

// ImportSprints takes over sprints (e.g. from an import). A new team is created with team; for an
// existing team, settings and people are kept and sprint files with the same name are replaced.
func ImportSprints(repo *Repository, team model.Team, sprints []*model.Sprint) ([]string, error) {
	// Check beforehand so that part of it is not written before a conflict shows up.
	candidates := []string{
		filepath.Join(repo.TeamDir(team.Key), "team.yaml"),
		filepath.Join(repo.TeamDir(team.Key), "people.yaml"),
	}
	for _, s := range sprints {
		p, err := repo.SprintPath(team.Key, s.ID)
		if err != nil {
			return nil, err
		}
		candidates = append(candidates, p)
	}
	var marked []string
	for _, p := range candidates {
		if fileExists(p) {
			text, err := ReadText(p)
			if err != nil {
				return nil, err
			}
			if HasConflictMarkers(text) {
				marked = append(marked, p)
			}
		}
	}
	if len(marked) > 0 {
		return nil, &ConflictError{Files: marked}
	}
	var paths []string
	if !repo.Exists(team.Key) {
		if problem := TeamKeyProblem(team.Key); problem != "" { // a new team needs a usable key
			return nil, &DataError{Msg: problem}
		}
		if clash, ok := repo.ClashingTeam(team.Key); ok {
			return nil, dataErr("Team {team} already exists (as {existing}).", "team", yamlx.PyRepr(team.Key), "existing", clash)
		}
		p, err := repo.SaveTeam(team)
		if err != nil {
			return nil, err
		}
		paths = append(paths, p)
	}
	if _, err := os.Stat(filepath.Join(repo.TeamDir(team.Key), "people.yaml")); err != nil {
		p, err := repo.SavePeople(team.Key, nil)
		if err != nil {
			return nil, err
		}
		paths = append(paths, p)
	}
	for _, s := range sprints {
		p, err := repo.SaveSprint(team.Key, s)
		if err != nil {
			return nil, err
		}
		paths = append(paths, p)
	}
	return paths, nil
}
