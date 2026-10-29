package storage

import (
	"runtime"
	"strings"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/yamlx"
)

// TeamHeader is the comment at the top of team.yaml.
const TeamHeader = "# Team settings. Explanations: `foresprint help team`\n"

// pyError is an error that Python raises as ValueError, TypeError or OverflowError while a team
// is built; the caller turns it into "<where>: <message>".
type pyError string

// enumValue is Enum(value) of a StrEnum: the value must be one of the allowed texts.
func enumValue[T ~string](v any, allowed []T, typeName string) (T, *pyError) {
	if s, ok := v.(string); ok {
		for _, a := range allowed {
			if string(a) == s {
				return a, nil
			}
		}
	}
	e := pyError(repr(v) + " is not a valid " + typeName)
	var zero T
	return zero, &e
}

// choice is _choice: a value of an enumeration; missing = def.
func choice[T ~string](v any, allowed []T, def T, where, name string) (T, error) {
	if isEmptyText(v) {
		return def, nil
	}
	if s, ok := v.(string); ok {
		for _, a := range allowed {
			if string(a) == s {
				return a, nil
			}
		}
	}
	names := make([]string, len(allowed))
	for i, a := range allowed {
		names[i] = string(a)
	}
	var zero T
	return zero, dataErr("{where}: {name} '{value}' unknown (allowed: {allowed})",
		"where", where, "name", name, "value", pyStr(v), "allowed", strings.Join(names, ", "))
}

var (
	units         = []model.Unit{model.UnitPT, model.UnitSP}
	trendModes    = []model.TrendMode{model.TrendClassic, model.TrendLinear, model.TrendFlat}
	productBases  = []model.ProductBasis{model.BasisPlan, model.BasisRoadmap}
	numberings    = []model.Numbering{model.NumberingYearly, model.NumberingSequential}
	planningUses  = []model.PlanningUses{model.UsesRemaining, model.UsesEstimate}
	budgetBases   = []model.BudgetBasis{model.BudgetRoadmapShare, model.BudgetPlan}
	absenceStates = []model.AbsenceState{model.AbsencesUnknown, model.AbsencesExpected, model.AbsencesConfirmed}
)

// windowsDevices are reserved as a device on Windows, even with an extension ("con.txt").
var windowsDevices = map[string]bool{"con": true, "prn": true, "aux": true, "nul": true,
	"com0": true, "com1": true, "com2": true, "com3": true, "com4": true, "com5": true,
	"com6": true, "com7": true, "com8": true, "com9": true,
	"lpt0": true, "lpt1": true, "lpt2": true, "lpt3": true, "lpt4": true, "lpt5": true,
	"lpt6": true, "lpt7": true, "lpt8": true, "lpt9": true}

// FileNameProblem says why name is not a safe file name (without extension), or "" if it is
// fine. It applies to sprint ids that become file names: no path separator, no drive or data
// stream (colon), no control characters, no Windows device names, no dot or space at the edge.
//
// With portable (default for external input such as an import) the strictest rule applies, so
// that the name is a file name on any system. Without it only what would be a path on THIS
// system applies; this protects writing without excluding existing data.
func FileNameProblem(name string, portable bool) string {
	strict := portable || runtime.GOOS == "windows"
	if name == "" || utf8.RuneCountInString(name) > 80 {
		return Translate("empty or longer than 80 characters")
	}
	forbidden := "/"
	if strict {
		forbidden = "<>:\"/\\|?*"
	}
	for _, c := range name {
		if c < 32 || strings.ContainsRune(forbidden, c) {
			return Translate("path separator, colon, special or control character")
		}
	}
	if name != strings.TrimSpace(name) || strings.HasPrefix(name, ".") || strings.HasSuffix(name, ".") {
		return Translate("starts or ends with a dot or a space")
	}
	if strict {
		head, _, _ := strings.Cut(name, ".")
		if windowsDevices[strings.ToLower(strings.TrimSpace(head))] {
			return Translate("reserved for devices on Windows")
		}
	}
	return ""
}

