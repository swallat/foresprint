// Package excel is the Excel output of a team and the way back (the import of such a workbook).
// It ports src/foresprint/excel.py and excel_import.py.
//
// The workbook is not identical to an earlier list, but calculates the same logic as the engine
// with real Excel formulas: normalized velocity, moving average, trend (using the trend mode
// valid at export), capacity, Forecast PLAN, plannable, small items, fulfillment and focus
// factor, plus the split by production access and by product and line charts of the trend. The
// formulas carry the value calculated by the engine as a cached result so that preview programs
// also show numbers.
package excel

import (
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/xuri/excelize/v2"

	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/yamlx"
)

// Sheet names and layout are fixed (not translated): the import recognizes the workbook by them
// and reads the inputs by column position, not by heading. Bump FormatVersion on changes.
const (
	FormatVersion  = "1"
	FormatProperty = "sprintforecast-format"
	TeamProperty   = "sprintforecast-team"

	SheetSettings = "Settings"
	SheetForecast = "Forecast"
	SheetSprints  = "Sprint data"
	SheetAbsences = "Absences"
	SheetPeople   = "People"
	SheetProducts = "Product list"
	SheetValues   = "Product values"
	SheetPrognose = "Prognoses"
	SheetTrend    = "Trend"
)

// SettingsFirstRow is the first row (1-based) of the settings: column A label, B value, C key
// (path in team.yaml, e.g. forecast.window).
const SettingsFirstRow = 3

// ForecastFirstRow is the first data row (0-based) of the Forecast sheet; columns 0-6 are the
// inputs the import reads.
const ForecastFirstRow = 3

// Columns of the sheets the import reads by position.
var (
	SprintColumns = []string{"id", "absence_state", "forecast_plan", "carryover", "backlog", "corrections",
		"not_done", "additional_done", "production_planned", "production_done", "note"}
	AbsenceColumns = []string{"sprint", "person", "name", "days", "kind"}
	AbsenceKinds   = []string{"absences", "expected_absences"}
	PersonColumns  = []string{"id", "name", "country", "region", "workweek", "production_access", "from", "to", "fte"}
	ProductColumns = []string{"id", "name", "po", "from", "to", "share"}
	ValueColumns   = []string{"sprint", "product", "name", "po", "standard",
		"preplanned", "planned", "done", "production_planned", "production_done"}
	PrognosisColumns = []string{"sprint", "at", "comment", "forecast_ist", "not_done", "additional_done", "expected_done",
		"target", "plan", "preplanned"}
)

const (
	yellow = "FFF8DC"
	headBG = "E8EEF7"
	greyFg = "BBBBBB"
)

var (
	boldF  = Format{Bold: true, Wrap: true, BG: headBG}
	dateF  = Format{Num: "dd.mm.yyyy"}
	n2     = Format{Num: "0.00"}
	n1     = Format{Num: "0.0"}
	pc     = Format{Num: "0.0%"}
	inp    = Format{Num: "0.00", BG: yellow}
	inp1   = Format{Num: "0.0", BG: yellow}
	setF   = Format{BG: yellow}
	scopeF = Format{Num: "0.0%", BG: yellow}
	grey   = Format{Color: greyFg}
	titleF = Format{Bold: true, Size: 14}
)

// Flatten returns nested settings as (path, value); missing values (nil) are omitted.
func Flatten(m *yamlx.Map, prefix string) []Setting {
	var out []Setting
	for _, e := range m.Entries {
		path := prefix + fmt.Sprint(e.Key)
		switch v := e.Value.(type) {
		case *yamlx.Map:
			out = append(out, Flatten(v, path+".")...)
		case nil:
		default:
			out = append(out, Setting{Path: path, Value: v})
		}
	}
	return out
}

// Setting is one flattened setting.
type Setting struct {
	Path  string
	Value any
}

// ImportUnsafeSprintIDs returns warnings for sprint ids the Excel import would refuse (it
// requires portable file names). On Linux and macOS such an id (for example "a:b") can exist and
// be exported, but the workbook could not be imported again.
func ImportUnsafeSprintIDs(data *storage.TeamData) []string {
	var warnings []string
	seen := map[string]bool{}
	var ids []string
	for _, s := range data.Sprints {
		ids = append(ids, s.ID)
	}
	if data.Team.Sprint.FirstID != nil {
		ids = append(ids, *data.Team.Sprint.FirstID)
	}
	for index, id := range ids {
		isFirstID := index >= len(data.Sprints)
		if problem := storage.FileNameProblem(id, true); problem != "" {
			warnings = append(warnings, i18n.T(
				"Sprint ID {id} ({problem}): the Excel import refuses it, so the workbook cannot be imported again.",
				"id", pyRepr(id), "problem", problem))
		} else if !isFirstID && seen[pytext.Casefold(id)] {
			warnings = append(warnings, i18n.T(
				"Sprint ID {id} appears twice (upper and lower case count as the same): the Excel import refuses it.",
				"id", pyRepr(id)))
		}
		if !isFirstID {
			seen[pytext.Casefold(id)] = true
		}
	}
	return warnings
}

