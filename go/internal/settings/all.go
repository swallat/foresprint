package settings

import (
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/model"
)

func f(v float64) *float64 { return &v }

func strPtr(s *string) Value {
	if s == nil {
		return nil
	}
	return *s
}

func optString(v Value) *string {
	if s, ok := v.(string); ok {
		return &s
	}
	return nil
}

func onOff(b bool) Value {
	if b {
		return "on"
	}
	return "off"
}

var switchOptions = []Option{{"off", "off"}, {"on", "on"}}

// sw is an on/off setting of the section features; writing marks the section as explicit.
func sw(key, label, help string, field func(*model.Team) *bool) Setting {
	return Setting{
		Key: key, Label: label, Help: help, Kind: Choice, Options: switchOptions, switchOf: true,
		get: func(t *model.Team) Value { return onOff(*field(t)) },
		set: func(t *model.Team, v Value) { *field(t) = v == "on"; t.Features.Explicit = true },
	}
}

func countryOptions() []Option {
	var out []Option
	for _, c := range calendar.Countries() {
		out = append(out, Option{c.Code, c.Name})
	}
	return out
}

// All lists the settings in the order they are asked.
var All = []Setting{
	{
		Key: "name", Label: "Display name", Help: "Team name in reports and headings.", Kind: Text,
		get: func(t *model.Team) Value { return t.Name },
		set: func(t *model.Team, v Value) { t.Name = v.(string) },
	},
	{
		Key: "unit", Label: "Estimation unit",
		Help: "PT (person days) or SP (story points). Only affects the display; the " +
			"capacity is always in PT.",
		Kind:    Choice,
		Options: []Option{{"PT", "person days"}, {"SP", "story points"}},
		get:     func(t *model.Team) Value { return string(t.Unit) },
		set:     func(t *model.Team, v Value) { t.Unit = model.Unit(v.(string)) },
	},
	sw("features.products", "Product distribution",
		"Only needed if the team looks after several products and the sprint amount "+
			"is distributed over them: product list, PO pre-planning, planning and done "+
			"per product, default distribution and balance. Off: these pages and inputs "+
			"are omitted; values already recorded stay in the files.",
		func(t *model.Team) *bool { return &t.Features.Products }),
	sw("features.po", "PO assignment",
		"Each product has a responsible product owner; the pre-planning shows sums "+
			"per PO. Only useful together with the product distribution. Off: there is no "+
			"PO column and no sums per PO.",
		func(t *model.Team) *bool { return &t.Features.PO }),
	sw("features.production", "Production access",
		"Only some of the people may work on tickets that need production access. On: "+
			"people are marked as authorized, planning and review record how much of the "+
			"amount needs production access, and a bottleneck hint shows whether the "+
			"authorized group can handle it. Off: no marking, no inputs, no hint.",
		func(t *model.Team) *bool { return &t.Features.Production }),
	sw("features.tickets", "Ticket pre-planning",
		"Tickets from the issue tracker (Jira or CSV export) are assigned to projects "+
			"and distributed over future sprints: project list with target date, earmarks "+
			"per sprint, project traffic light and refinement list (files projects.yaml, "+
			"tickets.yaml, preplan.yaml; section tracker in team.yaml). Off: the files "+
			"are not read, and there is no page and no command for it.",
		func(t *model.Team) *bool { return &t.Features.Tickets }),
	{
		Key: "capacity.country", Label: "Country",
		Help: "For public holidays and the weekend (ISO country code, e.g. DE, AT, CH, US, " +
			"GB, SA). Individual people can have a different country in the people list.",
		Kind: Choice, Options: countryOptions(), country: true, Retroactive: true,
		get: func(t *model.Team) Value { return t.Capacity.Country },
		set: func(t *model.Team, v Value) { t.Capacity.Country = v.(string) },
	},
	{
		Key: "capacity.region", Label: "Region (state, province)",
		Help: "For regional public holidays, e.g. NW (Germany), CA (USA), ON (Canada). " +
			"Empty = nationwide holidays only. Must match the country; individual people " +
			"can differ.",
		Kind: Text, Optional: true, Retroactive: true,
		get: func(t *model.Team) Value { return strPtr(t.Capacity.Region) },
		set: func(t *model.Team, v Value) { t.Capacity.Region = optString(v) },
	},
	{
		Key: "capacity.workweek", Label: "Work week",
		Help: `Which days count as working days. "auto" follows the country (e.g. Sunday ` +
			`to Thursday in Saudi Arabia).`,
		Kind: Choice, Retroactive: true,
		Options: []Option{
			{"auto", "as in the country"},
			{"mon-fri", "Monday to Friday"},
			{"sun-thu", "Sunday to Thursday"},
			{"mon-sat", "Monday to Saturday"},
		},
		get: func(t *model.Team) Value { return t.Capacity.Workweek },
		set: func(t *model.Team, v Value) { t.Capacity.Workweek = v.(string) },
	},
	{
		Key: "capacity.overhead_share", Label: "Scrum events deduction (%)",
		Help: "Flat share of the capacity for dailies, planning, review, retro, refinement. " +
			"0 if the absences already cover this.",
		Kind: Percent, Min: f(0), Max: f(90),
		get: func(t *model.Team) Value { return t.Capacity.OverheadShare },
		set: func(t *model.Team, v Value) { t.Capacity.OverheadShare = v.(float64) },
	},
	{
		Key: "capacity.overhead_days", Label: "Scrum events deduction (PT per person)",
		Help: "Fixed deduction per sprint and full-time person (part time pro rata), e.g. 1 " +
			"for planning, review and retro. Equals the deduction in % (both fields stay " +
			"in sync); 0 = the deduction in % applies.",
		Kind: Number, Min: f(0), Max: f(20), Step: 0.25,
		get: func(t *model.Team) Value { return t.Capacity.OverheadDays },
		set: func(t *model.Team, v Value) { t.Capacity.OverheadDays = v.(float64) },
	},
	{
		Key: "capacity.absence_history", Label: "Absence history (number of sprints)",
		Help: "For future sprints without known absences the capacity from calendar and " +
			"people list is reduced by the average absences of the last that many sprints " +
			"with confirmed absences. 0 = no estimate (no deduction for absences).",
		Kind: Int, Min: f(0), Max: f(26), Retroactive: true,
		get: func(t *model.Team) Value { return t.Capacity.AbsenceHistory },
		set: func(t *model.Team, v Value) { t.Capacity.AbsenceHistory = v.(int) },
	},
	{
		Key: "sprint.length_days", Label: "Sprint length (calendar days)",
		Help: "Applies to newly created sprints; recorded sprints keep their dates.",
		Kind: Int, Min: f(1), Max: f(56),
		get: func(t *model.Team) Value { return t.Sprint.LengthDays },
		set: func(t *model.Team, v Value) { t.Sprint.LengthDays = v.(int) },
	},
	{
		Key: "sprint.numbering", Label: "Sprint numbering", Help: "Scheme for newly created sprint IDs.",
		Kind:    Choice,
		Options: []Option{{"yearly", "per year (2026.1, 2026.2 …)"}, {"sequential", "sequential (1, 2, 3 …)"}},
		get:     func(t *model.Team) Value { return string(t.Sprint.Numbering) },
		set:     func(t *model.Team, v Value) { t.Sprint.Numbering = model.Numbering(v.(string)) },
	},
	{
		Key: "sprint.first_start", Label: "Start of the first sprint",
		Help: "Only needed as long as no sprint file exists.",
		Kind: Date, Optional: true, OnlyWithoutSprints: true,
		get: func(t *model.Team) Value {
			if t.Sprint.FirstStart == nil {
				return nil
			}
			return *t.Sprint.FirstStart
		},
		set: func(t *model.Team, v Value) {
			if day, ok := v.(time.Time); ok {
				t.Sprint.FirstStart = &day
			} else {
				t.Sprint.FirstStart = nil
			}
		},
	},
	{
		Key: "sprint.first_id", Label: "ID of the first sprint",
		Help: "The sprint that is running now or starts next, e.g. 2026.15 or 15. Only " +
			"needed as long as no sprint file exists; after that: Change sprint IDs.",
		Kind: Text, Optional: true, OnlyWithoutSprints: true,
		get: func(t *model.Team) Value { return strPtr(t.Sprint.FirstID) },
		set: func(t *model.Team, v Value) { t.Sprint.FirstID = optString(v) },
	},
	{
		Key: "forecast.reference_capacity", Label: "Reference capacity (PT)",
		Help: "Display scale of the normalized velocity (norm. velocity = focus factor × " +
			"reference capacity). Best the capacity of a fully staffed sprint. It cancels " +
			"out in the calculation: changes all normalized values but not the Forecast " +
			"PLAN.",
		Kind: Number, Min: f(1), Retroactive: true,
		get: func(t *model.Team) Value { return t.Forecast.ReferenceCapacity },
		set: func(t *model.Team, v Value) { t.Forecast.ReferenceCapacity = v.(float64) },
	},
	{
		Key: "forecast.window", Label: "Ø over sprints",
		Help: "Number of sprints in the moving average. Smaller = reacts faster, larger = smoother.",
		Kind: Int, Min: f(1), Max: f(20), Retroactive: true,
		get: func(t *model.Team) Value { return t.Forecast.Window },
		set: func(t *model.Team, v Value) { t.Forecast.Window = v.(int) },
	},
	{
		Key: "forecast.trend_mode", Label: "Trend mode",
		Help: "How the average is extrapolated into the future. “Constant” is robust and " +
			"the default. “Linear” and “classic” also extrapolate noise: they can rise or " +
			"fall and only make sense for a proven, stable trend.",
		Kind: Choice, Retroactive: true,
		Options: []Option{
			{"flat", "last average stays constant (default)"},
			{"classic", "linear, then multiplicative, then linear (caution: extrapolates noise)"},
			{"linear", "linear throughout (caution: extrapolates noise)"},
		},
		get: func(t *model.Team) Value { return string(t.Forecast.TrendMode) },
		set: func(t *model.Team, v Value) { t.Forecast.TrendMode = model.TrendMode(v.(string)) },
	},
	{
		Key: "forecast.roadmap_share", Label: "Plannable share (%)",
		Help: `Share of the Forecast PLAN reserved for plannable topics; the rest is "small items".`,
		Kind: Percent, Min: f(0), Max: f(100),
		get: func(t *model.Team) Value { return t.Forecast.RoadmapShare },
		set: func(t *model.Team, v Value) { t.Forecast.RoadmapShare = v.(float64) },
	},
	{
		Key: "forecast.horizon", Label: "Forecast horizon (sprints)",
		Help: "How many future sprints appear in the forecast and report.",
		Kind: Int, Min: f(1), Max: f(26),
		get: func(t *model.Team) Value { return t.Forecast.Horizon },
		set: func(t *model.Team, v Value) { t.Forecast.Horizon = v.(int) },
	},
	{
		Key: "forecast.rounding", Label: "Decimal places Forecast PLAN",
		Help: "The Forecast PLAN is rounded down to this many digits: it is the planning " +
			"quantity, and rounding down guards against over-planning. Capacity, by " +
			"contrast, is calculated unrounded internally and only rounded half-up when " +
			"shown and stored, so the denominator of the normalized velocity is not " +
			"systematically too small.",
		Kind: Int, Min: f(0), Max: f(3),
		get: func(t *model.Team) Value { return t.Forecast.Rounding },
		set: func(t *model.Team, v Value) { t.Forecast.Rounding = v.(int) },
	},
	{
		Key: "forecast.product_basis", Label: "Standard distribution per product based on",
		Help: "Which amount is distributed equally across the products handled (standard = " +
			"amount / number of products).",
		Kind: Choice,
		Options: []Option{
			{"plan", "entire Forecast PLAN"},
			{"roadmap", "plannable share only (small items stay across products)"},
		},
		get: func(t *model.Team) Value { return string(t.Forecast.ProductBasis) },
		set: func(t *model.Team, v Value) { t.Forecast.ProductBasis = model.ProductBasis(v.(string)) },
	},
}