// firstID is _first_id: the id of the first sprint; as with the sprint files, a number like
// 2026.20 must be in quotes (otherwise it becomes 2026.2).
func firstID(v any, where string) (*string, error) {
	if v == nil {
		return nil, nil
	}
	if _, ok := v.(float64); ok {
		return nil, dataErr("{where}: please quote the id, e.g. id: \"2026.20\"", "where", where)
	}
	s := pyStr(v)
	if problem := FileNameProblem(s, false); problem != "" {
		return nil, dataErr("{where}: id {id} is not allowed ({problem})", "where", where, "id", repr(s), "problem", problem)
	}
	return &s, nil
}

// TeamFromDict is team_from_dict.
func TeamFromDict(key string, d *yamlx.Map, where string) (model.Team, error) {
	sprint, err := mapping(get(d, "sprint"), where, "sprint")
	if err != nil {
		return model.Team{}, err
	}
	fc, err := mapping(get(d, "forecast"), where, "forecast")
	if err != nil {
		return model.Team{}, err
	}
	capm, err := mapping(get(d, "capacity"), where, "capacity")
	if err != nil {
		return model.Team{}, err
	}
	first, err := mapping(get(sprint, "first"), where, "sprint.first")
	if err != nil {
		return model.Team{}, err
	}
	rawFeatures, err := mapping(get(d, "features"), where, "features")
	if err != nil {
		return model.Team{}, err
	}
	features := model.Features{Explicit: false} // older file: the repository derives the values
	if has(d, "features") {
		features = model.Features{
			Products:   truthy(getOr(rawFeatures, "products", false)),
			PO:         truthy(getOr(rawFeatures, "po", false)),
			Production: truthy(getOr(rawFeatures, "production", false)),
			Tickets:    truthy(getOr(rawFeatures, "tickets", false)),
			Projects:   truthy(getOr(rawFeatures, "projects", false)),
			Explicit:   true,
		}
		// Before the switch could turn projects off, tickets implied them: a file with tickets and
		// no "projects" key keeps its projects.
		if !has(rawFeatures, "projects") && features.Tickets {
			features.Projects = true
		}
		if features.ProductionMax, err = floatOf(get(rawFeatures, "production_max"), where+": features.production_max"); err != nil {
			return model.Team{}, err
		}
		if m := features.ProductionMax; m != nil && *m < 0 {
			return model.Team{}, dataErr("{where}: production_max must not be negative", "where", where)
		}
		if features.ProductionMax != nil && *features.ProductionMax == 100 {
			features.ProductionMax = nil
		}
	}
	tracker := model.NewTrackerSettings()
	var trackerRaw any
	if features.Tickets {
		m, err := mapping(get(d, "tracker"), where, "tracker")
		if err != nil {
			return model.Team{}, err
		}
		if tracker, err = trackerFrom(m, where); err != nil {
			return model.Team{}, err
		}
	} else if truthy(get(d, "tracker")) {
		// Feature off: the section must not break the rest of the app. A valid one is still
		// read (switching the feature on again keeps it); an invalid one is kept as it is.
		m, err := mapping(get(d, "tracker"), where, "tracker")
		if err == nil {
			tracker, err = trackerFrom(m, where)
		}
		if err != nil {
			tracker = model.NewTrackerSettings()
			trackerRaw = get(d, "tracker")
		}
	}

	team := model.NewTeam(key, strOr(get(d, "name"), key))
	team.Features = features
	team.Tracker = tracker
	team.TrackerRaw = trackerRaw
	fail := func(m pyError) (model.Team, error) { return model.Team{}, &DataError{Msg: where + ": " + string(m)} }

	unit, perr := enumValue(getOr(d, "unit", "PT"), units, "Unit")
	if perr != nil {
		return fail(*perr)
	}
	team.Unit = unit
	n, msg := pyIntConv(getOr(sprint, "length_days", int64(14)))
	if msg != "" {
		return fail(pyError(msg))
	}
	team.Sprint.LengthDays = n
	if team.Sprint.Naming, err = namingFrom(get(sprint, "naming"), where+": sprint"); err != nil {
		return model.Team{}, err
	}
	if team.Sprint.ProForma, err = texts(get(sprint, "pro_forma"), where, "sprint.pro_forma"); err != nil {
		return model.Team{}, err
	}
	if team.Estimation, err = estimationFrom(get(d, "estimation"), where); err != nil {
		return model.Team{}, err
	}
	if team.ProductOwners, err = productOwnersFrom(get(d, "product_owners"), where); err != nil {
		return model.Team{}, err
	}
	numbering, perr := enumValue(getOr(sprint, "numbering", "yearly"), numberings, "Numbering")
	if perr != nil {
		return fail(*perr)
	}
	team.Sprint.Numbering = numbering
	if team.Sprint.FirstID, err = firstID(get(first, "id"), where); err != nil {
		return model.Team{}, err
	}
	if truthy(get(first, "start")) {
		start, err := dateOf(get(first, "start"), where)
		if err != nil {
			return model.Team{}, err
		}
		team.Sprint.FirstStart = &start
	}

	if truthy(get(d, "as_of")) {
		day, err := dateOf(get(d, "as_of"), where+": as_of")
		if err != nil {
			return model.Team{}, err
		}
		team.AsOf = &day
	}

	f := &team.Forecast
	if f.ReferenceCapacity, msg = finiteOf(getOr(fc, "reference_capacity", int64(67))); msg != "" {
		return fail(pyError(msg))
	}
	if f.Window, msg = pyIntConv(getOr(fc, "window", int64(5))); msg != "" {
		return fail(pyError(msg))
	}
	if f.RoadmapShare, msg = finiteOf(getOr(fc, "roadmap_share", 0.8)); msg != "" {
		return fail(pyError(msg))
	}
	if f.Rounding, msg = pyIntConv(getOr(fc, "rounding", int64(1))); msg != "" {
		return fail(pyError(msg))
	}
	modeRaw := getOr(fc, "trend_mode", "flat")
	if modeRaw == "klassisch" { // older files still name the mode in German
		modeRaw = "classic"
	}
	if f.TrendMode, perr = enumValue(modeRaw, trendModes, "TrendMode"); perr != nil {
		return fail(*perr)
	}
	if f.Horizon, msg = pyIntConv(getOr(fc, "horizon", int64(3))); msg != "" {
		return fail(pyError(msg))
	}
	if f.StartRate, msg = finiteOf(getOr(fc, "start_rate", 0.0)); msg != "" {
		return fail(pyError(msg))
	}
	if f.ProductBasis, perr = enumValue(getOr(fc, "product_basis", "plan"), productBases, "ProductBasis"); perr != nil {
		return fail(*perr)
	}

	c := &team.Capacity
	if c.OverheadShare, msg = finiteOf(getOr(capm, "overhead_share", 0.0)); msg != "" {
		return fail(pyError(msg))
	}
	if c.OverheadDays, msg = finiteOf(getOr(capm, "overhead_days", 0.0)); msg != "" {
		return fail(pyError(msg))
	}
	country, err := code(get(capm, "country"), where, "capacity.country")
	if err != nil {
		return model.Team{}, err
	}
	c.Country = "DE"
	if country != nil && *country != "" {
		c.Country = upper(*country)
	}
	if c.Region, err = code(get(capm, "region"), where, "capacity.region"); err != nil {
		return model.Team{}, err
	}
	c.Workweek = pyStr(getOr(capm, "workweek", "auto"))
	if c.Rounding, msg = pyIntConv(getOr(capm, "rounding", int64(1))); msg != "" {
		return fail(pyError(msg))
	}
	if c.AbsenceHistory, msg = pyIntConv(getOr(capm, "absence_history", int64(4))); msg != "" {
		return fail(pyError(msg))
	}
	if c.ProductionCap, msg = finiteOf(getOr(capm, "production_cap", 100.0)); msg != "" {
		return fail(pyError(msg))
	}
	return team, nil
}

