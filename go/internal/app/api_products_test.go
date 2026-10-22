package app

import (
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

func ownerNames(v ProductsView) []string {
	var out []string
	for _, o := range v.Owners {
		out = append(out, o.Name)
	}
	sort.Strings(out)
	return out
}

func productByName(v ProductsView, name string) ProductDTO {
	for _, p := range v.Products {
		if p.Name == name {
			return p
		}
	}
	return ProductDTO{}
}

func TestProductsViewOfAFileFrom08(t *testing.T) {
	api, team := demoCopy(t)
	v, err := api.Products(team)
	if err != nil {
		t.Fatal(err)
	}
	if !v.Legacy || len(v.Products) != 4 || strings.Join(ownerNames(v), ",") != "Alex,Bea" {
		t.Fatalf("view = %+v", v)
	}
	if !productByName(v, "Altsystem").Ended {
		t.Errorf("Altsystem should be ended: %+v", productByName(v, "Altsystem"))
	}
}

func TestSaveProductsRoundTripAndChecks(t *testing.T) {
	api, team := demoCopy(t)
	v, _ := api.Products(team)
	path := filepath.Join(api.DataDir(), team, "products.yaml")
	body := func() string { // the comment header is rewritten; the data must not change
		b, _ := os.ReadFile(path)
		var lines []string
		for _, l := range strings.Split(string(b), "\n") {
			if !strings.HasPrefix(l, "#") {
				lines = append(lines, l)
			}
		}
		return strings.Join(lines, "\n")
	}
	before := body()
	if _, err := api.SaveProducts(team, v.Products); err != nil {
		t.Fatal(err)
	}
	after := body()
	if before != after {
		t.Errorf("saving without a change rewrote products.yaml:\n%s\n---\n%s", before, after)
	}

	list := append([]ProductDTO{}, v.Products...)
	list = append(list, ProductDTO{Name: "Neu", PO: "Alex", Rule: `component = "Neu"`})
	got, err := api.SaveProducts(team, list)
	if err != nil {
		t.Fatal(err)
	}
	if p := productByName(got, "Neu"); p.ID != "neu" || p.Rule != `component = "Neu"` && p.Rule != `component = Neu` {
		t.Errorf("new product = %+v", p)
	}
	bad := append([]ProductDTO{}, list...)
	bad[0].Rule = `component = `
	if _, err := api.SaveProducts(team, bad); err == nil || !strings.Contains(err.Error(), "rule") {
		t.Errorf("bad rule: %v", err)
	}
	half := 1.5
	bad = append([]ProductDTO{}, list...)
	bad[0].Share = &half
	if _, err := api.SaveProducts(team, bad); err == nil {
		t.Error("share 150 percent accepted")
	}
	// Webshop has history (sprint values): it cannot be deleted.
	var rest []ProductDTO
	for _, p := range list {
		if p.Name != "Webshop" {
			rest = append(rest, p)
		}
	}
	if _, err := api.SaveProducts(team, rest); err == nil {
		t.Error("a product with history was deleted")
	}
}

func TestEndProductAndUndo(t *testing.T) {
	api, team := demoCopy(t)
	v, _ := api.Products(team)
	var shares = map[string]float64{}
	for _, p := range v.Products {
		if !p.Ended && p.Name != "Mobile App" {
			shares[p.ID] = 0
		}
	}
	for id := range shares {
		shares[id] = 1.0 / float64(len(shares))
	}
	if _, err := api.EndProduct(team, "app", "2026-10-27", map[string]float64{"webshop": 0.5}, ""); err == nil {
		t.Error("shares that do not reach 100 percent were accepted")
	}
	res, err := api.EndProduct(team, "app", "2026-10-13", shares, "")
	if err != nil {
		t.Fatal(err)
	}
	if p := productByName(res.View, "Mobile App"); !p.Ended || p.To != "2026-10-13" || p.Rule != "" {
		t.Errorf("ended product = %+v", p)
	}
	if err := api.Undo(team, res.Undo); err != nil {
		t.Fatal(err)
	}
	back, _ := api.Products(team)
	if productByName(back, "Mobile App").Ended {
		t.Error("undo did not bring the product back")
	}
	if err := api.Undo(team, res.Undo); err == nil {
		t.Error("undo worked twice")
	}
	if _, err := api.EndProduct(team, "nope", "2026-10-13", shares, ""); err == nil {
		t.Error("unknown product ended")
	}
}

func TestResumeProduct(t *testing.T) {
	api, team := demoCopy(t)
	step, err := api.ResumeProduct(team, "altsystem")
	if err != nil {
		t.Fatal(err)
	}
	p := productByName(step.View, "Altsystem")
	if p.Ended || p.To != "" || p.Share == nil || *p.Share != 0 {
		t.Errorf("resumed = %+v", p)
	}
}

func TestOwnersMigrateOnFirstEdit(t *testing.T) {
	api, team := demoCopy(t)
	step, err := api.AddOwner(team, "Cem Beispiel")
	if err != nil {
		t.Fatal(err)
	}
	v := step.View
	if v.Legacy || strings.Join(ownerNames(v), ",") != "Alex,Bea,Cem Beispiel" {
		t.Fatalf("owners after migration = %+v", v.Owners)
	}
	for _, p := range v.Products {
		if p.PO != "alex" && p.PO != "bea" {
			t.Errorf("product %s still names %q", p.Name, p.PO)
		}
	}
	if _, err := api.RemoveOwner(team, "alex", nil); err == nil {
		t.Error("a PO with products was removed without a handover")
	}
	handover := map[string]string{}
	for _, p := range v.Products {
		if p.PO == "alex" {
			handover[p.ID] = "cem-beispiel"
		}
	}
	rm, err := api.RemoveOwner(team, "alex", handover)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(ownerNames(rm.View), ",") != "Bea,Cem Beispiel" {
		t.Errorf("owners = %v", ownerNames(rm.View))
	}
	ren, err := api.RenameOwner(team, "bea", "Bea Muster")
	if err != nil || !strings.Contains(strings.Join(ownerNames(ren.View), ","), "Bea Muster") {
		t.Errorf("rename: %v %v", err, ownerNames(ren.View))
	}
	if err := api.Undo(team, ren.Undo); err != nil {
		t.Fatal(err)
	}
	if got, _ := api.Products(team); strings.Contains(strings.Join(ownerNames(got), ","), "Bea Muster") {
		t.Error("undo did not bring the old name back")
	}
}

func TestOwnerWorkingInTheTeam(t *testing.T) {
	api, team := demoCopy(t)
	before, _ := api.People(team)
	step, err := api.SetOwnerInTeam(team, "Bea", true, 0.2)
	if err != nil {
		t.Fatal(err)
	}
	var bea OwnerDTO
	for _, o := range step.View.Owners {
		if o.Name == "Bea" {
			bea = o
		}
	}
	if !bea.InTeam || bea.FTE != 0.2 || bea.Person == "" {
		t.Fatalf("owner = %+v", bea)
	}
	after, _ := api.People(team)
	if len(after.People) != len(before.People)+1 {
		t.Errorf("people %d -> %d", len(before.People), len(after.People))
	}
	off, err := api.SetOwnerInTeam(team, bea.ID, false, 0)
	if err != nil {
		t.Fatal(err)
	}
	for _, o := range off.View.Owners {
		if o.Name == "Bea" && o.InTeam {
			t.Error("still in the team")
		}
	}
	if _, err := api.SetOwnerInTeam(team, bea.ID, true, 3); err == nil {
		t.Error("share above 1 accepted")
	}
}

func TestProductsViewDefaultsFollowTheForecast(t *testing.T) {
	api, team := demoCopy(t)
	v, err := api.Products(team)
	if err != nil {
		t.Fatal(err)
	}
	if len(v.Defaults) == 0 {
		t.Fatal("no default rows")
	}
	var plan *ProductsDefault
	for i := range v.Defaults {
		if v.Defaults[i].Plan != nil {
			plan = &v.Defaults[i]
			break
		}
	}
	if plan == nil {
		t.Fatalf("no sprint with a forecast: %+v", v.Defaults)
	}
	for _, p := range v.Products {
		if p.Ended || p.Share == nil {
			continue
		}
		want := math.Round(*plan.Available * *p.Share)
		if got, ok := plan.Values[p.ID]; !ok || got != want {
			t.Errorf("%s: default %v (%v), want %v", p.Name, got, ok, want)
		}
	}
	for _, p := range v.Products {
		if p.Ended {
			if _, ok := plan.Values[p.ID]; ok {
				t.Errorf("ended product %s has a default", p.Name)
			}
		}
	}
}
