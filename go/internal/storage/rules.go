package storage

import (
	"strconv"
	"strings"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/yamlx"
)

// textValue is _text_value: a value compared as text. An unquoted 2026.20 is read by YAML as the
// number 2026.2 and would silently match the wrong sprint: floats must be quoted.
func textValue(v any, where, name string) (string, error) {
	if f, ok := v.(float64); ok {
		return "", dataErr("{where}: {name}: please put {value} in quotes (otherwise digits are lost, e.g. \"2026.20\")",
			"where", where, "name", name, "value", pyStr(f))
	}
	return pyStr(v), nil
}

// ruleValue is _rule_value: leaf values are compared as text; YAML booleans become true/false.
func ruleValue(v any, where, name string) (string, error) {
	if b, ok := v.(bool); ok {
		return strconv.FormatBool(b), nil
	}
	return textValue(v, where, name)
}

func ruleNode(m *yamlx.Map, where string) (*model.Rule, error) {
	var entries []*model.Rule
	for _, e := range m.Entries {
		name := pyStr(e.Key)
		if isOperator(name) {
			items, err := sequence(e.Value, where, name)
			if err != nil {
				return nil, err
			}
			children := make([]*model.Rule, 0, len(items))
			for i, item := range items {
				sub, err := mapping(item, where, name+"["+strconv.Itoa(i)+"]")
				if err != nil {
					return nil, err
				}
				child, err := ruleNode(sub, where)
				if err != nil {
					return nil, err
				}
				children = append(children, child)
			}
			entries = append(entries, &model.Rule{Op: name, Children: children})
			continue
		}
		if _, isMap := e.Value.(*yamlx.Map); isMap {
			return nil, dataErr("{where}: '{name}' must be a list of values (entries with '- '), found {value}",
				"where", where, "name", name, "value", cut60(repr(e.Value)))
		}
		var values []string
		switch v := e.Value.(type) {
		case []any:
			for _, it := range v {
				s, err := ruleValue(it, where, name)
				if err != nil {
					return nil, err
				}
				values = append(values, s)
			}
		default:
			if !isEmptyText(v) {
				s, err := ruleValue(v, where, name)
				if err != nil {
					return nil, err
				}
				values = []string{s}
			}
		}
		base := strings.TrimSuffix(name, model.ContainsSuffix)
		contains := base != "" && base != name // rule fields may be configured: names stay open
		source := name
		if contains {
			source = base
		}
		entries = append(entries, &model.Rule{Op: model.OpLeaf, Source: source, Values: values, Contains: contains})
	}
	if len(entries) == 1 {
		return entries[0], nil // a single leaf, or the long form: exactly one of any/all/none
	}
	// Short form (several sources directly in the mapping, OR-combined). Mixed forms and
	// several operators in one mapping land here too; the validation reports them.
	return &model.Rule{Op: model.OpAny, Children: entries, Short: true}, nil
}

func isOperator(name string) bool {
	for _, op := range model.RuleOperators {
		if op == name {
			return true
		}
	}
	return false
}

// ruleFrom is _rule_from: an assignment rule; missing or empty = nil. Unknown sources are kept as
// leaves so that the validation can name them.
func ruleFrom(raw any, where string) (*model.Rule, error) {
	m, err := mapping(raw, where, "match")
	if err != nil {
		return nil, err
	}
	if len(m.Entries) == 0 {
		return nil, nil
	}
	return ruleNode(m, where)
}

func ruleKey(leaf *model.Rule) string {
	if leaf.Contains {
		return leaf.Source + model.ContainsSuffix
	}
	return leaf.Source
}

func ruleValuesTo(leaf *model.Rule) []any {
	out := make([]any, len(leaf.Values))
	for i, v := range leaf.Values {
		out[i] = v
		if leaf.Source == "in_sprint" { // written back as YAML booleans
			switch v {
			case "true":
				out[i] = true
			case "false":
				out[i] = false
			}
		}
	}
	return out
}

func ruleChildren(children []*model.Rule) []any {
	out := make([]any, len(children))
	for i, c := range children {
		out[i] = ruleTo(c)
	}
	return out
}

func ruleTo(r *model.Rule) *yamlx.Map {
	if r.Short {
		out := &yamlx.Map{}
		for _, c := range r.Children {
			if c.Op == model.OpLeaf {
				put(out, ruleKey(c), ruleValuesTo(c))
			} else {
				put(out, c.Op, ruleChildren(c.Children))
			}
		}
		return out
	}
	if r.Op == model.OpLeaf {
		return omap(ruleKey(r), ruleValuesTo(r))
	}
	return omap(r.Op, ruleChildren(r.Children))
}
