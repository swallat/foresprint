import { describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({ ownCallRecent: vi.fn(() => false) }));

describe('liveData', () => {
  it('shows the page anew when the data changed behind its back, but not for its own work', async () => {
    (window as unknown as { foresprintFingerprint?: string }).foresprintFingerprint = 'a';
    const { app, refreshStatus } = await import('./app.svelte');
    void refreshStatus;
    const { ownCallRecent } = await import('./api');
    const { watchData } = await import('./liveData.svelte');
    watchData();
    const send = (fp: string) => window.dispatchEvent(new CustomEvent('foresprint:data', { detail: fp }));
    const before = app.changed;
    send('a');
    expect(app.changed).toBe(before);
    send('b');
    expect(app.changed).toBe(before + 1);
    vi.mocked(ownCallRecent).mockReturnValue(true);
    send('c');
    expect(app.changed).toBe(before + 1);
    vi.mocked(ownCallRecent).mockReturnValue(false);
    send('c');
    expect(app.changed).toBe(before + 1);
    send('d');
    expect(app.changed).toBe(before + 2);
  });
});
