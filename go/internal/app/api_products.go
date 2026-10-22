package app

import (
	"errors"
	"fmt"
	"math"
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/rules"
	"github.com/swallat/foresprint/internal/storage"
)

func (a *API) productsView(data *storage.TeamData) ProductsView {
	today := a.day()
	view := ProductsView{
		Source:   string(data.Team.Source()),
		Today:    today.Format(isoDay),
		Multi:    data.Team.Features.Products || len(data.Products) > 1,
		Legacy:   len(data.Team.ProductOwners) == 0,
		Products: []ProductDTO{},
		Owners:   ownersOf(data, today),
		Defaults: productsDefaults(data, today),
	}
	counts, points := countTickets(data, today)
	for _, p := range data.Products {
		d := ProductDTO{
			ID: p.ID, Name: p.Name, Share: p.Share,
			From: dayText(p.Start), To: dayText(p.End),
			Tickets: counts[p.ID], Points: points[p.ID],
			Ended: p.End != nil && p.End.Before(today),
		}
		if p.PO != nil {
			d.PO = *p.PO
		}
		if p.Match != nil {
			d.Rule = rules.FormatRule(p.Match)
		}
		d.Used = productUsed(data, p)
		view.Products = append(view.Products, d)
	}
	return view
}

// productsDefaults is the default amount per product for the running and the next sprints: the
// Forecast PLAN of each sprint split by StandardShares, the same numbers as the plan page. A
// team without a calculable forecast gets no rows.
func productsDefaults(data *storage.TeamData, today time.Time) []ProductsDefault {
	out := []ProductsDefault{}
	fc, err := forecast.Build(data, today)
	if err != nil {
		return out
	}
	roadmap := data.Team.Forecast.ProductBasis == model.BasisRoadmap
	for _, e := range fc.Upcoming() {
		row := ProductsDefault{Sprint: e.Sprint.ID, Values: map[string]float64{}}
		if roadmap {
			row.RoadmapShare = data.Team.Forecast.RoadmapShare
		}
		if plan := e.Result.Plan; plan != nil {
			row.Plan = plan
			av := *plan
			if roadmap {
				av *= data.Team.Forecast.RoadmapShare
			}
			row.Available = &av
			var active []model.Product
			for _, p := range data.Products {
				if p.ActiveBetween(e.Sprint.Start, e.Sprint.End) {
					active = append(active, p)
				}
			}
			for id, v := range products.StandardShares(active, &av) {
				row.Values[id] = math.Round(v)
			}
		}
		out = append(out, row)
	}
	return out
}

// countTickets counts, per active product, the tickets it takes: the first product whose rule
// matches (tracker), or the product of the work package.
func countTickets(data *storage.TeamData, today time.Time) (map[string]int, map[string]float64) {
	counts, points := map[string]int{}, map[string]float64{}
	for _, t := range data.Tickets {
		if t.Done {
			continue
		}
		id := ""
		switch data.Team.Source() {
		case model.SourcePackages:
			if t.Product != nil {
				id = *t.Product
			}
		case model.SourceTracker:
			facts := t.Facts()
			for _, p := range data.Products {
				if p.Match != nil && activeOn(p, today) && p.Match.Matches(facts) {
					id = p.ID
					break
				}
			}
		}
		if id == "" {
			continue
		}
		counts[id]++
		if t.Estimate != nil {
			points[id] += *t.Estimate
		}
	}
	return counts, points
}

func activeOn(p model.Product, day time.Time) bool {
	return (p.Start == nil || !p.Start.After(day)) && (p.End == nil || !p.End.Before(day))
}

// productUsed: the product appears in a sprint, has an end, or work packages point at it.
func productUsed(data *storage.TeamData, p model.Product) bool {
	if p.End != nil {
		return true
	}
	for _, s := range data.Sprints {
		if v, ok := s.Products[p.ID]; ok && !v.IsEmpty() {
			return true
		}
	}
	if data.Team.Source() == model.SourcePackages {
		for _, t := range data.Tickets {
			if t.Product != nil && *t.Product == p.ID {
				return true
			}
		}
	}
	return false
}

// Products returns the products of the team and its POs.
func (a *API) Products(team string) (ProductsView, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return ProductsView{}, err
	}
	return a.productsView(data), nil
}

