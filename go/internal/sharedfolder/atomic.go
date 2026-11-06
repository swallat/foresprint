package sharedfolder

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"time"
)

// Sum is the checksum of the content, the version token of a file.
func Sum(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

// SumFile is the checksum of a file; a missing file has the empty checksum and no error.
func SumFile(path string) (string, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return Sum(data), nil
}

// WriteFile replaces the file in one step: the content goes to a temporary file next to it, which
// then takes the place of the file. Others see the old or the new content, never half of it. On
// Windows another program that has the file open makes the replacement fail for a moment (sharing
// violation), and file servers can answer busy; the replacement is repeated for up to wait.
func WriteFile(path string, data []byte, wait time.Duration) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".sf-*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	deadline := time.Now().Add(wait)
	for {
		err = os.Rename(name, path)
		if err == nil || runtime.GOOS != "windows" || time.Now().After(deadline) {
			return err
		}
		time.Sleep(50 * time.Millisecond)
	}
}
