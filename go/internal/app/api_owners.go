package app

import (
	"errors"
	"time"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// ownersOf lists the POs of the team: the product_owners list, or, in a file from 0.8 where the
// product only names its PO, one entry per name in use (the name serves as the id).
func ownersOf(data *storage.TeamData, today time.Time) []OwnerDTO {
	out := []OwnerDTO{}
	count := func(ref string, po model.ProductOwner) int {
		n := 0
		for _, p := range data.Products {
			if p.PO == nil {
				continue
			}
			if *p.PO == ref || *p.PO == po.Name {
				n++
			}
		}
		return n
	}
	if len(data.Team.ProductOwners) == 0 {
		seen := map[string]bool{}
		for _, p := range data.Products {
			if p.PO == nil || *p.PO == "" || seen[*p.PO] {
				continue
			}
			seen[*p.PO] = true
			out = append(out, OwnerDTO{ID: *p.PO, Name: *p.PO, Products: count(*p.PO, model.ProductOwner{Name: *p.PO})})
		}
		return out
	}
	for _, po := range data.Team.ProductOwners {
		d := OwnerDTO{ID: po.ID, Name: po.Name, Products: count(po.ID, po)}
		if po.Person != nil {
			d.Person = *po.Person
			for _, p := range data.People {
				if p.ID == *po.Person {
					if f := p.FTEOn(today); f > 0 {
						d.InTeam, d.FTE = true, f
					}
				}
			}
		}
		out = append(out, d)
	}
	return out
}

// migrateOwners turns the plain PO names of a file from 0.8 into the list product_owners and
// the ids into the products. It changes data in memory; the caller writes it.
func migrateOwners(data *storage.TeamData) {
	if len(data.Team.ProductOwners) > 0 {
		return
	}
	taken := map[string]bool{}
	byName := map[string]string{}
	for _, p := range data.Products {
		if p.PO == nil || *p.PO == "" {
			continue
		}
		if _, ok := byName[*p.PO]; ok {
			continue
		}
		id := model.NewPersonID(*p.PO, taken, "po")
		taken[id] = true
		byName[*p.PO] = id
		data.Team.ProductOwners = append(data.Team.ProductOwners, model.ProductOwner{ID: id, Name: *p.PO})
	}
	for i, p := range data.Products {
		if p.PO != nil {
			if id, ok := byName[*p.PO]; ok {
				data.Products[i].PO = &id
			}
		}
	}
}

func (a *API) saveOwners(team string, data *storage.TeamData) error {
	repo := storage.NewRepository(a.DataDir())
	if _, err := repo.SaveTeam(data.Team); err != nil {
		return err
	}
	_, err := repo.SaveProducts(team, data.Products)
	return err
}

func ownerFiles(a *API, team string) []string {
	return []string{a.teamFile(team, "team.yaml"), a.teamFile(team, "products.yaml"), a.teamFile(team, "people.yaml")}
}

// AddOwner adds a PO who is outside the team and its capacity.
func (a *API) AddOwner(team, name string) (Step, error) {
	name = trimSpace(name)
	if name == "" {
		return Step{}, errors.New(i18n.T("Every person needs a name."))
	}
	data, err := a.loadTeam(team)
	if err != nil {
		return Step{}, err
	}
	token := a.remember(team, ownerFiles(a, team)...)
	migrateOwners(data)
	taken := map[string]bool{}
	for _, po := range data.Team.ProductOwners {
		taken[po.ID] = true
	}
	data.Team.ProductOwners = append(data.Team.ProductOwners, model.ProductOwner{ID: model.NewPersonID(name, taken, "po"), Name: name})
	if err := a.saveOwners(team, data); err != nil {
		return Step{}, err
	}
	return Step{View: a.productsView(data), Undo: token}, nil
}

// RenameOwner renames a PO. Minutes and history keep the old name.
func (a *API) RenameOwner(team, id, name string) (Step, error) {
	name = trimSpace(name)
	if name == "" {
		return Step{}, errors.New(i18n.T("Every person needs a name."))
	}
	data, err := a.loadTeam(team)
	if err != nil {
		return Step{}, err
	}
	token := a.remember(team, ownerFiles(a, team)...)
	// A legacy PO is named by its name; the first edit migrates, the id is looked up by the old name.
	oldName := id
	migrateOwners(data)
	found := false
	for i, po := range data.Team.ProductOwners {
		if po.ID == id || po.Name == oldName {
			data.Team.ProductOwners[i].Name = name
			found = true
			break
		}
	}
	if !found {
		return Step{}, errors.New(i18n.T("Unknown PO '{id}'.", "id", id))
	}
	if err := a.saveOwners(team, data); err != nil {
		return Step{}, err
	}
	return Step{View: a.productsView(data), Undo: token}, nil
}

// RemoveOwner removes a PO. Their products go to other POs first: handover maps each product id
// to the id of the new PO. A PO who works in the team stays in the team as a person.
func (a *API) RemoveOwner(team, id string, handover map[string]string) (Step, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return Step{}, err
	}
	token := a.remember(team, ownerFiles(a, team)...)
	oldName := id
	migrateOwners(data)
	idx := -1
	for i, po := range data.Team.ProductOwners {
		if po.ID == id || po.Name == oldName {
			idx = i
		}
	}
	if idx < 0 {
		return Step{}, errors.New(i18n.T("Unknown PO '{id}'.", "id", id))
	}
	if len(data.Team.ProductOwners) < 2 {
		return Step{}, errors.New(i18n.T("The only PO cannot be removed."))
	}
	gone := data.Team.ProductOwners[idx]
	for i, p := range data.Products {
		if p.PO == nil || *p.PO != gone.ID {
			continue
		}
		to := handover[p.ID]
		known := false
		for _, po := range data.Team.ProductOwners {
			known = known || (po.ID == to && po.ID != gone.ID)
		}
		if !known {
			return Step{}, errors.New(i18n.T("Say who takes over {name}.", "name", p.Name))
		}
		data.Products[i].PO = &to
	}
	data.Team.ProductOwners = append(data.Team.ProductOwners[:idx:idx], data.Team.ProductOwners[idx+1:]...)
	if err := a.saveOwners(team, data); err != nil {
		return Step{}, err
	}
	return Step{View: a.productsView(data), Undo: token}, nil
}

