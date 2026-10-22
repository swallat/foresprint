//go:build windows

package main

import (
	"os"
	"os/exec"
	"syscall"
	"unsafe"
)

const detachedProcess = 0x00000008 // DETACHED_PROCESS

// The Windows program is a console program, so that a terminal waits for it and gets its output
// (scripts and CI depend on both). Started without arguments (the window) from Explorer, it is the
// only process on its console, and that console is a window of its own, or a Windows Terminal tab,
// that FreeConsole would not close. So the program starts itself again without a console and
// ends: the copy has no console and opens the window. Started without arguments from a terminal
// the terminal is shared with other processes and stays as it is.
func init() {
	if len(os.Args) > 1 {
		return
	}
	list := syscall.NewLazyDLL("kernel32.dll").NewProc("GetConsoleProcessList")
	var pids [2]uint32
	n, _, _ := list.Call(uintptr(unsafe.Pointer(&pids[0])), uintptr(len(pids)))
	if n != 1 {
		return
	}
	exe, err := os.Executable()
	if err != nil {
		return
	}
	cmd := exec.Command(exe)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: detachedProcess}
	if cmd.Start() == nil {
		os.Exit(0)
	}
}
