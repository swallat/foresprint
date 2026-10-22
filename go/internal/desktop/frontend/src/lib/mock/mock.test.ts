// The browser answers (mock/) must cover every method of the Go API (internal/app), so that a
// page runs in the browser and in tests the same as in the program.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { mockApi } from './index';

// vitest runs in the frontend folder: go/internal/desktop/frontend
const dir = join(process.cwd(), '..', '..', 'app');

// Go methods the frontend never calls.
const goOnly = new Set(['DataDir']);

function goMethods(): string[] {
  const names = new Set<string>();
  for (const file of readdirSync(dir).filter((f) => f.endsWith('.go') && !f.endsWith('_test.go'))) {
    for (const m of readFileSync(join(dir, file), 'utf8').matchAll(/^func \(\w+ \*API\) ([A-Z]\w*)\(/gm)) names.add(m[1]!);
  }
  return [...names].filter((n) => !goOnly.has(n)).sort();
}

describe('mock', () => {
  it('answers every method of the Go API', () => {
    const have = new Set(Object.keys(mockApi));
    expect(goMethods().filter((m) => !have.has(m))).toEqual([]);
  });
  it('has no method the Go API does not know', () => {
    const go = new Set(goMethods());
    expect(Object.keys(mockApi).filter((m) => !go.has(m))).toEqual([]);
  });
});
