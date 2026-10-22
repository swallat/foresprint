package validate

import (
	"strings"

	"github.com/swallat/foresprint/internal/rules"
)

// RuleProblems explains why an assignment rule is invalid: unknown sources, leaves without
// values, operators without conditions, short and long form mixed. Empty = valid.
func RuleProblems(rule *rules.Rule, sources []string) []string {
	var problems []string
	var walk func(n *rules.Rule)
	walk = func(n *rules.Rule) {
		if n.Op == rules.OpLeaf {
			known := false
			for _, s := range sources {
				if s == n.Source {
					known = true
				}
			}
			if !known {
				problems = append(problems, msg("unknown source '{source}' (allowed: {allowed})",
					"source", n.Source, "allowed", strings.Join(sources, ", ")))
			}
			if len(n.Values) == 0 {
				problems = append(problems, msg("'{source}' without values (empty list)", "source", n.Source))
			}
			return
		}
		if n.Short {
			for _, c := range n.Children {
				if c.Op != rules.OpLeaf {
					problems = append(problems, msg("Short and long form mixed: any, all and none each stand alone, not next to sources or next to each other"))
					break
				}
			}
		}
		if len(n.Children) == 0 {
			if n.Short {
				problems = append(problems, msg("no condition"))
			} else {
				problems = append(problems, msg("'{op}' without conditions", "op", n.Op))
			}
		}
		for _, c := range n.Children {
			walk(c)
		}
	}
	walk(rule)
	return problems
}

// Dependency is a ticket with the keys it depends on.
type Dependency struct {
	Key       string
	DependsOn []string
}

// FindCycles finds cycles in depends_on (keys in dependency order, rotated to start with the
// smallest key), each reported once. Dependencies on keys outside the list are ignored.
func FindCycles(tickets []Dependency) [][]string {
	graph := map[string][]string{}
	var order []string
	for _, t := range tickets {
		if _, ok := graph[t.Key]; !ok {
			order = append(order, t.Key)
		}
		graph[t.Key] = nil
	}
	for _, t := range tickets {
		var deps []string
		for _, d := range t.DependsOn {
			if _, ok := graph[d]; ok {
				deps = append(deps, d)
			}
		}
		graph[t.Key] = deps
	}
	state := map[string]int{} // 1 = on the current path, 2 = finished
	var cycles [][]string
	seen := map[string]bool{}
	type frame struct {
		deps []string
		next int
	}
	for _, start := range order {
		if state[start] != 0 {
			continue
		}
		state[start] = 1
		path := []string{start}
		stack := []*frame{{deps: graph[start]}}
		for len(stack) > 0 {
			top := stack[len(stack)-1]
			advanced := false
			for top.next < len(top.deps) {
				nxt := top.deps[top.next]
				top.next++
				switch state[nxt] {
				case 1: // back edge: the path from nxt onwards is a cycle
					i := 0
					for path[i] != nxt {
						i++
					}
					cycle := path[i:]
					first := 0
					for j, k := range cycle {
						if k < cycle[first] {
							first = j
						}
					}
					canon := append(append([]string{}, cycle[first:]...), cycle[:first]...)
					if id := strings.Join(canon, "\x00"); !seen[id] {
						seen[id] = true
						cycles = append(cycles, canon)
					}
				case 0:
					state[nxt] = 1
					path = append(path, nxt)
					stack = append(stack, &frame{deps: graph[nxt]})
					advanced = true
				}
				if advanced {
					break
				}
			}
			if !advanced {
				state[path[len(path)-1]] = 2
				path = path[:len(path)-1]
				stack = stack[:len(stack)-1]
			}
		}
	}
	return cycles
}
