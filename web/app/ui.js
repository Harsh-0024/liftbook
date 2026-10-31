// Small helpers for building the screens: elements, messages, dates, a line chart.

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
export function toast(message, ms = 3200) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.hidden = true;
  }, ms);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied');
  } catch {
    const ta = h('textarea', { style: 'position:fixed;opacity:0' }, text);
    document.body.append(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    toast('Copied');
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

/** A simple line chart: labels along the bottom, values up the side. */
export function lineChart(labels, values, { unit = '' } = {}) {
  const W = 640;
  const H = 220;
  const pad = { l: 44, r: 12, t: 12, b: 26 };
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined && Number.isFinite(Number(v)));
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img', 'aria-label': 'Progress chart' });
  if (!pts.length) {
    const t = s('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' });
    t.textContent = 'Nothing to chart yet';
    svg.append(t);
    return svg;
  }
  let lo = Math.min(...pts.map((p) => Number(p[1])));
  let hi = Math.max(...pts.map((p) => Number(p[1])));
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const span = hi - lo;
  lo -= span * 0.08;
  hi += span * 0.08;
  const n = Math.max(1, values.length - 1);
  const x = (i) => pad.l + (i / n) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (Number(v) - lo) / (hi - lo)) * (H - pad.t - pad.b);
  for (let k = 0; k <= 3; k++) {
    const v = lo + ((hi - lo) * k) / 3;
    svg.append(s('line', { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), class: 'axis' }));
    const t = s('text', { x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end' });
    t.textContent = `${fmtNum(v, span < 10 ? 1 : 0)}${unit}`;
    svg.append(t);
  }
  const path = pts.map(([i, v], k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  svg.append(s('path', { d: `${path} L${x(pts[pts.length - 1][0])},${H - pad.b} L${x(pts[0][0])},${H - pad.b} Z`, class: 'area' }));
  svg.append(s('path', { d: path, class: 'line' }));
  if (pts.length <= 40) for (const [i, v] of pts) svg.append(s('circle', { cx: x(i), cy: y(v), r: 3, class: 'dot' }));
  const first = s('text', { x: pad.l, y: H - 6 });
  first.textContent = String(labels[pts[0][0]] ?? '');
  const last = s('text', { x: W - pad.r, y: H - 6, 'text-anchor': 'end' });
  last.textContent = String(labels[pts[pts.length - 1][0]] ?? '');
  svg.append(first, last);
  return svg;
}

/** A button that shows it is busy while `fn` runs, and any error as a message. */
export function busy(button, fn) {
  return async (event) => {
    event?.preventDefault?.();
    if (button.disabled) return;
    const label = button.textContent;
    button.disabled = true;
    button.textContent = 'Working…';
    try {
      await fn(event);
    } catch (err) {
      toast(err && err.message ? err.message : 'Something went wrong.', 5000);
    } finally {
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = label;
      }
    }
  };
}
