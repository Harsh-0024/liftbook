// Small pieces of Python behaviour the ported code relies on, so the JavaScript gives the
// same answers as the Python app: its regular expressions, str.split()/strip()/title(),
// f"{x:g}" and round().

// What Python's str.isspace() (and so str.split(), str.strip() and \s) counts as whitespace.
const WS = '\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const WS_SET = new Set();
for (const range of [[0x09, 0x0d], [0x1c, 0x20], [0x85, 0x85], [0xa0, 0xa0], [0x1680, 0x1680],
  [0x2000, 0x200a], [0x2028, 0x2029], [0x202f, 0x202f], [0x205f, 0x205f], [0x3000, 0x3000]]) {
  for (let c = range[0]; c <= range[1]; c++) WS_SET.add(String.fromCharCode(c));
}
// Python's \w: letters, numbers and "_".
const WORD = '\\p{L}\\p{N}_';
const BOUNDARY = `(?:(?<=[${WORD}])(?![${WORD}])|(?<![${WORD}])(?=[${WORD}]))`;
const NOT_BOUNDARY = `(?:(?<=[${WORD}])(?=[${WORD}])|(?<![${WORD}])(?![${WORD}]))`;
const END = '(?=\\n?(?![\\s\\S]))'; // Python's $: the end, or just before a final newline

// Python regex source -> JavaScript ("u" flag) source with the same meaning.
// \d stays ASCII digits (see DIFFERENCES.md); everything else follows Python.
function translate(src) {
  let out = '';
  let inClass = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (ch === '\\') {
      const next = src[++i];
      if (next === 's') out += inClass ? WS : `[${WS}]`;
      else if (next === 'S') {
        if (inClass) throw new Error('\\S inside a class is not supported');
        out += `[^${WS}]`;
      } else if (next === 'd') out += '\\p{Nd}';
      else if (next === 'D') {
        if (inClass) throw new Error('\\D inside a class is not supported');
        out += '\\P{Nd}';
      } else if (next === 'w') out += inClass ? WORD : `[${WORD}]`;
      else if (next === 'W') {
        if (inClass) throw new Error('\\W inside a class is not supported');
        out += `[^${WORD}]`;
      } else if (next === 'b' && !inClass) out += BOUNDARY;
      else if (next === 'B' && !inClass) out += NOT_BOUNDARY;
      else if (next === 'Z' && !inClass) out += '(?![\\s\\S])';
      else if (next === 'A' && !inClass) out += '^';
      else if ('^$\\.*+?()[]{}|/'.includes(next)) out += '\\' + next;
      else if (next === '-') out += inClass ? '\\-' : '-';
      else if (next === 'U') { out += `\\u{${src.slice(i + 1, i + 9)}}`; i += 8; }
      else if (/[0-9A-Za-z]/.test(next)) out += '\\' + next;
      else out += `\\u{${next.codePointAt(0).toString(16)}}`;
      continue;
    }
    if (inClass) {
      if (ch === ']') inClass = false;
      out += ch;
      continue;
    }
    if (ch === '[') {
      inClass = true;
      out += ch;
      // A "]" or "^]" right after "[" is a literal in Python.
      if (src[i + 1] === '^') { out += '^'; i++; }
      if (src[i + 1] === ']') { out += '\\]'; i++; }
      continue;
    }
    if (ch === '$') { out += END; continue; }
    if (ch === '.') { out += '[^\\n]'; continue; }
    if (ch === '(' && src.startsWith('(?P<', i)) { out += '(?<'; i += 3; continue; }
    out += ch;
  }
  return out;
}

const cache = new Map();

