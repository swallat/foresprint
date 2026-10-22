package cli

import (
	"strings"
	"unicode/utf8"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/guide"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/settings"
)

func init() { Register(helpCommand) }

const helpWidth = 100

func helpCommand(env *Env) *cobra.Command {
	var topics []string
	for _, t := range guide.Topics() {
		topics = append(topics, t.Key)
	}
	return &cobra.Command{
		Use:       "help [TOPIC]",
		Short:     i18n.T("Guide, terms, input fields, settings and commands."),
		Long:      i18n.P("Topic: {topics}", "topics", strings.Join(topics, ", ")),
		Args:      cobra.MaximumNArgs(1),
		ValidArgs: topics,
		RunE: func(cmd *cobra.Command, args []string) error {
			topic := "workflow"
			if len(args) > 0 {
				topic = args[0]
			}
			title := ""
			for _, t := range guide.Topics() {
				if t.Key == topic {
					title = i18n.T(t.Title)
				}
			}
			if title == "" {
				return Failf("Unknown topic. Available: {topics}", "topics", strings.Join(topics, ", "))
			}
			printTopic(env, cmd, topic, title)
			if topic == "terms" {
				env.Println()
				printPairs(env, i18n.T("Capacity source in the forecast"), guide.CapacitySources())
			}
			var others []string
			for _, k := range topics {
				if k != topic {
					others = append(others, k)
				}
			}
			env.Println()
			env.Println(i18n.P("More topics: {others} (foresprint help TOPIC)", "others", strings.Join(others, ", ")))
			return nil
		},
	}
}

func printTopic(env *Env, cmd *cobra.Command, topic, title string) {
	switch topic {
	case "workflow":
		env.Println(title)
		for _, s := range guide.Workflow() {
			env.Println()
			env.Println(i18n.T(s.When) + " – " + i18n.T(s.Title))
			env.Println(wrap(i18n.T(s.Text), "  "))
			env.Println("  " + s.CLI)
		}
	case "terms":
		printPairs(env, title, guide.Terms())
	case "fields":
		env.Println(title)
		for _, f := range guide.Fields() {
			env.Println()
			env.Println(i18n.T(f.Title))
			env.Println(wrap(i18n.T(f.What), "  "))
			env.Println(wrap(i18n.T("Source")+": "+i18n.T(f.Source), "  "))
			env.Println(wrap(i18n.T("Example")+": "+i18n.T(f.Example), "  "))
		}
	case "team":
		env.Println(title)
		for _, s := range settings.All {
			env.Println()
			env.Println(s.Title() + "  (" + s.Key + ")")
			env.Println(wrap(s.Text(), "  "))
		}
		env.Println()
		env.Println(i18n.P("Change interactively: foresprint settings TEAM"))
	default: // commands: only those this program has
		have := map[string]bool{}
		for _, c := range cmd.Root().Commands() {
			have[c.Name()] = true
		}
		var rows []guide.Pair
		for _, p := range guide.Commands() {
			if f := strings.Fields(p[0]); len(f) >= 2 && have[f[1]] {
				rows = append(rows, p)
			}
		}
		printPairs(env, title, rows)
	}
}

// printPairs writes a title and rows of a left column (not translated) and a text (translated for
// terms and purposes; the terms themselves are translated too, commands are not in the catalog).
func printPairs(env *Env, title string, rows []guide.Pair) {
	env.Println(title)
	width := 0
	left := make([]string, len(rows))
	for i, r := range rows {
		left[i] = i18n.T(r[0])
		if n := utf8.RuneCountInString(left[i]); n > width {
			width = n
		}
	}
	if width > 30 { // a wide left column: the text goes below, indented
		for i, r := range rows {
			env.Println("  " + left[i])
			env.Println(wrap(i18n.T(r[1]), "      "))
		}
		return
	}
	for i, r := range rows {
		pad := strings.Repeat(" ", width-utf8.RuneCountInString(left[i]))
		prefix := strings.Repeat(" ", width+4)
		text := wrap(i18n.T(r[1]), prefix)
		env.Println("  " + left[i] + pad + "  " + strings.TrimPrefix(text, prefix))
	}
}

// wrap breaks text at word borders so that no line is longer than width; every line starts with
// the prefix.
func wrap(text, prefix string) string {
	var lines []string
	line := prefix
	for _, word := range strings.Fields(text) {
		if line != prefix && utf8.RuneCountInString(line)+1+utf8.RuneCountInString(word) > helpWidth {
			lines = append(lines, line)
			line = prefix
		}
		if line != prefix {
			line += " "
		}
		line += word
	}
	return strings.Join(append(lines, line), "\n")
}

// explain prints the explanation of an input field before it is asked for.
func (e *Env) explain(key string) {
	f, ok := guide.FieldByKey(key)
	if !ok {
		return
	}
	e.Println(i18n.T(f.Title))
	e.Println(wrap(i18n.T(f.What), "  "))
	e.Println(wrap(i18n.T("Source")+": "+i18n.T(f.Source), "  "))
	e.Println(wrap(i18n.T("Example")+": "+i18n.T(f.Example), "  "))
}
