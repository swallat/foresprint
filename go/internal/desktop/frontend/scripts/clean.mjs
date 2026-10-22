// Empties dist/ but keeps .gitkeep, so that the embed in desktop.go finds the folder on a fresh clone.
import { readdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist');
for (const name of readdirSync(dist)) if (name !== '.gitkeep') rmSync(join(dist, name), { recursive: true, force: true });
