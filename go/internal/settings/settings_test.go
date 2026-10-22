package settings

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func init() { storage.Translate = func(s string) string { return i18n.T(s) } }

type parseRef struct {
	Display string `json:"display"`
	Kind    string `json:"kind"`
	Error   string `json:"error"`
}

type describeRef struct {
	Title   string      `json:"title"`
	Text    string      `json:"text"`
	Options [][2]string `json:"options"`
}

type settingRef struct {
	Key                string                         `json:"key"`
	Kind               string                         `json:"kind"`
	Optional           bool                           `json:"optional"`
	OnlyWithoutSprints bool                           `json:"only_without_sprints"`
	Retroactive        bool                           `json:"retroactive"`
	Minimum            *float64                       `json:"minimum"`
	Maximum            *float64                       `json:"maximum"`
	Step               *float64                       `json:"step"`
	Default            string                         `json:"default"`
	En                 describeRef                    `json:"en"`
	De                 describeRef                    `json:"de"`
	Parse              map[string]map[string]parseRef `json:"parse"`
}

type ref struct {
	Settings []settingRef `json:"settings"`
	Without  []string     `json:"applicable_without_sprints"`
	With     []string     `json:"applicable_with_sprints"`
	Changes  [][3]string  `json:"changes"`
}

func kindName(v Value) string {
	switch v.(type) {
	case nil:
		return "none"
	case string:
		return "str"
	case int:
		return "int"
	case float64:
		return "float"
	case time.Time:
		return "date"
	}
	return "?"
}

func TestSettingsMatchPython(t *testing.T) {
	var want ref
	golden.Load(t, &want, "settings", "settings.json")
	t.Cleanup(func() { i18n.SetLanguage("") })
	if len(want.Settings) != len(All) {
		t.Fatalf("%d settings, reference has %d", len(All), len(want.Settings))
	}
	fresh := model.NewTeam("t", "T")
	for i, w := range want.Settings {
		s := All[i]
		if s.Key != w.Key || string(s.Kind) != w.Kind || s.Optional != w.Optional ||
			s.OnlyWithoutSprints != w.OnlyWithoutSprints || s.Retroactive != w.Retroactive {
			t.Errorf("%s: description differs from the reference", w.Key)
		}
		if (s.Min == nil) != (w.Minimum == nil) || (s.Min != nil && *s.Min != *w.Minimum) ||
			(s.Max == nil) != (w.Maximum == nil) || (s.Max != nil && *s.Max != *w.Maximum) {
			t.Errorf("%s: limits differ", w.Key)
		}
		if got := s.Display(&fresh); got != w.Default {
			t.Errorf("%s: default %q, want %q", w.Key, got, w.Default)
		}
		for lang, desc := range map[string]describeRef{"en": w.En, "de": w.De} {
			i18n.SetLanguage(lang)
			if s.Title() != desc.Title || s.Text() != desc.Text {
				t.Errorf("%s/%s: title or text differs", w.Key, lang)
			}
			choices := s.Choices()
			if len(choices) != len(desc.Options) {
				t.Errorf("%s/%s: %d choices, want %d", w.Key, lang, len(choices), len(desc.Options))
				continue
			}
			for j, o := range choices {
				if o.Key != desc.Options[j][0] || o.Label != desc.Options[j][1] {
					t.Errorf("%s/%s: choice %v, want %v", w.Key, lang, o, desc.Options[j])
				}
			}
			for raw, exp := range w.Parse[lang] {
				value, err := s.Parse(raw)
				switch {
				case exp.Error != "":
					if err == nil || err.Error() != exp.Error {
						t.Errorf("%s/%s: Parse(%q) = %v, %v; want error %q", w.Key, lang, raw, value, err, exp.Error)
					}
				case err != nil:
					t.Errorf("%s/%s: Parse(%q) failed: %v; want %q", w.Key, lang, raw, err, exp.Display)
				default:
					team := model.NewTeam("t", "T")
					s.Set(&team, value)
					if got := s.Display(&team); got != exp.Display || kindName(value) != exp.Kind {
						t.Errorf("%s/%s: Parse(%q) displays %q (%s), want %q (%s)", w.Key, lang, raw,
							got, kindName(value), exp.Display, exp.Kind)
					}
				}
			}
		}
	}
	keys := func(list []Setting) []string {
		var out []string
		for _, s := range list {
			out = append(out, s.Key)
		}
		return out
	}
	if g, w := keys(Applicable(false)), want.Without; len(g) != len(w) {
		t.Errorf("applicable without sprints: %v", g)
	}
	if g, w := keys(Applicable(true)), want.With; len(g) != len(w) {
		t.Errorf("applicable with sprints: %v", g)
	}
	changed := model.NewTeam("t", "T")
	for _, s := range All {
		if s.Kind == Int && s.Min != nil {
			s.Set(&changed, int(*s.Min))
		}
	}
	got := Changes(&fresh, &changed)
	if len(got) != len(want.Changes) {
		t.Fatalf("changes: %d, want %d", len(got), len(want.Changes))
	}
	for i, c := range got {
		if c.Setting.Key != want.Changes[i][0] || c.Old != want.Changes[i][1] || c.New != want.Changes[i][2] {
			t.Errorf("change %d = %v, want %v", i, c, want.Changes[i])
		}
	}
}