func blank(v *float64) any {
	if v == nil {
		return ""
	}
	return *v
}

// Build returns the team's Excel workbook (.xlsx).
func Build(fc *forecast.Forecast) ([]byte, error) {
	data := fc.Data
	team := data.Team
	settings := team.Forecast
	mode, err := engine.ParseTrendMode(settings.TrendMode)
	if err != nil {
		return nil, err
	}
	entries := fc.Entries // all sprints: the workbook contains the full history
	unit := string(team.Unit)

	b := newBook()
	if err := b.f.SetCustomProps(excelize.CustomProperty{Name: FormatProperty, Value: FormatVersion}); err != nil {
		return nil, err
	}
	if err := b.f.SetCustomProps(excelize.CustomProperty{Name: TeamProperty, Value: team.Key}); err != nil {
		return nil, err
	}
	wsSet := b.addSheet(SheetSettings)
	ws := b.addSheet(SheetForecast)
	wsSp := b.addSheet(SheetSprints)
	wsA := b.addSheet(SheetAbsences)
	wsPe := b.addSheet(SheetPeople)
	wsPr := b.addSheet(SheetProducts)
	wsP := b.addSheet(SheetValues)
	wsPg := b.addSheet(SheetPrognose)
	wsT := b.addSheet(SheetTrend)
	first, last := ForecastFirstRow, ForecastFirstRow+len(entries)-1

	teamName := team.Name
	if teamName == "" {
		teamName = team.Key
	}

	// --- Settings -------------------------------------------------------------------------
	wsSet.str(0, 0, i18n.T("Settings of {team}", "team", teamName), titleF)
	wsSet.str(1, 0, i18n.T("Label"), boldF)
	wsSet.str(1, 1, i18n.T("Value"), boldF)
	wsSet.str(1, 2, i18n.T("Key (team.yaml)"), boldF)
	labels := map[string]string{
		"forecast.reference_capacity": i18n.T("Reference capacity (PT)"),
		"forecast.window":             i18n.T("Window (sprints)"),
		"forecast.roadmap_share":      i18n.T("Plannable share"),
		"forecast.rounding":           i18n.T("Rounding (decimal places, rounded down)"),
		"forecast.trend_mode":         i18n.T("Trend mode (fixed at export)"),
	}
	names := map[string]string{
		"forecast.reference_capacity": "Referenz",
		"forecast.window":             "Fenster",
		"forecast.roadmap_share":      "Roadmap_Anteil",
		"forecast.rounding":           "Rundung",
	}
	// The tracker section (ticket pre-planning) is not a spreadsheet setting: the import keeps
	// the existing section of team.yaml.
	var flat []Setting
	for _, s := range Flatten(storage.TeamToDict(team), "") {
		if !strings.HasPrefix(s.Path, "tracker.") {
			flat = append(flat, s)
		}
	}
	for k, s := range flat {
		row := SettingsFirstRow - 1 + k
		label := s.Path
		if l, ok := labels[s.Path]; ok {
			label = l
		}
		wsSet.str(row, 0, label, Format{})
		switch v := s.Value.(type) {
		case yamlx.Date:
			wsSet.date(row, 1, time.Time(v), dateF)
		case bool:
			wsSet.boolean(row, 1, v, setF)
		case int64:
			wsSet.num(row, 1, float64(v), setF)
		case int:
			wsSet.num(row, 1, float64(v), setF)
		case float64:
			wsSet.num(row, 1, v, setF)
		case string:
			wsSet.str(row, 1, v, setF)
		default:
			wsSet.str(row, 1, fmt.Sprint(v), setF)
		}
		wsSet.str(row, 2, s.Path, grey)
		if name, ok := names[s.Path]; ok {
			b.define(name, fmt.Sprintf("'%s'!$B$%d", wsSet.name, row+1))
		}
	}
	thinRow := SettingsFirstRow - 1 + len(flat) + 1
	wsSet.str(thinRow+3, 0, i18n.T("Current status"), Format{})
	wsSet.str(thinRow+3, 1, fc.Today.Format("02.01.2006"), Format{})
	wsSet.str(thinRow+5, 0, i18n.T("Yellow cells are inputs (settings and sprint values); all other cells are formulas. The trend mode is fixed in the formulas."), Format{})
	wsSet.column(0, 0, 48)
	wsSet.column(1, 1, 16)
	wsSet.column(2, 2, 30)

	// --- Columns of the "Forecast" sheet --------------------------------------------------
	cols := []string{
		"id", "start", "end", "ist", "vel", "scope", "caprec", "capcalc", "src", "cap",
		"norm", "norm_n", "norm_avg", "norm_trend", "norm_known",
		"cap_n", "cap_avg", "cap_trend", "cap_known",
		"plancap", "plan", "roadmap", "small", "ful", "focus",
		"share", "capprod", "capnon", "planprod", "plannon", "sumprod", "delta",
	}
	c := map[string]int{}
	for i, name := range cols {
		c[name] = i
	}
	headers := map[string]string{
		"id":         i18n.T("Sprint"),
		"start":      i18n.T("Start"),
		"end":        i18n.T("End"),
		"ist":        i18n.T("Commitment ({unit})", "unit", unit),
		"vel":        i18n.T("Velocity ({unit})", "unit", unit),
		"scope":      i18n.T("Scope creep"),
		"caprec":     i18n.T("Capacity (PD), recorded (input)"),
		"capcalc":    i18n.T("Capacity (PD), calculated from people and calendar"),
		"cap":        i18n.T("Capacity (PD), recorded or calculated"),
		"src":        i18n.T("Source of the capacity"),
		"norm":       i18n.T("norm. velocity"),
		"norm_n":     i18n.T("Count n. velocity"),
		"norm_avg":   i18n.T("Ø norm. velocity"),
		"norm_trend": i18n.T("norm. velocity trend"),
		"norm_known": i18n.T("n. velocity known (avg or trend)"),
		"cap_n":      i18n.T("Count capacity"),
		"cap_avg":    i18n.T("Avg capacity"),
		"cap_trend":  i18n.T("Capacity trend"),
		"cap_known":  i18n.T("Capacity known (avg or trend)"),
		"plancap":    i18n.T("Capacity for the Forecast PLAN (PD)"),
		"plan":       i18n.T("Forecast PLAN ({unit})", "unit", unit),
		"roadmap":    i18n.T("Plannable ({unit})", "unit", unit),
		"small":      i18n.T("Small stuff ({unit})", "unit", unit),
		"ful":        i18n.T("Fulfillment"),
		"focus":      i18n.T("Focus factor"),
		"share":      i18n.T("Share of production access in the capacity"),
		"capprod":    i18n.T("Capacity with production access (PD)"),
		"capnon":     i18n.T("Capacity without production access (PD)"),
		"planprod":   i18n.T("Forecast PLAN: up to with production access ({unit})", "unit", unit),
		"plannon":    i18n.T("Forecast PLAN: for all others ({unit})", "unit", unit),
		"sumprod":    i18n.T("Σ planning per product ({unit})", "unit", unit),
		"delta":      i18n.T("Forecast PLAN − Σ planning ({unit})", "unit", unit),
	}
	ws.str(0, 0, i18n.T("Forecast {team}", "team", teamName), titleF)
	ws.str(1, 0, i18n.T("Inputs are yellow; the columns to the right calculate like the web interface (calculation)."), Format{})
	for i, name := range cols {
		ws.str(2, i, headers[name], boldF)
	}
	ws.rowHeight(2, 60)
	ws.column(0, 0, 10)
	ws.column(1, 2, 11)
	ws.column(3, len(cols), 14)
	ws.freeze(3, 1)

	at := func(name string, row int) string { return ref(row, c[name], false, false) }
	atAbs := func(name string, row int, ca, ra bool) string { return ref(row, c[name], ra, ca) }
	rng := func(name string, a, z int) string {
		return atAbs(name, a, true, true) + ":" + atAbs(name, z, true, true)
	}

	normAll := rng("norm", first, last)
	// Thin history per series (too few values for a full window, but ≥ 3).
	sheetRef := "'" + ws.name + "'!"
	minThin := strconv.Itoa(engine.MinThinHistory)
	thinN := fmt.Sprintf("AND(COUNT(%s%s)>=%s,COUNT(%s%s)<Fenster)", sheetRef, normAll, minThin, sheetRef, normAll)
	capAll := rng("cap", first, last)
	thinC := fmt.Sprintf("AND(COUNT(%s%s)>=%s,COUNT(%s%s)<Fenster)", sheetRef, capAll, minThin, sheetRef, capAll)
	wsSet.str(thinRow, 0, i18n.T("Thin history n. velocity (fewer values than the window, at least 3)"), Format{})
	wsSet.str(thinRow+1, 0, i18n.T("Thin history capacity"), Format{})
	b.define("Duenn_nVelocity", fmt.Sprintf("'%s'!$B$%d", wsSet.name, thinRow+1))
	b.define("Duenn_Kapazitaet", fmt.Sprintf("'%s'!$B$%d", wsSet.name, thinRow+2))

	// Cached values: calculated as the engine does, so that previews show numbers.
	var normSeries, capSeries engine.Series
	for _, e := range entries {
		normSeries = append(normSeries, e.Result.NormalizedVelocity.Value)
		capSeries = append(capSeries, e.Result.Capacity.Value)
	}
	normThin := engine.ThinHistory(normSeries, settings.Window)
	capThin := engine.ThinHistory(capSeries, settings.Window)
	wsSet.formula(thinRow, 1, thinN, Format{}, normThin)
	wsSet.formula(thinRow+1, 1, thinC, Format{}, capThin)

	seriesColumns := func(i, row int, prefix, valname string, m engine.Metric, count int, thinName string) {
		nC, avgC, trC, knC := prefix+"_n", prefix+"_avg", prefix+"_trend", prefix+"_known"
		ws.formula(row, c[nC], fmt.Sprintf("COUNT(%s:%s)", atAbs(valname, first, false, true), at(valname, row)), Format{}, count)
		cnt := at(nC, row)
		val := at(valname, row)
		windowAvg := fmt.Sprintf(`AVERAGEIFS(%s:%s,%s:%s,">"&(%s-Fenster))`, //nolint:misspell // Excel function name
			atAbs(valname, first, false, true), at(valname, row), atAbs(nC, first, false, true), cnt, cnt)
		thinAvg := fmt.Sprintf("AVERAGE(%s:%s)", atAbs(valname, first, false, true), at(valname, row))
		ws.formula(row, c[avgC],
			fmt.Sprintf(`IF(NOT(%s),"",IF(%s>=Fenster,%s,IF(AND(%s,%s>=%s),%s,"")))`,
				isNumber(val), cnt, windowAvg, thinName, cnt, minThin, thinAvg),
			n2, blank(m.Average))

		r := func(col string, off int) string { return at(prefix+"_"+col, row-off) }
		body := TrendFormula(mode, thinName, r, i)
		var trendCached *float64
		if m.Average == nil {
			trendCached = m.Trend
		}
		ws.formula(row, c[trC], fmt.Sprintf(`IF(%s,"",%s)`, isNumber(at(avgC, row)), body), n2, blank(trendCached))
		knownV := m.Average
		if knownV == nil {
			knownV = m.Trend
		}
		ws.formula(row, c[knC], known(at(avgC, row), at(trC, row)), n2, blank(knownV))
	}

	nCount, capCount := 0, 0
	for i := range entries {
		e := &entries[i]
		row := first + i
		res := e.Result
		s := e.Sprint
		ws.str(row, c["id"], s.ID, Format{})
		ws.date(row, c["start"], s.Start, dateF)
		ws.date(row, c["end"], s.End, dateF)
		// Inputs (yellow): exactly the fields of the sprint file; a missing value leaves the
		// cell empty.
		for _, in := range []struct {
			name string
			v    *float64
			f    Format
		}{
			{"ist", s.Commitment, inp}, {"vel", s.Velocity, inp},
			{"scope", s.ScopeCreep, scopeF}, {"caprec", s.Capacity, inp1},
		} {
			if in.v != nil {
				ws.num(row, c[in.name], *in.v, in.f)
			} else {
				ws.blank(row, c[in.name], in.f)
			}
		}
		if s.Capacity == nil && res.Input.Capacity != nil {
			ws.num(row, c["capcalc"], *res.Input.Capacity, n1)
		}
		ws.formula(row, c["cap"],
			fmt.Sprintf(`IF(%s,%s,IF(%s,%s,""))`, isNumber(at("caprec", row)), at("caprec", row), isNumber(at("capcalc", row)), at("capcalc", row)),
			n1, blank(res.Input.Capacity))
		src := ""
		if res.Input.CapacitySource != nil {
			src = string(*res.Input.CapacitySource)
		}
		ws.str(row, c["src"], src, Format{})
		nv := res.NormalizedVelocity
		ws.formula(row, c["norm"],
			fmt.Sprintf(`IF(AND(%s,%s,%s>0),%s/%s*Referenz,"")`, isNumber(at("vel", row)), isNumber(at("cap", row)), at("cap", row), at("vel", row), at("cap", row)),
			n2, blank(nv.Value))
		if nv.Value != nil {
			nCount++
		}
		if res.Capacity.Value != nil {
			capCount++
		}
		seriesColumns(i, row, "norm", "norm", nv, nCount, "Duenn_nVelocity")
		seriesColumns(i, row, "cap", "cap", res.Capacity, capCount, "Duenn_Kapazitaet")
		ws.formula(row, c["plancap"],
			fmt.Sprintf(`IF(%s,%s,%s)`, isNumber(at("cap", row)), at("cap", row), at("cap_trend", row)),
			n1, blank(res.PlanCapacity))
		tr, pcap, commitment := at("norm_trend", row), at("plancap", row), at("ist", row)
		ws.formula(row, c["plan"],
			fmt.Sprintf(`IF(AND(%s,%s),MAX(0,ROUNDDOWN(%s/Referenz*%s,Rundung)),IF(%s,ROUNDDOWN(%s,Rundung),""))`,
				isNumber(tr), isNumber(pcap), tr, pcap, isNumber(commitment), commitment),
			n2, blank(res.Plan))
		plan := at("plan", row)
		ws.formula(row, c["roadmap"], fmt.Sprintf(`IF(%s,%s*Roadmap_Anteil,"")`, isNumber(plan), plan), n2, blank(res.Roadmap))
		ws.formula(row, c["small"], fmt.Sprintf(`IF(%s,%s-%s,"")`, isNumber(plan), plan, at("roadmap", row)), n2, blank(res.SmallStuff))
		vel, cap := at("vel", row), at("cap", row)
		ws.formula(row, c["ful"],
			fmt.Sprintf(`IF(AND(%s,%s,%s<>0),%s/%s,"")`, isNumber(vel), isNumber(commitment), commitment, vel, commitment),
			pc, blank(res.Fulfillment.Value))
		var focus *float64
		if res.Input.Velocity != nil && res.Input.Capacity != nil && *res.Input.Capacity != 0 {
			f := *res.Input.Velocity / *res.Input.Capacity
			focus = &f
		}
		ws.formula(row, c["focus"],
			fmt.Sprintf(`IF(AND(%s,%s,%s>0),%s/%s,"")`, isNumber(vel), isNumber(cap), cap, vel, cap),
			pc, blank(focus))
		productionColumns(ws, c, at, row, fc, e)
	}

	dataSheets(fc, entries, wsSp, wsA, wsPe, wsPr, wsPg)
	productsSheet(wsP, ws, c, fc, entries, first, unit)
	trendSheet(b, wsT, ws, c, entries, first)
	return b.finish()
}

