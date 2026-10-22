// Browser answers for the area Forecast (forecast table, products over time, what-if, report,
// Excel import) for the demo team.

import type { Api } from '../api';
import type { ForecastRow, ForecastView, ImportPreview, ProductsOverTime, ReportFile, WhatIfRow, WhenDoneView } from '../types.forecast';

// Forecast of Team Atlas: 10 completed sprints, the current one and 4 coming ones.
const round1 = (n: number) => Math.round(n * 10) / 10;
function forecastView(): ForecastView {
  const ref = 40;
  const vel = [31, 36, 34, 38, 33, 40, 37, 41, 39, 42];
  const caps = [38, 41, 36, 40, 35, 42, 39, 41, 38, 40];
  const day = 86400000;
  const base = Date.UTC(2026, 0, 5);
  const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  const row = (i: number, state: ForecastRow['state']): ForecastRow => {
    const v = vel[i] ?? null;
    const nv = v !== null ? round1((v / (caps[i] ?? 39)) * ref) : null;
    return {
      id: `2026.${12 + i}`, start: iso(base + i * 14 * day), end: iso(base + i * 14 * day + 11 * day), state, recorded: i < 11,
      capacity: caps[i] ?? 39, capacitySource: i < 10 ? 'recorded' : 'people list', unsure: false,
      commitment: v !== null ? v + 2 : null, velocity: v, normalizedVelocity: nv, average: nv, trend: nv,
      fulfillment: v !== null ? Math.round((v / (v + 2)) * 1000) / 1000 : null, plan: null, planSource: '', low: null, high: null, plannable: null, small: null,
    };
  };
  const past = Array.from({ length: 10 }, (_, i) => row(i, 'past'));
  const nvTrend = 40.2;
  const upcoming = Array.from({ length: 5 }, (_, k) => {
    const r = row(10 + k, k === 0 ? 'current' : 'future');
    const cap = [38, 37, 41, 36, 40][k] ?? 38;
    const plan = Math.floor((nvTrend / ref) * cap);
    return { ...r, velocity: null, commitment: null, normalizedVelocity: null, fulfillment: null, capacity: cap, capacitySource: k < 2 ? 'announced absences' : 'expected absences', unsure: k > 3,
      average: nvTrend, trend: nvTrend, plan, planSource: 'projection' as const, low: Math.floor((33 / ref) * cap), high: Math.floor((42 / ref) * cap),
      plannable: plan * 0.8, small: round1(plan * 0.2) };
  });
  return { team: 'atlas', today: iso(base + 10 * 14 * day + 3 * day), referenceCapacity: ref, window: 6, roadmapShare: 0.8, trendMode: 'flat', horizon: 4, rounding: 0, products: 3, samples: 6, fewSamples: false, rate: nvTrend / ref, past, upcoming };
}

const forecastMock: Partial<Api> = {
  async ForecastProducts(): Promise<ProductsOverTime> {
    const v = forecastView();
    const sprints = [...v.past.slice(-4), ...v.upcoming].map((r) => r.id);
    const line = (id: string, name: string, share: number) => {
      const cells = [...v.past.slice(-4), ...v.upcoming].map((r, i) => {
        const standard = Math.floor((r.plan ?? r.velocity ?? 0) * share);
        const past = r.state === 'past';
        return {
          standard,
          preplanned: past ? null : standard + (i % 2),
          planned: past || r.state === 'current' ? standard : null,
          done: past ? standard + ((i % 3) - 1) : null,
        };
      });
      const done = cells.filter((c) => c.done !== null);
      const std = done.reduce((a, c) => a + (c.standard ?? 0), 0);
      const dn = done.reduce((a, c) => a + (c.done ?? 0), 0);
      return { id, name, cells, sprints: done.length, standard: std, done: dn, difference: dn - std, missing: 0 };
    };
    return { enabled: true, sprints, current: v.upcoming[0]?.id ?? '', lines: [line('core', 'Core platform', 0.5), line('apps', 'Mobile apps', 0.3), line('data', 'Data services', 0.2)] };
  },
  async ForecastReport() {
    const v = forecastView();
    return `# Sprint forecast Team Atlas\n\n| Sprint | Capacity | Forecast PLAN | Range |\n| --- | --- | --- | --- |\n${v.upcoming.map((r) => `| ${r.id} | ${r.capacity} | ${r.plan} | ${r.low} – ${r.high} |`).join('\n')}\n`;
  },
  async ForecastSave(_team, kind): Promise<ReportFile> {
    return { path: `/demo/export/atlas-forecast.${kind === 'excel' ? 'xlsx' : 'md'}`, cancelled: false };
  },
  async ExcelImportPreview(): Promise<ImportPreview> {
    return {
      path: '/demo/export/atlas-forecast.xlsx',
      hash: 'demo',
      changes: [
        { file: 'team.yaml', path: 'forecast.window', old: '5', new: '6' },
        { file: 'sprints/2026.21.yaml', path: 'velocity', old: '–', new: '42' },
      ],
      more: 0,
      untouched: [],
      noTeam: false,
      cancelled: false,
    };
  },
  async ExcelImportApply() {
    return ['team.yaml', 'sprints/2026.21.yaml'];
  },
  async Forecast() {
    return forecastView();
  },
  async ForecastWhatIf(_team, extraAbsenceDays, focusPercent): Promise<WhatIfRow[]> {
    return forecastView().upcoming.map((r) => {
      const capacity = Math.max(0, (r.capacity ?? 0) - extraAbsenceDays);
      const forecast = Math.floor(((r.trend ?? 0) / 40) * capacity * (focusPercent / 100));
      return { id: r.id, capacity, forecast, base: r.plan ?? 0, delta: forecast - (r.plan ?? 0) };
    });
  },
  async ForecastWhenDone(_team, remaining, sharePercent): Promise<WhenDoneView> {
    const per = 36 * (sharePercent / 100);
    const sprints = Array.from({ length: 12 }, (_, i) => `2026.${23 + i}`);
    const cumulative = sprints.map((_, i) => Math.min(1, Math.max(0, (per * (i + 1) - remaining * 0.6) / (remaining * 0.8))));
    const first = (p: number) => sprints.find((_, i) => (cumulative[i] ?? 0) >= p) ?? '';
    return { remaining, share: sharePercent, runs: 10000, samples: 6, p50: first(0.5), p85: first(0.85), sprints, cumulative, perSprint: per, trendCapacity: sprints.slice(6), available: remaining > 0 && sharePercent > 0 };
  },
};

export default forecastMock;
