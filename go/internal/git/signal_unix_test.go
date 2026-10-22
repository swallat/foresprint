//go:build !windows

package git

import (
	"os/exec"
	"testing"
)

func TestExitSignalNamesTheSignal(t *testing.T) {
	cmd := exec.Command("sh", "-c", "kill -TERM $$")
	_ = cmd.Run()
	if got := exitSignal(cmd.ProcessState); got != "terminated" {
		t.Fatalf("got %q, want terminated", got)
	}
	if got := exitSignal(nil); got != "" {
		t.Fatalf("nil state: got %q", got)
	}
}