// productionColumns is the split by production access (approximation via the capacity share).
func productionColumns(ws *sheet, c map[string]int, at func(string, int) string, row int, fc *forecast.Forecast, e *forecast.TimelineEntry) {
	if !fc.Data.Team.Features.Production {
		return
	}
	d := products.Distribute(fc, e)
	if d.ProductionState() != products.ProductionOK || d.ProductionShare == nil {
		return
	}
	share := *d.ProductionShare
	res := e.Result
	ws.num(row, c["share"], share, pc)
	shareRef, pcap, plan := at("share", row), at("plancap", row), at("plan", row)
	scaled := func(v *float64, factor float64) any {
		if v == nil {
			return ""
		}
		return *v * factor
	}
	ws.formula(row, c["capprod"], fmt.Sprintf(`IF(%s,%s*%s,"")`, isNumber(pcap), pcap, shareRef), n1, scaled(res.PlanCapacity, share))
	ws.formula(row, c["capnon"], fmt.Sprintf(`IF(%s,%s*(1-%s),"")`, isNumber(pcap), pcap, shareRef), n1, scaled(res.PlanCapacity, 1-share))
	ws.formula(row, c["planprod"], fmt.Sprintf(`IF(%s,%s*%s,"")`, isNumber(plan), plan, shareRef), n2, scaled(res.Plan, share))
	ws.formula(row, c["plannon"], fmt.Sprintf(`IF(%s,%s*(1-%s),"")`, isNumber(plan), plan, shareRef), n2, scaled(res.Plan, 1-share))
}

