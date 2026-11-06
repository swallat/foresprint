package sharedfolder

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"
)

// LockTTL is how long a save lock holds before others may take it over (a save takes a second;
// a program that died while holding it must not block the team).
const LockTTL = 60 * time.Second

// Lock is the content of the lock file.
type Lock struct {
	Owner   string    `json:"owner"`
	Host    string    `json:"host"`
	Token   string    `json:"token"`
	Since   time.Time `json:"since"`
	Expires time.Time `json:"expires"`
}

// Held reports a lock that somebody else holds.
type Held struct{ By Lock }

// Error describes who holds the lock.
func (h *Held) Error() string {
	return fmt.Sprintf("the shared folder is being saved by %s", h.By.Owner)
}

// LockPath is the lock file of a shared folder.
func LockPath(root string) string { return filepath.Join(root, Dir, "lock") }

// ReadLock reads the current lock, ok is false when there is none.
func ReadLock(root string) (l Lock, ok bool) {
	data, err := os.ReadFile(LockPath(root))
	if err != nil || json.Unmarshal(data, &l) != nil {
		return Lock{}, false
	}
	return l, true
}

// Acquire takes the save lock for owner, waiting up to wait for another holder. The lock file is
// created exclusively (the one operation file servers do atomically); an expired lock is removed
// first. now is the clock; the expiry is written in the clock of the one who takes the lock, so
// clocks of the team members should agree within a few seconds (the check of the setup tells).
// The returned function releases the lock; it removes the file only if it is still this lock.
func Acquire(root, owner, host string, wait time.Duration, now func() time.Time) (release func(), err error) {
	if err := os.MkdirAll(filepath.Join(root, Dir), 0o755); err != nil {
		return nil, err
	}
	token := fmt.Sprintf("%d-%d", os.Getpid(), now().UnixNano())
	deadline := now().Add(wait)
	path := LockPath(root)
	for {
		l := Lock{Owner: owner, Host: host, Token: token, Since: now(), Expires: now().Add(LockTTL)}
		data, _ := json.Marshal(l)
		f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
		if err == nil {
			_, werr := f.Write(data)
			cerr := f.Close()
			if werr != nil || cerr != nil {
				os.Remove(path)
				return nil, errors.Join(werr, cerr)
			}
			return func() {
				if cur, ok := ReadLock(root); ok && cur.Token == token {
					os.Remove(path)
				}
			}, nil
		}
		if !errors.Is(err, fs.ErrExist) {
			return nil, err
		}
		cur, ok := ReadLock(root)
		switch {
		case ok && !cur.Expires.After(now()):
			os.Remove(path) // expired: taken over
			continue
		case !now().Before(deadline):
			return nil, &Held{By: cur}
		}
		time.Sleep(25 * time.Millisecond)
	}
}
