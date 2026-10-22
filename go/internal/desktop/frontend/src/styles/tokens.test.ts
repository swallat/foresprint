// Contrast of the design tokens (DESIGN.md: text >= 4.5:1, borders and icons >= 3:1), measured
// with the WCAG formula for both themes, so a changed token that breaks it fails the build.
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8');

function tokens(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]!] = m[2]!;
  return out;
}

const light = tokens(css.slice(0, css.indexOf('@media')));
const dark = { ...light, ...tokens(css.slice(css.indexOf(':root[data-theme="dark"]'))) };

function luminance(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

// [foreground, background, minimum]
const pairs: [string, string, number][] = [
  ['text', 'bg', 4.5], ['text', 'surface', 4.5], ['text', 'surface-2', 4.5],
  ['text-muted', 'bg', 4.5], ['text-muted', 'surface', 4.5], ['text-muted', 'surface-2', 4.5],
  ['primary', 'surface', 4.5], ['primary', 'bg', 4.5], ['primary', 'primary-weak', 4.5],
  ['on-primary', 'primary', 4.5],
  ['secondary', 'surface', 4.5],
  ['forecast', 'surface', 4.5], ['forecast', 'forecast-weak', 4.5],
  ['ok', 'surface', 4.5], ['ok', 'ok-weak', 4.5],
  ['warn', 'surface', 4.5], ['warn', 'warn-weak', 4.5],
  ['bad', 'surface', 4.5], ['bad', 'bad-weak', 4.5],
  ['border-control', 'surface', 3], ['border-control', 'bg', 3],
];

describe.each([['light', light], ['dark', dark]] as const)('%s theme', (_, theme) => {
  it.each(pairs)('%s on %s reaches %s:1', (fg, bg, min) => {
    expect(theme[fg], `token ${fg}`).toBeDefined();
    expect(theme[bg], `token ${bg}`).toBeDefined();
    expect(ratio(theme[fg]!, theme[bg]!)).toBeGreaterThanOrEqual(min);
  });
});