// TeamToDict is team_to_dict.
func TeamToDict(team model.Team) *yamlx.Map {
	sprint := omap("length_days", int64(team.Sprint.LengthDays), "numbering", string(team.Sprint.Numbering))
	if team.Sprint.FirstID != nil && team.Sprint.FirstStart != nil {
		put(sprint, "first", omap("id", *team.Sprint.FirstID, "start", yamlx.Date(*team.Sprint.FirstStart)))
	}
	fc := omap(
		"reference_capacity", clean(team.Forecast.ReferenceCapacity),
		"window", int64(team.Forecast.Window),
		"roadmap_share", team.Forecast.RoadmapShare,
		"rounding", int64(team.Forecast.Rounding),
		"trend_mode", string(team.Forecast.TrendMode),
		"horizon", int64(team.Forecast.Horizon),
	)
	if team.Forecast.StartRate != 0 {
		put(fc, "start_rate", clean(team.Forecast.StartRate))
	}
	if team.Forecast.ProductBasis != model.BasisPlan {
		put(fc, "product_basis", string(team.Forecast.ProductBasis))
	}
	capm := omap("overhead_share", team.Capacity.OverheadShare)
	if team.Capacity.OverheadDays != 0 {
		put(capm, "overhead_days", clean(team.Capacity.OverheadDays))
	}
	if team.Capacity.Country != "DE" {
		put(capm, "country", team.Capacity.Country)
	}
	put(capm, "region", strPtr(team.Capacity.Region))
	put(capm, "rounding", int64(team.Capacity.Rounding))
	if team.Capacity.Workweek != "auto" {
		put(capm, "workweek", team.Capacity.Workweek)
	}
	if team.Capacity.AbsenceHistory != 4 { // also 0 = off
		put(capm, "absence_history", int64(team.Capacity.AbsenceHistory))
	}
	if team.Capacity.ProductionCap != 100 { // only when set: files of teams without it stay unchanged
		put(capm, "production_cap", clean(team.Capacity.ProductionCap))
	}
	features := omap("products", team.Features.Products, "po", team.Features.PO, "production", team.Features.Production)
	if m := team.Features.ProductionMax; m != nil && *m != 100 {
		put(features, "production_max", *m)
	}
	if team.Features.Tickets { // only when on: files of teams without it stay unchanged
		put(features, "tickets", true)
	}
	if team.Features.Tickets {
		// With tickets, projects are the default and stay unwritten (older files read the same);
		// only "off" is stored, or the file would read as "projects with tickets" again.
		if !team.Features.Projects {
			put(features, "projects", false)
		}
	} else if team.Features.Projects {
		put(features, "projects", true)
	}
	if len(team.Sprint.Naming) > 0 {
		put(sprint, "naming", namingTo(team.Sprint.Naming))
	}
	if len(team.Sprint.ProForma) > 0 {
		put(sprint, "pro_forma", strs(team.Sprint.ProForma))
	}
	out := omap("name", team.Name, "unit", string(team.Unit), "features", features,
		"sprint", sprint, "forecast", fc, "capacity", capm)
	if est := estimationTo(team.Estimation); len(est.Entries) > 0 {
		put(out, "estimation", est)
	}
	if team.AsOf != nil { // only when set: files of teams without it stay unchanged
		put(out, "as_of", yamlx.Date(*team.AsOf))
	}
	if len(team.ProductOwners) > 0 { // only with a list: files from 0.8 stay unchanged
		put(out, "product_owners", productOwnersTo(team.ProductOwners))
	}
	// The tracker section is kept while the feature is on and whenever it holds settings, so
	// switching the feature off and on again does not lose the configuration.
	switch {
	case team.TrackerRaw != nil: // unreadable while the feature was off: written as it was
		put(out, "tracker", team.TrackerRaw)
	case team.Features.Tickets || !team.Tracker.IsDefault():
		put(out, "tracker", trackerTo(team.Tracker))
	}
	return out
}
