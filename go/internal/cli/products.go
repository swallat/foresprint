package cli

import (
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() {
	Register(productsCommand)
	Register(productListCommand)
}

// requireProducts stops a command when the team does not use the product distribution.
func requireProducts(data *storage.TeamData, team string) error {
	if !data.Team.Features.Products {
		return Failf("The product distribution is switched off for this team. Switch it on "+
			"with: {command}", "command", "foresprint settings "+team)
	}
	return nil
}

func productsCommand(env *Env) *cobra.Command {
	var preplanning, doCommit bool
	var history int
	cmd := &cobra.Command{
		Use:   "products TEAM [SPRINT]",
		Short: i18n.T("Distribution across the products: default, PO pre-planning, planning, done, balance."),
		Args:  cobra.RangeArgs(1, 2),
		RunE: func(cmd *cobra.Command, args []string) error {
			if history < 1 {
				return Failf("Sprints for the balance.")
			}
			id := ""
			if len(args) > 1 {
				id = args[1]
			}
			return runProducts(env, args[0], id, preplanning, history, doCommit)
		},
	}
	teamArg(env, cmd)
	cmd.Flags().BoolVar(&preplanning, "preplanning", false, i18n.T("Record PO pre-planning per product."))
	cmd.Flags().IntVar(&history, "history", 6, i18n.T("Sprints for the balance."))
	commitFlag(cmd, &doCommit)
	return cmd
}

func runProducts(env *Env, key, sprintID string, preplanning bool, history int, doCommit bool) error {
	data, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	if err := requireProducts(data, key); err != nil {
		return err
	}
	if len(data.Products) == 0 {
		return Failf("No products recorded. First: {command}", "command", "foresprint product-list "+key)
	}
	found, err := findOrCreateSprint(data, env, sprintID, forecast.PurposePlanning)
	if err != nil {
		return err
	}
	s := found.Clone()
	fc, err := forecast.Build(data, env.Today)
	if err != nil {
		return asFail(err)
	}
	unit := cliUnitAt(data, s.Start)
	if preplanning {
		prior := s.Clone()
		if err := env.askProductValues(data, fc, &s, "preplanned"); err != nil {
			return err
		}
		if !sameProducts(prior.Products, s.Products) {
			path, err := env.Repo().SaveSprint(key, &s)
			if err != nil {
				return asFail(err)
			}
			env.saved(path)
			if err := env.maybeCommit(key, []string{path},
				i18n.T("{team} {id}: PO pre-planning", "team", data.Team.Name, "id", s.ID), "", doCommit); err != nil {
				return err
			}
			if data, err = env.LoadTeam(key); err != nil {
				return err
			}
			if fc, err = forecast.Build(data, env.Today); err != nil {
				return asFail(err)
			}
		}
	}
	if entry := fc.Entry(s.ID); entry != nil {
		d := products.Distribute(fc, entry)
		distributionTable(&d, unit).Render(env.Out)
	}
	var entries []*forecast.TimelineEntry
	for i := range fc.Entries {
		if !fc.Entries[i].Sprint.Start.After(s.Start) {
			entries = append(entries, &fc.Entries[i])
		}
	}
	if len(entries) > history {
		entries = entries[len(entries)-history:]
	}
	var rows []products.Balance
	withMissing := false
	for _, b := range products.BalanceOf(fc, entries) {
		if b.Sprints > 0 { // only products with at least one value
			rows = append(rows, b)
			withMissing = withMissing || b.Missing > 0
		}
	}
	if len(rows) == 0 {
		return nil
	}
	l := i18n.Language()
	t := &Table{Title: i18n.P("Balance: Σ done − Σ standard"),
		Header: []string{i18n.T("Product"), i18n.T("Sprints"), i18n.T("Σ standard"), i18n.T("Σ done"), i18n.T("Balance")},
		Right:  []bool{false, true, true, true, true}}
	if withMissing {
		t.Header = append(t.Header, i18n.T("no value"))
		t.Right = append(t.Right, true)
	}
	for _, b := range rows {
		std, done, diff := b.Standard, b.Done, b.Difference()
		row := []string{textfmt.BlankControls(b.Product.Name), strconv.Itoa(b.Sprints),
			textfmt.FmtPtr(l, &std, 2), textfmt.FmtPtr(l, &done, 2), textfmt.FmtPtr(l, &diff, 2)}
		if withMissing {
			row = append(row, strconv.Itoa(b.Missing))
		}
		t.Add(row...)
	}
	t.Render(env.Out)
	if withMissing {
		env.Println(products.MissingFootnote())
	}
	return nil
}

// sameProducts reports whether two sets of product values are equal.
func sameProducts(a, b map[string]model.ProductValues) bool {
	if len(a) != len(b) {
		return false
	}
	for k, x := range a {
		y, ok := b[k]
		if !ok || !samePtr(x.Preplanned, y.Preplanned) || !samePtr(x.Planned, y.Planned) ||
			!samePtr(x.Done, y.Done) || !samePtr(x.ProductionPlanned, y.ProductionPlanned) ||
			!samePtr(x.ProductionDone, y.ProductionDone) {
			return false
		}
	}
	return true
}

func samePtr(a, b *float64) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

func productListCommand(env *Env) *cobra.Command {
	var doCommit bool
	cmd := &cobra.Command{
		Use:   "product-list TEAM",
		Short: i18n.T("Maintain the team's products (new, change PO, hand over)."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return runProductList(env, args[0], doCommit)
		},
	}
	teamArg(env, cmd)
	commitFlag(cmd, &doCommit)
	return cmd
}

func productTable(list []model.Product, withPO bool) *Table {
	t := &Table{Title: i18n.P("Products"), Header: []string{i18n.T("Name")}}
	if withPO {
		t.Header = append(t.Header, "PO")
	}
	t.Header = append(t.Header, i18n.T("from"), i18n.T("until"))
	dayOrDash := func(d *time.Time) string {
		if d == nil {
			return "–"
		}
		return day(*d)
	}
	for _, p := range list {
		row := []string{textfmt.BlankControls(p.Name)}
		if withPO {
			po := ""
			if p.PO != nil {
				po = textfmt.BlankControls(*p.PO)
			}
			row = append(row, po)
		}
		t.Add(append(row, dayOrDash(p.Start), dayOrDash(p.End))...)
	}
	return t
}

func runProductList(env *Env, key string, doCommit bool) error {
	data, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	if err := requireProducts(data, key); err != nil {
		return err
	}
	list := data.Products
	before := cloneData(data)
	before.Products = append([]model.Product(nil), data.Products...)
	withPO := data.Team.Features.PO
	changed := false
	for {
		productTable(list, withPO).Render(env.Out)
		label, choices := i18n.P("Action: n = new product, e = hand over product, q = done"), []string{"n", "e", "q"}
		if withPO {
			label = i18n.P("Action: n = new product, p = change PO, e = end product, q = done")
			choices = []string{"n", "p", "e", "q"}
		}
		action, err := env.AskChoice(label, choices, "q")
		if err != nil {
			return err
		}
		if action == "q" {
			break
		}
		if action == "n" {
			product, ok, err := askNewProduct(env, data, list, withPO)
			if err != nil {
				return err
			}
			if !ok {
				continue
			}
			list = append(list, product)
			data.Products = list
		} else {
			ok, err := changeProduct(env, list, action)
			if err != nil {
				return err
			}
			if !ok {
				continue
			}
		}
		changed = true
	}
	if !changed {
		return nil
	}
	after := *data
	after.Products = list
	if err := env.refuseInvalid(before, &after, "products.yaml"); err != nil {
		return err
	}
	path, err := env.Repo().SaveProducts(key, list)
	if err != nil {
		return asFail(err)
	}
	env.saved(path)
	return env.maybeCommit(key, []string{path}, i18n.T("{team}: product list updated", "team", data.Team.Name), "", doCommit)
}

func askNewProduct(env *Env, data *storage.TeamData, list []model.Product, withPO bool) (model.Product, bool, error) {
	raw, err := env.Ask(i18n.P("Name"), "")
	if err != nil {
		return model.Product{}, false, err
	}
	name := strings.TrimSpace(raw)
	ids := map[string]bool{}
	for _, p := range list {
		ids[p.ID] = true
		if strings.EqualFold(p.Name, name) {
			name = ""
		}
	}
	if name == "" {
		env.Println(i18n.P("Please enter a new, unique name."))
		return model.Product{}, false, nil
	}
	var po *string
	if withPO {
		raw, err := env.Ask(i18n.P("PO (empty = not specified)"), "")
		if err != nil {
			return model.Product{}, false, err
		}
		if v := strings.TrimSpace(raw); v != "" {
			po = &v
		}
	}
	start, err := env.AskDate(i18n.P("Handled from"), &env.Today)
	if err != nil {
		return model.Product{}, false, err
	}
	product := model.Product{ID: model.NewPersonID(name, ids, "produkt"), Name: name, PO: po, Start: &start}
	tentative := *data
	tentative.Products = append(append([]model.Product{}, list...), product)
	if env.reportNewErrors(data, &tentative, "products.yaml") {
		return model.Product{}, false, nil
	}
	return product, true, nil
}

// changeProduct changes the PO (action "p") or ends the handling (action "e") of a product.
func changeProduct(env *Env, list []model.Product, action string) (bool, error) {
	var current []*model.Product
	var names []string
	for i := range list {
		p := &list[i]
		if p.End == nil || !p.End.Before(env.Today) {
			current = append(current, p)
			names = append(names, p.Name)
		}
	}
	if len(current) == 0 {
		env.Println(i18n.P("No active products."))
		return false, nil
	}
	env.Println(i18n.P("Products") + ": " + textfmt.BlankControls(strings.Join(names, ", ")))
	raw, err := env.Ask(i18n.P("Name"), "")
	if err != nil {
		return false, err
	}
	raw = strings.ToLower(strings.TrimSpace(raw))
	var product *model.Product
	for _, p := range current {
		if strings.ToLower(p.Name) == raw {
			product = p
		}
	}
	if product == nil {
		env.Println(i18n.P("Product not found."))
		return false, nil
	}
	if action == "p" {
		old := ""
		if product.PO != nil {
			old = *product.PO
		}
		answer, err := env.Ask(i18n.P("New PO"), old)
		if err != nil {
			return false, err
		}
		product.PO = nil
		if v := strings.TrimSpace(answer); v != "" {
			product.PO = &v
		}
		return true, nil
	}
	end, err := env.AskDate(i18n.P("Last day handled"), &env.Today)
	if err != nil {
		return false, err
	}
	product.End = &end
	return true, nil
}
