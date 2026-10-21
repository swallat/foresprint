//go:build !windows

package protocol

import (
	"errors"
	"os"
	"strconv"
	"syscall"
)

const (
	isWindows   = false
	privateMode = 0o700
)

// tryLock tries to lock the file without waiting; false means another session holds it. Any
// other error is permanent (e.g. a file system without file locks).
func tryLock(f *os.File) (bool, error) {
	err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	if err == nil {
		return true, nil
	}
	for _, busy := range []error{syscall.EWOULDBLOCK, syscall.EAGAIN, syscall.EACCES, syscall.EDEADLK} {
		if errors.Is(err, busy) {
			return false, nil
		}
	}
	return false, err
}

func unlock(f *os.File) error { return syscall.Flock(int(f.Fd()), syscall.LOCK_UN) }

func currentUser() string { return strconv.Itoa(os.Getuid()) }

// safeLockDir: a link or a folder of another user is not a safe place.
func safeLockDir(root string) bool {
	info, err := os.Lstat(root)
	if err != nil || !info.IsDir() {
		return false
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	return ok && int(st.Uid) == os.Getuid()
}

func writableDir(path string) bool { return syscall.Access(path, 0x2|0x1) == nil }
