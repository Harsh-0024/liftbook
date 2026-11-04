// Small helpers for building the screens: elements, icons, rows, messages, dates, a line chart.

/** h('div', {class: 'card', onclick: fn}, 'text', child, [more]) */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'value' && 'value' in el) el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected') el[k] = Boolean(v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

let toastTimer = null;
/** A short message near the bottom. toast('Saved'), or with a button: toast('Cleared', { action: 'Undo', onAction }). */
export function toast(message, opts = 3200) {
  const el = document.getElementById('toast');
  if (!el) return;
  const { ms = opts?.action ? 6000 : 3200, action = null, onAction = null } = typeof opts === 'number' ? { ms: opts } : (opts || {});
  el.replaceChildren(message);
  if (action) {
    el.append(h('button', { type: 'button', class: 'toast-act', onclick: () => {
      el.hidden = true;
      clearTimeout(toastTimer);
      onAction?.();
    } }, action));
  }
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.hidden = true;
  }, ms);
}

export async function copyText(text, { quiet = false } = {}) {
  try {
    await navigator.clipboard.writeText(text);
    if (!quiet) toast('Copied');
  } catch {
    const ta = h('textarea', { style: 'position:fixed;opacity:0' }, text);
    document.body.append(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    if (!quiet) toast('Copied');
  }
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-10-31" -> "Sat 31 Oct 2026" (calendar maths only, no time zones). */
export function formatDay(day, { weekday = true, year = true } = {}) {
  const [y, m, d] = String(day).slice(0, 10).split('-').map(Number);
  if (!y) return String(day || '');
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${weekday ? `${DAYS[wd]} ` : ''}${d} ${MONTHS[m - 1]}${year ? ` ${y}` : ''}`;
}

/** "3 min ago" for a sync time. */
export function ago(iso) {
  if (!iso) return 'never';
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return formatDay(new Date(Date.parse(iso)).toISOString(), { weekday: false });
}

export const fmtNum = (n, digits = 1) => (n === null || n === undefined || Number.isNaN(n) ? '–'
  : Number(n).toLocaleString(undefined, { maximumFractionDigits: digits }));

const SVG = 'http://www.w3.org/2000/svg';
function s(tag, attrs = {}) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

// Line icons (24 × 24, drawn with the current text colour), in the spirit of the original app's.
const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  log: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
  stats: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 6-6"/><path d="M15 8h5v5"/>',
  coach: '<path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M19 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
  back: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m14 6 4 4"/>',
  share: '<path d="M4 13v6a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-6"/><path d="M12 3v12M7 8l5-5 5 5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  person: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/>',
  plan: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  dumbbell: '<path d="M6 8v8M3 10v4M18 8v8M21 10v4M6 12h12"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  sync: '<path d="M20 12a8 8 0 0 1-14.3 4.9M4 12A8 8 0 0 1 18.3 7.1"/><path d="M18.5 3v4.3h-4.3M5.5 21v-4.3h4.3"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M15 8l2 2"/>',
  shield: '<path d="M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  scale: '<circle cx="12" cy="5" r="2"/><path d="M12 8v6M8 22l4-8 4 8M7 11h10"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  clipboard: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3h6v1M9 10h6M9 14h4"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  heart: '<path d="M12 20s-7-4.4-9-9a4.8 4.8 0 0 1 9-3 4.8 4.8 0 0 1 9 3c-2 4.6-9 9-9 9z"/>',
  thumbdown: '<path d="M10 15v4a2.5 2.5 0 0 0 2.5 2.5L16 14V3H6.7a2 2 0 0 0-2 1.7L3.3 12a2 2 0 0 0 2 2.3H10zM16 3h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>',
  wrench: '<path d="M14.7 6.3a4 4 0 0 0 5 5L21 13l-8 8-3-3 8-8-1.3-1.3a4 4 0 0 1-5-5L14 2z"/><path d="m3 21 6-6"/>',
  bulb: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.3 1 2.2h5.2c0-.9.4-1.7 1-2.2A6 6 0 0 0 12 3z"/>',
  send: '<path d="M21 3 10 14M21 3l-7 18-4-7-7-4z"/>',
  medal: '<circle cx="12" cy="15" r="6"/><path d="M8.5 3 12 9l3.5-6M12 12.5v5M10.5 14l1.5-1.5"/>',
  logout: '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l5-5-5-5M15 12H3"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  'eye-off': '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.7 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  right: '<path d="M5 12h14M13 6l6 6-6 6"/>',
};

/** An icon: icon('stats'). */
export function icon(name, cls = '') {
  const el = s('svg', { viewBox: '0 0 24 24', class: `i ${cls}`.trim(), 'aria-hidden': 'true' });
  el.innerHTML = ICONS[name] || '';
  return el;
}

/** A row in a group: icon, title, description, a value on the right, and a chevron when it opens something. */
export function rowItem({ href, onclick, ico, title, desc, value, chev = Boolean(href || onclick), cls = '' }) {
  const tag = href ? 'a' : onclick ? 'button' : 'div';
  return h(tag, { class: `rowi ${cls}`.trim(), href, type: onclick ? 'button' : null, onclick },
    ico ? h('span', { class: 'ico' }, icon(ico)) : null,
    h('span', { class: 'main' }, h('span', { class: 'title' }, title), desc ? h('span', { class: 'desc' }, desc) : null),
    value !== undefined && value !== null && value !== '' ? h('span', { class: 'value' }, value) : null,
    chev ? h('span', { class: 'chev-i' }, icon('chev')) : null);
}

/** A page heading: an optional back link, the title, one quiet line, and anything for the right. */
export function pageHead(title, sub = '', { back = null, aside = null } = {}) {
  return h('header', { class: 'page-head' },
    h('div', {},
      back ? h('a', { class: 'back', href: back, 'aria-label': 'Back' }, icon('back')) : null,
      h('h1', {}, title),
      sub ? h('p', {}, sub) : null),
    aside);
}

/** "Today", "Yesterday", a weekday this past week, then "28 Oct" (and the year if not this one). */
export function softDay(day, now = new Date()) {
  const [y, m, d] = String(day).slice(0, 10).split('-').map(Number);
  if (!y) return String(day || '');
  const then = Date.UTC(y, m - 1, d);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today - then) / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days > 1 && days < 7) return ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][new Date(then).getUTCDay()];
  return formatDay(day, { weekday: false, year: y !== now.getFullYear() });
}

let gradientId = 0;
/** A line chart: soft gold area, values up the side, first and last dates along the bottom.
 *  base: a value drawn as a dashed "start" line; tag: label the last point (e.g. "+14%"). */
export function lineChart(labels, values, { unit = '', base = null, tag = null, height = 240, format = null } = {}) {
  // Drawn at about the width it shows at, so the labels stay readable on a phone.
  const W = Math.round(Math.max(300, Math.min(640, (globalThis.innerWidth || 640) - 72)));
  const H = W < 480 ? Math.round(height * 0.85) : height;
  const pad = { l: 46, r: tag ? 54 : 14, t: 16, b: 28 };
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined && Number.isFinite(Number(v)));
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img', 'aria-label': 'Progress chart', style: `height:${H}px` });
  if (!pts.length) {
    const t = s('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' });
    t.textContent = 'Nothing to chart yet';
    svg.append(t);
    return svg;
  }
  const id = `gold-fade-${++gradientId}`;
  const defs = s('defs');
  const grad = s('linearGradient', { id, x1: 0, y1: 0, x2: 0, y2: 1 });
  grad.append(s('stop', { offset: '0%', style: 'stop-color:var(--gold);stop-opacity:.3' }), s('stop', { offset: '100%', style: 'stop-color:var(--gold);stop-opacity:0' }));
  defs.append(grad);
  svg.append(defs);
  const nums = pts.map((p) => Number(p[1]));
  if (base !== null) nums.push(base);
  let lo = Math.min(...nums);
  let hi = Math.max(...nums);
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const span = hi - lo;
  lo -= span * 0.1;
  hi += span * 0.1;
  const n = Math.max(1, values.length - 1);
  const x = (i) => pad.l + (i / n) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (Number(v) - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const fmt = format || ((v) => `${fmtNum(v, span < 10 ? 1 : 0)}${unit}`);
  for (let k = 0; k <= 4; k++) {
    const v = lo + ((hi - lo) * k) / 4;
    svg.append(s('line', { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), class: 'axis' }));
    const t = s('text', { x: pad.l - 8, y: y(v) + 4, 'text-anchor': 'end' });
    t.textContent = fmt(v);
    svg.append(t);
  }
  if (base !== null) svg.append(s('line', { x1: pad.l, x2: W - pad.r, y1: y(base), y2: y(base), class: 'base' }));
  // A smooth line through the points (monotone enough for progress data).
  const P = pts.map(([i, v]) => [x(i), y(v)]);
  let path = `M${P[0][0].toFixed(1)},${P[0][1].toFixed(1)}`;
  for (let k = 1; k < P.length; k++) {
    const [x0, y0] = P[k - 1];
    const [x1, y1] = P[k];
    const cx = (x0 + x1) / 2;
    path += ` C${cx.toFixed(1)},${y0.toFixed(1)} ${cx.toFixed(1)},${y1.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
  }
  const bottom = H - pad.b;
  svg.append(s('path', { d: `${path} L${P[P.length - 1][0]},${bottom} L${P[0][0]},${bottom} Z`, fill: `url(#${id})` }));
  svg.append(s('path', { d: path, class: 'line' }));
  if (pts.length <= 60) P.forEach(([px, py], k) => svg.append(s('circle', { cx: px, cy: py, r: k === P.length - 1 ? 4.5 : 2.6, class: 'dot' })));
  if (tag) {
    const [lx, ly] = P[P.length - 1];
    const g = s('g', { class: 'tag' });
    const w = 8 + tag.length * 7;
    g.append(s('rect', { x: lx + 8, y: ly - 11, width: w, height: 22, rx: 11 }));
    const t = s('text', { x: lx + 8 + w / 2, y: ly + 4, 'text-anchor': 'middle' });
    t.textContent = tag;
    g.append(t);
    svg.append(g);
  }
  const first = s('text', { x: pad.l, y: H - 8 });
  first.textContent = String(labels[pts[0][0]] ?? '');
  const last = s('text', { x: W - pad.r, y: H - 8, 'text-anchor': 'end' });
  last.textContent = String(labels[pts[pts.length - 1][0]] ?? '');
  svg.append(first, last);
  return svg;
}

/** A button that shows it is busy while `fn` runs, and any error as a message. */
export function busy(button, fn) {
  return async (event) => {
    event?.preventDefault?.();
    if (button.disabled) return;
    const label = [...button.childNodes]; // icon and text, put back as they were
    button.disabled = true;
    button.textContent = 'Working…';
    try {
      await fn(event);
    } catch (err) {
      toast(err && err.message ? err.message : 'Something went wrong.', 5000);
    } finally {
      if (button.isConnected) {
        button.disabled = false;
        button.replaceChildren(...label);
      }
    }
  };
}

/**
 * Ask before something that can't be undone, on the page rather than in a browser pop-up (as the
 * original app's "Confirm" dialog). Resolves true for yes; Cancel, Escape or a tap outside is no.
 * The safe answer has the focus, so Enter never deletes by accident.
 */
export function ask(message, { title = 'Are you sure?', yes = 'Confirm', no = 'Cancel', danger = false } = {}) {
  return new Promise((resolve) => {
    const noBtn = h('button', { class: 'btn', type: 'button' }, no);
    const yesBtn = h('button', { class: `btn ${danger ? 'danger solid' : 'primary'}`, type: 'button' }, yes);
    const dlg = h('dialog', { class: 'ask-dialog', 'aria-labelledby': 'ask-title', 'aria-describedby': 'ask-text' },
      h('h2', { id: 'ask-title' }, title), h('p', { id: 'ask-text' }, message), h('div', { class: 'ask-actions' }, noBtn, yesBtn));
    let answered = false;
    const done = (v) => {
      if (answered) return;
      answered = true;
      dlg.close();
      dlg.remove();
      resolve(v);
    };
    noBtn.addEventListener('click', () => done(false));
    yesBtn.addEventListener('click', () => done(true));
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); done(false); });
    dlg.addEventListener('click', (e) => { if (e.target === dlg) done(false); });
    document.body.append(dlg);
    dlg.showModal();
    noBtn.focus();
  });
}
