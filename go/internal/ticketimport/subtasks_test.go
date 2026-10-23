package ticketimport

import (
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

func TestSplitSubtasks(t *testing.T) {
	raws := []sources.RawTicket{
		{Key: "A-1"}, {Key: "A-2", Parent: "A-1"}, {Key: "A-3", Parent: "A-1"}, {Key: "A-4", Parent: "X-9"},
	}
	kept, counts := splitSubtasks(raws, model.NewTrackerSettings())
	if len(kept) != 2 || kept[0].Key != "A-1" || kept[1].Key != "A-4" || counts["A-1"] != 2 {
		t.Fatalf("kept %v counts %v", kept, counts)
	}
	tr := model.NewTrackerSettings()
	tr.IncludeSubtasks = true
	kept, counts = splitSubtasks(raws, tr)
	if len(kept) != 4 || len(counts) != 0 {
		t.Fatalf("kept %v counts %v", kept, counts)
	}
}