// SaveProducts replaces the products of the team (products.yaml). A product with an empty id is
// new. A product that is missing is deleted, which only works for one without history; ending a
// product is EndProduct. The answer is the page as saved.
func (a *API) SaveProducts(team string, list []ProductDTO) (ProductsView, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return ProductsView{}, err
	}
	fields := model.RuleSourcesWith(data.Team.Tracker.RuleFields)
	old := map[string]model.Product{}
	taken := map[string]bool{}
	for _, p := range data.Products {
		old[p.ID] = p
		taken[p.ID] = true
	}
	var out []model.Product
	seen := map[string]bool{}
	for _, d := range list {
		p, err := productFrom(d, old[d.ID], fields)
		if err != nil {
			return ProductsView{}, err
		}
		if p.ID == "" {
			p.ID = model.NewPersonID(p.Name, taken, "product")
			taken[p.ID] = true
		}
		if seen[p.ID] {
			return ProductsView{}, errors.New(i18n.T("{name} is listed twice.", "name", p.Name))
		}
		seen[p.ID] = true
		out = append(out, p)
	}
	for _, p := range data.Products {
		if !seen[p.ID] && productUsed(data, p) {
			return ProductsView{}, errors.New(i18n.T("{name} has history and cannot be deleted. End it instead.", "name", p.Name))
		}
	}
	a.forget(team)
	if _, err := storage.NewRepository(a.DataDir()).SaveProducts(team, out); err != nil {
		return ProductsView{}, err
	}
	data.Products = out
	return a.productsView(data), nil
}

func productFrom(d ProductDTO, stored model.Product, fields []string) (model.Product, error) {
	p := stored
	p.ID = d.ID
	p.Name = trimSpace(d.Name)
	if p.Name == "" {
		return p, errors.New(i18n.T("Every product needs a name."))
	}
	p.PO = optionalText(d.PO)
	if d.Share != nil && !(*d.Share >= 0 && *d.Share <= 1) {
		return p, errors.New(i18n.T("The share of {name} must be between 0 and 100 percent.", "name", p.Name))
	}
	p.Share = d.Share
	p.Match = nil
	if trimSpace(d.Rule) != "" {
		rule, err := rules.ParseRule(d.Rule, fields)
		if err != nil {
			return p, errors.New(i18n.T("The rule of {name} is not valid: {problem}", "name", p.Name, "problem", err.Error()))
		}
		p.Match = rule
	}
	var err error
	if p.Start, err = optionalDay(d.From); err != nil {
		return p, err
	}
	if p.End, err = optionalDay(d.To); err != nil {
		return p, err
	}
	if p.Start != nil && p.End != nil && p.End.Before(*p.Start) {
		return p, errors.New(i18n.T("The last day of {name} lies before its first day.", "name", p.Name))
	}
	return p, nil
}

func optionalDay(s string) (*time.Time, error) {
	if s == "" {
		return nil, nil
	}
	t, err := parseTeamDay(s)
	if err != nil {
		return nil, err
	}
	return &t, nil
}

