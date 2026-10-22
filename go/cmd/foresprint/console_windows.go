//go:build windows

package main

import (
	"os"
	"syscall"
	"unsafe"
)

// The Windows program is a console program, so that a terminal waits for it and gets its output
// (scripts and CI depend on both). Started without arguments (the window, by a double click or
// from the shortcut) from Explorer, it is the only process on its console: the console is
// released then, so no console window stays behind. Started without arguments from a terminal
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
	_, _, _ = syscall.NewLazyDLL("kernel32.dll").NewProc("FreeConsole").Call()
}
