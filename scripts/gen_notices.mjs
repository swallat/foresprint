// Writes the licence texts of everything that ships inside the program:
//   THIRD_PARTY_NOTICES.md                                      (repository root)
//   go/internal/desktop/frontend/src/assets/third-party-notices.txt   (shown in the About page)
// Run after changing go.mod or the frontend dependencies:
//   cd go/internal/desktop/frontend && npm ci && cd ../../../.. && node scripts/gen_notices.mjs
// It reads the licence files of the Go modules linked into the program (all three systems) from the
// module cache and of the frontend packages from node_modules.
import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const front = join(root, 'go', 'internal', 'desktop', 'frontend');

function licenseOf(dir) {
  const name = readdirSync(dir).find((f) => /^(licen[sc]e|copying|unlicense)(\.|$)/i.test(f));
  return name ? readFileSync(join(dir, name), 'utf8').trim() : '';
}

const modules = new Map();
for (const goos of ['linux', 'windows', 'darwin']) {
  const out = execFileSync(
    'go',
    ['list', '-tags', 'desktop,production', '-deps', '-f', '{{with .Module}}{{if not .Main}}{{.Path}}|{{.Version}}|{{.Dir}}{{end}}{{end}}', './cmd/foresprint'],
    { cwd: join(root, 'go'), env: { ...process.env, GOOS: goos, CGO_ENABLED: '1' }, encoding: 'utf8' },
  );
  for (const line of out.split('\n').filter(Boolean)) {
    const [path, version, dir] = line.split('|');
    modules.set(path, { version, dir });
  }
}

const parts = [
  `# Third-party notices\n\nForesprint itself is licensed under the EUPL-1.2 (see LICENSE). The program contains the following\nthird-party components, which are licensed as stated below.\n`,
];
const section = (title, text) => parts.push(`\n---\n\n## ${title}\n\n${text}\n`);

section('Iosevka and Iosevka Aile (fonts)', readFileSync(join(front, 'src/assets/fonts/LICENSE-Iosevka.md'), 'utf8').trim());
section('Material Symbols (icons), @material-symbols/svg-400', licenseOf(join(front, 'node_modules/@material-symbols/svg-400')));
const svelte = JSON.parse(readFileSync(join(front, 'node_modules/svelte/package.json'), 'utf8'));
section(`Svelte ${svelte.version} (user interface runtime)`, licenseOf(join(front, 'node_modules/svelte')));

for (const [path, { version, dir }] of [...modules].sort(([a], [b]) => a.localeCompare(b))) {
  const text = existsSync(dir) ? licenseOf(dir) : '';
  if (!text) throw new Error(`no licence file for ${path} ${version}`);
  section(`${path} ${version}`, text);
}

const text = parts.join('');
writeFileSync(join(root, 'THIRD_PARTY_NOTICES.md'), text);
writeFileSync(join(front, 'src/assets/third-party-notices.txt'), text);
console.log(`${modules.size} Go modules, ${(text.length / 1024).toFixed(0)} KiB`);
