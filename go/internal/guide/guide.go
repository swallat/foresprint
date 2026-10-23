// Package guide holds the help texts (input fields, workflow, terms, commands) as data. The file
// data/guide.json was written from the Python version 0.8; the texts are
// English source texts that the program translates with the text catalogs.
package guide

import (
	_ "embed"
	"encoding/json"
)

// Field explains one input.
type Field struct {
	Key     string `json:"key"`
	Title   string `json:"title"`
	What    string `json:"what"`
	Source  string `json:"source"`
	Example string `json:"example"`
}

// Step is one step of the workflow.
type Step struct {
	When  string `json:"when"`
	Title string `json:"title"`
	Text  string `json:"text"`
	Page  string `json:"page"`
	CLI   string `json:"cli"`
}

// Pair is a term with its explanation, or a command with its purpose.
type Pair [2]string

// Topic is a help topic with its title.
type Topic struct{ Key, Title string }

type document struct {
	Fields          []Field     `json:"fields"`
	Workflow        []Step      `json:"workflow"`
	Terms           []Pair      `json:"terms"`
	GitHelp         []Pair      `json:"git_help"`
	CapacitySources []Pair      `json:"capacity_sources"`
	Commands        []Pair      `json:"commands"`
	Topics          [][2]string `json:"topics"`
}

//go:embed data/guide.json
var raw []byte

var doc = func() document {
	var d document
	if err := json.Unmarshal(raw, &d); err != nil {
		panic("guide: " + err.Error())
	}
	return d
}()

// Fields are the explained inputs in the order of the guide.
func Fields() []Field { return doc.Fields }

// FieldByKey returns an explained input.
func FieldByKey(key string) (Field, bool) {
	for _, f := range doc.Fields {
		if f.Key == key {
			return f, true
		}
	}
	return Field{}, false
}

// Workflow is the list of steps: what to do when.
func Workflow() []Step { return doc.Workflow }

// Terms are the terms with their explanation.
func Terms() []Pair { return doc.Terms }

// GitHelp are the Git terms with their explanation.
func GitHelp() []Pair { return doc.GitHelp }

// CapacitySources explain where the capacity of a sprint comes from.
func CapacitySources() []Pair { return doc.CapacitySources }

// Commands are the commands with their purpose, as the Python version lists them.
func Commands() []Pair { return doc.Commands }

// Topics are the help topics in order.
func Topics() []Topic {
	out := make([]Topic, len(doc.Topics))
	for i, t := range doc.Topics {
		out[i] = Topic{t[0], t[1]}
	}
	return out
}
