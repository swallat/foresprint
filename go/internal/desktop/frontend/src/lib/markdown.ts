// A small reader for the minutes: headings, bullet lists, tables, paragraphs and **bold**. The
// result is plain data that the page renders itself, so no HTML from a file is ever injected.

export type Inline = { text: string; bold: boolean };

export type Block =
  | { kind: 'h1' | 'h2' | 'h3' | 'p'; inline: Inline[] }
  | { kind: 'ul'; items: Inline[][] }
  | { kind: 'table'; head: Inline[][]; rows: Inline[][][] };

export function inline(text: string): Inline[] {
  const out: Inline[] = [];
  text.split(/(\*\*[^*]+\*\*)/).forEach((part) => {
    if (part === '') return;
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) out.push({ text: part.slice(2, -2), bold: true });
    else out.push({ text: part, bold: false });
  });
  return out;
}

const cells = (line: string): string[] =>
  line
    .trim()
    .replace(/^\||\|$/g, '')
    .split(/(?<!\\)\|/)
    .map((c) => c.trim().replace(/\\\|/g, '|'));

export function parse(source: string): Block[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const out: Block[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';
    if (line.startsWith('<!--') || line.trim() === '') continue; // markers and gaps
    const head = /^(#{1,3}) (.*)$/.exec(line);
    if (head) {
      out.push({ kind: (['h1', 'h2', 'h3'] as const)[(head[1] ?? '#').length - 1] ?? 'h3', inline: inline(head[2] ?? '') });
    } else if (line.startsWith('- ')) {
      const items: Inline[][] = [];
      while (i < lines.length && (lines[i] ?? '').startsWith('- ')) items.push(inline((lines[i++] ?? '').slice(2)));
      i--;
      out.push({ kind: 'ul', items });
    } else if (line.startsWith('|')) {
      const rows: string[] = [];
      while (i < lines.length && (lines[i] ?? '').startsWith('|')) rows.push(lines[i++] ?? '');
      i--;
      const [first, , ...body] = rows;
      out.push({ kind: 'table', head: cells(first ?? '').map(inline), rows: body.map((r) => cells(r).map(inline)) });
    } else {
      out.push({ kind: 'p', inline: inline(line) });
    }
  }
  return out;
}