func header(ws *sheet, labels []string, widths []float64) {
	for i, label := range labels {
		ws.str(0, i, label, boldF)
	}
	ws.rowHeight(0, 45)
	for i, w := range widths {
		ws.column(i, i, w)
	}
	ws.freeze(1, 0)
}

// put writes a value; nil stays an empty cell (with a format so that it is yellow).
func put(ws *sheet, row, col int, v any, f Format) {
	switch x := v.(type) {
	case nil:
		ws.blank(row, col, f)
	case time.Time:
		ws.date(row, col, x, f)
	case *time.Time:
		if x == nil {
			ws.blank(row, col, f)
		} else {
			ws.date(row, col, *x, f)
		}
	case *float64:
		if x == nil {
			ws.blank(row, col, f)
		} else {
			ws.num(row, col, *x, f)
		}
	case *string:
		if x == nil {
			ws.blank(row, col, f)
		} else {
			ws.str(row, col, *x, f)
		}
	case string:
		ws.str(row, col, x, f)
	case float64:
		ws.num(row, col, x, f)
	case bool:
		ws.boolean(row, col, x, f)
	default:
		panic(fmt.Sprintf("excel: put of %T", v))
	}
}

func strPtr(s string) *string { return &s }

func joinG(values []float64) string {
	parts := make([]string, len(values))
	for i, v := range values {
		parts[i] = pyG(v)
	}
	return strings.Join(parts, " ")
}

