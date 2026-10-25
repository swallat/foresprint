// Texts of the window. Source texts are English and are the keys: t("Save"). A language is a
// map from source text to translation, served by the Go core (internal/i18n/data/<code>.ui.json);
// a text without entry shows as English. {name} placeholders are filled from `vars`.
//
// t() reads reactive state, so components that call it in their markup update on a language
// change without further work.

import { api } from './api';

let texts = $state<Record<string, string>>({});
let current = $state('en');

export function format(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

/** Translates a source text. */
export function t(text: string, vars?: Record<string, string | number>): string {
  return format(texts[text] ?? text, vars);
}

/** The language in use ("en", "de"). */
export function language(): string {
  return current;
}

/** Loads the texts of a language and switches to it. */
export async function useLanguage(code: string): Promise<void> {
  texts = code === 'en' ? {} : await api.Texts(code);
  current = code;
  document.documentElement.lang = code;
}