/** A compiled Python-style regular expression. flags: "i" for re.IGNORECASE. */
export class PyRe {
  constructor(src, flags = '') {
    this.source = src;
    const js = translate(src);
    const f = 'u' + (flags.includes('i') ? 'i' : '');
    this.sticky = new RegExp(js, f + 'y');
    this.full = new RegExp(`(?:${js})(?![\\s\\S])`, f + 'y');
    this.global = new RegExp(js, f + 'g');
    this.plain = new RegExp(js, f);
  }
  /** re.match: at the start only. Returns a Match or null. */
  match(s) {
    this.sticky.lastIndex = 0;
    return wrap(this.sticky.exec(s));
  }
  fullmatch(s) {
    this.full.lastIndex = 0;
    return wrap(this.full.exec(s));
  }
  search(s) {
    return wrap(this.plain.exec(s));
  }
  test(s) {
    return this.plain.test(s);
  }
  *finditer(s) {
    this.global.lastIndex = 0;
    let m;
    while ((m = this.global.exec(s)) !== null) {
      yield wrap(m);
      if (m[0] === '') this.global.lastIndex++;
    }
  }
  /** re.findall: whole matches, or the one group, or tuples of groups ("" when unmatched). */
  findall(s) {
    const out = [];
    for (const m of this.finditer(s)) {
      const groups = m.raw.length - 1;
      if (groups === 0) out.push(m.raw[0]);
      else if (groups === 1) out.push(m.raw[1] ?? '');
      else out.push(m.raw.slice(1).map((g) => g ?? ''));
    }
    return out;
  }
  /** re.sub. repl is a string using \1 / \g<1> or a function of the Match. */
  sub(repl, s, count = 0) {
    let out = '';
    let last = 0;
    let n = 0;
    for (const m of this.finditer(s)) {
      if (count && n >= count) break;
      out += s.slice(last, m.start) + (typeof repl === 'function' ? repl(m) : expand(repl, m));
      last = m.end;
      n++;
    }
    return out + s.slice(last);
  }
  /** re.split without capture groups. */
  split(s) {
    const out = [];
    let last = 0;
    for (const m of this.finditer(s)) {
      out.push(s.slice(last, m.start));
      last = m.end;
    }
    out.push(s.slice(last));
    return out;
  }
}

function expand(repl, m) {
  return repl.replace(/\\(\d+)|\\g<(\w+)>/g, (_, num, name) => m.group(num !== undefined ? Number(num) : /^\d+$/.test(name) ? Number(name) : name) ?? '');
}

class Match {
  constructor(raw) {
    this.raw = raw;
    this.start = raw.index;
    this.end = raw.index + raw[0].length;
  }
  group(n = 0) {
    if (typeof n === 'string') return this.raw.groups?.[n];
    return this.raw[n];
  }
}

function wrap(raw) {
  return raw ? new Match(raw) : null;
}

/** A regex compiled once and reused. */
export function re(src, flags = '') {
  const key = flags + '\u0000' + src;
  let r = cache.get(key);
  if (!r) {
    r = new PyRe(src, flags);
    cache.set(key, r);
  }
  return r;
}

// --- Strings ---

export function isSpace(ch) {
  return WS_SET.has(ch);
}

/** str.split() with no arguments. */
export function split(s) {
  const out = [];
  let cur = '';
  for (const ch of s) {
    if (WS_SET.has(ch)) {
      if (cur) out.push(cur);
      cur = '';
    } else cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}

/** str.strip(chars); whitespace when chars is omitted. */
export function strip(s, chars) {
  return rstrip(lstrip(s, chars), chars);
}
export function lstrip(s, chars) {
  const has = chars === undefined ? (c) => WS_SET.has(c) : (c) => chars.includes(c);
  let i = 0;
  while (i < s.length && has(s[i])) i++;
  return s.slice(i);
}
export function rstrip(s, chars) {
  const has = chars === undefined ? (c) => WS_SET.has(c) : (c) => chars.includes(c);
  let i = s.length;
  while (i > 0 && has(s[i - 1])) i--;
  return s.slice(0, i);
}

/** str.splitlines(): splits on every line break Python knows, drops the breaks. */
export function splitlines(s) {
  const out = [];
  let cur = '';
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === '\r' && s[i + 1] === '\n') { out.push(cur); cur = ''; i++; continue; }
    if ('\n\r\v\f\x1c\x1d\x1e\x85  '.includes(ch)) { out.push(cur); cur = ''; continue; }
    cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}

/** str.split(sep, 1) -> [head, tail] or [s]. */
export function split1(s, sep) {
  const i = s.indexOf(sep);
  return i < 0 ? [s] : [s.slice(0, i), s.slice(i + sep.length)];
}

/** str.rsplit(sep, 1). */
export function rsplit1(s, sep) {
  const i = s.lastIndexOf(sep);
  return i < 0 ? [s] : [s.slice(0, i), s.slice(i + sep.length)];
}

