package yamlx

import (
	"errors"
	"fmt"
	"io"
	"math"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

// Load reads a YAML document the way PyYAML's SafeLoader (YAML 1.1) does and returns the values
// of the package doc: *Map (keys in order of their first appearance, equal keys like Python's
// 1 == True == 1.0 are one key), []any, nil, bool, int64 (*big.Int beyond), float64, string,
// Date and time.Time. A text without a document gives nil. Timestamps with a zone other than
// "no zone" carry their offset; a timestamp without a zone has location time.UTC, one with "Z"
// has a fixed zone of offset 0, so the two stay apart as they do in Python.
//
// Known differences from PyYAML (the Foresprint files never need them): recursive structures and
// the tags !!binary, !!set, !!omap and !!pairs are errors; explicit tags are stricter (no white
// space or signs inside !!int/!!float values, no !!value or bare "!" tags); a duplicate anchor
// is accepted; and yaml.v3 differs from libyaml in a few exotic spellings (the escape "\/",
// "?" inside plain scalars of a flow collection, a trailing ":" in a flow collection).
func Load(text string) (any, error) {
	dec := yaml.NewDecoder(strings.NewReader(NormalizeDirective(text)))
	var doc yaml.Node
	if err := dec.Decode(&doc); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, nil
		}
		return nil, err
	}
	var extra yaml.Node
	if err := dec.Decode(&extra); err == nil {
		return nil, errors.New("expected a single document in the stream")
	} else if !errors.Is(err, io.EOF) {
		return nil, err
	}
	if doc.Kind != yaml.DocumentNode || len(doc.Content) == 0 {
		return nil, nil
	}
	l := &loader{done: map[*yaml.Node]any{}, active: map[*yaml.Node]bool{}, flattening: map[*yaml.Node]bool{}}
	return l.construct(doc.Content[0])
}

type loader struct {
	flattening map[*yaml.Node]bool
	done       map[*yaml.Node]any
	active     map[*yaml.Node]bool
}

// Names of the tags of a node ("!!str" and the like).
// reDirective finds a "%YAML 1.2" line: PyYAML accepts 1.1 and 1.2, yaml.v3 only 1.1.
var reDirective = regexp.MustCompile(`^(%YAML[ \t]+)1\.2\b`)

// NormalizeDirective makes a "%YAML 1.x" directive acceptable to yaml.v3.
func NormalizeDirective(text string) string {
	if !strings.HasPrefix(strings.TrimLeft(text, "\ufeff"), "%") && !strings.Contains(text[:min(len(text), 2000)], "\n%") {
		return text
	}
	lines := strings.SplitAfter(text, "\n")
	for i, line := range lines {
		t := strings.TrimLeft(line, "\ufeff")
		switch {
		case strings.HasPrefix(t, "%"):
			lines[i] = reDirective.ReplaceAllString(t, "${1}1.1")
		case strings.HasPrefix(t, "#") || strings.TrimSpace(t) == "":
		default:
			return strings.Join(lines, "")
		}
	}
	return strings.Join(lines, "")
}

func shortTag(n *yaml.Node) string {
	t := n.Tag
	if strings.HasPrefix(t, "tag:yaml.org,2002:") {
		return "!!" + strings.TrimPrefix(t, "tag:yaml.org,2002:")
	}
	return t
}

func (l *loader) construct(n *yaml.Node) (any, error) {
	if n.Kind == yaml.AliasNode {
		return l.construct(n.Alias)
	}
	if v, ok := l.done[n]; ok {
		return v, nil
	}
	if l.active[n] {
		return nil, errors.New("recursive structures are not supported")
	}
	l.active[n] = true
	defer delete(l.active, n)
	var (
		v   any
		err error
	)
	switch n.Kind {
	case yaml.ScalarNode:
		v, err = l.scalar(n)
	case yaml.SequenceNode:
		if tag := shortTag(n); n.Style&yaml.TaggedStyle != 0 && tag != "!!seq" {
			return nil, fmt.Errorf("could not determine a constructor for the tag %s", tag)
		}
		items := make([]any, 0, len(n.Content))
		for _, c := range n.Content {
			x, err := l.construct(c)
			if err != nil {
				return nil, err
			}
			items = append(items, x)
		}
		v = items
	case yaml.MappingNode:
		if tag := shortTag(n); n.Style&yaml.TaggedStyle != 0 && tag != "!!map" {
			return nil, fmt.Errorf("could not determine a constructor for the tag %s", tag)
		}
		v, err = l.mapping(n)
	default:
		err = errors.New("unexpected node")
	}
	if err != nil {
		return nil, err
	}
	l.done[n] = v
	return v, nil
}

