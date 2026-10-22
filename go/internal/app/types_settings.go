package app

// Types of the settings area (api_settings.go, api_tracker.go). The JSON names are the tags.

// ForecastSettings is the forecast model of 0.8 (decision 24).
type ForecastSettings struct {
	Window            int     `json:"window"`            // sprints in the rolling mean
	Trend             string  `json:"trend"`             // "flat", "linear" or "classic"
	ReferenceCapacity float64 `json:"referenceCapacity"` // PT
	PlannableShare    float64 `json:"plannableShare"`    // percent, 0 to 100
	Rounding          int     `json:"rounding"`          // decimals
	Horizon           int     `json:"horizon"`           // sprints
	Basis             string  `json:"basis"`             // "plan" or "share" (budget basis)
}

// UnitChangeInfo is a switch of the estimation unit in a sprint (decision 19).
type UnitChangeInfo struct {
	From string `json:"from"`
	Unit string `json:"unit"`
}

// TeamSettings is the page Settings > Team.
type TeamSettings struct {
	Name          string           `json:"name"`
	Unit          string           `json:"unit"`        // "SP" or "PT", valid now
	UnitFrom      string           `json:"unitFrom"`    // "" = from the first sprint
	UnitChanges   []UnitChangeInfo `json:"unitChanges"` // earlier switches
	Factor        *float64         `json:"factor"`      // points per person day; nil = measured team rate
	Forecast      ForecastSettings `json:"forecast"`
	LengthDays    int              `json:"lengthDays"` // default sprint length in working days
	Products      bool             `json:"products"`
	PO            bool             `json:"po"`
	Production    bool             `json:"production"`
	ProductionCap float64          `json:"productionCap"` // percent of the production time that counts, 100 = no cap
	Projects      bool             `json:"projects"`
	ProForma      []string         `json:"proForma"` // names of pro-forma sprints
}

// TrackerFields are the fields of the tracker for the values of Foresprint ("" = not mapped).
type TrackerFields struct {
	Estimate   string `json:"estimate"`
	Remaining  string `json:"remaining"`
	Epic       string `json:"epic"`
	Status     string `json:"status"`
	Acceptance string `json:"acceptance"`
	Product    string `json:"product"`
	Project    string `json:"project"`
	Refined    string `json:"refined"`
	Production string `json:"production"`
}

// ProdRule gives the tickets that fit the rule a production share.
type ProdRule struct {
	Rule    string  `json:"rule"`
	Percent float64 `json:"percent"`
}

// RuleField registers an additional tracker field for rules.
type RuleField struct {
	Name    string `json:"name"`
	Display string `json:"display"`
}

// TokenState says where the tracker token is; the token itself never leaves Go.
type TokenState struct {
	Host           string `json:"host"`           // "" while the address is unusable
	Stored         bool   `json:"stored"`         // an entry in the keychain of the operating system
	FromEnv        bool   `json:"fromEnv"`        // the environment variable is set and wins
	KeychainUsable bool   `json:"keychainUsable"` // this machine has a keychain
	Variable       string `json:"variable"`       // name of the environment variable
}

// TrackerSettings is the page Settings > Tickets and tracker.
type TrackerSettings struct {
	Source          string        `json:"source"` // "tracker", "packages" or "none"
	Kind            string        `json:"kind"`   // "jira" or "csv"
	BaseURL         string        `json:"baseUrl"`
	Query           string        `json:"query"`
	Fields          TrackerFields `json:"fields"`
	ProductBy       string        `json:"productBy"` // "rule" or "field"
	ProjectBy       string        `json:"projectBy"` // "rule" or "field"
	RefinedBy       string        `json:"refinedBy"` // "rule" or "field"
	RefinedLabel    string        `json:"refinedLabel"`
	RefinedRule     string        `json:"refinedRule"`  // rule text, "" = none
	ProductionBy    string        `json:"productionBy"` // "manual", "rule" or "field+rule"
	ProductionLabel string        `json:"productionLabel"`
	ProdRules       []ProdRule    `json:"prodRules"`
	RuleFields      []RuleField   `json:"ruleFields"`
	FixedSources    []string      `json:"fixedSources"` // rule sources that always exist
	WriteSprint     bool          `json:"writeSprint"`
	RemovedTarget   string        `json:"removedTarget"` // "backlog", "pro_forma" or "next"
	WriteLabels     bool          `json:"writeLabels"`
	PackagePrefix   string        `json:"packagePrefix"`
	Token           TokenState    `json:"token"`
	Tickets         int           `json:"tickets"`  // tickets in the last import
	Imported        string        `json:"imported"` // time of the last import (RFC 3339), "" if none
}

// Connection is the answer to a connection test.
type Connection struct {
	OK      bool   `json:"ok"`
	Message string `json:"message"` // translated; for a failure what is wrong
	User    string `json:"user,omitempty"`
}

// QueryCheck is the answer to a test of the query.
type QueryCheck struct {
	OK      bool   `json:"ok"`
	Message string `json:"message"`
	Count   int    `json:"count"`
}

// Features says which optional parts of the window the team uses (decisions 15 and 13 of the
// design): the pages hide what is not configured instead of greying it out.
type Features struct {
	Source     string `json:"source"` // "tracker", "packages" or "none"
	Products   bool   `json:"products"`
	PO         bool   `json:"po"`
	Production bool   `json:"production"`
	Projects   bool   `json:"projects"`
}
