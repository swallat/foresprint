package sources

import "testing"

func TestSubtaskOf(t *testing.T) {
	sub := map[string]any{
		"issuetype": map[string]any{"name": "Sub-task", "subtask": true},
		"parent":    map[string]any{"key": "A-1"},
	}
	if ok, parent := subtaskOf(sub); !ok || parent != "A-1" {
		t.Fatalf("got %v %q", ok, parent)
	}
	orphan := map[string]any{"issuetype": map[string]any{"subtask": true}}
	if ok, parent := subtaskOf(orphan); !ok || parent != "" {
		t.Fatalf("got %v %q", ok, parent)
	}
	story := map[string]any{"issuetype": map[string]any{"name": "Story", "subtask": false}}
	if ok, _ := subtaskOf(story); ok {
		t.Fatal("a story is no sub-task")
	}
}