// SetOwnerInTeam makes a PO work in the team with a share (decision 11), or stop doing so. The
// PO then is a person with membership periods like everybody else.
func (a *API) SetOwnerInTeam(team, id string, inTeam bool, fte float64) (Step, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return Step{}, err
	}
	if inTeam && !(fte > 0 && fte <= 1) {
		return Step{}, errors.New(i18n.T("The share must be between 0.1 and 1.0."))
	}
	token := a.remember(team, ownerFiles(a, team)...)
	oldName := id
	migrateOwners(data)
	idx := -1
	for i, po := range data.Team.ProductOwners {
		if po.ID == id || po.Name == oldName {
			idx = i
		}
	}
	if idx < 0 {
		return Step{}, errors.New(i18n.T("Unknown PO '{id}'.", "id", id))
	}
	po := &data.Team.ProductOwners[idx]
	today := a.day()
	personIdx := -1
	if po.Person != nil {
		for i, p := range data.People {
			if p.ID == *po.Person {
				personIdx = i
			}
		}
	}
	switch {
	case inTeam && personIdx < 0:
		taken := map[string]bool{}
		for _, p := range data.People {
			taken[p.ID] = true
		}
		pid := model.NewPersonID(po.Name, taken, "person")
		data.People = append(data.People, model.Person{ID: pid, Name: po.Name, Kind: model.KindMember, Memberships: []model.Membership{{Start: today, FTE: fte}}})
		po.Person = &pid
	case inTeam:
		p := &data.People[personIdx]
		last := &p.Memberships[len(p.Memberships)-1]
		switch {
		case last.End == nil || !last.End.Before(today):
			last.End = nil
			last.FTE = fte // the share of the running period
		default:
			p.Memberships = append(p.Memberships, model.Membership{Start: today, FTE: fte})
		}
	case personIdx >= 0:
		p := &data.People[personIdx]
		last := &p.Memberships[len(p.Memberships)-1]
		switch {
		case !last.Start.Before(today) && len(p.Memberships) == 1:
			// Started today or later and has no history: the person is simply taken out again.
			data.People = append(data.People[:personIdx:personIdx], data.People[personIdx+1:]...)
			po.Person = nil
		case last.End == nil || !last.End.Before(today):
			end := today.AddDate(0, 0, -1)
			if end.Before(last.Start) {
				end = last.Start
			}
			last.End = &end
		}
	}
	repo := storage.NewRepository(a.DataDir())
	if _, err := repo.SavePeople(team, data.People); err != nil {
		return Step{}, err
	}
	if err := a.saveOwners(team, data); err != nil {
		return Step{}, err
	}
	return Step{View: a.productsView(data), Undo: token}, nil
}
