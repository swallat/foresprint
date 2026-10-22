package excel

import (
	"math"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/yamlx"
)

var (
	settingInts = []string{
		"sprint.length_days", "forecast.window", "forecast.rounding", "forecast.horizon",
		"capacity.rounding", "capacity.absence_history",
	}
	settingFloats = []string{
		"forecast.reference_capacity", "forecast.roadmap_share", "capacity.overhead_share",
		"capacity.overhead_days",
	}
	settingFlags = []string{"features.products", "features.po", "features.production", "features.tickets", "features.projects"}
	settingDates = []string{"sprint.first.start"}
	settingTexts = []string{
		"name", "unit", "sprint.numbering", "sprint.first.id", "forecast.trend_mode",
		"forecast.product_basis", "capacity.country", "capacity.region", "capacity.workweek",
	}
)

func knownSetting(path string) bool {
	return slices.Contains(settingTexts, path) || slices.Contains(settingInts, path) ||
		slices.Contains(settingFloats, path) || slices.Contains(settingFlags, path) ||
		slices.Contains(settingDates, path)
}

// checkFormat checks the format and returns the workbook's team key (nil for older workbooks).
func checkFormat(wb *workbook) (*string, error) {
	for _, l := range LegacySheets {
		if wb.has(l[0]) && !wb.has(l[1]) {
			wb.rename(l[0], l[1])
		}
	}
	var missing []string
	for _, n := range []string{SheetSettings, SheetForecast, SheetSprints, SheetPeople, SheetProducts} {
		if !wb.has(n) {
			missing = append(missing, n)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return nil, dataErr("Not an Excel output of foresprint: missing sheet(s): {missing}", "missing", strings.Join(missing, ", "))
	}
	if version, ok := wb.properties[FormatProperty]; ok && version != FormatVersion {
		return nil, dataErr("The workbook has format {found}; this program reads format {expected}.", "found", version, "expected", FormatVersion)
	}
	if team, ok := wb.properties[TeamProperty]; ok {
		return &team, nil
	}
	return nil, nil
}

// settingsOf is the settings as a nested mapping as in team.yaml. Only known keys, each value
// with its type: finite numbers (whole numbers as integers), yes/no switches.
func settingsOf(sh sheet0) (*yamlx.Map, error) {
	result := &yamlx.Map{}
	for _, r := range sh.rows(SettingsFirstRow) {
		pathV := sh.get(r, 2)
		path, isStr := pathV.(string)
		if !isStr || !knownSetting(path) {
			if isStr && path != "" && sh.get(r, 1) != nil && strings.Contains(path, ".") {
				return nil, dataErr("{where}: unknown key {key}", "where", sh.where(r.number, 2), "key", yamlx.PyRepr(path))
			}
			continue // label rows without a key
		}
		if sh.get(r, 1) == nil {
			continue
		}
		var value any
		switch {
		case slices.Contains(settingInts, path):
			n, err := sh.number(r, 1)
			if err != nil {
				return nil, err
			}
			if n == nil || *n != math.Trunc(*n) {
				return nil, dataErr("{where}: a whole number expected, found: {value}", "where", sh.where(r.number, 1), "value", reprValue(sh.get(r, 1)))
			}
			value = int64(*n)
		case slices.Contains(settingFloats, path):
			n, err := sh.number(r, 1)
			if err != nil {
				return nil, err
			}
			if n != nil {
				value = *n
			}
		case slices.Contains(settingFlags, path):
			b, err := sh.flag(r, 1)
			if err != nil {
				return nil, err
			}
			value = b
		case slices.Contains(settingDates, path):
			d, err := sh.day(r, 1)
			if err != nil {
				return nil, err
			}
			if d != nil {
				value = yamlx.Date(*d)
			}
		default:
			s, err := sh.text(r, 1)
			if err != nil {
				return nil, err
			}
			if s != nil {
				value = *s
			}
		}
		node := result
		parts := strings.Split(path, ".")
		for _, key := range parts[:len(parts)-1] {
			child, ok := node.Get(key)
			if !ok {
				child = &yamlx.Map{}
				node.Set(key, child)
			}
			node = child.(*yamlx.Map)
		}
		node.Set(parts[len(parts)-1], value)
	}
	return result, nil
}

func peopleOf(sh sheet0) ([]model.Person, error) {
	var order []string
	people := map[string]*model.Person{}
	for _, r := range sh.rows(2) {
		pid, err := sh.text(r, 0)
		if err != nil {
			return nil, err
		}
		if pid == nil {
			continue
		}
		person := people[*pid]
		if person == nil {
			name, err := sh.text(r, 1)
			if err != nil {
				return nil, err
			}
			country, err := sh.text(r, 2)
			if err != nil {
				return nil, err
			}
			region, err := sh.text(r, 3)
			if err != nil {
				return nil, err
			}
			workweek, err := sh.text(r, 4)
			if err != nil {
				return nil, err
			}
			access, err := sh.flag(r, 5)
			if err != nil {
				return nil, err
			}
			person = &model.Person{ID: *pid, Name: *pid, Region: region, Workweek: workweek, ProductionAccess: access}
			if name != nil && *name != "" {
				person.Name = *name
			}
			if c := strings.ToUpper(strings.ReplaceAll(strOf(country), "ß", "SS")); c != "" {
				person.Country = &c
			}
			people[*pid] = person
			order = append(order, *pid)
		}
		start, err := sh.day(r, 6)
		if err != nil {
			return nil, err
		}
		if start != nil {
			fte, err := sh.number(r, 8)
			if err != nil {
				return nil, err
			}
			end, err := sh.day(r, 7)
			if err != nil {
				return nil, err
			}
			m := model.Membership{Start: *start, End: end, FTE: 1.0}
			if fte != nil {
				m.FTE = *fte
			}
			person.Memberships = append(person.Memberships, m)
		}
	}
	out := make([]model.Person, len(order))
	for i, id := range order {
		out[i] = *people[id]
	}
	return out, nil
}

func productsOf(sh sheet0) ([]model.Product, error) {
	var out []model.Product
	for _, r := range sh.rows(2) {
		pid, err := sh.text(r, 0)
		if err != nil {
			return nil, err
		}
		if pid == nil {
			continue
		}
		name, err := sh.text(r, 1)
		if err != nil {
			return nil, err
		}
		po, err := sh.text(r, 2)
		if err != nil {
			return nil, err
		}
		start, err := sh.day(r, 3)
		if err != nil {
			return nil, err
		}
		end, err := sh.day(r, 4)
		if err != nil {
			return nil, err
		}
		share, err := sh.number(r, 5)
		if err != nil {
			return nil, err
		}
		p := model.Product{ID: *pid, Name: *pid, PO: po, Start: start, End: end, Share: share}
		if name != nil && *name != "" {
			p.Name = *name
		}
		out = append(out, p)
	}
	return out, nil
}

func preplannedOf(sh sheet0, r sheetRow) (model.OrderedMap[float64], error) {
	var result model.OrderedMap[float64]
	text, err := sh.text(r, 9)
	if err != nil {
		return result, err
	}
	for _, part := range strings.Split(strOf(text), ";") {
		if pytext.Strip(part) == "" {
			continue
		}
		key, value, _ := strings.Cut(part, "=")
		v, ok := parseFloat(strings.ReplaceAll(pytext.Strip(value), ",", "."))
		if !ok || math.IsNaN(v) || math.IsInf(v, 0) || math.Abs(v) > MaxNumber {
			shown := "None"
			if text != nil {
				shown = yamlx.PyRepr(*text)
			}
			return result, dataErr("{where}: expected ID=value; …, found: {value}", "where", sh.where(r.number, 9), "value", shown)
		}
		result.Set(pytext.Strip(key), v)
	}
	return result, nil
}

type forecastRow struct {
	start, end                            *time.Time
	commitment, velocity, scope, capacity *float64
	row                                   int
}

func (f forecastRow) empty() bool {
	return f.start == nil && f.end == nil && f.commitment == nil && f.velocity == nil && f.scope == nil && f.capacity == nil
}

func (f forecastRow) hasNumber() bool {
	return f.commitment != nil || f.velocity != nil || f.scope != nil || f.capacity != nil
}

func dateValue(t *time.Time) any {
	if t == nil {
		return nil
	}
	return yamlx.Date(*t)
}

func sprintsOf(wb *workbook) ([]model.Sprint, error) {
	fc := sheet0{wb.sheets[SheetForecast], SheetForecast}
	sp := sheet0{wb.sheets[SheetSprints], SheetSprints}
	base := map[string]forecastRow{}
	var baseOrder []string
	seen := map[string]bool{}
	sheetIDs := map[string]bool{}
	for _, r := range sp.rows(2) {
		id, err := sp.text(r, 0)
		if err != nil {
			return nil, err
		}
		if id != nil {
			sheetIDs[*id] = true
		}
	}
	for _, r := range fc.rows(ForecastFirstRow + 1) {
		sid, err := fc.text(r, 0)
		if err != nil {
			return nil, err
		}
		if sid == nil {
			continue
		}
		var e forecastRow
		e.row = r.number
		if e.start, err = fc.day(r, 1); err != nil {
			return nil, err
		}
		if e.end, err = fc.day(r, 2); err != nil {
			return nil, err
		}
		if e.commitment, err = fc.number(r, 3); err != nil {
			return nil, err
		}
		if e.velocity, err = fc.number(r, 4); err != nil {
			return nil, err
		}
		if e.scope, err = fc.number(r, 5); err != nil {
			return nil, err
		}
		if e.capacity, err = fc.number(r, 6); err != nil {
			return nil, err
		}
		if !sheetIDs[*sid] && e.empty() {
			continue // free text (sum, hint) below the sprints: not a sprint row
		}
		if _, err := CheckSprintID(*sid, fc.where(r.number, 0)); err != nil {
			return nil, err
		}
		if seen[pytext.Casefold(*sid)] {
			return nil, dataErr("{where}: sprint ID {id} appears twice (upper and lower case count as the same on Windows and macOS).",
				"where", fc.where(r.number, 0), "id", yamlx.PyRepr(*sid))
		}
		seen[pytext.Casefold(*sid)] = true
		if _, dup := base[*sid]; !dup {
			baseOrder = append(baseOrder, *sid)
		}
		base[*sid] = e
	}
	type listedRow struct {
		r sheetRow
	}
	listed := map[string]listedRow{}
	var listedOrder []string
	for _, r := range sp.rows(2) {
		sid, err := sp.text(r, 0)
		if err != nil {
			return nil, err
		}
		if sid == nil {
			continue
		}
		if _, err := CheckSprintID(*sid, sp.where(r.number, 0)); err != nil {
			return nil, err
		}
		for _, other := range listedOrder {
			if pytext.Casefold(other) == pytext.Casefold(*sid) {
				return nil, dataErr("{where}: sprint ID {id} appears twice (upper and lower case count as the same on Windows and macOS).",
					"where", sp.where(r.number, 0), "id", yamlx.PyRepr(*sid))
			}
		}
		if _, dup := listed[*sid]; !dup {
			listedOrder = append(listedOrder, *sid)
		}
		listed[*sid] = listedRow{r}
	}
	var ids []string
	for _, sid := range baseOrder {
		if _, ok := listed[sid]; ok || base[sid].hasNumber() {
			ids = append(ids, sid)
		}
	}
	for _, sid := range listedOrder {
		if _, ok := base[sid]; !ok {
			return nil, dataErr("{where}: sprint {id} is missing on the sheet {sheet}",
				"where", sp.where(listed[sid].r.number, 0), "id", sid, "sheet", SheetForecast)
		}
	}
	var result []model.Sprint
	for _, sid := range ids {
		v := base[sid]
		if v.start == nil || v.end == nil {
			return nil, dataErr("{where}: start and end of sprint {id} are missing", "where", fc.where(v.row, 1), "id", sid)
		}
		d := &yamlx.Map{}
		put := func(key string, value any) {
			if value != nil {
				d.Set(key, value)
			}
		}
		floatOrNil := func(p *float64) any {
			if p == nil {
				return nil
			}
			return *p
		}
		put("id", sid)
		put("start", dateValue(v.start))
		put("end", dateValue(v.end))
		put("capacity", floatOrNil(v.capacity))
		put("forecast_ist", floatOrNil(v.commitment))
		put("velocity", floatOrNil(v.velocity))
		put("scope_creep", floatOrNil(v.scope))
		if l, ok := listed[sid]; ok {
			r := l.r
			state, err := sp.text(r, 1)
			if err != nil {
				return nil, err
			}
			if state != nil {
				if !slices.Contains([]string{string(model.AbsencesUnknown), string(model.AbsencesExpected), string(model.AbsencesConfirmed), string(model.AbsencesOpen)}, *state) {
					return nil, dataErr("{where}: unknown state of the absences: {value}", "where", sp.where(r.number, 1), "value", yamlx.PyRepr(*state))
				}
				put("absence_state", *state)
			}
			for _, f := range []struct {
				key string
				col int
			}{{"forecast_plan", 2}, {"not_done", 6}, {"additional_done", 7}, {"production_planned", 8}, {"production_done", 9}} {
				n, err := sp.number(r, f.col)
				if err != nil {
					return nil, err
				}
				put(f.key, floatOrNil(n))
			}
			carry, err := sp.number(r, 3)
			if err != nil {
				return nil, err
			}
			backlog, err := sp.number(r, 4)
			if err != nil {
				return nil, err
			}
			corrText, err := sp.text(r, 5)
			if err != nil {
				return nil, err
			}
			if carry != nil || backlog != nil || strOf(corrText) != "" {
				corrections := []any{}
				for _, part := range pytext.Fields(strOf(corrText)) {
					f, ok := parseFloat(strings.ReplaceAll(part, ",", "."))
					if !ok {
						return nil, dataErr("{where}: please enter corrections as numbers separated by spaces", "where", sp.where(r.number, 5))
					}
					corrections = append(corrections, f)
				}
				planning := &yamlx.Map{}
				planning.Set("carryover", orZero(carry))
				planning.Set("backlog", orZero(backlog))
				planning.Set("corrections", corrections)
				put("planning", planning)
			}
			note, err := sp.text(r, 10)
			if err != nil {
				return nil, err
			}
			if note != nil {
				put("note", *note)
			}
		}
		raw := &yamlx.Map{}
		for _, e := range d.Entries {
			if e.Value != nil {
				raw.Set(e.Key, e.Value)
			}
		}
		s, err := storage.SprintFromDict(raw, SheetForecast+": "+sid)
		if err != nil {
			return nil, err
		}
		result = append(result, s)
	}
	byID := map[string]*model.Sprint{}
	for i := range result {
		byID[result[i].ID] = &result[i]
	}

	if wb.has(SheetAbsences) {
		ab := sheet0{wb.sheets[SheetAbsences], SheetAbsences}
		for _, r := range ab.rows(2) {
			sid, err := ab.text(r, 0)
			if err != nil {
				return nil, err
			}
			pid, err := ab.text(r, 1)
			if err != nil {
				return nil, err
			}
			kind, err := ab.text(r, 4)
			if err != nil {
				return nil, err
			}
			days, err := ab.number(r, 3)
			if err != nil {
				return nil, err
			}
			if sid == nil || pid == nil || days == nil {
				continue
			}
			sprint := byID[*sid]
			if sprint == nil || kind == nil || !slices.Contains(AbsenceKinds, *kind) {
				shown := "None"
				if kind != nil {
					shown = yamlx.PyRepr(*kind)
				}
				return nil, dataErr("{where}: unknown sprint {id} or kind {kind}", "where", ab.where(r.number, 0), "id", *sid, "kind", shown)
			}
			target := &sprint.Absences
			if *kind == "expected_absences" {
				target = &sprint.ExpectedAbsences
			}
			if *target == nil {
				*target = map[string]float64{}
			}
			(*target)[*pid] = *days
		}
	}

	if wb.has(SheetValues) {
		vs := sheet0{wb.sheets[SheetValues], SheetValues}
		for _, r := range vs.rows(2) {
			sid, err := vs.text(r, 0)
			if err != nil {
				return nil, err
			}
			pid, err := vs.text(r, 1)
			if err != nil {
				return nil, err
			}
			if sid == nil || pid == nil {
				continue
			}
			var values model.ProductValues
			for k, dst := range []**float64{&values.Preplanned, &values.Planned, &values.Done, &values.ProductionPlanned, &values.ProductionDone} {
				n, err := vs.number(r, 5+k)
				if err != nil {
					return nil, err
				}
				*dst = n
			}
			if values.IsEmpty() {
				continue
			}
			sprint := byID[*sid]
			if sprint == nil {
				return nil, dataErr("{where}: unknown sprint {id}", "where", vs.where(r.number, 0), "id", *sid)
			}
			if sprint.Products == nil {
				sprint.Products = map[string]model.ProductValues{}
			}
			sprint.Products[*pid] = values
		}
	}

	if wb.has(SheetPrognose) {
		pg := sheet0{wb.sheets[SheetPrognose], SheetPrognose}
		for _, r := range pg.rows(2) {
			sid, err := pg.text(r, 0)
			if err != nil {
				return nil, err
			}
			if sid == nil || pg.get(r, 1) == nil {
				continue
			}
			sprint := byID[*sid]
			if sprint == nil {
				return nil, dataErr("{where}: unknown sprint {id}", "where", pg.where(r.number, 0), "id", *sid)
			}
			at, ok := pg.timestamp(r, 1)
			if !ok {
				return nil, dataErr("{where}: point in time (date with time) expected", "where", pg.where(r.number, 1))
			}
			p := model.Prognosis{At: at}
			if p.Comment, err = pg.text(r, 2); err != nil {
				return nil, err
			}
			if p.Commitment, err = pg.number(r, 3); err != nil {
				return nil, err
			}
			if p.NotDone, err = pg.number(r, 4); err != nil {
				return nil, err
			}
			if p.AdditionalDone, err = pg.number(r, 5); err != nil {
				return nil, err
			}
			if p.ExpectedDone, err = pg.number(r, 6); err != nil {
				return nil, err
			}
			if p.Target, err = pg.text(r, 7); err != nil {
				return nil, err
			}
			if p.Plan, err = pg.number(r, 8); err != nil {
				return nil, err
			}
			if p.Preplanned, err = preplannedOf(pg, r); err != nil {
				return nil, err
			}
			sprint.Prognoses = append(sprint.Prognoses, p)
		}
	}
	for i := range result { // the UI expects "older first"
		sort.SliceStable(result[i].Prognoses, func(a, b int) bool { return result[i].Prognoses[a].At.Before(result[i].Prognoses[b].At) })
	}
	sort.SliceStable(result, func(a, b int) bool { return result[a].Start.Before(result[b].Start) })
	return result, nil
}

func orZero(p *float64) float64 {
	if p == nil {
		return 0
	}
	return *p
}

// ReadWorkbook reads the workbook into team data; errors name the sheet and the cell. The
// second result is the team key from the workbook (nil for an older workbook without a key,
// callers should warn). A workbook of a different team is an error so that no team overwrites
// another team's data.
func ReadWorkbook(source []byte, teamKey string) (*storage.TeamData, *string, error) {
	wb, err := openWorkbook(source)
	if err != nil {
		return nil, nil, dataErr("The file is not a readable Excel workbook: {error}", "error", err.Error())
	}
	fileTeam, err := checkFormat(wb)
	if err != nil {
		return nil, nil, err
	}
	if fileTeam != nil && *fileTeam != teamKey {
		return nil, nil, dataErr("The workbook is from team {found}, but it is being imported into team {expected}.",
			"found", yamlx.PyRepr(*fileTeam), "expected", yamlx.PyRepr(teamKey))
	}
	settings, err := settingsOf(sheet0{wb.sheets[SheetSettings], SheetSettings})
	if err != nil {
		return nil, nil, err
	}
	team, err := storage.TeamFromDict(teamKey, settings, SheetSettings)
	if err != nil {
		return nil, nil, err
	}
	people, err := peopleOf(sheet0{wb.sheets[SheetPeople], SheetPeople})
	if err != nil {
		return nil, nil, err
	}
	products, err := productsOf(sheet0{wb.sheets[SheetProducts], SheetProducts})
	if err != nil {
		return nil, nil, err
	}
	sprints, err := sprintsOf(wb)
	if err != nil {
		return nil, nil, err
	}
	return &storage.TeamData{Team: team, People: people, Products: products, Sprints: sprints}, fileTeam, nil
}
