package excel

import (
	"fmt"
	"math"
	"math/big"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/settings"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/validate"
	"github.com/swallat/foresprint/internal/yamlx"
)

// Change is one value that differs between a file and the workbook.
type Change struct {
	File string
	Path string
	Old  any
	New  any
}

// ImportPlan is what an import would do. Files are written (relative to the team folder);
// Untouched are sprint files that already exist but do not appear in the workbook (they stay
// unchanged).
type ImportPlan struct {
	Data      *storage.TeamData
	Changes   []Change
	Files     []string
	Untouched []string
}

func documents(data *storage.TeamData) (names []string, docs map[string]*yamlx.Map) {
	docs = map[string]*yamlx.Map{
		"team.yaml":     storage.TeamToDict(data.Team),
		"people.yaml":   storage.PeopleToDict(data.People),
		"products.yaml": storage.ProductsToDict(data.Products),
	}
	names = []string{"team.yaml", "people.yaml", "products.yaml"}
	for i := range data.Sprints {
		name := "sprints/" + data.Sprints[i].ID + ".yaml"
		docs[name] = storage.SprintToDict(data.Sprints[i])
		names = append(names, name)
	}
	return names, docs
}

// Documents are the files the import writes for these data, as YAML text by file name.
func Documents(data *storage.TeamData) (names []string, texts map[string]string) {
	names, docs := documents(data)
	texts = map[string]string{}
	for name, doc := range docs {
		texts[name] = storage.DumpYAML(doc)
	}
	return names, texts
}

// flatten turns a document into path -> value; lists are broken down per entry with an index.
func flatten(doc any) map[string]any {
	out := map[string]any{}
	var walk func(v any, prefix string)
	walk = func(v any, prefix string) {
		switch x := v.(type) {
		case *yamlx.Map:
			for _, e := range x.Entries {
				walk(e.Value, prefix+yamlx.PyStr(e.Key)+".")
			}
		case []any:
			for i, it := range x {
				walk(it, fmt.Sprintf("%s%d.", prefix, i))
			}
		default:
			out[strings.TrimRight(prefix, ".")] = v
		}
	}
	walk(doc, "")
	return out
}

// pyEqual is Python's == for the values of a document: numbers compare by value across int,
// float and bool.
func pyEqual(a, b any) bool {
	na, aNum := pyNumber(a)
	nb, bNum := pyNumber(b)
	if aNum || bNum {
		return aNum && bNum && na.Cmp(nb) == 0
	}
	switch x := a.(type) {
	case nil:
		return b == nil
	case string:
		y, ok := b.(string)
		return ok && x == y
	case yamlx.Date:
		y, ok := b.(yamlx.Date)
		return ok && time.Time(x).Equal(time.Time(y))
	case time.Time:
		y, ok := b.(time.Time)
		return ok && x.Equal(y)
	}
	return fmt.Sprint(a) == fmt.Sprint(b)
}

func pyNumber(v any) (*big.Float, bool) {
	switch x := v.(type) {
	case bool:
		if x {
			return big.NewFloat(1), true
		}
		return big.NewFloat(0), true
	case int64:
		return new(big.Float).SetInt64(x), true
	case int:
		return new(big.Float).SetInt64(int64(x)), true
	case *big.Int:
		return new(big.Float).SetInt(x), true
	case float64:
		if math.IsNaN(x) || math.IsInf(x, 0) {
			return nil, false
		}
		return big.NewFloat(x), true
	}
	return nil, false
}

// CheckTeamKey checks that the key is a plain folder name below the data folder (no path, no
// drive, no ".."); a new team must also carry a permitted key and must not equal an existing one
// (not even up to upper and lower case).
func CheckTeamKey(repo *storage.Repository, key string) error {
	plain := key != "" && key != "." && key != ".." && !strings.ContainsAny(key, "/\\:\x00") &&
		storage.FileNameProblem(key, true) == ""
	if !plain {
		return dataErr("Key {key}: not a plain folder name in the data folder.", "key", yamlx.PyRepr(key))
	}
	if !repo.Exists(key) {
		if problem := storage.TeamKeyProblem(key); problem != "" {
			return &storage.DataError{Msg: problem}
		}
		if clash, ok := repo.ClashingTeam(key); ok {
			return dataErr("Team {team} already exists (as {existing}).", "team", yamlx.PyRepr(key), "existing", clash)
		}
	}
	return nil
}

