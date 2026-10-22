package ticketimport

import (
	"reflect"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/rules"
	"github.com/swallat/foresprint/internal/sources"
)

func str(s string) *string { return &s }

func TestParsePercent(t *testing.T) {
	cases := []struct {
		in   []string
		want float64
		ok   bool
	}{
		{[]string{"60"}, 60, true}, {[]string{" 60 % "}, 60, true}, {[]string{"0,5"}, 0.5, true},
		{[]string{"100"}, 100, true}, {[]string{"101"}, 0, false}, {[]string{"-1"}, 0, false},
		{[]string{"x", "30"}, 30, true}, {nil, 0, false}, {[]string{"nan"}, 0, false},
	}
	for _, c := range cases {
		got, ok := ParsePercent(c.in)
		if got != c.want || ok != c.ok {
			t.Errorf("ParsePercent(%v) = %v, %v", c.in, got, ok)
		}
	}
}

func TestProductionOrder(t *testing.T) {
	tracker := model.TrackerSettings{
		ProductionLabel: str("prod"),
		ProductionRules: []model.ProductionRule{{Match: rules.NewLeaf("component", "Betrieb"), Percent: 80}},
	}
	tracker.Fields.Production = str("Prod share")
	ticket := model.Ticket{Key: "A-1", Labels: []string{"prod"}, Components: []string{"Betrieb"}}
	ticket.Extra.Set(MapProduction, []string{"40 %"})
	var preplan model.Preplan

	if p := ProductionOf(ticket, tracker, preplan); p.Source != ProductionField || p.Percent != 40 {
		t.Errorf("field: %+v", p)
	}
	preplan.Production = []model.ProductionShare{{Ticket: "A-1", Percent: 10}}
	if p := ProductionOf(ticket, tracker, preplan); p.Source != ProductionHand || p.Percent != 10 {
		t.Errorf("hand: %+v", p)
	}
	preplan.Production = nil
	ticket.Extra = model.OrderedMap[[]string]{}
	if p := ProductionOf(ticket, tracker, preplan); p.Source != ProductionLabel || p.Percent != 100 {
		t.Errorf("label: %+v", p)
	}
	ticket.Labels = nil
	if p := ProductionOf(ticket, tracker, preplan); p.Source != ProductionRule || p.Percent != 80 || p.Rule != 0 {
		t.Errorf("rule: %+v", p)
	}
	ticket.Components = nil
	if p := ProductionOf(ticket, tracker, preplan); p.Source != ProductionNone || p.Percent != 0 {
		t.Errorf("none: %+v", p)
	}
}

func TestMappedFieldsReachTheSources(t *testing.T) {
	tracker := model.TrackerSettings{}
	tracker.RuleFields.Set("team", "Team")
	tracker.Fields.Production = str("Prod share")
	tracker.Fields.Project = str("Projekt")
	s := SourceSettings(tracker)
	want := []sources.RuleField{{Name: "team", Display: "Team"}, {Name: MapProduction, Display: "Prod share"}, {Name: MapProject, Display: "Projekt"}}
	if !reflect.DeepEqual(s.RuleFields, want) {
		t.Fatalf("%+v", s.RuleFields)
	}
}

func TestConvertMappedProjectProductRefined(t *testing.T) {
	tracker := model.TrackerSettings{RefinedLabel: str("refined")}
	tracker.Fields.Project = str("Projekt")
	tracker.Fields.Product = str("Produkt")
	tracker.Fields.Refined = str("Bereit")
	env := Env{
		Tracker:  tracker,
		Projects: []model.Project{{ID: "p1", Name: "Relaunch"}},
		Products: []model.Product{{ID: "shop", Name: "Webshop"}},
		Sprints:  noSprints{},
	}
	est := 5.0
	raw := sources.RawTicket{Key: "A-1", Estimate: &est, Extra: map[string][]string{
		MapProject: {"relaunch"}, MapProduct: {"WEBSHOP"}, MapRefined: {"Ja"},
	}}
	tk := Convert(raw, env)
	if tk.Project == nil || *tk.Project != "p1" || tk.Product == nil || *tk.Product != "shop" {
		t.Fatalf("project/product: %v %v", tk.Project, tk.Product)
	}
	if tk.EstimateSource != model.EstimateRefined {
		t.Fatalf("refined field: %v", tk.EstimateSource)
	}
	raw.Extra[MapRefined] = []string{"nein"}
	if tk := Convert(raw, env); tk.EstimateSource != model.EstimateRough {
		t.Fatalf("not refined: %v", tk.EstimateSource)
	}
	raw.Extra[MapRefined] = nil
	raw.Labels = []string{"refined"} // no value in the field: the label decides
	if tk := Convert(raw, env); tk.EstimateSource != model.EstimateRefined {
		t.Fatalf("label fallback: %v", tk.EstimateSource)
	}
	raw.Extra[MapProject] = []string{"unknown"}
	if tk := Convert(raw, env); tk.Project != nil {
		t.Fatalf("unknown project value: %v", *tk.Project)
	}
}

