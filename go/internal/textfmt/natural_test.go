package textfmt_test

import (
	"sort"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/textfmt"
)

func TestNaturalLess(t *testing.T) {
	ids := []string{"Sprint 2026.10", "Sprint 2026.2", "Sprint 2026.1", "Sprint 20", "Sprint 17", "Sprint 2026.11", "Sprint 2026.9"}
	sort.Slice(ids, func(i, j int) bool { return textfmt.NaturalLess(ids[i], ids[j]) })
	want := "Sprint 17|Sprint 20|Sprint 2026.1|Sprint 2026.2|Sprint 2026.9|Sprint 2026.10|Sprint 2026.11"
	if got := strings.Join(ids, "|"); got != want {
		t.Errorf("order = %s", got)
	}
}