// CheckIDs checks the sprint ids and the id of the first sprint before they form a path.
func CheckIDs(data *storage.TeamData) error {
	for _, s := range data.Sprints {
		if _, err := CheckSprintID(s.ID, SheetForecast+": "+s.ID); err != nil {
			return err
		}
	}
	if first := data.Team.Sprint.FirstID; first != nil {
		if _, err := CheckSprintID(*first, SheetSettings+": sprint.first.id"); err != nil {
			return err
		}
	}
	return nil
}

// back writes a document as YAML and reads it again.
func back(doc *yamlx.Map) (*yamlx.Map, error) {
	v, err := yamlx.Load(storage.DumpYAML(doc))
	if err != nil {
		return nil, err
	}
	if v == nil {
		return &yamlx.Map{}, nil
	}
	m, ok := v.(*yamlx.Map)
	if !ok {
		return nil, fmt.Errorf("document is not a mapping")
	}
	return m, nil
}

// reload is the data as they would be loaded again after writing: each document is written as
// YAML and read back with the same checks as when loading. This catches everything the own load
// check would reject later (non-finite numbers, wrong types, invalid ids) before writing, and
// rounds like saving does.
func reload(data *storage.TeamData) (*storage.TeamData, error) {
	key := data.Team.Key
	doc, err := back(storage.TeamToDict(data.Team))
	if err != nil {
		return nil, err
	}
	team, err := storage.TeamFromDict(key, doc, "team.yaml")
	if err != nil {
		return nil, err
	}
	if doc, err = back(storage.PeopleToDict(data.People)); err != nil {
		return nil, err
	}
	people, err := storage.PeopleFromDict(doc, "people.yaml")
	if err != nil {
		return nil, err
	}
	if doc, err = back(storage.ProductsToDict(data.Products)); err != nil {
		return nil, err
	}
	products, err := storage.ProductsFromDict(doc, "products.yaml")
	if err != nil {
		return nil, err
	}
	sprints := make([]model.Sprint, 0, len(data.Sprints))
	for _, s := range data.Sprints {
		if doc, err = back(storage.SprintToDict(s)); err != nil {
			return nil, err
		}
		sprint, err := storage.SprintFromDict(doc, "sprints/"+s.ID+".yaml")
		if err != nil {
			return nil, err
		}
		sprints = append(sprints, sprint)
	}
	return &storage.TeamData{Team: team, People: people, Sprints: sprints, Products: products}, nil
}

// CheckSettings checks that every setting passes the check of the settings page and of the
// command line (ranges, choices, region matching the country).
func CheckSettings(team model.Team) error {
	var problems []string
	for _, s := range settings.All {
		if s.Get(&team) == nil && s.Optional {
			continue
		}
		if _, err := s.Parse(s.Display(&team)); err != nil {
			problems = append(problems, s.Key+": "+err.Error())
		}
	}
	if len(problems) > 0 {
		lines := make([]string, len(problems))
		for i, p := range problems {
			lines[i] = "- " + p
		}
		return &storage.DataError{Msg: i18n.T("The workbook contains invalid settings:") + "\n" + strings.Join(lines, "\n")}
	}
	return nil
}