type pair struct{ key, value *yaml.Node }

func target(n *yaml.Node) *yaml.Node {
	for n.Kind == yaml.AliasNode {
		n = n.Alias
	}
	return n
}

// IsMergeKey reports whether a mapping key node is the merge key "<<".
func IsMergeKey(k *yaml.Node) bool { return isMergeKey(k) }

func isMergeKey(k *yaml.Node) bool {
	k = target(k)
	if k.Kind != yaml.ScalarNode {
		return false
	}
	if k.Style&yaml.TaggedStyle != 0 {
		return shortTag(k) == "!!merge"
	}
	return k.Style&(yaml.DoubleQuotedStyle|yaml.SingleQuotedStyle|yaml.LiteralStyle|yaml.FoldedStyle) == 0 && k.Value == "<<"
}

// flatten returns the pairs of a mapping with the merged ones first (SafeConstructor.flatten_mapping).
func (l *loader) flatten(n *yaml.Node, depth int) ([]pair, error) {
	l.flattening[n] = true
	defer delete(l.flattening, n)
	var merge, explicit []pair
	for i := 0; i+1 < len(n.Content); i += 2 {
		k, v := n.Content[i], n.Content[i+1]
		if !isMergeKey(k) {
			explicit = append(explicit, pair{k, v})
			continue
		}
		v = target(v)
		switch v.Kind {
		case yaml.MappingNode:
			if l.flattening[v] {
				continue
			}
			sub, err := l.flatten(v, depth+1)
			if err != nil {
				return nil, err
			}
			merge = append(merge, sub...)
		case yaml.SequenceNode:
			var subs [][]pair
			for _, item := range v.Content {
				item = target(item)
				if item.Kind != yaml.MappingNode {
					return nil, errors.New("expected a mapping for merging, but found " + kindName(item))
				}
				if l.flattening[item] {
					continue
				}
				sub, err := l.flatten(item, depth+1)
				if err != nil {
					return nil, err
				}
				subs = append(subs, sub)
			}
			for i := len(subs) - 1; i >= 0; i-- {
				merge = append(merge, subs[i]...)
			}
		default:
			return nil, errors.New("expected a mapping or list of mappings for merging, but found " + kindName(v))
		}
	}
	return append(merge, explicit...), nil
}

func kindName(n *yaml.Node) string {
	switch n.Kind {
	case yaml.ScalarNode:
		return "scalar"
	case yaml.SequenceNode:
		return "sequence"
	case yaml.MappingNode:
		return "mapping"
	}
	return "node"
}

func (l *loader) mapping(n *yaml.Node) (any, error) {
	pairs, err := l.flatten(n, 0)
	if err != nil {
		return nil, err
	}
	m := &Map{}
	index := map[string]int{}
	for _, p := range pairs {
		var key any
		kn := target(p.key)
		if kn.Kind == yaml.ScalarNode && kn.Style&yaml.TaggedStyle == 0 && kn.Style&(yaml.DoubleQuotedStyle|yaml.SingleQuotedStyle|yaml.LiteralStyle|yaml.FoldedStyle) == 0 && kn.Value == "=" {
			key = "=" // the value tag of a key is read as a string
		} else {
			key, err = l.construct(p.key)
			if err != nil {
				return nil, err
			}
		}
		switch key.(type) {
		case *Map, []any:
			return nil, errors.New("found unhashable key")
		}
		value, err := l.construct(p.value)
		if err != nil {
			return nil, err
		}
		canon := CanonicalKey(key)
		if i, ok := index[canon]; ok {
			m.Entries[i].Value = value
			continue
		}
		index[canon] = len(m.Entries)
		m.Entries = append(m.Entries, MapEntry{key, value})
	}
	return m, nil
}