// dataSheets are the remaining data of the team (sprint files, absences, people, products,
// prognoses) in the fixed column order the import reads. All inputs (yellow) except the names.
func dataSheets(fc *forecast.Forecast, entries []forecast.TimelineEntry, wsSp, wsA, wsPe, wsPr, wsPg *sheet) {
	data := fc.Data
	unit := string(data.Team.Unit)
	inpDate := Format{Num: "dd.mm.yyyy", BG: yellow}
	inpTime := Format{Num: "dd.mm.yyyy hh:mm:ss", BG: yellow}
	inpText := Format{BG: yellow}
	names := map[string]string{}
	for _, p := range data.People {
		names[p.ID] = p.Name
	}
	var recorded []model.Sprint
	for _, e := range entries {
		if e.Recorded {
			recorded = append(recorded, e.Sprint)
		}
	}

	header(wsSp, []string{
		i18n.T("Sprint"), i18n.T("State of the absences (unknown, expected, confirmed)"),
		i18n.T("Forecast PLAN at planning, frozen ({unit})", "unit", unit),
		i18n.T("Carry-over ({unit})", "unit", unit), "Backlog (" + unit + ")",
		i18n.T("Corrections of remaining effort (separated by spaces)"),
		i18n.T("Of which not finished ({unit})", "unit", unit),
		i18n.T("Additionally done ({unit})", "unit", unit),
		i18n.T("Of which with production access, planning ({unit})", "unit", unit),
		i18n.T("Of which with production access, done ({unit})", "unit", unit),
		i18n.T("Note"),
	}, []float64{10, 22, 18, 14, 12, 26, 16, 16, 20, 20, 40})
	for i, sp := range recorded {
		row := i + 1
		var absence *string
		if sp.AbsenceState != nil {
			absence = strPtr(string(*sp.AbsenceState))
		}
		var carry, backlog *float64
		var corrections *string
		if pl := sp.Planning; pl != nil {
			carry, backlog = &pl.Carryover, &pl.Backlog
			if len(pl.Corrections) > 0 {
				corrections = strPtr(joinG(pl.Corrections))
			}
		}
		values := []any{sp.ID, absence, sp.ForecastPlan, carry, backlog, corrections,
			sp.NotDone, sp.AdditionalDone, sp.ProductionPlanned, sp.ProductionDone, sp.Note}
		for col, v := range values {
			f := inp
			switch col {
			case 0:
				f = Format{}
			case 1, 5, 10:
				f = inpText
			}
			put(wsSp, row, col, v, f)
		}
	}

	header(wsA, []string{
		i18n.T("Sprint"), i18n.T("Person (ID)"), i18n.T("Name"), i18n.T("days"),
		i18n.T("Kind (absences = confirmed, expected_absences = announced)"),
	}, []float64{10, 20, 24, 8, 30})
	row := 1
	for _, sp := range recorded {
		for _, kind := range AbsenceKinds {
			days := sp.Absences
			if kind == "expected_absences" {
				days = sp.ExpectedAbsences
			}
			ids := make([]string, 0, len(days))
			for id := range days {
				ids = append(ids, id)
			}
			slices.Sort(ids)
			for _, pid := range ids {
				for col, v := range []any{sp.ID, pid, names[pid], days[pid], kind} {
					f := Format{}
					if col == 3 {
						f = inp
					}
					put(wsA, row, col, v, f)
				}
				row++
			}
		}
	}

	header(wsPe, []string{
		i18n.T("ID"), i18n.T("Name"), i18n.T("Country"), i18n.T("Region"), i18n.T("Work week"),
		i18n.T("Production access"), i18n.T("Member from"), i18n.T("Member until"), "FTE",
	}, []float64{16, 24, 8, 8, 18, 12, 13, 13, 8})
	row = 1
	for _, person := range data.People {
		memberships := person.Memberships
		if len(memberships) == 0 {
			memberships = []model.Membership{{}}
		}
		for mi, m := range memberships {
			var access any
			if person.ProductionAccess {
				access = true
			}
			var from, to, fte any
			if len(person.Memberships) > 0 {
				from = m.Start
				if m.End != nil {
					to = *m.End
				}
				fte = m.FTE
			}
			_ = mi
			values := []any{person.ID, person.Name, person.Country, person.Region, person.Workweek, access, from, to, fte}
			for col, v := range values {
				f := inpText
				switch col {
				case 6, 7:
					f = inpDate
				case 8:
					f = inp
				}
				put(wsPe, row, col, v, f)
			}
			row++
		}
	}

	header(wsPr, []string{
		i18n.T("ID"), i18n.T("Name"), "PO", i18n.T("Handled from"), i18n.T("Handled until"),
		i18n.T("Fixed share (0–1)"),
	}, []float64{16, 24, 18, 13, 13, 12})
	for i, p := range data.Products {
		for col, v := range []any{p.ID, p.Name, p.PO, p.Start, p.End, p.Share} {
			f := inpText
			switch col {
			case 3, 4:
				f = inpDate
			case 5:
				f = inp
			}
			put(wsPr, i+1, col, v, f)
		}
	}

	header(wsPg, []string{
		i18n.T("Sprint"), i18n.T("Time"), i18n.T("Comment"), i18n.T("Commitment ({unit})", "unit", unit),
		i18n.T("Expected not finished ({unit})", "unit", unit),
		i18n.T("Additionally done ({unit})", "unit", unit), i18n.T("Expected done"),
		i18n.T("Target sprint"), i18n.T("Forecast PLAN"), i18n.T("Pre-planning per product (ID=value; …)"),
	}, []float64{10, 19, 40, 12, 14, 14, 12, 10, 12, 40})
	row = 1
	for _, sp := range recorded {
		for _, pg := range sp.Prognoses {
			var pre any
			if pg.Preplanned.Len() > 0 {
				parts := make([]string, 0, pg.Preplanned.Len())
				for _, e := range pg.Preplanned.Entries {
					parts = append(parts, e.Key+"="+pyG(e.Value))
				}
				pre = strings.Join(parts, "; ")
			}
			values := []any{sp.ID, pg.At, pg.Comment, pg.Commitment, pg.NotDone, pg.AdditionalDone,
				pg.ExpectedDone, pg.Target, pg.Plan, pre}
			for col, v := range values {
				f := inpText
				switch col {
				case 0:
					f = Format{}
				case 1:
					f = inpTime
				case 3, 4, 5, 6, 8:
					f = inp
				}
				put(wsPg, row, col, v, f)
			}
			row++
		}
	}
}

