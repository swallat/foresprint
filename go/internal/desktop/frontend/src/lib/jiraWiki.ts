// A reader for Jira wiki markup (what REST API v2 returns for descriptions and comments on Jira
// Server, Data Center and Cloud): h3. headings, "* " and "# " lists, *bold*, _italic_, {{mono}},
// {code}, {quote}, {panel}, tables, [text|url] links. The result is plain data that the page
// renders itself, so no HTML from the tracker is ever injected and nothing needs sanitizing.
// Only http(s) addresses become links.

export type WikiInline =
  | { t: 'text'; v: string }
  | { t: 'b' | 'i' | 's' | 'u' | 'sup' | 'sub' | 'cite'; c: WikiInline[] }
  | { t: 'code'; v: string }
  | { t: 'link'; href: string; c: WikiInline[] }
  | { t: 'img'; name: string }
  | { t: 'br' };

export interface WikiItem {
  c: WikiInline[];
  sub: WikiBlock[];
}

export type WikiBlock =
  | { t: 'h'; level: number; c: WikiInline[] }
  | { t: 'p'; c: WikiInline[] }
  | { t: 'list'; ordered: boolean; items: WikiItem[] }
  | { t: 'quote'; c: WikiBlock[] }
  | { t: 'panel'; title: string; c: WikiBlock[] }
  | { t: 'code'; v: string }
  | { t: 'table'; rows: { head: boolean; c: WikiInline[] }[][] }
  | { t: 'hr' };

const SPECIAL = '*_-+^~?{[!\\\\';
const isWord = (ch: string | undefined): boolean => ch !== undefined && /[\p{L}\p{N}]/u.test(ch);
const isSpace = (ch: string | undefined): boolean => ch === undefined || /\s/.test(ch);
const isHttp = (u: string): boolean => /^https?:\/\/\S+$/i.test(u);

// Pairs of emphasis markers; the key is what opens and closes.
const PAIRS: Record<string, 'b' | 'i' | 's' | 'u' | 'sup' | 'sub'> = { '*': 'b', _: 'i', '-': 's', '+': 'u', '^': 'sup', '~': 'sub' };

function push(out: WikiInline[], v: string): void {
  if (v === '') return;
  const last = out[out.length - 1];
  if (last?.t === 'text') last.v += v;
  else out.push({ t: 'text', v });
}

// Finds the closing marker of an emphasis that opened at `from`: not after a space, not inside a
// word. Returns -1 when the marker is just a character (a hyphen, a lone star).
function closer(s: string, mark: string, from: number): number {
  const limit = Math.min(s.length, from + 500); // a marker without a closer must not rescan the whole line
  for (let j = from; j < limit; j++) {
    const ch = s[j];
    if (ch === '[' || (ch === '{' && s[j + 1] === '{')) {
      // a link or mono span is skipped as a whole, so a marker inside an address does not close
      const end = s.indexOf(ch === '[' ? ']' : '}}', j + 1);
      if (end !== -1 && end < limit) j = end + (ch === '[' ? 0 : 1);
      continue;
    }
    if (s.startsWith(mark, j) && j > from && !isSpace(s[j - 1]) && !isWord(s[j + mark.length])) return j;
  }
  return -1;
}

