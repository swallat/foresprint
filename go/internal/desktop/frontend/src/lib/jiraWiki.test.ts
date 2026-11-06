import { describe, expect, it } from 'vitest';
import { parseInline, parseWiki } from './jiraWiki';

describe('Jira wiki markup', () => {
  it('reads headings, bullets and italic text', () => {
    const doc = parseWiki('h3. Roles\n * Alpha\n * Beta\n\nh3. Risk\n\n_HIGH_ - rollout under time pressure');
    expect(doc[0]).toEqual({ t: 'h', level: 3, c: [{ t: 'text', v: 'Roles' }] });
    expect(doc[1]).toMatchObject({ t: 'list', ordered: false });
    expect(doc[1]?.t === 'list' && doc[1].items.map((i) => i.c)).toEqual([[{ t: 'text', v: 'Alpha' }], [{ t: 'text', v: 'Beta' }]]);
    expect(doc[3]).toMatchObject({ t: 'p', c: [{ t: 'i', c: [{ t: 'text', v: 'HIGH' }] }, { t: 'text', v: ' - rollout under time pressure' }] });
  });

  it('nests and numbers lists', () => {
    const doc = parseWiki('# one\n## inner\n# two\n* x\n** y');
    expect(doc).toHaveLength(2);
    const first = doc[0];
    expect(first?.t === 'list' && first.ordered).toBe(true);
    expect(first?.t === 'list' && first.items[0]?.sub).toHaveLength(1);
    const second = doc[1];
    expect(second?.t === 'list' && second.ordered).toBe(false);
  });

  it('keeps bold, mono, strike and snake_case apart', () => {
    expect(parseInline('a *b* {{c}} -d- snake_case_word')).toEqual([
      { t: 'text', v: 'a ' }, { t: 'b', c: [{ t: 'text', v: 'b' }] }, { t: 'text', v: ' ' },
      { t: 'code', v: 'c' }, { t: 'text', v: ' ' }, { t: 's', c: [{ t: 'text', v: 'd' }] },
      { t: 'text', v: ' snake_case_word' },
    ]);
    expect(parseInline('2 * 3 and a - b')).toEqual([{ t: 'text', v: '2 * 3 and a - b' }]);
  });

  it('links only web addresses', () => {
    expect(parseInline('[docs|https://example.org/a]')).toEqual([{ t: 'link', href: 'https://example.org/a', c: [{ t: 'text', v: 'docs' }] }]);
    expect(parseInline('[x|javascript:alert(1)]')).toEqual([{ t: 'text', v: 'x' }]);
    expect(parseInline('see https://example.org/b.')).toEqual([{ t: 'text', v: 'see ' }, { t: 'link', href: 'https://example.org/b', c: [{ t: 'text', v: 'https://example.org/b' }] }, { t: 'text', v: '.' }]);
  });

  it('never produces HTML: tags stay text', () => {
    expect(parseInline('<img src=x onerror=alert(1)>')).toEqual([{ t: 'text', v: '<img src=x onerror=alert(1)>' }]);
  });

  it('reads code, quote, panel, table and rule', () => {
    const doc = parseWiki('{code:java}\nint a = 1;\n{code}\n{quote}\nquoted\n{quote}\n{panel:title=Note}\ninside\n{panel}\n||h1||h2||\n|a|[l|https://example.org]|\n----');
    expect(doc.map((b) => b.t)).toEqual(['code', 'quote', 'panel', 'table', 'hr']);
    expect(doc[0]).toEqual({ t: 'code', v: 'int a = 1;' });
    expect(doc[2]).toMatchObject({ t: 'panel', title: 'Note' });
    const table = doc[3];
    expect(table?.t === 'table' && table.rows.map((r) => r.map((c) => c.head))).toEqual([[true, true], [false, false]]);
  });

  it('keeps plain text lines together', () => {
    expect(parseWiki('one\ntwo')).toEqual([{ t: 'p', c: [{ t: 'text', v: 'one' }, { t: 'br' }, { t: 'text', v: 'two' }] }]);
  });

  it('keeps text after an inline code close and links with markers inside', () => {
    const doc = parseWiki('{code}a{code} after');
    expect(doc.map((b) => b.t)).toEqual(['code', 'p']);
    expect(parseInline('*a [b|https://example.org/*] c*')[0]).toMatchObject({ t: 'b' });
  });

  it('stays fast on a long line of unclosed markers', () => {
    const start = Date.now();
    parseInline('*b '.repeat(20000));
    expect(Date.now() - start).toBeLessThan(2000);
  });
});