// productsSheet holds the values per product and sprint (long table, fixed columns as in
// ValueColumns) and writes the sum per sprint back to the Forecast sheet.
func productsSheet(wsP, ws *sheet, c map[string]int, fc *forecast.Forecast, entries []forecast.TimelineEntry, first int, unit string) {
	production := fc.Data.Team.Features.Production
	inpV := Format{Num: "0.00", BG: yellow}
	label := func(m string) string { return products.MeasureLabel(m) + " (" + unit + ")" }
	header(wsP, []string{
		i18n.T("Sprint"), i18n.T("Product (ID)"), i18n.T("Product"), "PO",
		label("standard"), label("preplanned"), label("planned"), label("done"),
		label("production_planned"), label("production_done"),
		i18n.T("Planning without production access ({unit})", "unit", unit),
		i18n.T("Done without production access ({unit})", "unit", unit),
	}, []float64{10, 16, 22, 16, 12, 12, 12, 12, 14, 14, 16, 16})
	measures := []string{"preplanned", "planned", "done", "production_planned", "production_done"}
	row := 1
	for i := range entries {
		e := &entries[i]
		d := products.Distribute(fc, e)
		for _, r := range d.Rows {
			any_ := false
			for _, m := range measures {
				if r.Value(m) != nil {
					any_ = true
				}
			}
			if !r.Active && !any_ {
				continue
			}
			po := ""
			if r.Product.PO != nil {
				po = *r.Product.PO
			}
			for col, v := range []string{e.Sprint.ID, r.Product.ID, r.Product.Name, po} {
				wsP.str(row, col, v, Format{})
			}
			if r.Standard != nil {
				wsP.num(row, 4, *r.Standard, n2)
			}
			for col, m := range measures {
				put(wsP, row, 5+col, r.Value(m), inpV)
			}
			if production {
				for _, spec := range []struct {
					col         int
					whole, part string
					a, b        string
				}{
					{10, "G", "I", "planned", "production_planned"},
					{11, "H", "J", "done", "production_done"},
				} {
					w, p := fmt.Sprintf("%s%d", spec.whole, row+1), fmt.Sprintf("%s%d", spec.part, row+1)
					va, vb := r.Value(spec.a), r.Value(spec.b)
					var cached any = ""
					if va != nil && vb != nil {
						cached = *va - *vb
					}
					wsP.formula(row, spec.col, fmt.Sprintf(`IF(AND(ISNUMBER(%s),ISNUMBER(%s)),%s-%s,"")`, w, p, w, p), n2, cached)
				}
			}
			row++
		}
	}
	sheetRef := "'" + wsP.name + "'!"
	lastRow := max(row, 2)
	ids := fmt.Sprintf("%s$A$2:$A$%d", sheetRef, lastRow)
	planCol := fmt.Sprintf("%s$G$2:$G$%d", sheetRef, lastRow)
	for i := range entries {
		e := &entries[i]
		r := first + i
		d := products.Distribute(fc, e)
		total := d.Total("planned")
		idRef := ref(r, c["id"], false, false)
		ws.formula(r, c["sumprod"],
			fmt.Sprintf(`IF(COUNTIFS(%s,%s,%s,"<>")=0,"",SUMIFS(%s,%s,%s))`, ids, idRef, planCol, planCol, ids, idRef),
			n2, blank(total))
		plan := ref(r, c["plan"], false, false)
		sums := ref(r, c["sumprod"], false, false)
		var delta any = ""
		if total != nil && e.Result.Plan != nil {
			delta = *e.Result.Plan - *total
		}
		ws.formula(r, c["delta"], fmt.Sprintf(`IF(AND(ISNUMBER(%s),ISNUMBER(%s)),%s-%s,"")`, plan, sums, plan, sums), n2, delta)
	}
}

