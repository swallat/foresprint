//go:build windows

package main

import (
	"os"
	"syscall"
)

// The Windows release is linked for the GUI subsystem (-H windowsgui), so a double click opens no
// console window. A call from a terminal then has no standard streams of its own: attach to the
// console of the parent and use it for the streams that are not redirected.
func init() {
	attach := syscall.NewLazyDLL("kernel32.dll").NewProc("AttachConsole")
	const attachParent = ^uintptr(0) // ATTACH_PARENT_PROCESS
	if ok, _, _ := attach.Call(attachParent); ok == 0 {
		return
	}
	reopen(&os.Stdin, syscall.STD_INPUT_HANDLE, "CONIN$", os.O_RDONLY)
	reopen(&os.Stdout, syscall.STD_OUTPUT_HANDLE, "CONOUT$", os.O_WRONLY)
	reopen(&os.Stderr, syscall.STD_ERROR_HANDLE, "CONOUT$", os.O_WRONLY)
}

// reopen replaces a stream that has no valid handle (started without a console) by the console.
func reopen(stream **os.File, id int, device string, flag int) {
	if h, err := syscall.GetStdHandle(id); err == nil && h != 0 && h != syscall.InvalidHandle {
		return
	}
	if f, err := os.OpenFile(device, flag, 0); err == nil {
		*stream = f
	}
}
