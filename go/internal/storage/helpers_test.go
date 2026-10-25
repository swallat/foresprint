package storage

import (
	"runtime"
	"testing"
	"time"
)

func isWindows() bool { return runtime.GOOS == "windows" }

func yamlxTime(t *testing.T) time.Time {
	t.Helper()
	return time.Date(2020, 1, 2, 3, 4, 5, 0, time.UTC)
}
