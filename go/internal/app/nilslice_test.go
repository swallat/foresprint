package app

import (
	"fmt"
	"os/exec"
	"reflect"
	"strings"
	"testing"

	"github.com/zalando/go-keyring"
)

// nilLists walks a value the way encoding/json would and reports every nil slice: it becomes
// JSON null, and the window reads .length of it. Every list in an answer must be empty, not nil.
func nilLists(v reflect.Value, path string, out *[]string) {
	switch v.Kind() {
	case reflect.Pointer, reflect.Interface:
		if !v.IsNil() {
			nilLists(v.Elem(), path, out)
		}
	case reflect.Struct:
		for i := range v.NumField() {
			f := v.Type().Field(i)
			tag := f.Tag.Get("json")
			if f.IsExported() && tag != "-" {
				if strings.Contains(tag, "omitempty") && v.Field(i).Kind() == reflect.Slice && v.Field(i).IsNil() {
					continue // left out of the JSON, the window reads it as undefined
				}
				nilLists(v.Field(i), path+"."+f.Name, out)
			}
		}
	case reflect.Slice:
		if v.IsNil() {
			*out = append(*out, path)
			return
		}
		for i := range v.Len() {
			nilLists(v.Index(i), fmt.Sprintf("%s[%d]", path, i), out)
		}
	case reflect.Map:
		if v.IsNil() {
			return // a map is an object ({} or null); the window reads keys with ?? and Object.entries
		}
		for _, k := range v.MapKeys() {
			nilLists(v.MapIndex(k), fmt.Sprintf("%s[%v]", path, k), out)
		}
	}
}

func assertNoNilLists(t *testing.T, what string, answer any) {
	t.Helper()
	var bad []string
	nilLists(reflect.ValueOf(answer), what, &bad)
	for _, p := range bad {
		t.Errorf("%s is a nil list (JSON null)", p)
	}
}

func TestPlanAnswersHaveNoNilLists(t *testing.T) {
	api, team := planTeam(t)
	sprints, err := api.Sprints(team)
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range sprints {
		v, err := api.PlanSprint(team, s.ID, nil)
		if err != nil {
			continue
		}
		assertNoNilLists(t, "PlanSprint("+s.ID+")", v)
		if r, err := api.RunningTickets(team, s.ID); err == nil {
			assertNoNilLists(t, "RunningTickets("+s.ID+")", r)
		}
		as := Assumption{Label: "A"}
		if w, err := api.WhatIf(team, s.ID, as); err == nil {
			assertNoNilLists(t, "WhatIf("+s.ID+")", w)
		}
		if p, err := api.PlanWritePreview(team, s.ID); err == nil {
			assertNoNilLists(t, "PlanWritePreview("+s.ID+")", p)
		}
	}
}

// TestReadAnswersHaveNoNilLists calls the read methods of the API with the demo team and with
// an empty team and checks that no list in an answer is nil (JSON null). New read methods go
// into readCalls.
func TestReadAnswersHaveNoNilLists(t *testing.T) {
	keyring.MockInit() // the tracker settings probe the keychain of the system
	api, team := planTeam(t)
	// The data folder is a Git repository, so that the methods of the storage area answer.
	for _, args := range [][]string{{"init", "-q"}, {"-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "start"}} {
		cmd := exec.Command("git", args...)
		cmd.Dir = api.DataDir()
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	sprints, _ := api.Sprints(team)
	var future, past string
	for _, s := range sprints {
		if s.State == "future" && future == "" {
			future = s.ID
		}
		if s.State == "past" {
			past = s.ID
		}
	}
	// A saved assumption without a carried ticket and a frozen plan reach the answers as well.
	if err := api.SaveAssumption(team, future, Assumption{Label: "A"}); err != nil {
		t.Fatal(err)
	}
	// A new team has no tickets, people, products or projects yet.
	fresh, err := api.SetupCreateTeam(NewTeam{Name: "Fresh", Country: "DE", FirstSprintID: "2026.1", FirstStart: "2026-10-12", Source: SourceNone})
	if err != nil {
		t.Fatal(err)
	}
	freshSprint := "2026.1"
	calls := map[string][]any{
		"Backlog": {team}, "Calendar": {team, 6}, "Forecast": {team}, "ForecastProducts": {team},
		"People": {team}, "AbsencePeriods": {team}, "Products": {team}, "Projects": {team},
		"TeamSettings": {team}, "TeamFeatures": {team}, "AbsenceGrid": {team, "", 6},
		"SprintPrepare": {team, future}, "SprintOverview": {team, 4}, "SprintReview": {team, past},
		"SprintMinutes": {team, future}, "Today": {team}, "TrackerSettings": {team},
		"TrackerInfo": {team}, "Sprints": {team}, "PlanSprint": {team, future, (*Assumption)(nil)},
		"RunningTickets": {team, future}, "PlanWritePreview": {team, future},
		"Teams": {}, "Prefs": {}, "Info": {}, "Storage": {}, "Conflicts": {}, "DataIncoming": {},
		"PendingTags": {}, "UnsavedChanges": {},
	}
	for _, target := range []struct {
		name string
		api  *API
		team string
	}{{"demo", api, team}, {"fresh", api, fresh.Key}} {
		for name, args := range calls {
			m := reflect.ValueOf(target.api).MethodByName(name)
			if !m.IsValid() {
				t.Fatalf("API has no method %s", name)
			}
			in := make([]reflect.Value, len(args))
			for i, a := range args {
				if s, ok := a.(string); ok && s == team && target.team != team {
					a = target.team
				} else if ok && s == future && target.team != team {
					a = freshSprint
				} else if ok && s == past && target.team != team {
					a = freshSprint
				}
				in[i] = reflect.ValueOf(a)
			}
			out := m.Call(in)
			if n := len(out); n > 0 && out[n-1].Type().Implements(reflect.TypeFor[error]()) && !out[n-1].IsNil() {
				if target.name == "demo" {
					t.Errorf("demo: %s was rejected: %v (the demo team must answer)", name, out[n-1].Interface())
				}
				continue // a rejected call carries no answer
			}
			for i, o := range out {
				if o.Type().Implements(reflect.TypeFor[error]()) {
					continue
				}
				assertNoNilLists(t, fmt.Sprintf("%s: %s result %d", target.name, name, i), o.Interface())
			}
		}
	}
}
