//go:build !windows

package git

import (
	"os"
	"os/exec"
	"syscall"
	"time"
)

// The process gets a session of its own, so that the whole tree (ssh, credential helpers) can be
// ended together and no terminal is available to prompt on.
func setProcAttr(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

// terminateTree ends the process and everything it started: first politely, after a grace
// period for good.
func terminateTree(cmd *exec.Cmd) error {
	pid := cmd.Process.Pid
	_ = syscall.Kill(-pid, syscall.SIGTERM)
	time.AfterFunc(killDelay, func() {
		// Only while the leader is still there: once reaped, the group id may belong to others.
		if cmd.Process.Signal(syscall.Signal(0)) == nil {
			_ = syscall.Kill(-pid, syscall.SIGKILL)
		}
	})
	return nil
}

// exitSignal names the signal that ended the process ("" if it exited by itself).
func exitSignal(ps *os.ProcessState) string {
	if ps == nil {
		return ""
	}
	if ws, ok := ps.Sys().(syscall.WaitStatus); ok && ws.Signaled() {
		return ws.Signal().String()
	}
	return ""
}
