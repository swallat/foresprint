package ticketimport

import (
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

func TestSplitSubtasks(t *testing.T) {
	raws := []sources.RawTicket{
		{Key: "A-1"}, {Key: "A-2", Subtask: true, Parent: "A-1"}, {Key: "A-3", Subtask: true, Parent: "A-1"}, {Key: "A-4", Subtask: true, Parent: "X-9"}, {Key: "A-5", Subtask: true},
	}
	kept, counts := splitSubtasks(raws, model.NewTrackerSettings())
	if len(kept) != 1 || kept[0].Key != "A-1" || counts["A-1"] != 2 {
		t.Fatalf("kept %v counts %v", kept, counts)
	}
	tr := model.NewTrackerSettings()
	tr.IncludeSubtasks = true
	kept, counts = splitSubtasks(raws, tr)
	if len(kept) != 5 || len(counts) != 0 {
		t.Fatalf("kept %v counts %v", kept, counts)
	}
}
