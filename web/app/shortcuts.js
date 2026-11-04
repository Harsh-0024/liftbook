// Keyboard shortcuts on a computer, as the original app had them (templates/base.html):
// H home, L log, R retrieve, S settings, G stats, K coach, A admin (admins), 1-9 a session on
// Retrieve, / search, ? this list.
// Never while typing, with a modifier held, or from behind an open dialog.

import { h } from './ui.js';

const KEYS = [
  ['H', 'Go to home', ''], ['L', 'Log workout', 'log'], ['R', 'Retrieve plan', 'retrieve'],
  ['1-9', 'Pick a session (on Retrieve)'], ['S', 'Settings', 'settings'], ['G', 'View stats', 'stats'],
  ['K', 'Ask the coach', 'coach'], ['/', 'Search (history or stats)'], ['?', 'Show these shortcuts'],
];
const ADMIN_KEYS = [['A', 'Admin', 'settings/admin']];

function typing(el) {
  if (!el || el === document.body) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  return !['button', 'checkbox', 'radio', 'range', 'submit', 'reset', 'color', 'file'].includes((el.type || '').toLowerCase());
}

let dialog = null;
function toggleHelp(admin) {
  if (dialog?.open) { dialog.close(); return; }
  dialog?.remove(); // drawn fresh: the admin keys come and go with the account
  dialog = h('dialog', { class: 'keys-dialog', 'aria-labelledby': 'keys-title' },
    h('h2', { id: 'keys-title' }, 'Keyboard shortcuts'),
    h('dl', {}, [...KEYS, ...(admin ? ADMIN_KEYS : [])].flatMap(([k, what]) => [h('dt', {}, h('kbd', {}, k)), h('dd', {}, what)])),
    h('form', { method: 'dialog' }, h('button', { class: 'btn small', type: 'submit' }, 'Close')));
  dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
  document.body.append(dialog);
  dialog.showModal();
}

/** signedIn(): whether the app pages (not the sign-in pages) are showing. go(path) opens a page. */
export function installShortcuts({ signedIn, isAdmin = () => false, go }) {
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
    if (typing(e.target) || !signedIn()) return;
    if (document.querySelector('dialog[open]:not(.keys-dialog)')) return;
    const key = (e.key || '').toLowerCase();
    if (key === '?' || (e.shiftKey && key === '/')) { e.preventDefault(); toggleHelp(isAdmin()); return; }
    if (dialog?.open) return;
    if (/^[1-9]$/.test(key)) {
      if (!/^#\/retrieve\/?$/.test(location.hash)) return;
      const target = document.querySelectorAll('main a[href^="#/retrieve/day/"]')[Number(key) - 1];
      if (target) { e.preventDefault(); target.click(); }
      return;
    }
    if (key === '/') {
      const search = document.querySelector('main input[type="search"], main input#search, main select#exercise');
      if (search) { e.preventDefault(); search.focus(); }
      return;
    }
    const to = [...KEYS, ...(isAdmin() ? ADMIN_KEYS : [])].find(([k, , path]) => path !== undefined && k.toLowerCase() === key);
    if (to) { e.preventDefault(); go(to[2]); }
  });
}
