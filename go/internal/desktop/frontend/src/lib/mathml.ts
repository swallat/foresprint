// Tiny MathML builders for the calculation paths. WebView2, WebKitGTK and WKWebView draw MathML
// natively, so no external resource is needed. Every product, quotient and square is grouped
// explicitly (par), so the reader never has to know the order of operations.
export type M = string;

export const id = (s: string): M => `<mi>${s}</mi>`;
export const num = (s: string | number): M => `<mn>${s}</mn>`;
export const op = (s: string): M => `<mo>${s}</mo>`;
export const row = (...c: M[]): M => `<mrow>${c.join('')}</mrow>`;
/** Round brackets around the content. */
export const par = (...c: M[]): M => row(op('('), ...c, op(')'));
/** Function call: name( args ). */
export const fn = (name: string, ...args: M[]): M => row(id(name), par(...args));
export const frac = (top: M, bottom: M): M => `<mfrac>${row(top)}${row(bottom)}</mfrac>`;
/** The root bar covers the whole content. */
export const sqrt = (...c: M[]): M => `<msqrt>${c.join('')}</msqrt>`;
export const sq = (base: M): M => `<msup>${base}${num(2)}</msup>`;
export const floor = (...c: M[]): M => row(op('⌊'), ...c, op('⌋'));
export const times = op('×');
export const eq = op('=');
export const minus = op('−');
export const plus = op('+');
export const sub = (base: M, s: M): M => `<msub>${base}${s}</msub>`;

/** One formula per math element, one line each. */
export const lines = (...l: M[]): M => l.map((m) => `<math display="block">${row(m)}</math>`).join('');
/** Sum sign with bounds below and above. */
export const sum = (from: M, to: M): M => `<munderover>${op('∑')}${row(from)}${row(to)}</munderover>`;
/** Prime mark after an identifier, e.g. P′. */
export const prime = (base: M): M => `<msup>${base}${op('′')}</msup>`;