type noSprints struct{}

func (noSprints) End(string) (e time.Time, ok bool) { return }

func TestOrigins(t *testing.T) {
	tracker := model.TrackerSettings{}
	tracker.Fields.Estimate = str("Story Points")
	tracker.Fields.Production = str("Prod")
	tracker.ProductionLabel = str("prod")
	got := map[string]Origin{}
	for _, o := range Origins(tracker) {
		got[o.Value] = o
	}
	if got["estimate"].From != FromTrackerField || got["estimate"].Field != "Story Points" {
		t.Errorf("estimate %+v", got["estimate"])
	}
	if got["production"].From != FromFieldOrRules || got["product"].From != FromRules || got["refined"].From != FromHand {
		t.Errorf("origins %+v", got)
	}
}

func TestRuleFieldUsers(t *testing.T) {
	tracker := model.TrackerSettings{ProductionRules: []model.ProductionRule{{Match: rules.NewLeaf("team", "x"), Percent: 10}}}
	products := []model.Product{{ID: "shop", Match: rules.NewLeaf("team", "a")}, {ID: "app", Match: rules.NewLeaf("epic", "e")}}
	projects := []model.Project{{ID: "p1", Match: rules.NewLeaf("team", "b")}}
	got := RuleFieldUsers("team", tracker, products, projects)
	want := []string{"product shop", "project p1", "production rule 1"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("%v", got)
	}
	if got := RuleFieldUsers("unused", tracker, products, projects); len(got) != 0 {
		t.Fatalf("%v", got)
	}
}

func TestDetectDrift(t *testing.T) {
	in := func(k string) model.Ticket { return model.Ticket{Key: k, InSprint: str("2026.1")} }
	tickets := []model.Ticket{in("A-1"), in("A-9"), {Key: "A-2"}, {Key: "A-3", Done: true}}
	d := DetectDrift([]string{"A-1", "A-2", "A-3", "A-7"}, tickets, "2026.1")
	if !reflect.DeepEqual(d.PulledIn, []string{"A-9"}) || !reflect.DeepEqual(d.Dropped, []string{"A-2"}) ||
		!reflect.DeepEqual(d.Unknown, []string{"A-7"}) {
		t.Fatalf("%+v", d)
	}
	if d := DetectDrift(nil, tickets, "2026.1"); len(d.PulledIn)+len(d.Dropped) != 0 {
		t.Fatalf("unfrozen: %+v", d)
	}
}

func TestHandOverrideWinsOverMappedFields(t *testing.T) {
	tracker := model.TrackerSettings{}
	tracker.Fields.Project = str("Projekt")
	tracker.Fields.Product = str("Produkt")
	env := Env{
		Tracker:  tracker,
		Projects: []model.Project{{ID: "p1", Name: "Relaunch"}, {ID: "p2", Name: "Other"}},
		Products: []model.Product{{ID: "shop", Name: "Webshop"}},
		Sprints:  noSprints{},
		Preplan: model.Preplan{Overrides: []model.TicketOverride{
			{Ticket: "A-1", Project: str("p2")}, {Ticket: "A-2", Daily: true}, {Ticket: "A-3", Product: str("app")},
		}},
	}
	raw := func(key string) sources.RawTicket {
		return sources.RawTicket{Key: key, Extra: map[string][]string{MapProject: {"relaunch"}, MapProduct: {"webshop"}}}
	}
	if tk := Convert(raw("A-1"), env); *tk.Project != "p2" {
		t.Errorf("project override: %v", tk.Project)
	}
	if tk := Convert(raw("A-2"), env); tk.Project != nil {
		t.Errorf("daily override: %v", *tk.Project)
	}
	if tk := Convert(raw("A-3"), env); *tk.Product != "app" || *tk.Project != "p1" {
		t.Errorf("product override: %v %v", tk.Product, tk.Project)
	}
	if tk := Convert(raw("A-4"), env); *tk.Project != "p1" || *tk.Product != "shop" {
		t.Errorf("no override: %v %v", tk.Project, tk.Product)
	}
}

func TestMappedProductionLandsInExtraProduction(t *testing.T) {
	tracker := model.TrackerSettings{}
	tracker.Fields.Production = str("Prod share")
	tk := Convert(sources.RawTicket{Key: "A-1", Extra: map[string][]string{"production": {"40"}}}, Env{Tracker: tracker, Sprints: noSprints{}})
	if v, ok := tk.Extra.Get("production"); !ok || len(v) != 1 || v[0] != "40" {
		t.Fatalf("%+v", tk.Extra)
	}
	// A rule field of the team with the same name keeps the name; the mapped field is not added twice.
	tracker.RuleFields.Set("production", "Other")
	if got := MappedRuleFields(tracker); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
}
