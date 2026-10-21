//go:build windows

package git

import (
	"os/exec"
	"strconv"
	"syscall"
)

const createNoWindow = 0x08000000

// No console windows for helper processes (otherwise one flashes up on every call).
func setProcAttr(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNoWindow, HideWindow: true}
}

// terminateTree ends the process and everything it started.
func terminateTree(cmd *exec.Cmd) error {
	kill := exec.Command("taskkill", "/PID", strconv.Itoa(cmd.Process.Pid), "/T", "/F")
	kill.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNoWindow, HideWindow: true}
	_ = kill.Run()
	return cmd.Process.Kill()
}