// EndProduct ends a product after lastDay (the end of a sprint). shares gives the new share of
// every remaining product in the range 0 to 1 and must reach 100 percent. The open tickets go
// to the product target ("" = nobody): with a tracker the rule of the ended product is added to
// the rule of the target, with work packages their product changes. The rule of the ended
// product is dropped and open projects continue without it. Undo takes it all back.
func (a *API) EndProduct(team, id, lastDay string, shares map[string]float64, target string) (EndResult, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return EndResult{}, err
	}
	end, err := parseTeamDay(lastDay)
	if err != nil {
		return EndResult{}, err
	}
	idx := -1
	for i, p := range data.Products {
		if p.ID == id {
			idx = i
		}
	}
	if idx < 0 {
		return EndResult{}, errors.New(i18n.T("Unknown product '{id}'.", "id", id))
	}
	if s := data.Products[idx].Start; s != nil && end.Before(*s) {
		return EndResult{}, errors.New(i18n.T("The last day of {name} lies before its first day.", "name", data.Products[idx].Name))
	}
	var rest []int
	for i, p := range data.Products {
		if i != idx && (p.End == nil || !p.End.Before(a.day())) { // the same ones the window offers: not ended yet
			rest = append(rest, i)
		}
	}
	if len(rest) == 0 {
		return EndResult{}, errors.New(i18n.T("The only product cannot be ended."))
	}
	sum := 0.0
	for _, i := range rest {
		s, ok := shares[data.Products[i].ID]
		if !ok || s < 0 || s > 1 {
			return EndResult{}, errors.New(i18n.T("Give every remaining product a share between 0 and 100 percent."))
		}
		sum += s
	}
	if math.Abs(sum-1) > 0.005 {
		return EndResult{}, errors.New(i18n.T("The shares add up to {sum} percent, not 100.", "sum", fmt.Sprintf("%.0f", sum*100)))
	}
	tIdx := -1
	if target != "" {
		for _, i := range rest {
			if data.Products[i].ID == target {
				tIdx = i
			}
		}
		if tIdx < 0 {
			return EndResult{}, errors.New(i18n.T("Unknown product '{id}'.", "id", target))
		}
	}

	repo := storage.NewRepository(a.DataDir())
	token := a.remember(team, a.teamFile(team, "products.yaml"), a.teamFile(team, storage.TicketFileName(data.Team)), a.teamFile(team, "projects.yaml"))
	moved := 0
	ended := data.Products[idx]
	switch data.Team.Source() {
	case model.SourcePackages:
		for i := range data.Tickets {
			t := &data.Tickets[i]
			if t.Done || t.Product == nil || *t.Product != id {
				continue
			}
			t.Product = optionalText(target)
			if target != "" {
				moved++
			}
		}
		if _, err := repo.SavePackages(team, storage.TicketsFile{Tickets: data.Tickets, Imported: data.TicketsImported, Source: data.TicketsSource}); err != nil {
			return EndResult{}, err
		}
	case model.SourceTracker:
		if tIdx >= 0 && ended.Match != nil {
			for _, t := range data.Tickets {
				if !t.Done && ended.Match.Matches(t.Facts()) {
					moved++
				}
			}
			joined := ended.Match
			if m := data.Products[tIdx].Match; m != nil {
				joined = &rules.Rule{Op: rules.OpAny, Children: []*rules.Rule{m, ended.Match}}
			}
			data.Products[tIdx].Match = joined
		}
	}
	for i, p := range data.Projects {
		if p.Closed() {
			continue
		}
		data.Projects[i] = withoutProduct(p, id)
	}
	if data.Team.Features.Tickets || data.Team.Features.Projects {
		if _, err := repo.SaveProjects(team, data.Projects); err != nil {
			return EndResult{}, err
		}
	}
	data.Products[idx].End = &end
	data.Products[idx].Share = model.Ptr(0.0)
	data.Products[idx].Match = nil
	for _, i := range rest {
		data.Products[i].Share = model.Ptr(shares[data.Products[i].ID])
	}
	if _, err := repo.SaveProducts(team, data.Products); err != nil {
		return EndResult{}, err
	}
	return EndResult{View: a.productsView(data), Moved: moved, Undo: token}, nil
}

// withoutProduct removes a product from a project; the project keeps at least what is left.
func withoutProduct(p model.Project, id string) model.Project {
	all := p.Products()
	var left []string
	for _, x := range all {
		if x != id {
			left = append(left, x)
		}
	}
	if len(left) == len(all) {
		return p
	}
	p.Product, p.AlsoProducts = nil, nil
	if len(left) > 0 {
		p.Product = &left[0]
		p.AlsoProducts = left[1:]
	}
	return p
}

// ResumeProduct takes up an ended product again, with a share of 0 and without a rule.
func (a *API) ResumeProduct(team, id string) (Step, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return Step{}, err
	}
	for i := range data.Products {
		if data.Products[i].ID != id {
			continue
		}
		token := a.remember(team, a.teamFile(team, "products.yaml"))
		data.Products[i].End = nil
		data.Products[i].Share = model.Ptr(0.0)
		if _, err := storage.NewRepository(a.DataDir()).SaveProducts(team, data.Products); err != nil {
			return Step{}, err
		}
		return Step{View: a.productsView(data), Undo: token}, nil
	}
	return Step{}, errors.New(i18n.T("Unknown product '{id}'.", "id", id))
}
