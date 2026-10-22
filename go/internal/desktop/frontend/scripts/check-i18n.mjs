// Checks the texts of the window: every source text used in the code (t('...'), page titles and
// navigation labels) must have a German translation in go/internal/i18n/data/de.ui.json, and
// that file must not hold texts the code no longer uses.
//
//   node scripts/check-i18n.mjs          # check
//   node scripts/check-i18n.mjs --list   # print the source texts found

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const catalog = join(here, '..', '..', '..', 'i18n', 'data', 'de.ui.json');

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.(svelte|ts)$/.test(name) && !name.endsWith('.test.ts') ? [path] : [];
  });
}

const str = String.raw`(?:'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|\x60((?:[^\x60\\$]|\\.)*)\x60)`;
const patterns = [
  new RegExp(String.raw`(?<![\w.$])t\(\s*${str}`, 'g'), // t('text')
  new RegExp(String.raw`\b(?:title|label)\s*[:=]\s*${str}`, 'g'), // route table, nav, <Placeholder title="...">
];

function unescape(text) {
  return text.replace(/\\(['"\x60\\])/g, '$1').replace(/\\n/g, '\n');
}

const used = new Map();
for (const file of files(src)) {
  const text = readFileSync(file, 'utf8');
  for (const re of patterns) {
    for (const m of text.matchAll(re)) {
      const raw = m[1] ?? m[2] ?? m[3];
      if (raw === undefined) continue;
      // `title=` and `label=` also occur for dynamic or non-text values; only routes.ts and
      // Placeholder usages are texts.
      if (re === patterns[1] && !(file.endsWith('routes.ts') || /<Placeholder/.test(text.slice(Math.max(0, m.index - 40), m.index)))) continue;
      used.set(unescape(raw), file);
    }
  }
}

if (process.argv.includes('--list')) {
  for (const k of [...used.keys()].sort()) console.log(k);
  process.exit(0);
}

const de = JSON.parse(readFileSync(catalog, 'utf8')).texts;
let bad = 0;
for (const [text, file] of used) {
  if (!(text in de)) {
    console.error(`missing German text: ${JSON.stringify(text)} (${file.replace(src, 'src')})`);
    bad++;
  }
}
for (const text of Object.keys(de)) {
  if (!used.has(text)) {
    console.error(`unused German text: ${JSON.stringify(text)}`);
    bad++;
  }
}
if (bad) {
  console.error(`${bad} problem(s) in the texts of the window`);
  process.exit(1);
}
console.log(`texts ok (${used.size})`);
