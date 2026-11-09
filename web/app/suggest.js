// Exercise-name suggestions while typing a name at the start of a line, as the old Log page had:
// up to six names you've used, those starting with what you typed first. Arrow keys move, Tab or
// a tap picks, Escape closes.

import { h } from './ui.js';

const SEPARATORS = [' - [', ' - ', ' – ', ' — ', ':', '['];

/**
 * The name being typed at the cursor, or null when the cursor isn't in one: the first line is the
 * date and title, and lines starting with a number or "bw" are sets.
 */
export function nameAt(value, cursor, { firstLineIsTitle = true } = {}) {
  const lineStart = value.lastIndexOf('\n', cursor - 1) + 1;
  let lineEnd = value.indexOf('\n', cursor);
  if (lineEnd === -1) lineEnd = value.length;
  const line = value.slice(lineStart, lineEnd);
  const trimmed = line.trim();
  if (!trimmed || /^[\d,.\-]/.test(trimmed) || /^bw/i.test(trimmed)) return null;
  if (firstLineIsTitle && value.slice(0, lineStart).trim() === '') return null;
  let cut = line.length;
  for (const sep of SEPARATORS) {
    const i = line.indexOf(sep);
    if (i !== -1 && i < cut) cut = i;
  }
  const caret = cursor - lineStart;
  if (caret > cut) return null;
  const leading = line.match(/^\s*/)[0];
  const prefix = line.slice(leading.length, caret).trim();
  if (prefix.length < 2 || /\d/.test(prefix)) return null;
  // Mid-word: the rest of the name is replaced too; otherwise what follows the cursor stays.
  const keepFrom = /^[A-Za-z]/.test(line.slice(caret, cut)) ? cut : caret;
  return { lineStart, lineEnd, leading, prefix, suffix: line.slice(keepFrom) };
}

/** Names starting with the prefix, then names containing it; never the name already typed. */
export function matchNames(names, prefix, max = 6) {
  const q = prefix.toLowerCase();
  const starts = names.filter((n) => n.toLowerCase().startsWith(q));
  const contains = names.filter((n) => !n.toLowerCase().startsWith(q) && n.toLowerCase().includes(q));
  return starts.concat(contains).filter((n) => n.toLowerCase() !== q).slice(0, max);
}

/** The text with the name at the cursor replaced, and where the cursor goes. */
export function applyName(value, at, name) {
  const text = value.slice(0, at.lineStart) + at.leading + name + at.suffix + value.slice(at.lineEnd);
  return { text, cursor: at.lineStart + at.leading.length + name.length };
}

/** Where the cursor's line sits inside the textarea, measured with a hidden copy of it. */
function caretTop(ta) {
  const style = getComputedStyle(ta);
  const mirror = document.createElement('div');
  for (const k of ['boxSizing', 'width', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'borderTopWidth',
    'borderLeftWidth', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'wordSpacing', 'tabSize']) mirror.style[k] = style[k];
  Object.assign(mirror.style, { position: 'absolute', visibility: 'hidden', whiteSpace: 'pre-wrap', overflowWrap: 'break-word' });
  mirror.textContent = ta.value.slice(0, ta.selectionStart || 0);
  const marker = mirror.appendChild(document.createElement('span'));
  marker.textContent = '​';
  document.body.appendChild(mirror);
  const top = marker.offsetTop;
  mirror.remove();
  return { top: top - ta.scrollTop, lineHeight: parseFloat(style.lineHeight) || 22 };
}

/**
 * Wires suggestions to a textarea. Returns the list element: put it next to the textarea inside
 * an element with position: relative.
 */
export function attachSuggestions(ta, getNames, options) {
  const box = h('div', { class: 'suggest', role: 'listbox', 'aria-label': 'Exercise names', hidden: true });
  let items = [];
  let active = 0;
  let names = null;
  const hide = () => {
    box.hidden = true;
    box.replaceChildren();
    items = [];
    ta.removeAttribute('aria-activedescendant');
  };
  const paint = () => {
    if (!items.length) return hide();
    box.replaceChildren(...items.map((name, i) => h('button', {
      type: 'button', role: 'option', id: `suggest-${i}`, tabindex: '-1',
      class: i === active ? 'active' : '', 'aria-selected': String(i === active), 'data-i': String(i),
    }, name)));
    const { top, lineHeight } = caretTop(ta);
    box.style.top = `${ta.offsetTop + top + lineHeight + 4}px`;
    box.hidden = false;
    ta.setAttribute('aria-activedescendant', `suggest-${active}`);
  };
  const update = () => {
    const at = nameAt(ta.value, ta.selectionStart || 0, options);
    if (!at || ta.selectionStart !== ta.selectionEnd) return hide();
    names ??= getNames();
    items = matchNames(names, at.prefix);
    active = 0;
    paint();
  };
  const pick = (i) => {
    const at = nameAt(ta.value, ta.selectionStart || 0, options);
    if (!items[i] || !at) return;
    const { text, cursor } = applyName(ta.value, at, items[i]);
    ta.value = text;
    ta.setSelectionRange(cursor, cursor);
    hide();
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    hide();
  };
  ta.addEventListener('input', update);
  ta.addEventListener('click', update);
  ta.addEventListener('keydown', (e) => {
    if (box.hidden || !items.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
      paint();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      pick(active);
    } else if (e.key === 'Escape') hide();
  });
  // pointerdown with preventDefault keeps the keyboard up and the cursor in the box while picking.
  box.addEventListener('pointerdown', (e) => {
    const b = e.target.closest('button[data-i]');
    if (!b) return;
    e.preventDefault();
    pick(Number(b.dataset.i));
  });
  ta.addEventListener('blur', () => setTimeout(hide, 150));
  return box;
}
