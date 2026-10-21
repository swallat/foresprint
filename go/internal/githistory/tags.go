package githistory

import (
	"context"
	"sort"
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
)

// Tag is a tag. Local: present on this computer; OnServer: present on the server (nil = unknown,
// because not queried or server not reachable); Differs: locally and on the server the tag
// points to different states.
type Tag struct {
	Name     string
	Target   string // short hash of the tagged commit
	Day      string
	Subject  string
	Local    bool
	OnServer *bool
	Differs  bool
}

func remoteOf(ctx context.Context, root string) string {
	out, _ := git.Lenient(ctx, root, "remote")
	remotes := strings.Fields(out)
	if contains(remotes, "origin") {
		return "origin"
	}
	if len(remotes) > 0 {
		return remotes[0]
	}
	return ""
}

// serverTags are the tags on the server: name -> commit they point to (queries the server).
func serverTags(ctx context.Context, root, remote string) (map[string]string, error) {
	out, err := git.With(ctx, root, git.Opts{Network: true, URL: git.RemoteURL(ctx, root, remote)},
		"ls-remote", "--tags", remote)
	if err != nil {
		return nil, err
	}
	objects := map[string]string{}
	peeled := map[string]string{}
	for _, line := range pySplitLines(out) {
		sha, ref, _ := strings.Cut(line, "\t")
		name, ok := strings.CutPrefix(ref, "refs/tags/")
		if !ok {
			continue
		}
		if base, ok := strings.CutSuffix(name, "^{}"); ok {
			peeled[base] = sha
		} else {
			objects[name] = sha
		}
	}
	tags := make(map[string]string, len(objects))
	for name, sha := range objects {
		if p, ok := peeled[name]; ok {
			sha = p
		}
		tags[name] = sha
	}
	return tags, nil
}

// ServerReachable says whether the server of the tags can be queried (network). False also
// without a server.
func ServerReachable(ctx context.Context, path string) (bool, error) {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return false, err
	}
	remote := remoteOf(ctx, root)
	if remote == "" {
		return false, nil
	}
	if _, err := serverTags(ctx, root, remote); err != nil {
		if git.As(err) != nil {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func boolPtr(b bool) *bool { return &b }

// ListTags lists the tags of this repository, newest first. With checkServer the server is
// queried (network): OnServer and Differs then show differences, and tags that exist only on the
// server come last with Local false. If the server is not reachable, OnServer stays nil.
func ListTags(ctx context.Context, path string, checkServer bool) ([]Tag, error) {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return nil, err
	}
	format := strings.Join([]string{
		"%(refname:strip=2)", "%(*objectname)", "%(objectname)", "%(*objectname:short)",
		"%(objectname:short)", "%(creatordate:short)", "%(contents:subject)",
	}, sep)
	out, err := git.With(ctx, root, git.Opts{Lenient: true},
		"for-each-ref", "--sort=-creatordate", "--format="+format, "refs/tags")
	if err != nil {
		return nil, err
	}
	type localTag struct {
		tag  Tag
		full string
	}
	var local []localTag
	// not splitlines: U+2028, \x0c ... would split the subject into several entries
	for _, line := range strings.Split(out, "\n") {
		if line == "" {
			continue
		}
		f := git.SplitRecord(line, 7, sep)
		target := f[3]
		if target == "" {
			target = f[4]
		}
		full := f[1]
		if full == "" {
			full = f[2]
		}
		local = append(local, localTag{Tag{Name: f[0], Target: target, Day: f[5], Subject: f[6], Local: true}, full})
	}
	var server map[string]string
	if checkServer {
		if remote := remoteOf(ctx, root); remote != "" {
			if server, err = serverTags(ctx, root, remote); err != nil {
				if git.As(err) == nil {
					return nil, err
				}
				server = nil
			}
		}
	}
	tags := make([]Tag, 0, len(local))
	if server == nil {
		for _, l := range local {
			tags = append(tags, l.tag)
		}
		return tags, nil
	}
	known := map[string]bool{}
	for _, l := range local {
		sha, on := server[l.tag.Name]
		t := l.tag
		t.OnServer = boolPtr(on)
		t.Differs = on && sha != l.full
		tags = append(tags, t)
		known[t.Name] = true
	}
	names := make([]string, 0, len(server))
	for name := range server {
		if !known[name] {
			names = append(names, name)
		}
	}
	sort.Strings(names)
	for _, name := range names {
		sha := server[name]
		if len(sha) > 7 {
			sha = sha[:7]
		}
		tags = append(tags, Tag{Name: name, Target: sha, OnServer: boolPtr(true)})
	}
	return tags, nil
}

func commitOf(ctx context.Context, root, ref string) string {
	out, _ := git.Lenient(ctx, root, "rev-parse", "--verify", "--quiet", ref+"^{commit}")
	return out
}

func tagExists(ctx context.Context, root, name string) bool {
	out, _ := git.Lenient(ctx, root, "rev-parse", "--verify", "--quiet", "refs/tags/"+name)
	return out != ""
}

// SetTag sets a tag (also retroactively) and uploads it. It returns a warning if the upload
// failed (the tag then stays local; a new call uploads it). If the tag already exists locally at
// the same state, it is only uploaded; at a different state the function refuses. If the server
// is reachable and already has the name for a different state, the tag is not created (error
// tag_exists); if it has it for the same state, it is adopted. An empty rev means HEAD, an empty
// message the tag name.
func SetTag(ctx context.Context, path, name, rev, message string) (warning *git.Error, err error) {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return nil, err
	}
	if err := git.ValidTagName(ctx, root, name); err != nil {
		return nil, err
	}
	if rev == "" {
		rev = "HEAD"
	}
	if rev, err = checkRev(rev); err != nil {
		return nil, err
	}
	existing := commitOf(ctx, root, "refs/tags/"+name)
	target := commitOf(ctx, root, rev)
	if existing != "" && existing != target {
		return nil, git.New(i18n.T("The tag {name} already exists.", "name", name), "", "")
	}
	if existing == "" {
		adopted, err := adoptServerTag(ctx, root, name, target)
		if err != nil {
			return nil, err
		}
		if adopted {
			return nil, nil
		}
		if message == "" {
			message = name
		}
		if _, err := git.Git(ctx, root, "tag", "-a", "-m", message, "--", name, rev); err != nil {
			return nil, err
		}
		git.InvalidateStatus()
	}
	return pushTag(ctx, root, name)
}

