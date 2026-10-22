package excel

import (
	"testing"

	"github.com/swallat/foresprint/internal/i18n"
)

func TestTable(t *testing.T) {
	i18n.SetLanguage("en")
	raw := readGolden(t, "case-demo")
	rows, sheets, err := Table(raw, SheetPeople)
	if err != nil {
		t.Fatal(err)
	}
	if len(sheets) < 5 || len(rows) < 2 || rows[0][0] == "" {
		t.Fatalf("sheets %v rows %v", sheets, rows)
	}
	if _, _, err := Table(raw, "nope"); err == nil {
		t.Fatal("unknown sheet")
	}
	if _, _, err := Table([]byte("not a zip"), ""); err == nil {
		t.Fatal("not a workbook")
	}
	first, _, err := Table(raw, "")
	if err != nil || len(first) == 0 {
		t.Fatalf("first sheet: %v", err)
	}
}