function isCased(ch) {
  return ch.toLowerCase() !== ch.toUpperCase();
}

/** str.title(). */
export function title(s) {
  let out = '';
  let prevCased = false;
  for (const ch of s) {
    if (isCased(ch)) {
      out += prevCased ? ch.toLowerCase() : ch.toUpperCase();
      prevCased = true;
    } else {
      out += ch;
      prevCased = false;
    }
  }
  return out;
}

/** list(dict.fromkeys(values)). */
export function unique(values) {
  return [...new Set(values)];
}

// --- Numbers ---

/** Exact decimal digits of a finite double: [sign, digits, pointPosition]. */
function exactDigits(x) {
  const a = Math.abs(x);
  const s = a >= 1e21 ? BigInt(a).toString() + '.' : a.toFixed(100).replace(/0+$/, '');
  const [intPart, frac = ''] = s.split('.');
  let digits = (intPart + frac).replace(/^0+/, '');
  const lead = (intPart + frac).length - digits.length;
  const point = intPart.length - lead; // value = 0.digits * 10^point
  return [x < 0 || Object.is(x, -0) ? '-' : '', digits || '0', digits ? point : 1];
}

// Round a digit string to `keep` digits, halves to even (as Python formats and rounds).
function roundDigits(digits, keep) {
  if (keep < 0) return { digits: '0', carry: 0, zero: true };
  if (digits.length <= keep) return { digits: digits.padEnd(keep, '0'), carry: 0 };
  const head = digits.slice(0, keep);
  const rest = digits.slice(keep);
  let up;
  if (rest[0] > '5') up = true;
  else if (rest[0] < '5') up = false;
  else if (/[1-9]/.test(rest.slice(1))) up = true;
  else up = keep > 0 ? Number(head[keep - 1]) % 2 === 1 : false;
  if (!up) return { digits: head || '', carry: 0 };
  // add one to head
  const arr = (head || '').split('').map(Number);
  let i = arr.length - 1;
  while (i >= 0) {
    if (arr[i] === 9) { arr[i] = 0; i--; } else { arr[i]++; break; }
  }
  if (i < 0) return { digits: '1' + arr.join(''), carry: 1 };
  return { digits: arr.join(''), carry: 0 };
}

/** f"{x:g}" (6 significant digits, trailing zeros dropped). */
export function formatG(x, precision = 6) {
  if (Number.isNaN(x)) return 'nan';
  if (x === Infinity) return 'inf';
  if (x === -Infinity) return '-inf';
  if (x === 0) return Object.is(x, -0) ? '-0' : '0';
  const [sign, digits, point] = exactDigits(x);
  let { digits: d, carry } = roundDigits(digits, precision);
  let exp = point - 1 + carry;
  if (carry) d = d.slice(0, precision);
  if (exp >= -4 && exp < precision) {
    let s;
    if (exp >= 0) s = d.slice(0, exp + 1).padEnd(exp + 1, '0') + '.' + d.slice(exp + 1);
    else s = '0.' + '0'.repeat(-exp - 1) + d;
    s = s.replace(/0+$/, '').replace(/\.$/, '');
    return sign + s;
  }
  let mant = d[0] + '.' + d.slice(1);
  mant = mant.replace(/0+$/, '').replace(/\.$/, '');
  const e = Math.abs(exp);
  return `${sign}${mant}e${exp < 0 ? '-' : '+'}${e < 10 ? '0' + e : e}`;
}

/** f"{x:.nf}". */
export function formatFixed(x, n) {
  if (!Number.isFinite(x)) return formatG(x);
  const [sign, digits, point] = exactDigits(x);
  // digits with `intCount` of them before the decimal point
  let all;
  let intCount;
  if (point > 0) {
    all = digits.padEnd(point, '0');
    intCount = point;
  } else {
    all = '0'.repeat(-point) + digits;
    intCount = 0;
  }
  const { digits: r, carry } = roundDigits(all, intCount + n);
  const ints = intCount + carry;
  const intPart = r.slice(0, ints).replace(/^0+(?=\d)/, '') || '0';
  return sign + intPart + (n ? '.' + r.slice(ints) : '');
}

