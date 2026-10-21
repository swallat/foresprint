package model

import (
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Unit is the estimation unit of a team.
type Unit string

// The units.
const (
	UnitPT Unit = "PT"
	UnitSP Unit = "SP"
)

// TrendMode says how the forecast carries the average into the future.
type TrendMode string

// The trend modes. Files from before the rename name Classic "klassisch"; the storage maps it.
const (
	// TrendClassic: 1st future sprint linear, 2nd multiplicative, then linear. Carries noise
	// forward, so only choose it explicitly.
	TrendClassic TrendMode = "classic"
	// TrendLinear is the linear projection of the rolling average throughout.
	TrendLinear TrendMode = "linear"
	// TrendFlat carries the last known average forward unchanged (default, robust).
	TrendFlat TrendMode = "flat"
)

// ProductBasis is the basis of the default distribution per product.
type ProductBasis string

// The product bases.
const (
	// BasisPlan distributes the whole forecast PLAN.
	BasisPlan ProductBasis = "plan"
	// BasisRoadmap distributes only the plannable share.
	BasisRoadmap ProductBasis = "roadmap"
)

// Numbering is the scheme of the sprint ids.
type Numbering string

// The numbering schemes.
const (
	// NumberingYearly gives 2026.1, 2026.2, ...; the counter restarts with the start year.
	NumberingYearly Numbering = "yearly"
	// NumberingSequential gives 1, 2, 3, ...
	NumberingSequential Numbering = "sequential"
)

// SprintSettings is the section sprint of team.yaml.
type SprintSettings struct {
	LengthDays int
	Numbering  Numbering
	// FirstID and FirstStart are only needed as long as no sprint is recorded yet.
	FirstID    *string
	FirstStart *time.Time
}

// ForecastSettings is the section forecast of team.yaml.
type ForecastSettings struct {
	ReferenceCapacity float64
	Window            int
	RoadmapShare      float64
	Rounding          int
	TrendMode         TrendMode
	Horizon           int
	ProductBasis      ProductBasis
}

// CapacitySettings is the section capacity of team.yaml.
type CapacitySettings struct {
	// OverheadShare is the share of the capacity for Scrum events and the like, deducted as a
	// flat amount.
	OverheadShare float64
	// OverheadDays is the same deduction in person days per full-time person and sprint
	// (times FTE). If set, it applies instead of the share (not in addition).
	OverheadDays float64
	// Country (ISO 3166-1, "DE") and Region within it ("NW") for holidays; people can differ.
	// Workweek follows the country ("auto") or is fixed ("mon-fri", "sun-thu", "mon-sat").
	Country  string
	Region   *string
	Workweek string
	Rounding int
	// AbsenceHistory: for future sprints without known absences, expect the average absences of
	// the last this many sprints with confirmed absences. 0 = no estimate.
	AbsenceHistory int
}

// Features are the optional areas that not every team needs. For a new team all are off.
type Features struct {
	// Products: distribution of the sprint over several products.
	Products bool
	// PO: assignment of a PO to each product.
	PO bool
	// Production: topics with production access.
	Production bool
	// Tickets: ticket pre-planning (projects.yaml, tickets.yaml, preplan.yaml).
	Tickets bool
	// Explicit is false when the file has no features section (older files); the values were
	// derived from the existing data so that nothing disappears.
	Explicit bool
}

// Team is a team and its settings (team.yaml).
type Team struct {
	Key      string
	Name     string
	Unit     Unit
	Sprint   SprintSettings
	Forecast ForecastSettings
	Capacity CapacitySettings
	Features Features
	// Tracker is the settings of the ticket pre-planning (section tracker); only used with
	// Features.Tickets.
	Tracker TrackerSettings
	// TrackerRaw is the raw tracker section (a YAML value) that could not be read while
	// Features.Tickets is off; kept so that writing team.yaml does not drop it. Nil if none.
	TrackerRaw any
}

// NewTeam returns a team with the defaults of a new team file.
func NewTeam(key, name string) Team {
	return Team{
		Key:  key,
		Name: name,
		Unit: UnitPT,
		Sprint: SprintSettings{
			LengthDays: 14,
			Numbering:  NumberingYearly,
		},
		Forecast: ForecastSettings{
			ReferenceCapacity: 67,
			Window:            5,
			RoadmapShare:      0.8,
			Rounding:          1,
			TrendMode:         TrendFlat,
			Horizon:           3,
			ProductBasis:      BasisPlan,
		},
		Capacity: CapacitySettings{
			Country:        "DE",
			Workweek:       "auto",
			Rounding:       1,
			AbsenceHistory: 4,
		},
		Features: Features{Explicit: true},
		Tracker:  NewTrackerSettings(),
	}
}

// Membership is a period in which a person is in the team.
type Membership struct {
	Start time.Time
	End   *time.Time
	// FTE is the share in the team; 1.0 = full time.
	FTE float64
}

// Covers reports whether day lies in the period (both ends included).
func (m Membership) Covers(day time.Time) bool {
	return !m.Start.After(day) && (m.End == nil || !day.After(*m.End))
}

// Person is a member of the team. People are never deleted, the membership ends instead.
type Person struct {
	ID          string
	Name        string
	Region      *string
	Memberships []Membership
	// ProductionAccess: may work on tickets that require production access.
	ProductionAccess bool
	// Country is the person's own country if different (holidays and weekend).
	Country *string
	// Workweek is the person's own workweek (e.g. "mon,tue,wed,thu"), if different.
	Workweek *string
}

// FTEOn returns the share in the team on day, 0 if the person is not in the team.
func (p Person) FTEOn(day time.Time) float64 {
	for _, m := range p.Memberships {
		if m.Covers(day) {
			return m.FTE
		}
	}
	return 0
}

// ActiveBetween reports whether the person is in the team at some time in [start, end): a
// membership starts before end and has not ended before start.
func (p Person) ActiveBetween(start, end time.Time) bool {
	for _, m := range p.Memberships {
		if m.Start.Before(end) && (m.End == nil || !m.End.Before(start)) {
			return true
		}
	}
	return false
}

// IsCurrent reports whether the person is in the team on day or later (has not left).
func (p Person) IsCurrent(day time.Time) bool {
	for _, m := range p.Memberships {
		if m.End == nil || !m.End.Before(day) {
			return true
		}
	}
	return false
}

var umlauts = strings.NewReplacer("ä", "ae", "ö", "oe", "ü", "ue", "ß", "ss")

var nonSlug = regexp.MustCompile(`[^a-z0-9]+`)

// NewPersonID derives an internal id from the name, "Jörg Müller" gives "joerg-mueller", and
// makes it unique among existing. fallback replaces an empty slug (Python default "person").
func NewPersonID(name string, existing map[string]bool, fallback string) string {
	slug := nonSlug.ReplaceAllString(umlauts.Replace(strings.ToLower(name)), "-")
	slug = strings.Trim(slug, "-")
	if slug == "" {
		slug = fallback
	}
	candidate := slug
	for n := 2; existing[candidate]; n++ {
		candidate = slug + "-" + strconv.Itoa(n)
	}
	return candidate
}

// Product is a product the team looks after. Like people, never deleted, ended with End.
type Product struct {
	ID   string
	Name string
	// PO is the responsible PO (optional, only for grouping).
	PO    *string
	Start *time.Time
	End   *time.Time
	// Share is the agreed fixed share of the distributable amount (0-1). If nil, the products
	// without a fixed share split the remainder evenly.
	Share *float64
	// Match is the rule for the product's tickets without a project.
	Match *Rule
}

// ActiveBetween reports whether the product is looked after on at least one day of [start, end).
func (p Product) ActiveBetween(start, end time.Time) bool {
	return (p.Start == nil || p.Start.Before(end)) && (p.End == nil || !p.End.Before(start))
}

// Base URL problems returned by BaseURLProblem.
const (
	URLInvalid     = "invalid"
	URLCredentials = "credentials"
	URLExtra       = "extra"
)

// BaseURLProblem says why tracker.base_url is unusable, or "" if it is fine: URLInvalid (no
// http/https address), URLCredentials (user or password in the address) or URLExtra (query or
// fragment). The address itself is never part of the result.
func BaseURLProblem(raw string) string {
	raw = strings.TrimSpace(raw)
	u, err := url.Parse(raw)
	if err != nil {
		return URLInvalid
	}
	if u.Port() != "" {
		if _, ok := parsePort(u.Port()); !ok {
			return URLInvalid
		}
	}
	if (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" {
		return URLInvalid
	}
	if strings.Contains(u.Host, "@") || u.User != nil {
		return URLCredentials
	}
	if u.RawQuery != "" || u.Fragment != "" || strings.ContainsAny(raw, "?#") {
		return URLExtra
	}
	return ""
}

func parsePort(s string) (int, bool) {
	n := 0
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, false
		}
		n = n*10 + int(c-'0')
		if n > 65535 {
			return 0, false
		}
	}
	return n, true
}
