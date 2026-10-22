package model

import (
	"time"
)

// This file holds the data types that 1.0 adds to the 0.8 model. Every field is optional and
// absent from a file written by 0.8; the storage writes a field only when it has a value, so a
// 0.8 file reads and writes back unchanged.

// TicketSource says where the work of a team comes from (decision 15 of the design).
type TicketSource string

// The ticket sources.
const (
	// SourceTracker: tickets are read from a tracker such as Jira (or a CSV export of it).
	SourceTracker TicketSource = "tracker"
	// SourcePackages: work packages kept in Foresprint itself (arbeitspakete.yaml).
	SourcePackages TicketSource = "packages"
	// SourceNone: no tickets; the pre-planning holds amounts per product and project.
	SourceNone TicketSource = "none"
)

// PackagesKind is the value of tracker.kind that selects work packages kept in Foresprint.
const PackagesKind = "packages"

// DefaultPackagePrefix starts the keys of work packages ("AP-424").
const DefaultPackagePrefix = "AP"

// Source returns the ticket source of the team: none while the tickets feature is off, the
// work packages if tracker.kind says so, otherwise the tracker.
func (t Team) Source() TicketSource {
	switch {
	case !t.Features.Tickets:
		return SourceNone
	case t.Tracker.Kind == PackagesKind:
		return SourcePackages
	default:
		return SourceTracker
	}
}

// UnitChange switches the estimation unit of a team from a sprint on (decision 19). Past sprints
// keep their unit. Factor converts between story points and person days (points per person
// day); nil = use the measured team rate.
type UnitChange struct {
	// From is the id of the first sprint the unit applies to.
	From   string
	Unit   Unit
	Factor *float64
}

// NamingRule is a sprint naming pattern valid from a sprint on (decision 18); From nil = from
// the first sprint. See FormatSprintName for the placeholders.
type NamingRule struct {
	From    *string
	Pattern string
}

// PersonKind says how a person belongs to the team (decision 16). All three count for
// capacity; minutes and calculations show guests and externals separately.
type PersonKind string

// The kinds of people.
const (
	// KindMember is a permanent member (default; not written).
	KindMember PersonKind = "member"
	// KindGuest helps out from another team.
	KindGuest PersonKind = "guest"
	// KindExternal is a temporary outside resource; needs an end date.
	KindExternal PersonKind = "external"
)

// AbsencePeriod is a planned absence of one person from the first to the last day (both
// included). Only the dates are stored, never a reason or type (data protection).
type AbsencePeriod struct {
	From, To time.Time
	// Confirmed: a closed lock; otherwise the period is announced.
	Confirmed bool
}

// Covers reports whether day lies in the period.
func (a AbsencePeriod) Covers(day time.Time) bool {
	return !a.From.After(day) && !day.After(a.To)
}

// Absences are the absence periods per person id (abwesenheiten.yaml).
type Absences = OrderedMap[[]AbsencePeriod]

// CarryItem is the rest of a ticket that is carried over from a sprint (decisions 14 and 17).
type CarryItem struct {
	// Ticket is the ticket key; nil without tickets.
	Ticket *string
	// Rest is the remaining effort in the team's unit.
	Rest float64
	// Target says where the rest continues: "" = the next sprint, a sprint id, CarryBacklog or
	// CarryProForma + name.
	Target string
}

// Carry targets besides a sprint id.
const (
	CarryBacklog  = "backlog"
	CarryProForma = "proforma:"
)

// ProjectState is the state of a project; the empty value is an open project.
type ProjectState string

// The project states. A project with history is closed, not deleted (decision 22).
const (
	ProjectOpen      ProjectState = ""
	ProjectFinished  ProjectState = "finished"
	ProjectCancelled ProjectState = "cancelled"
)

// Milestone is a date of a project, optionally with tickets that have to be done by then.
type Milestone struct {
	ID      string
	Name    string
	Date    time.Time
	Tickets []string
	// Light is the traffic light the PO set by hand (LightGreen, LightYellow, LightRed);
	// empty = not set, the tool derives one from the tickets.
	Light string
}

// Milestone lights set by hand.
const (
	LightGreen  = "green"
	LightYellow = "yellow"
	LightRed    = "red"
)

// MilestoneLights are the allowed values of Milestone.Light.
var MilestoneLights = []string{LightGreen, LightYellow, LightRed}

// Contingent is what a project lead booked from the team, in person days (PD) for the whole
// project, optionally split per month ("2026-07").
type Contingent struct {
	Total    *float64
	PerMonth OrderedMap[float64]
	// Used is the consumption booked by hand in PD for the whole project, UsedPerMonth the same
	// per month ("2026-07"); both optional.
	Used         *float64
	UsedPerMonth OrderedMap[float64]
}

// Subtask is a part of a work package.
type Subtask struct {
	Title string
	Done  bool
}

// Comment is a note on a work package.
type Comment struct {
	Author string
	At     *time.Time
	Text   string
}

// ProductionShare is the part of a ticket that needs production access, from 0 to 100 percent,
// set in Foresprint (preplan.yaml).
type ProductionShare struct {
	Ticket  string
	Percent float64
	Note    *string
}

// TicketOverride is what the PO decided for one ticket against the rules: its product and
// project (decision 5). Daily business sets no project on purpose.
type TicketOverride struct {
	Ticket  string
	Product *string
	Project *string
	// Daily: the ticket is daily business of its product although a rule would give a project.
	Daily bool
}

// ProductionRule gives the tickets that fit the rule a production share (decision 20).
type ProductionRule struct {
	Match   *Rule
	Percent float64
}
