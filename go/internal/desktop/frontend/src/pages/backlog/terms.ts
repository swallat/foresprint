// Work packages kept in Foresprint are called that everywhere (flows.md decision 15): where the
// texts of this area say "ticket", a team without a tracker reads "work package"
// ("Arbeitspaket" in German). The texts keep one source wording; this turns the result.

const de: [RegExp, string][] = [
  [/Tickets\b/g, 'Arbeitspakete'],
  [/Ticket\b/g, 'Arbeitspaket'],
  [/tickets\b/g, 'Arbeitspakete'],
  [/ticket\b/g, 'Arbeitspaket'],
];

const en: [RegExp, string][] = [
  [/Tickets\b/g, 'Work packages'],
  [/Ticket\b/g, 'Work package'],
  [/tickets\b/g, 'work packages'],
  [/ticket\b/g, 'work package'],
];

/** Replaces the word ticket for a team with work packages; other texts stay as they are. */
export function localTerms(text: string, source: string | undefined, language: string): string {
  if (source !== 'packages') return text;
  let out = text;
  for (const [re, to] of language === 'de' ? de : en) out = out.replace(re, to);
  return out;
}
