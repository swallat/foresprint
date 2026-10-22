package app

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/workpackages"
)

// maxImportBytes is the largest file the import reads.
const maxImportBytes = 20 << 20

func isCSV(path string) bool {
	return strings.EqualFold(filepath.Ext(path), ".csv")
}

// packageImport is a CSV table read against the work packages of a team.
type packageImport struct {
	data     *storage.TeamData
	merged   []model.Ticket
	changes  []ImportChange
	problem  []workpackages.Problem
	unmapped []string
	hash     string
}

// readImportFile reads a regular file of reasonable size.
func readImportFile(path string) ([]byte, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > maxImportBytes {
		return nil, errors.New(i18n.T("The file is not a regular file or larger than 20 MB."))
	}
	return os.ReadFile(path)
}

// planPackages reads the CSV table and merges it with the work packages of the team. Only a
// team that keeps its work packages in Foresprint takes a table; a tracker team gets its tickets
// from the tracker. The hash covers the table and the current work packages, so apply refuses
// when either changed since the preview.
func (a *API) planPackages(team, path string) (*packageImport, error) {
	raw, err := readImportFile(path)
	if err != nil {
		return nil, err
	}
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return nil, err
	}
	switch data.Team.Source() {
	case model.SourceNone:
		return nil, errors.New(i18n.T("The tickets are switched off for this team."))
	case model.SourcePackages:
	default:
		return nil, errors.New(i18n.T("This team gets its tickets from a tracker. A CSV table can only be imported as work packages."))
	}
	current, _ := os.ReadFile(filepath.Join(repo.TeamDir(team), storage.TicketFileName(data.Team)))
	sum := sha256.New()
	sum.Write(raw)
	sum.Write([]byte{0})
	sum.Write(current)

	rows, err := workpackages.ReadCSV(raw)
	if err != nil {
		return nil, err
	}
	res := workpackages.ParseTable(rows, workpackages.Options{Tracker: data.Team.Tracker, Existing: data.Tickets})
	old := map[string]model.Ticket{}
	for _, t := range data.Tickets {
		old[t.Key] = t
	}
	if !res.HasLabels { // the table says nothing about labels: keep the existing ones
		for i, p := range res.Packages {
			if o, ok := old[p.Key]; ok {
				res.Packages[i].Labels = unionOf(o.Labels, p.Labels)
			}
		}
	}
	merged, _ := workpackages.Merge(data.Tickets, res.Packages)
	file := storage.TicketFileName(data.Team)
	var changes []ImportChange
	for _, m := range merged {
		o, existed := old[m.Key]
		if !existed {
			changes = append(changes, ImportChange{File: file, Path: textfmt.BlankControls(m.Key), Old: "–", New: textfmt.BlankControls(m.Title)})
			continue
		}
		changes = append(changes, packageDiff(file, o, m)...)
	}
	return &packageImport{data: data, merged: merged, changes: changes, problem: res.Problems, unmapped: res.Unmapped, hash: hex.EncodeToString(sum.Sum(nil))}, nil
}

func unionOf(a, b []string) []string {
	out := append([]string(nil), a...)
	for _, x := range b {
		if !slices.Contains(out, x) {
			out = append(out, x)
		}
	}
	return out
}

// packageDiff lists the fields an import changes in an existing work package.
func packageDiff(file string, o, n model.Ticket) []ImportChange {
	var out []ImportChange
	add := func(field, before, after string) {
		if before != after {
			out = append(out, ImportChange{File: file, Path: textfmt.BlankControls(n.Key + "." + field), Old: textfmt.BlankControls(orDash(before)), New: textfmt.BlankControls(orDash(after))})
		}
	}
	str := func(p *string) string {
		if p == nil {
			return ""
		}
		return *p
	}
	num := func(p *float64) string {
		if p == nil {
			return ""
		}
		return fmt.Sprint(*p)
	}
	add("title", o.Title, n.Title)
	add("status", str(o.Status), str(n.Status))
	add("type", str(o.IssueType), str(n.IssueType))
	add("priority", str(o.Priority), str(n.Priority))
	add("assignee", str(o.Assignee), str(n.Assignee))
	add("product", str(o.Product), str(n.Product))
	add("project", str(o.Project), str(n.Project))
	add("estimate", num(o.Estimate), num(n.Estimate))
	add("labels", strings.Join(o.Labels, ", "), strings.Join(n.Labels, ", "))
	add("depends_on", strings.Join(o.DependsOn, ", "), strings.Join(n.DependsOn, ", "))
	add("description", str(o.Description), str(n.Description))
	add("acceptance", str(o.Acceptance), str(n.Acceptance))
	add("done", fmt.Sprint(o.Done), fmt.Sprint(n.Done))
	return out
}

func orDash(s string) string {
	if s == "" {
		return "–"
	}
	return s
}

func (a *API) previewPackages(team, path string) (ImportPreview, error) {
	plan, err := a.planPackages(team, path)
	if err != nil {
		return ImportPreview{}, err
	}
	out := ImportPreview{Kind: "packages", Path: path, Hash: plan.hash, Changes: []ImportChange{}, Untouched: []string{}, Problems: []string{}, Unmapped: []string{}}
	for i, c := range plan.changes {
		if i == importPreviewLimit {
			out.More = len(plan.changes) - importPreviewLimit
			break
		}
		out.Changes = append(out.Changes, c)
	}
	for i, p := range plan.problem {
		if i == importPreviewLimit {
			out.Problems = append(out.Problems, i18n.T("… and {n} more rows", "n", len(plan.problem)-importPreviewLimit))
			break
		}
		out.Problems = append(out.Problems, i18n.T("Row {row}: {msg}", "row", p.Row, "msg", textfmt.BlankControls(p.Msg)))
	}
	for _, u := range plan.unmapped {
		out.Unmapped = append(out.Unmapped, textfmt.BlankControls(u))
	}
	return out, nil
}

func (a *API) applyPackages(team, path, hash string) ([]string, error) {
	plan, err := a.planPackages(team, path)
	if err != nil {
		return nil, err
	}
	if plan.hash != hash {
		return nil, errors.New(i18n.T("The file changed since the preview. Choose it again."))
	}
	if len(plan.changes) == 0 {
		return []string{}, nil
	}
	written, err := storage.NewRepository(a.DataDir()).SavePackages(team, storage.TicketsFile{
		Tickets: plan.merged, Imported: plan.data.TicketsImported, Source: plan.data.TicketsSource,
	})
	if err != nil {
		return nil, err
	}
	storage.ClearTeamCache()
	return []string{filepath.Base(written)}, nil
}