// CanonicalKey is the identity of a key under Python equality: 1, True and 1.0 are one key; a
// NaN is never equal to anything.
func CanonicalKey(k any) string {
	switch v := k.(type) {
	case nil:
		return "n"
	case bool:
		if v {
			return "i1"
		}
		return "i0"
	case int64:
		return "i" + strconv.FormatInt(v, 10)
	case *big.Int:
		return "i" + v.String()
	case float64:
		switch {
		case math.IsNaN(v):
			return "nan" // PyYAML hands out one shared NaN object, so NaN keys are equal
		case math.IsInf(v, 0):
			return "f" + strconv.FormatFloat(v, 'g', -1, 64)
		case v == math.Trunc(v):
			i, _ := new(big.Float).SetFloat64(v).Int(nil)
			return "i" + i.String()
		}
		return "f" + strconv.FormatFloat(v, 'x', -1, 64)
	case string:
		return "s" + v
	case Date:
		return "d" + time.Time(v).Format("2006-01-02")
	case time.Time:
		return "t" + strconv.FormatBool(v.Location() == time.UTC) + v.UTC().Format(time.RFC3339Nano)
	}
	return fmt.Sprintf("?%T%v", k, k)
}

// --- scalars --------------------------------------------------------------------------------

var (
	reBool  = regexp.MustCompile(`^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$`)
	reFloat = regexp.MustCompile(`^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$`)
	reInt   = regexp.MustCompile(`^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$`)
	reTime  = regexp.MustCompile(`^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$`)
	reStamp = regexp.MustCompile(`^([0-9][0-9][0-9][0-9])-([0-9][0-9]?)-([0-9][0-9]?)(?:(?:[Tt]|[ \t]+)([0-9][0-9]?):([0-9][0-9]):([0-9][0-9])(?:\.([0-9]*))?(?:[ \t]*(Z|([-+])([0-9][0-9]?)(?::([0-9][0-9]))?))?)?$`)
)

// ResolveTag is the tag PyYAML's resolver gives a plain scalar without an explicit tag
// ("!!null", "!!bool", "!!int", "!!float", "!!timestamp", "!!merge", "!!value" or "!!str").
func ResolveTag(value string) string {
	first := byte(0)
	if value != "" {
		first = value[0]
	}
	has := func(chars string) bool { return value != "" && strings.IndexByte(chars, first) >= 0 }
	switch {
	case has("yYnNtTfFoO") && reBool.MatchString(value):
		return "!!bool"
	case has("-+0123456789.") && reFloat.MatchString(value):
		return "!!float"
	case has("-+0123456789") && reInt.MatchString(value):
		return "!!int"
	case first == '<' && value == "<<":
		return "!!merge"
	case (value == "" || has("~nN")) && isNull(value):
		return "!!null"
	case has("0123456789") && reTime.MatchString(value):
		return "!!timestamp"
	case first == '=' && value == "=":
		return "!!value"
	}
	return "!!str"
}

func isNull(v string) bool {
	switch v {
	case "~", "null", "Null", "NULL", "":
		return true
	}
	return false
}

// ScalarTag is the tag PyYAML gives a scalar node: the explicit one, "!!str" for quoted and block
// scalars, else the one of the implicit resolver.
func ScalarTag(n *yaml.Node) string {
	switch {
	case n.Style&yaml.TaggedStyle != 0:
		return shortTag(n)
	case n.Style&(yaml.DoubleQuotedStyle|yaml.SingleQuotedStyle|yaml.LiteralStyle|yaml.FoldedStyle) != 0:
		return "!!str"
	}
	return ResolveTag(n.Value)
}

// Scalar is the value of a scalar node (see Load).
func Scalar(n *yaml.Node) (any, error) { return (&loader{}).scalar(n) }

func (l *loader) scalar(n *yaml.Node) (any, error) {
	tag := ScalarTag(n)
	v := n.Value
	switch tag {
	case "!!null":
		return nil, nil
	case "!!bool":
		switch strings.ToLower(v) {
		case "yes", "true", "on":
			return true, nil
		case "no", "false", "off":
			return false, nil
		}
		return nil, fmt.Errorf("invalid boolean %q", v)
	case "!!int":
		return constructInt(v)
	case "!!float":
		return constructFloat(v)
	case "!!timestamp":
		return constructTimestamp(v)
	case "!!str", "!":
		return v, nil
	}
	return nil, fmt.Errorf("could not determine a constructor for the tag %s", tag)
}

