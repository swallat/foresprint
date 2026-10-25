package cli

import (
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/config"
	"github.com/swallat/foresprint/internal/i18n"
)

func init() { Register(languageCommand) }

func languageCommand(env *Env) *cobra.Command {
	return &cobra.Command{
		Use:       "language [de|en]",
		Short:     i18n.T("Show or set the interface language (de, en)."),
		Args:      cobra.MaximumNArgs(1),
		ValidArgs: languageCodes(),
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) == 0 {
				code := i18n.Language()
				env.Printf("%s (%s)\n", code, i18n.Name(code))
				return nil
			}
			code := i18n.Normalize(args[0])
			if code == "" {
				return Failf("Allowed: {values}", "values", strings.Join(languageCodes(), ", "))
			}
			if err := config.SaveLanguage(code); err != nil {
				return err
			}
			i18n.SetLanguage(code)
			env.Println(i18n.T("Language: {language}", "language", i18n.Name(code)))
			return nil
		},
	}
}

func languageCodes() []string {
	var codes []string
	for _, l := range i18n.Languages() {
		codes = append(codes, l.Code)
	}
	return codes
}