// adoptServerTag asks the server (if reachable): if the name is taken there for a different
// state, error. If it points to the same state, that tag is fetched (true) instead of creating a
// second one that the server would reject as differing.
func adoptServerTag(ctx context.Context, root, name, target string) (bool, error) {
	remote := remoteOf(ctx, root)
	if remote == "" {
		return false, nil
	}
	tags, err := serverTags(ctx, root, remote)
	if err != nil {
		if git.As(err) != nil {
			return false, nil // without an answer from the server nothing can be said
		}
		return false, err
	}
	onServer := tags[name]
	if onServer == "" || target == "" {
		return false, nil
	}
	if onServer != target {
		short := onServer
		if len(short) > 7 {
			short = short[:7]
		}
		return false, git.New(i18n.T("The tag {name} is already used on the server for a different version "+
			"({rev}). It was not created.", "name", name, "rev", short), "tag_exists",
			i18n.T("Choose a different name or delete the tag on the server first."))
	}
	if _, err := git.With(ctx, root, git.Opts{Network: true, URL: git.RemoteURL(ctx, root, remote)},
		"fetch", remote, "refs/tags/"+name+":refs/tags/"+name); err != nil {
		if git.As(err) != nil {
			return false, nil
		}
		return false, err
	}
	git.InvalidateStatus()
	return true, nil
}

func pushTag(ctx context.Context, root, name string) (*git.Error, error) {
	remote := remoteOf(ctx, root)
	if remote == "" {
		return nil, nil
	}
	if _, err := git.With(ctx, root, git.Opts{Network: true, URL: git.RemoteURL(ctx, root, remote)},
		"push", remote, "refs/tags/"+name); err != nil {
		if e := git.As(err); e != nil {
			return e, nil
		}
		return nil, err
	}
	return nil, nil
}

// UploadTag uploads an existing local tag to the server (e.g. after the upload failed when
// setting it). Errors (no local tag, no server, server not reachable, tag with a different state
// already there) come as *git.Error.
func UploadTag(ctx context.Context, path, name string) error {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return err
	}
	if err := git.ValidTagName(ctx, root, name); err != nil {
		return err
	}
	if !tagExists(ctx, root, name) {
		return git.New(i18n.T("The tag {name} does not exist on this computer.", "name", name), "", "")
	}
	if remoteOf(ctx, root) == "" {
		return git.New(i18n.T("No server set up."), "no_remote", git.HintFor("no_remote"))
	}
	warning, err := pushTag(ctx, root, name)
	if err != nil {
		return err
	}
	if warning != nil {
		return warning
	}
	return nil
}

// DeleteTag deletes a tag locally and on the server (also one that exists on only one of the two
// sides; calling repeatedly does no harm). It returns a warning if the server was not reachable
// (the tag stays there; a new call deletes it there).
func DeleteTag(ctx context.Context, path, name string) (warning *git.Error, err error) {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return nil, err
	}
	if err := git.ValidTagName(ctx, root, name); err != nil {
		return nil, err
	}
	if tagExists(ctx, root, name) {
		if _, err := git.Git(ctx, root, "tag", "-d", "--", name); err != nil {
			return nil, err
		}
		git.InvalidateStatus()
	}
	if remote := remoteOf(ctx, root); remote != "" {
		if _, err := git.With(ctx, root, git.Opts{Network: true, URL: git.RemoteURL(ctx, root, remote)},
			"push", remote, ":refs/tags/"+name); err != nil {
			e := git.As(err)
			if e == nil {
				return nil, err
			}
			if strings.Contains(e.Error(), "remote ref does not exist") {
				return nil, nil
			}
			return e, nil
		}
	}
	return nil, nil
}
