package workpackages

import (
	"reflect"
	"testing"

	"github.com/swallat/foresprint/internal/model"
)

func str(s string) *string { return &s }

func TestKeysAndRanks(t *testing.T) {
	existing := []model.Ticket{{Key: "AP-3", Rank: str("00000010")}, {Key: "AP-17", Rank: str("00000050")}, {Key: "X-99"}}
	if got := NextKey(existing, "AP"); got != "AP-18" {
		t.Errorf("NextKey = %s", got)
	}
	if got := NextKey(nil, "AP"); got != "AP-1" {
		t.Errorf("first key = %s", got)
	}
	if got := RankAfter(existing); got != "00000060" {
		t.Errorf("RankAfter = %s", got)
	}
	if Prefix(model.TrackerSettings{PackagePrefix: " WP "}) != "WP" || Prefix(model.TrackerSettings{}) != "AP" {
		t.Error("prefix")
	}
}

func TestReadCSV(t *testing.T) {
	rows, err := ReadCSV([]byte("\xef\xbb\xbfTitel;Schätzung;Labels\nOne;3;a,b\n\"Two; with\";5,5;\n"))
	if err != nil {
		t.Fatal(err)
	}
	want := [][]string{{"Titel", "Schätzung", "Labels"}, {"One", "3", "a,b"}, {"Two; with", "5,5", ""}}
	if !reflect.DeepEqual(rows, want) {
		t.Fatalf("%v", rows)
	}
}

func TestParseTable(t *testing.T) {
	rows := [][]string{
		{"Key", "Titel", "Status", "Schätzung", "Labels", "Bereit", "Produkt", "Foo"},
		{"AP-5", "Login", "In Arbeit", "3", "ui, web", "ja", "Webshop", "x"},
		{"", "Suche", "Erledigt", "5,5", "", "", "", ""},
		{"", "", "", "", "", "", "", ""},
		{"", "Kaputt", "", "viel", "", "", "", ""},
		{"AP-5", "Doppelt", "", "", "", "", "", ""},
		{"", "", "x", "", "", "", "", ""},
	}
	existing := []model.Ticket{{Key: "AP-7", Rank: str("00000100")}}
	res := ParseTable(rows, Options{Existing: existing})
	if len(res.Packages) != 2 || len(res.Problems) != 3 {
		t.Fatalf("%d packages, problems %+v", len(res.Packages), res.Problems)
	}
	login, search := res.Packages[0], res.Packages[1]
	if login.Key != "AP-5" || *login.Product != "Webshop" || *login.Estimate != 3 ||
		!reflect.DeepEqual(login.Labels, []string{"ui", "web", "refined"}) || login.Done {
		t.Errorf("login %+v", login)
	}
	if search.Key != "AP-8" || *search.Estimate != 5.5 || !search.Done || *search.Rank <= *login.Rank {
		t.Errorf("search %+v", search)
	}
	if !reflect.DeepEqual(res.Unmapped, []string{"Foo"}) {
		t.Errorf("unmapped %v", res.Unmapped)
	}
	rows[0][1] = "Foo2"
	if r := ParseTable(rows, Options{}); len(r.Packages) != 0 || r.Problems[0].Row != 1 {
		t.Errorf("no title column: %+v", r)
	}
}

func TestMerge(t *testing.T) {
	old := model.Ticket{Key: "AP-1", Title: "Old", Status: str("Open"), Assignee: str("Anna"), Rank: str("00000010")}
	est := 2.0
	in := []model.Ticket{
		{Key: "AP-1", Title: "New", Status: str("Doing"), Estimate: &est, Rank: str("99999999")},
		{Key: "AP-2", Title: "Added"},
	}
	out, changes := Merge([]model.Ticket{old}, in)
	if len(out) != 2 || len(changes) != 2 || !changes[0].Update || changes[1].Update {
		t.Fatalf("%+v %+v", out, changes)
	}
	if out[0].Title != "New" || *out[0].Status != "Doing" || *out[0].Assignee != "Anna" || *out[0].Rank != "00000010" || *out[0].Estimate != 2 {
		t.Errorf("merged %+v", out[0])
	}
}
