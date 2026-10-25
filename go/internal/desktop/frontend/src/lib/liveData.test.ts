import { describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
  ownCallRecent: vi.fn(() => false),
  api: { Teams: vi.fn(async () => []), Status: vi.fn(async () => ({ storage: 'saved', tracker: { syncing: false } })), PendingTags: vi.fn(async () => []), Sprints: vi.fn(async () => []), TrackerInfo: vi.fn(async () => ({})) },
}));

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

  it('does not wait for a field that was only left focused (no key pressed lately)', async () => {
    const { app } = await import('./app.svelte');
    const main = document.createElement('main');
    main.id = 'main';
    const input = document.createElement('input');
    main.appendChild(input);
    document.body.appendChild(main);
    input.focus();
    const before = app.changed;
    window.dispatchEvent(new CustomEvent('foresprint:data', { detail: 'e1' }));
    expect(app.changed).toBe(before + 1);
    main.remove();
  });
});
