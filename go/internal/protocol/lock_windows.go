//go:build windows

package protocol

import (
	"errors"
	"os"
	"os/user"
	"syscall"
	"unsafe"
)

const (
	isWindows   = true
	privateMode = 0o777
)

var (
	kernel32         = syscall.NewLazyDLL("kernel32.dll")
	procLockFileEx   = kernel32.NewProc("LockFileEx")
	procUnlockFileEx = kernel32.NewProc("UnlockFileEx")
)

const (
	lockfileFailImmediately = 0x1
	lockfileExclusive       = 0x2
	errSharingViolation     = syscall.Errno(32)
	errLockViolation        = syscall.Errno(33)
)

// tryLock tries to lock the first byte of the file without waiting; false means another
// session holds it.
func tryLock(f *os.File) (bool, error) {
	var ol syscall.Overlapped
	r, _, err := procLockFileEx.Call(f.Fd(), lockfileExclusive|lockfileFailImmediately, 0, 1, 0, uintptr(unsafe.Pointer(&ol)))
	if r != 0 {
		return true, nil
	}
	if errors.Is(err, errSharingViolation) || errors.Is(err, errLockViolation) {
		return false, nil
	}
	return false, err
}

func unlock(f *os.File) error {
	var ol syscall.Overlapped
	r, _, err := procUnlockFileEx.Call(f.Fd(), 0, 1, 0, uintptr(unsafe.Pointer(&ol)))
	if r == 0 {
		return err
	}
	return nil
}

func currentUser() string {
	if u, err := user.Current(); err == nil {
		return u.Username
	}
	return ""
}

// safeLockDir: permissions are not checked on Windows (the per-user temp folder is private).
func safeLockDir(root string) bool {
	info, err := os.Lstat(root)
	return err == nil && info.IsDir()
}

// writableDir says nothing on Windows; opening the lock file covers that.
func writableDir(string) bool { return true }