/** round(x, n) as Python does it: the nearest n-decimal value, halves to even. */
export function pyRound(x, n = 0) {
  if (!Number.isFinite(x)) return x;
  return Number(formatFixed(x, n));
}

/** Python's float formatting with repr(), for messages: 100.0 -> "100.0". */
export function floatRepr(x) {
  if (Number.isInteger(x) && Math.abs(x) < 1e16) return x.toFixed(1);
  return String(x);
}

/** Python's sum() of floats (3.12+ uses compensated summation). */
export function fsum(values) {
  let s = 0;
  let c = 0;
  for (const x of values) {
    const t = s + x;
    if (Math.abs(s) >= Math.abs(x)) c += (s - t) + x;
    else c += (x - t) + s;
    s = t;
  }
  return c && Number.isFinite(c) ? s + c : s;
}

/** max(items, key=...) returning the first of equal maxima, like Python. */
export function maxBy(items, key, cmp = compareKeys) {
  let best;
  let bestKey;
  let first = true;
  for (const item of items) {
    const k = key(item);
    if (first || cmp(k, bestKey) > 0) {
      best = item;
      bestKey = k;
      first = false;
    }
  }
  return best;
}

/** Python ordering of numbers, strings and (nested) tuples/arrays. */
export function compareKeys(a, b) {
  if (Array.isArray(a) && Array.isArray(b)) {
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i++) {
      const c = compareKeys(a[i], b[i]);
      if (c) return c;
    }
    return a.length - b.length;
  }
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

/** sorted(values, key, reverse) — stable like Python's, reverse keeping equal items in order. */
export function sortBy(values, key = (x) => x, reverse = false) {
  const decorated = values.map((v, i) => [key(v), i, v]);
  decorated.sort((x, y) => {
    const c = compareKeys(x[0], y[0]);
    if (c) return reverse ? -c : c;
    return x[1] - y[1];
  });
  return decorated.map((d) => d[2]);
}

/** float(x) for the values the app stores (numbers or numeric strings); throws like Python. */
export function toFloat(x) {
  if (typeof x === 'number') return x;
  if (typeof x === 'boolean') return x ? 1 : 0;
  if (typeof x === 'string') {
    const t = asciiDigits(strip(x)).replace(/_/g, '');
    if (/^[+-]?(?:\d+\.?\d*(?:e[+-]?\d+)?|\.\d+(?:e[+-]?\d+)?)$/i.test(t)) return Number(t);
    if (/^[+-]?(?:inf|infinity)$/i.test(t)) return t.startsWith('-') ? -Infinity : Infinity;
    if (/^[+-]?nan$/i.test(t)) return NaN;
  }
  throw new TypeError(`could not convert to float: ${x}`);
}

const DECIMAL_DIGIT = /\p{Nd}/u;

/**
 * Digits from any script ("١٠", "१०") as ASCII ("10"), as Python's int() and float() read them.
 * Unicode keeps each script's digits together, 0 to 9 in order.
 */
export function asciiDigits(text) {
  return text.replace(/[^\x00-\x7f]/gu, (ch) => {
    if (!DECIMAL_DIGIT.test(ch)) return ch;
    let cp = ch.codePointAt(0);
    let below = 0;
    while (DECIMAL_DIGIT.test(String.fromCodePoint(cp - 1))) {
      cp -= 1;
      below += 1;
    }
    return String(below % 10);
  });
}

/** int(x): numbers truncate, strings must be whole numbers; throws like Python. */
export function toInt(x) {
  if (typeof x === 'number') {
    if (!Number.isFinite(x)) throw new TypeError('cannot convert to int');
    return Math.trunc(x);
  }
  if (typeof x === 'boolean') return x ? 1 : 0;
  if (typeof x === 'string') {
    const t = asciiDigits(strip(x)).replace(/_/g, '');
    if (/^[+-]?\d+$/.test(t)) return Number(t);
  }
  throw new TypeError(`invalid literal for int(): ${x}`);
}

/** Python truthiness for the values that reach it here. */
export function truthy(x) {
  if (Array.isArray(x)) return x.length > 0;
  if (x && typeof x === 'object') return Object.keys(x).length > 0;
  return Boolean(x);
}

/** A plain object (dict) check, like isinstance(x, dict). */
export function isDict(x) {
  return x !== null && typeof x === 'object' && !Array.isArray(x);
}
