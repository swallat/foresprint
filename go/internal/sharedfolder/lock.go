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

// Handle is a lock this program holds.
type Handle struct {
	root, token string
	owner, host string
}

// ErrLockLost is returned by Renew when the lock was taken over, for example because the save took
// longer than LockTTL.
var ErrLockLost = errors.New("the save lock was lost")

func lockData(l Lock) []byte {
	data, _ := json.Marshal(l)
	return data
}

// Acquire takes the save lock for owner, waiting up to wait for another holder. The lock file is
// created exclusively (the one operation file servers do atomically). An expired lock is taken
// over by renaming it away first, which only one of several waiting programs can do; the one that
// finds it grabbed a lock that was renewed meanwhile puts it back. A lock file that is empty or
// unreadable counts as expired once it is older than LockTTL. now is the clock; the expiry is
// written in the clock of the one who takes the lock, so clocks of the team members should agree
// within a few seconds (the setup check tells).
func Acquire(root, owner, host string, wait time.Duration, now func() time.Time) (*Handle, error) {
	if err := os.MkdirAll(filepath.Join(root, Dir), 0o755); err != nil {
		return nil, err
	}
	token := fmt.Sprintf("%d-%d", os.Getpid(), now().UnixNano())
	deadline := now().Add(wait)
	path := LockPath(root)
	for {
		l := Lock{Owner: owner, Host: host, Token: token, Since: now(), Expires: now().Add(LockTTL)}
		f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
		if err == nil {
			_, werr := f.Write(lockData(l))
			cerr := f.Close()
			if werr != nil || cerr != nil {
				_ = os.Remove(path)
				return nil, errors.Join(werr, cerr)
			}
			return &Handle{root: root, token: token, owner: owner, host: host}, nil
		}
		if !errors.Is(err, fs.ErrExist) {
			return nil, err
		}
		cur, ok := ReadLock(root)
		expired := ok && !cur.Expires.After(now())
		if !ok {
			if info, serr := os.Stat(path); serr == nil {
				expired = now().Sub(info.ModTime()) > LockTTL
			}
		}
		switch {
		case expired:
			takeOver(path, token, cur, ok, now)
			continue
		case !now().Before(deadline):
			return nil, &Held{By: cur}
		}
		time.Sleep(25 * time.Millisecond)
	}
}

// takeOver removes an expired lock. The file is renamed to a name of its own first; if what was
// renamed turns out to be a live lock of somebody who took the file in the meantime, it is put back.
func takeOver(path, token string, seen Lock, seenOK bool, now func() time.Time) {
	stale := path + ".stale-" + token
	if os.Rename(path, stale) != nil {
		return // somebody else was faster
	}
	data, _ := os.ReadFile(stale)
	var got Lock
	live := json.Unmarshal(data, &got) == nil && got.Expires.After(now()) && (!seenOK || got.Token != seen.Token)
	if live {
		if os.Rename(stale, path) == nil {
			return
		}
	}
	_ = os.Remove(stale)
}

// Renew extends the lock; call it before each step of a long save. It fails with ErrLockLost if the
// lock is no longer this one.
func (h *Handle) Renew(now func() time.Time) error {
	cur, ok := ReadLock(h.root)
	if !ok || cur.Token != h.token {
		return ErrLockLost
	}
	cur.Expires = now().Add(LockTTL)
	return WriteFile(LockPath(h.root), lockData(cur), time.Second)
}

// Release gives the lock back; a lock that was taken over is left alone.
func (h *Handle) Release() {
	if cur, ok := ReadLock(h.root); ok && cur.Token == h.token {
		_ = os.Remove(LockPath(h.root))
	}
}