// trendSheet has the chart data (#N/A = gap) and two line charts: trend of the normalized
// velocity, Forecast PLAN against velocity and commitment.
func trendSheet(b *book, wsT, ws *sheet, c map[string]int, entries []forecast.TimelineEntry, first int) {
	sheetRef := "'" + ws.name + "'!"
	heads := []string{
		i18n.T("Sprint"), i18n.T("norm. velocity"), i18n.T("Ø norm. velocity"), i18n.T("norm. velocity trend"),
		i18n.T("Forecast PLAN"), i18n.T("Velocity"), i18n.T("Commitment"),
	}
	for i, h := range heads {
		wsT.str(0, i, h, boldF)
	}
	wsT.column(0, 6, 16)
	sources := []string{"id", "norm", "norm_avg", "norm_trend", "plan", "vel", "ist"}
	cached := []func(e *forecast.TimelineEntry) *float64{
		nil,
		func(e *forecast.TimelineEntry) *float64 { return e.Result.NormalizedVelocity.Value },
		func(e *forecast.TimelineEntry) *float64 { return e.Result.NormalizedVelocity.Average },
		func(e *forecast.TimelineEntry) *float64 { return e.Result.NormalizedVelocity.Trend },
		func(e *forecast.TimelineEntry) *float64 { return e.Result.Plan },
		func(e *forecast.TimelineEntry) *float64 { return e.Result.Input.Velocity },
		func(e *forecast.TimelineEntry) *float64 { return e.Result.Input.Commitment },
	}
	for i := range entries {
		e := &entries[i]
		for k, src := range sources {
			r := sheetRef + ref(first+i, c[src], false, false)
			if k == 0 {
				wsT.formula(i+1, 0, r, Format{}, e.Sprint.ID)
				continue
			}
			var v any = NA
			if x := cached[k](e); x != nil {
				v = *x
			}
			wsT.formula(i+1, k, fmt.Sprintf("IF(ISNUMBER(%s),%s,NA())", r, r), Format{}, v)
		}
	}
	last := len(entries)
	b.errorsGrey(wsT, fmt.Sprintf("B2:%s", ref(last, 6, false, false)))
	tname := "'" + wsT.name + "'!"
	chart := func(title string, columns []int, anchor, ytitle string) {
		var series []excelize.ChartSeries
		for _, col := range columns {
			series = append(series, excelize.ChartSeries{
				Name:       tname + ref(0, col, true, true),
				Categories: fmt.Sprintf("%s$A$2:$A$%d", tname, last+1),
				Values:     fmt.Sprintf("%s%s:%s", tname, ref(1, col, true, true), ref(last, col, true, true)),
				Marker:     excelize.ChartMarker{Symbol: "circle", Size: 5},
				Line:       excelize.ChartLine{Width: 2},
			})
		}
		b.must(wsT, b.f.AddChart(wsT.name, anchor, &excelize.Chart{
			Type:         excelize.Line,
			Series:       series,
			Title:        []excelize.RichTextRun{{Text: title}},
			XAxis:        excelize.ChartAxis{Title: []excelize.RichTextRun{{Text: i18n.T("Sprint")}}},
			YAxis:        excelize.ChartAxis{Title: []excelize.RichTextRun{{Text: ytitle}}, MajorGridLines: true},
			Legend:       excelize.ChartLegend{Position: "bottom"},
			Dimension:    excelize.ChartDimension{Width: 760, Height: 340},
			ShowBlanksAs: "gap",
		}))
	}
	chart(i18n.T("Trend of the normalized velocity"), []int{1, 2, 3}, "I2", i18n.T("norm. velocity"))
	chart(i18n.T("Forecast PLAN, velocity and commitment"), []int{4, 5, 6}, "I20", i18n.T("Amount"))
}

func (b *book) define(name, refersTo string) {
	if err := b.f.SetDefinedName(&excelize.DefinedName{Name: name, RefersTo: refersTo}); err != nil {
		panic(err)
	}
}

func (b *book) must(s *sheet, err error) { s.must(err) }

// errorsGrey greys out the cells with an error (#N/A) in the range.
func (b *book) errorsGrey(s *sheet, rng string) {
	id := b.dxf(Format{Color: greyFg})
	s.must(b.f.SetConditionalFormat(s.name, rng, []excelize.ConditionalFormatOptions{{Type: "errors", Format: &id}}))
}

func (b *book) dxf(f Format) int {
	id, err := b.f.NewConditionalStyle(&excelize.Style{Font: &excelize.Font{Color: f.Color}})
	if err != nil {
		panic(err)
	}
	return id
}