// CheckValid rejects the workbook if, as it would be saved, it cannot be loaded or the data
// check (as before every save) finds errors. The overall state is checked: the workbook together
// with the existing sprint files that are missing from it. It returns the reloaded data.
func CheckValid(data *storage.TeamData, today time.Time, existing *storage.TeamData) (*storage.TeamData, error) {
	if err := CheckIDs(data); err != nil {
		return nil, err
	}
	reloaded, err := reload(data)
	if err != nil {
		return nil, err
	}
	if err := CheckSettings(reloaded.Team); err != nil {
		return nil, err
	}
	union := reloaded
	if existing != nil {
		newIDs := map[string]bool{}
		folded := map[string]string{}
		for _, s := range reloaded.Sprints {
			newIDs[s.ID] = true
			folded[pytext.Casefold(s.ID)] = s.ID
		}
		var extra []model.Sprint
		for _, s := range existing.Sprints {
			if !newIDs[s.ID] {
				extra = append(extra, s)
			}
		}
		for _, old := range extra { // on Windows and macOS the same file as an imported ID
			if clash, ok := folded[pytext.Casefold(old.ID)]; ok {
				return nil, dataErr("Sprint ID {new} from the workbook and the existing sprint file {old} differ only in upper and lower case (the same file on Windows and macOS).",
					"new", yamlx.PyRepr(clash), "old", yamlx.PyRepr(old.ID))
			}
		}
		all := append(append([]model.Sprint(nil), reloaded.Sprints...), extra...)
		sort.SliceStable(all, func(a, b int) bool { return all[a].Start.Before(all[b].Start) })
		union = &storage.TeamData{Team: reloaded.Team, People: reloaded.People, Sprints: all, Products: reloaded.Products}
	}
	var errs []string
	for _, i := range validate.CheckTeam(union, today) {
		if i.Level == validate.Error {
			errs = append(errs, fmt.Sprintf("- %s: %s", i.Where, i.Message))
		}
	}
	if len(errs) > 0 {
		if len(errs) > 20 {
			errs = errs[:20]
		}
		return nil, &storage.DataError{Msg: i18n.T("The workbook contains invalid values:") + "\n" + strings.Join(errs, "\n")}
	}
	return reloaded, nil
}

// normalize brings an existing file into the same form in which the workbook would write it.
func normalize(name string, raw *yamlx.Map, key string) (*yamlx.Map, error) {
	switch name {
	case "team.yaml":
		team, err := storage.TeamFromDict(key, raw, name)
		if err != nil {
			return nil, err
		}
		return storage.TeamToDict(team), nil
	case "people.yaml":
		people, err := storage.PeopleFromDict(raw, name)
		if err != nil {
			return nil, err
		}
		return storage.PeopleToDict(people), nil
	case "products.yaml":
		products, err := storage.ProductsFromDict(raw, name)
		if err != nil {
			return nil, err
		}
		return storage.ProductsToDict(products), nil
	}
	sprint, err := storage.SprintFromDict(raw, name)
	if err != nil {
		return nil, err
	}
	return storage.SprintToDict(sprint), nil
}

// carryOver takes what the workbook cannot hold from the existing files, so that reading it back
// does not delete it: the product owners, the estimation unit, the sprint naming and the
// pro-forma sprints of the team, the kind of each person, the rule of each product, and the
// hand-given name and pre-planning details of each sprint (matching ids). Values the workbook
// does hold (a cell can be cleared) are never carried over.
func carryOver(data, existing *storage.TeamData) {
	data.Team.AsOf = existing.Team.AsOf
	data.Team.ProductOwners = existing.Team.ProductOwners
	data.Team.Estimation = existing.Team.Estimation
	data.Team.Sprint.Naming = existing.Team.Sprint.Naming
	data.Team.Sprint.ProForma = existing.Team.Sprint.ProForma
	kinds := map[string]model.PersonKind{}
	for _, p := range existing.People {
		kinds[p.ID] = p.Kind
	}
	for i := range data.People {
		if kind, ok := kinds[data.People[i].ID]; ok {
			data.People[i].Kind = kind
		}
	}
	rules := map[string]*model.Rule{}
	for _, p := range existing.Products {
		rules[p.ID] = p.Match
	}
	for i := range data.Products {
		if rule, ok := rules[data.Products[i].ID]; ok {
			data.Products[i].Match = rule
		}
	}
	old := map[string]*model.Sprint{}
	for i := range existing.Sprints {
		old[existing.Sprints[i].ID] = &existing.Sprints[i]
	}
	for i := range data.Sprints {
		s := &data.Sprints[i]
		o, ok := old[s.ID]
		if !ok {
			continue
		}
		s.Name = o.Name
		if s.Preplanned == nil {
			s.Preplanned = o.Preplanned
		}
		s.Matrix, s.Removed, s.Projects = o.Matrix, o.Removed, o.Projects
		s.CommittedTickets, s.Carry, s.RestNext = o.CommittedTickets, o.Carry, o.RestNext
		s.StartedOn, s.StartPending = o.StartedOn, o.StartPending
		for j := range s.Prognoses {
			for _, op := range o.Prognoses {
				if op.At.Equal(s.Prognoses[j].At) {
					s.Prognoses[j].Label, s.Prognoses[j].Finish = op.Label, op.Finish
					s.Prognoses[j].Carry, s.Prognoses[j].RestNext = op.Carry, op.RestNext
					s.Prognoses[j].FocusPercent, s.Prognoses[j].ExtraAbsenceDays = op.FocusPercent, op.ExtraAbsenceDays
				}
			}
		}
	}
}

