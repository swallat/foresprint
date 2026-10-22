package datasvc

import (
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
)

// Capabilities are what this storage can do.
func (s *Store) Capabilities() Capabilities {
	return Capabilities{OfflineWrite: true, Tags: true, Branches: true}
}

// Status is the state of the storage without network access (what the last check found). Call
// CheckForChanges to ask the server first.
func (s *Store) Status() Status {
	dir := s.Folder()
	out := Status{Kind: "git", Writable: true, Connected: true, Capabilities: s.Capabilities(),
		IncomingFrom: []string{}}
	if dir == "" {
		return withProblem(out, git.New(i18n.T("No data folder chosen."), "path", ""))
	}
	ctx := s.ctx()
	st, err := gitsync.CachedState(ctx, dir)
	if err != nil {
		return withProblem(out, err)
	}
	info, _ := gitsync.CachedRemoteInfo(ctx, dir)
	out.Location = info.URL
	out.Configured = st.Remote != ""
	out.Pending = st.Ahead
	out.Incoming = st.Behind
	out.Conflicts = len(st.Conflicts)
	out.Connected = !st.Offline()
	if pending, err := git.CachedPendingChanges(ctx, dir); err == nil {
		out.Unsaved = len(pending)
	}
	if st.Unfinished == "merge" && out.Conflicts == 0 {
		out.Conflicts = 1 // an open merge always needs the person
	}
	if st.Behind > 0 {
		commits, _, _ := gitsync.Incoming(ctx, dir, 20)
		out.IncomingFrom = names(commits)
	}
	viaReview := false
	if mode, err := gitsync.ShareMode(ctx, st.Root); err == nil && mode == gitsync.ShareMergeRequest {
		viaReview = st.Ahead > 0 && st.Remote != ""
	}
	if viaReview {
		out.Link = s.lastReview()
		if out.Link == "" {
			target := st.Upstream
			if i := strings.Index(target, "/"); i >= 0 {
				target = target[i+1:]
			}
			out.Link = gitsync.CompareURL(info.URL, target, gitsync.MergeRequestBranch(ctx, st.Root))
		}
	}
	out.Chip = chipFor(out, st, viaReview)
	return out
}

func withProblem(out Status, err error) Status {
	out.Problem = problemOf(err)
	out.Connected = false
	out.Writable = false
	out.Chip = Chip{State: ChipProblem, Text: out.Problem.Message}
	return out
}

func chipFor(s Status, st gitsync.SyncState, viaReview bool) Chip {
	switch {
	case s.Conflicts > 0:
		return Chip{State: ChipConflict, Text: plural(s.Conflicts, "{count} file needs your decision", "{count} files need your decision")}
	case st.Detached():
		return Chip{State: ChipProblem, Text: i18n.T("The data is not on a working version.")}
	case s.Configured && !s.Connected:
		return Chip{State: ChipOffline, Text: i18n.T("Offline: saving works, sharing waits")}
	case s.Incoming > 0:
		return Chip{State: ChipIncoming, Text: plural(s.Incoming, "{count} new change from {who}", "{count} new changes from {who}",
			"who", who(s.IncomingFrom))}
	case viaReview:
		return Chip{State: ChipWaitingForReview, Text: i18n.T("Waiting for review"), Link: s.Link}
	case s.Unsaved > 0:
		return Chip{State: ChipUnsaved, Text: plural(s.Unsaved, "{count} unsaved change", "{count} unsaved changes")}
	case !s.Configured:
		return Chip{State: ChipLocal, Text: i18n.T("Saved on this computer only")}
	case s.Pending > 0:
		return Chip{State: ChipPending, Text: plural(s.Pending, "{count} save not shared yet", "{count} saves not shared yet")}
	}
	return Chip{State: ChipOK, Text: i18n.T("Up to date")}
}

// CheckForChanges asks the server whether others have changed something (a fetch, nothing is
// taken over) and returns the new status. An unreachable server is not an error; the status then
// says offline.
func (s *Store) CheckForChanges() Status {
	dir := s.Folder()
	if dir != "" {
		_, _ = gitsync.Fetch(s.ctx(), dir)
		git.InvalidateStatus()
	}
	return s.Status()
}

// StartBackgroundCheck starts the check for changes in the background if it is due (at start and
// every 30 minutes) and says whether it started. The window reads Status a little later.
func (s *Store) StartBackgroundCheck() bool {
	dir := s.Folder()
	if dir == "" {
		return false
	}
	return gitsync.StartBackgroundFetch(s.ctx(), dir)
}

// IncomingChanges lists what others have changed and Refresh would take over.
func (s *Store) IncomingChanges() []Change {
	dir := s.Folder()
	if dir == "" {
		return []Change{}
	}
	commits, _, err := gitsync.Incoming(s.ctx(), dir, 50)
	if err != nil {
		return []Change{}
	}
	return changes(commits)
}

// plural picks the English source text by the number and fills in {count} and the other values.
func plural(n int, one, many string, values ...any) string {
	text := many
	if n == 1 {
		text = one
	}
	return i18n.T(text, append([]any{"count", n}, values...)...)
}
