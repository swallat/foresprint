package sharedfolder

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"
)

// CheckResult is one test of Check.
type CheckResult struct {
	Key    string `json:"key"`
	OK     bool   `json:"ok"`
	Detail string `json:"detail"`
}

// Check tests whether a folder is fit for the shared storage, in the order a person cares about:
// can we write, does the exclusive create of the lock file work, can a file be replaced in one
// step, do the clocks agree (the lock expiry relies on it), do umlauts in names survive. It works
// in a subfolder of its own and removes it again; the folder must exist.
func Check(root string) []CheckResult {
	out := []CheckResult{}
	add := func(key string, ok bool, detail string) { out = append(out, CheckResult{key, ok, detail}) }
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		add("exists", false, fmt.Sprint(err))
		return out
	}
	add("exists", true, "")
	dir := filepath.Join(root, ".foresprint-check")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		add("write", false, err.Error())
		return out
	}
	defer os.RemoveAll(dir)
	f := filepath.Join(dir, "a.yaml")
	if err := WriteFile(f, []byte("n: 1\n"), time.Second); err != nil {
		add("write", false, err.Error())
		return out
	}
	add("write", true, "")

	lock := filepath.Join(dir, "lock")
	fd, err := os.OpenFile(lock, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err == nil {
		fd.Close()
		_, err2 := os.OpenFile(lock, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
		add("lock", errors.Is(err2, fs.ErrExist), "")
	} else {
		add("lock", false, err.Error())
	}

	held, herr := os.Open(f)
	rerr := WriteFile(f, []byte("n: 2\n"), time.Second)
	if herr == nil {
		held.Close()
	}
	b, _ := os.ReadFile(f)
	add("replace", rerr == nil && string(b) == "n: 2\n", errText(rerr))

	t0 := time.Now()
	if err := os.WriteFile(filepath.Join(dir, "m"), []byte("x"), 0o644); err == nil {
		if st, err := os.Stat(filepath.Join(dir, "m")); err == nil {
			skew := st.ModTime().Sub(t0)
			add("clock", skew < 5*time.Second && skew > -5*time.Second, fmt.Sprintf("%+.1f s", skew.Seconds()))
		}
	}

	uerr := os.WriteFile(filepath.Join(dir, "Äö-Test.yaml"), []byte("x"), 0o644)
	_, serr := os.Stat(filepath.Join(dir, "Äö-Test.yaml"))
	add("names", uerr == nil && serr == nil, errText(uerr))
	return out
}

func errText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
