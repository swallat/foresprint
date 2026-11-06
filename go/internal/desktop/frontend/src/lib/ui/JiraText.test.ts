import { mount, unmount } from 'svelte';
import { describe, expect, it } from 'vitest';
import JiraText from './JiraText.svelte';

describe('JiraText', () => {
  it('renders wiki markup as elements and keeps tags as text', () => {
    const target = document.createElement('div');
    const c = mount(JiraText, { target, props: { text: 'h3. Roles\n * Dev\n * Test\n\n_HIGH_ <b>x</b>' } });
    expect(target.querySelectorAll('li')).toHaveLength(2);
    expect(target.querySelector('[role=heading]')?.textContent).toBe('Roles');
    expect(target.querySelector('em')?.textContent).toBe('HIGH');
    expect(target.querySelector('b')).toBeNull();
    expect(target.textContent).toContain('<b>x</b>');
    unmount(c);
  });
});