export function parseInline(s: string): WikiInline[] {
  const out: WikiInline[] = [];
  let i = 0;
  while (i < s.length) {
    const ch = s[i] ?? '';
    const rest = s.slice(i);
    // bare web address
    const url = /^https?:\/\/[^\s<>\]|]+/i.exec(rest);
    if (url && !isWord(s[i - 1])) {
      const href = url[0].replace(/[.,;:!?)]+$/, '');
      out.push({ t: 'link', href, c: [{ t: 'text', v: href }] });
      i += href.length;
      continue;
    }
    if (ch === '\\') {
      if (s[i + 1] === '\\') {
        out.push({ t: 'br' });
        i += 2;
      } else if (i + 1 < s.length && SPECIAL.includes(s[i + 1] ?? '')) {
        push(out, s[i + 1] ?? '');
        i += 2;
      } else {
        push(out, ch);
        i++;
      }
      continue;
    }
    if (!SPECIAL.includes(ch)) {
      // copy the run up to the next special character
      let j = i + 1;
      while (j < s.length && !SPECIAL.includes(s[j] ?? '') && !/^https?:\/\//i.test(s.slice(j, j + 8))) j++;
      push(out, s.slice(i, j));
      i = j;
      continue;
    }
    if (rest.startsWith('{{')) {
      const end = s.indexOf('}}', i + 2);
      if (end > i + 2) {
        out.push({ t: 'code', v: s.slice(i + 2, end) });
        i = end + 2;
        continue;
      }
    }
    if (ch === '{') {
      // {color:red}...{color} and other macros inside a line: keep the content, drop the macro
      const m = /^\{(color|anchor|noformat|code|quote|panel)(?::[^}]*)?\}/.exec(rest);
      if (m) {
        i += m[0].length;
        continue;
      }
    }
    if (ch === '[') {
      const end = s.indexOf(']', i + 1);
      if (end > i + 1) {
        const body = s.slice(i + 1, end);
        i = end + 1;
        if (body.startsWith('~')) push(out, '@' + (body.startsWith('~accountid:') ? 'user' : body.slice(1)));
        else if (body.startsWith('#') || body.startsWith('^')) push(out, body.slice(1));
        else {
          const bar = body.indexOf('|');
          const label = bar === -1 ? body : body.slice(0, bar);
          const target = (bar === -1 ? body : body.slice(bar + 1)).trim();
          if (isHttp(target)) out.push({ t: 'link', href: target, c: parseInline(label.trim() === '' ? target : label) });
          else push(out, bar === -1 ? '[' + body + ']' : label);
        }
        continue;
      }
    }
    if (ch === '!') {
      const m = /^!([^!\s|][^!\n]*?)!/.exec(rest);
      if (m && !isWord(s[i - 1])) {
        out.push({ t: 'img', name: (m[1] ?? '').split('|')[0] ?? '' });
        i += m[0].length;
        continue;
      }
    }
    if (rest.startsWith('??')) {
      const end = s.indexOf('??', i + 2);
      if (end > i + 2 && !isSpace(s[i + 2])) {
        out.push({ t: 'cite', c: parseInline(s.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }
    const kind = PAIRS[ch];
    if (kind && !isWord(s[i - 1]) && !isSpace(s[i + 1])) {
      const end = closer(s, ch, i + 1);
      if (end !== -1) {
        out.push({ t: kind, c: parseInline(s.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }
    push(out, ch);
    i++;
  }
  return out;
}

// Splits a table row at | but not inside [text|url] links.
function cells(line: string): { head: boolean; c: WikiInline[] }[] {
  const row: { head: boolean; c: WikiInline[] }[] = [];
  const t = line.trim();
  let depth = 0;
  let cur = '';
  let head = false;
  let started = false;
  const flush = () => {
    if (started) row.push({ head, c: parseInline(cur.trim()) });
    cur = '';
  };
  for (let i = 0; i < t.length; i++) {
    const ch = t[i] ?? '';
    if (ch === '[') depth++;
    else if (ch === ']' && depth > 0) depth--;
    if (ch === '|' && depth === 0) {
      const double = t[i + 1] === '|';
      flush();
      started = true;
      head = double;
      if (double) i++;
      continue;
    }
    cur += ch;
  }
  if (cur.trim() !== '') row.push({ head, c: parseInline(cur.trim()) });
  return row;
}

const LIST = /^\s*([*#-]+)\s+(.*)$/;

function parseList(lines: string[]): WikiBlock {
  // marker length is the depth; the last marker character says bullet or number
  const root: WikiBlock = { t: 'list', ordered: false, items: [] };
  const stack: { depth: number; list: Extract<WikiBlock, { t: 'list' }> }[] = [{ depth: 1, list: root }];
  lines.forEach((line, n) => {
    const m = LIST.exec(line);
    if (!m) return;
    const marks = m[1] ?? '';
    const depth = marks.length;
    const ordered = marks.endsWith('#');
    while (stack.length > 1 && (stack[stack.length - 1]?.depth ?? 0) > depth) stack.pop();
    let top = stack[stack.length - 1]!;
    if (depth > top.depth) {
      const parent = top.list.items[top.list.items.length - 1];
      const child: Extract<WikiBlock, { t: 'list' }> = { t: 'list', ordered, items: [] };
      if (parent) parent.sub.push(child);
      else top.list.items.push({ c: [], sub: [child] });
      top = { depth, list: child };
      stack.push(top);
    }
    if (n === 0) top.list.ordered = ordered;
    top.list.items.push({ c: parseInline((m[2] ?? '').trim()), sub: [] });
  });
  return root;
}

export function parseWiki(source: string): WikiBlock[] {
  return blocks(source.replace(/\r\n?/g, '\n').split('\n'));
}

function blocks(lines: string[]): WikiBlock[] {
  const out: WikiBlock[] = [];
  let para: string[] = [];
  const endPara = () => {
    if (para.length === 0) return;
    const c: WikiInline[] = [];
    para.forEach((l, k) => {
      if (k > 0) c.push({ t: 'br' });
      c.push(...parseInline(l.trim()));
    });
    out.push({ t: 'p', c });
    para = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';
    const trimmed = line.trim();
    if (trimmed === '') {
      endPara();
      continue;
    }
    // {code} and {noformat} keep their text as it is
    const fence = /^\{(code|noformat)(?::[^}]*)?\}(.*)$/.exec(trimmed);
    if (fence) {
      endPara();
      const name = fence[1] ?? 'code';
      const body: string[] = [];
      let first = fence[2] ?? '';
      let closed = false;
      const close = '{' + name + '}';
      for (;;) {
        const at = first.indexOf(close);
        if (at !== -1) {
          body.push(first.slice(0, at));
          closed = true;
        } else body.push(first);
        if (closed) {
          const tail = first.slice(at + close.length);
          if (tail.trim() !== '') lines.splice(i + 1, 0, tail); // text after the closing tag goes on
          break;
        }
        if (i + 1 >= lines.length) break;
        first = lines[++i] ?? '';
      }
      out.push({ t: 'code', v: body.join('\n').replace(/^\n+|\n+$/g, '') });
      continue;
    }
    // {quote} and {panel} hold blocks of their own
    const wrap = /^\{(quote|panel)(?::([^}]*))?\}\s*$/.exec(trimmed);
    if (wrap) {
      endPara();
      const name = wrap[1] ?? 'quote';
      const inner: string[] = [];
      while (i + 1 < lines.length && (lines[i + 1] ?? '').trim() !== '{' + name + '}') inner.push(lines[++i] ?? '');
      i++; // the closing tag (or the end)
      const title = /(?:^|\|)title=([^|]*)/.exec(wrap[2] ?? '')?.[1] ?? '';
      out.push(name === 'quote' ? { t: 'quote', c: blocks(inner) } : { t: 'panel', title, c: blocks(inner) });
      continue;
    }
    if (/^-{4,}$/.test(trimmed)) {
      endPara();
      out.push({ t: 'hr' });
      continue;
    }
    const head = /^h([1-6])\.\s+(.*)$/.exec(trimmed);
    if (head) {
      endPara();
      out.push({ t: 'h', level: Number(head[1]), c: parseInline((head[2] ?? '').trim()) });
      continue;
    }
    const bq = /^bq\.\s+(.*)$/.exec(trimmed);
    if (bq) {
      endPara();
      out.push({ t: 'quote', c: [{ t: 'p', c: parseInline((bq[1] ?? '').trim()) }] });
      continue;
    }
    if (trimmed.startsWith('|')) {
      endPara();
      const rows: ReturnType<typeof cells>[] = [];
      while (i < lines.length && (lines[i] ?? '').trim().startsWith('|')) rows.push(cells(lines[i++] ?? ''));
      i--;
      out.push({ t: 'table', rows });
      continue;
    }
    if (LIST.test(line) && !/^\s*-{2,}\s/.test(line) && !/^\s*\*[^\s*#-].*\*\s*$/.test(line)) {
      endPara();
      const group: string[] = [];
      const kind = (LIST.exec(line)?.[1] ?? '')[0]; // a bullet list followed by a numbered one is two lists
      while (i < lines.length && LIST.test(lines[i] ?? '') && (LIST.exec(lines[i] ?? '')?.[1] ?? '')[0] === kind) group.push(lines[i++] ?? '');
      i--;
      out.push(parseList(group));
      continue;
    }
    para.push(line);
  }
  endPara();
  return out;
}
