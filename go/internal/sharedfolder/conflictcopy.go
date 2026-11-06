package sharedfolder

import (
	"path"
	"regexp"
	"strings"
)

// OneDrive and SharePoint append the computer name ("plan-DESKTOP-ABC123.yaml"); that is too
// ambiguous to recognise by name and is left out.
//
// Sync services do not merge; when two computers change a file at once they keep both and give
// the second one a new name. These patterns recognise the names the common services use.
var conflictCopyRes = []*regexp.Regexp{
	// Dropbox: "plan (Anna's conflicted copy 2026-11-06).yaml", German "(In Konflikt stehende Kopie von Anna ...)".
	// A plain "(Konflikte)" in a name is a normal file name.
	regexp.MustCompile(`(?i) \([^)]*(conflicted copy|in konflikt stehende kopie)[^)]*\)`),
	// Nextcloud / ownCloud: "plan (conflicted copy 2026-11-06 101010).yaml".
	regexp.MustCompile(`(?i)\(conflicted copy [^)]*\)`),
	// Syncthing: "plan.sync-conflict-20261106-101010-ABCDEFG.yaml".
	regexp.MustCompile(`\.sync-conflict-\d{8}-\d{6}`),
	// Nextcloud server side: "plan_conflict-20261106-101010.yaml".
	regexp.MustCompile(`_conflict-\d{8}-\d{6}`),
}

// IsConflictCopy says whether the file name (a path relative to the shared folder) looks like a
// copy that a sync service made because two computers changed the file at once.
func IsConflictCopy(rel string) bool {
	base := path.Base(rel)
	for _, re := range conflictCopyRes {
		if re.MatchString(base) {
			return true
		}
	}
	return false
}

// OriginalOf guesses the file a conflict copy belongs to, "" if it cannot tell.
func OriginalOf(rel string) string {
	dir, base := path.Split(rel)
	ext := path.Ext(base)
	stem := strings.TrimSuffix(base, ext)
	for _, re := range conflictCopyRes[:2] {
		if re.MatchString(stem) {
			return dir + strings.TrimSpace(re.ReplaceAllString(stem, "")) + ext
		}
	}
	for _, re := range conflictCopyRes[2:] {
		if loc := re.FindStringIndex(base); loc != nil {
			return dir + base[:loc[0]] + ext
		}
	}
	return ""
}