// Plan compares the workbook with the existing files: list of changes per file and value. It
// rejects an invalid key, invalid ids, values that cannot be loaded and data with validation
// errors up front; nothing is written.
func Plan(repo *storage.Repository, data *storage.TeamData, today time.Time) (*ImportPlan, error) {
	if err := CheckTeamKey(repo, data.Team.Key); err != nil {
		return nil, err
	}
	var existing *storage.TeamData
	if repo.Exists(data.Team.Key) {
		var err error
		if existing, err = repo.Load(data.Team.Key); err != nil {
			return nil, err
		}
		// The workbook never contains the tracker section: the existing one is carried over.
		data.Team.Tracker = existing.Team.Tracker
		data.Team.TrackerRaw = existing.Team.TrackerRaw
		carryOver(data, existing)
	}
	if _, err := CheckValid(data, today, existing); err != nil {
		return nil, err
	}
	teamDir := repo.TeamDir(data.Team.Key)
	names, docs := documents(data)
	plan := &ImportPlan{Data: data}
	for _, name := range names {
		path := filepath.Join(teamDir, filepath.FromSlash(name))
		var oldFlat map[string]any
		if info, err := os.Stat(path); err == nil && info.Mode().IsRegular() {
			old, err := storage.ReadFile(path)
			if err != nil {
				return nil, err
			}
			normalized, err := normalize(name, old, data.Team.Key)
			if err != nil {
				return nil, err
			}
			oldFlat = flatten(normalized)
		}
		newFlat := flatten(docs[name])
		if oldFlat == nil {
			plan.Changes = append(plan.Changes, Change{File: name, New: i18n.T("newly created")})
			plan.Files = append(plan.Files, name)
			continue
		}
		keys := map[string]bool{}
		for k := range oldFlat {
			keys[k] = true
		}
		for k := range newFlat {
			keys[k] = true
		}
		sorted := make([]string, 0, len(keys))
		for k := range keys {
			sorted = append(sorted, k)
		}
		sort.Strings(sorted)
		changed := false
		for _, k := range sorted {
			before, after := oldFlat[k], newFlat[k]
			if !pyEqual(before, after) {
				changed = true
				plan.Changes = append(plan.Changes, Change{File: name, Path: k, Old: before, New: after})
			}
		}
		if changed {
			plan.Files = append(plan.Files, name)
		}
	}
	if entries, err := os.ReadDir(filepath.Join(teamDir, "sprints")); err == nil {
		known := map[string]bool{}
		for _, s := range data.Sprints {
			known["sprints/"+s.ID+".yaml"] = true
		}
		for _, e := range entries {
			name := "sprints/" + e.Name()
			if strings.HasSuffix(e.Name(), ".yaml") && !known[name] {
				plan.Untouched = append(plan.Untouched, name)
			}
		}
		sort.Strings(plan.Untouched)
	}
	return plan, nil
}

// Apply writes the changed files (unchanged ones are left untouched) and returns their paths.
func Apply(repo *storage.Repository, plan *ImportPlan) ([]string, error) {
	data := plan.Data
	key := data.Team.Key
	if err := CheckTeamKey(repo, key); err != nil { // here too: a plan can be assembled by hand
		return nil, err
	}
	if err := CheckIDs(data); err != nil {
		return nil, err
	}
	sprints := map[string]*model.Sprint{}
	for i := range data.Sprints {
		sprints["sprints/"+data.Sprints[i].ID+".yaml"] = &data.Sprints[i]
	}
	var paths []string
	for _, name := range plan.Files {
		var path string
		var err error
		switch name {
		case "team.yaml":
			path, err = repo.SaveTeam(data.Team)
		case "people.yaml":
			path, err = repo.SavePeople(key, data.People)
		case "products.yaml":
			path, err = repo.SaveProducts(key, data.Products)
		default:
			sprint, ok := sprints[name]
			if !ok {
				return paths, fmt.Errorf("%s: not in the plan", name)
			}
			path, err = repo.SaveSprint(key, sprint)
		}
		if err != nil {
			return paths, err
		}
		paths = append(paths, path)
	}
	return paths, nil
}