func constructInt(raw string) (any, error) {
	value := strings.ReplaceAll(raw, "_", "")
	if value == "" {
		return nil, errors.New("invalid integer")
	}
	sign := int64(1)
	if value[0] == '-' {
		sign = -1
	}
	if value[0] == '+' || value[0] == '-' {
		value = value[1:]
	}
	parse := func(s string, base int) (any, error) {
		n, ok := new(big.Int).SetString(s, base)
		if !ok || s == "" || strings.ContainsAny(s, "+-") {
			return nil, fmt.Errorf("invalid integer %q", raw)
		}
		if sign < 0 {
			n.Neg(n)
		}
		if n.IsInt64() {
			return n.Int64(), nil
		}
		return n, nil
	}
	switch {
	case value == "0":
		return int64(0), nil
	case strings.HasPrefix(value, "0b"):
		return parse(value[2:], 2)
	case strings.HasPrefix(value, "0x"):
		return parse(value[2:], 16)
	case value != "" && value[0] == '0':
		return parse(strings.TrimPrefix(value, "0o"), 8)
	case strings.Contains(value, ":"):
		total, base := new(big.Int), big.NewInt(1)
		parts := strings.Split(value, ":")
		for i := len(parts) - 1; i >= 0; i-- {
			d, ok := new(big.Int).SetString(parts[i], 10)
			if !ok {
				return nil, fmt.Errorf("invalid integer %q", raw)
			}
			total.Add(total, new(big.Int).Mul(d, base))
			base.Mul(base, big.NewInt(60))
		}
		if sign < 0 {
			total.Neg(total)
		}
		if total.IsInt64() {
			return total.Int64(), nil
		}
		return total, nil
	}
	return parse(value, 10)
}

func constructFloat(raw string) (any, error) {
	value := strings.ToLower(strings.ReplaceAll(raw, "_", ""))
	if value == "" {
		return nil, errors.New("invalid float")
	}
	sign := 1.0
	if value[0] == '-' {
		sign = -1
	}
	if value[0] == '+' || value[0] == '-' {
		value = value[1:]
	}
	switch {
	case value == ".inf":
		return sign * math.Inf(1), nil
	case value == ".nan":
		return math.NaN(), nil
	case strings.Contains(value, ":"):
		parts := strings.Split(value, ":")
		total, base := 0.0, 1.0
		for i := len(parts) - 1; i >= 0; i-- {
			d, err := strconv.ParseFloat(parts[i], 64)
			if err != nil && !errors.Is(err, strconv.ErrRange) {
				return nil, fmt.Errorf("invalid float %q", raw)
			}
			total += d * base
			base *= 60
		}
		return sign * total, nil
	}
	f, err := strconv.ParseFloat(value, 64)
	if err != nil && !errors.Is(err, strconv.ErrRange) {
		return nil, fmt.Errorf("invalid float %q", raw)
	}
	return sign * f, nil
}

func constructTimestamp(v string) (any, error) {
	m := reStamp.FindStringSubmatch(v)
	if m == nil {
		return nil, fmt.Errorf("invalid timestamp %q", v)
	}
	num := func(s string) int { n, _ := strconv.Atoi(s); return n }
	year, month, day := num(m[1]), num(m[2]), num(m[3])
	valid := func(y, mo, d int) bool {
		if y < 1 || mo < 1 || mo > 12 || d < 1 {
			return false
		}
		return d <= time.Date(y, time.Month(mo)+1, 0, 0, 0, 0, 0, time.UTC).Day()
	}
	if !valid(year, month, day) {
		return nil, fmt.Errorf("day is out of range for month in %q", v)
	}
	if m[4] == "" {
		return Date(time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)), nil
	}
	hour, minute, second := num(m[4]), num(m[5]), num(m[6])
	if hour > 23 || minute > 59 || second > 59 {
		return nil, fmt.Errorf("time is out of range in %q", v)
	}
	nano := 0
	if frac := m[7]; frac != "" {
		if len(frac) > 6 {
			frac = frac[:6]
		}
		for len(frac) < 6 {
			frac += "0"
		}
		nano = num(frac) * 1000
	}
	loc := time.UTC
	switch {
	case m[9] != "":
		offset := num(m[10])*3600 + num(m[11])*60
		if num(m[10]) >= 24 || offset >= 24*3600 {
			return nil, fmt.Errorf("offset must be a timedelta strictly between -24h and 24h in %q", v)
		}
		if m[9] == "-" {
			offset = -offset
		}
		loc = time.FixedZone("", offset)
	case m[8] != "":
		loc = time.FixedZone("", 0)
	}
	return time.Date(year, time.Month(month), day, hour, minute, second, nano, loc), nil
}
