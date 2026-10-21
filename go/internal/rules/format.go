package rules

import "strings"

func quote(value string) string {
	if value != "" && !isKeyword(value) && !strings.ContainsFunc(value, func(r rune) bool {
		return isSpace(r) || strings.ContainsRune(`=!~(),"`, r)
	}) {
		return value
	}
	return `"` + strings.NewReplacer(`\`, `\\`, `"`, `\"`).Replace(value) + `"`
}

func quoteAll(values []string) string {
	q := make([]string, len(values))
	for i, v := range values {
		q[i] = quote(v)
	}
	return strings.Join(q, ", ")
}

func leafText(leaf *Rule) string {
	if leaf.Contains {
		parts := make([]string, len(leaf.Values))
		for i, v := range leaf.Values {
			parts[i] = leaf.Source + " ~ " + quote(v)
		}
		if len(parts) == 1 {
			return parts[0]
		}
		return "(" + strings.Join(parts, " OR ") + ")"
	}
	if len(leaf.Values) == 1 {
		return leaf.Source + " = " + quote(leaf.Values[0])
	}
	return leaf.Source + " IN (" + quoteAll(leaf.Values) + ")"
}

// FormatRule is the expression of a rule (empty text for no rule); ParseRule reads it back into
// an equal-meaning rule.
func FormatRule(rule *Rule) string {
	if rule == nil {
		return ""
	}
	return format(rule, true)
}

func format(rule *Rule, top bool) string {
	switch rule.Op {
	case OpLeaf:
		return leafText(rule)
	case OpNone:
		inner := rule.Children
		if len(inner) == 1 && inner[0].Op == OpLeaf {
			leaf := inner[0]
			if leaf.Contains && len(leaf.Values) == 1 {
				return leaf.Source + " !~ " + quote(leaf.Values[0])
			}
			if !leaf.Contains && len(leaf.Values) == 1 {
				return leaf.Source + " != " + quote(leaf.Values[0])
			}
			if !leaf.Contains {
				return leaf.Source + " NOT IN (" + quoteAll(leaf.Values) + ")"
			}
		}
		var body string
		if len(inner) == 1 {
			body = format(inner[0], true)
		} else {
			parts := make([]string, len(inner))
			for i, c := range inner {
				parts[i] = format(c, false)
			}
			body = strings.Join(parts, " OR ")
		}
		return "NOT (" + body + ")"
	}
	joiner := " OR "
	if rule.Op == OpAll {
		joiner = " AND "
	}
	parts := make([]string, len(rule.Children))
	for i, c := range rule.Children {
		parts[i] = format(c, false)
	}
	text := strings.Join(parts, joiner)
	if top || len(parts) == 1 {
		return text
	}
	return "(" + text + ")"
}
