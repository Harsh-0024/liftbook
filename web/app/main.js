// Starting the app: the sign-in, the account's own database on this device, sync, and the
// screens (one page, addresses after "#").

import { SUPABASE_URL, SUPABASE_ANON_KEY } from '../config.js';
import { createClient } from './supabase.js';
import { Store, idbBackend, deleteDatabase } from './store.js';
import { createSync, startAutoSync } from './sync.js';
import { Liftbook } from './data.js';
import { h, toast, ago } from './ui.js';
import { authScreens, welcomeScreen, resetScreen } from './screens/auth.js';
import { homeScreen, historyScreen, workoutScreen, editScreen } from './screens/home.js';
import { logScreen, DRAFT_KEY } from './screens/log.js';
import { retrieveScreen, retrieveDayScreen, retrieveCustomScreen } from './screens/retrieve.js';
import { statsScreen } from './screens/stats.js';
import { settingsScreen } from './screens/settings.js';
import { coachScreen } from './screens/coach.js';
import { isNative, startNative, wantsApp, appHandOff } from './native.js';

const main = document.getElementById('app');
document.getElementById('year').textContent = String(new Date().getFullYear());
const pill = document.getElementById('sync-pill');
const client = createClient({ url: SUPABASE_URL, key: SUPABASE_ANON_KEY });
const dbName = (uid) => `liftbook-${uid}`;

let ctx = null; // the signed-in app: {lb, store, sync, client, ...}
let stopSync = null;
let current = null; // the screen on show: {name, live}

/* ---------------- routes ---------------- */

const ROUTES = [
  [/^$/, 'home', homeScreen, true],
  [/^log$/, 'log', logScreen],
  [/^history$/, 'home', historyScreen, true],
  [/^workout\/(\d{4}-\d{2}-\d{2})$/, 'home', workoutScreen, true],
  [/^workout\/(\d{4}-\d{2}-\d{2})\/edit$/, 'home', editScreen],
  [/^retrieve$/, 'retrieve', retrieveScreen, true],
  [/^retrieve\/custom$/, 'retrieve', retrieveCustomScreen],
  [/^retrieve\/day\/([^/]+)\/(\d+)$/, 'retrieve', retrieveDayScreen],
  [/^stats$/, 'stats', statsScreen],
  [/^coach$/, 'coach', coachScreen],
  [/^settings(?:\/([a-z-]+))?$/, 'settings', settingsScreen],
  [/^welcome$/, 'settings', welcomeScreen],
];

const path = () => decodeURIComponent(location.hash.replace(/^#\/?/, '').split('?')[0]);
export const go = (to) => {
  if (location.hash === `#/${to}`) render();
  else location.hash = `#/${to}`;
};

async function render() {
  if (!ctx) return renderSignedOut();
  const p = path();
  if (p === 'signin' || p === 'signup' || p === 'forgot') return go('');
  if (p === 'reset') return show(resetScreen(ctx), 'settings');
  if (!ctx.lb.profile() && p !== 'welcome' && ctx.store.getMeta('first_sync_done')) return go('welcome');
  for (const [re, nav, screen, live] of ROUTES) {
    const m = re.exec(p);
    if (!m) continue;
    current = { nav, live: Boolean(live) };
    try {
      return show(await screen(ctx, ...m.slice(1)), nav);
    } catch (err) {
      console.error(err);
      return show(h('div', { class: 'card' }, h('h2', {}, 'Something went wrong'), h('p', { class: 'muted' }, String(err.message || err))), nav);
    }
  }
  return go('');
}

let shownPath = null;
function show(el, nav) {
  el.classList?.add('screen');
  main.classList.toggle('wide', Boolean(el.dataset?.wide));
  const hadFocus = main.contains(document.activeElement) && document.activeElement !== main;
  // A synced change redraws the page you're on: keep what's typed in its search boxes, and the
  // cursor if you were typing there.
  const same = shownPath === path();
  const kept = same ? [...main.querySelectorAll('input[type=search]')].map((i) => ({
    label: i.getAttribute('aria-label'), value: i.value, focused: i === document.activeElement,
    start: i.selectionStart, end: i.selectionEnd })).filter((k) => k.value || k.focused) : [];
  main.replaceChildren(el);
  for (const k of kept) {
    const i = [...main.querySelectorAll('input[type=search]')].find((x) => x.getAttribute('aria-label') === k.label);
    if (!i) continue;
    if (k.value && !i.value) {
      i.value = k.value;
      i.dispatchEvent(new Event('input', { bubbles: true }));
    }
    if (k.focused) {
      i.focus({ preventScroll: true });
      i.setSelectionRange?.(k.start, k.end);
    }
  }
  for (const a of document.querySelectorAll('[data-nav]')) {
    a.classList.toggle('active', a.dataset.nav === nav);
    if (a.dataset.nav === nav) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  if (!show.keepScroll) window.scrollTo(0, 0);
  show.keepScroll = false;
  // Each page has its own title, and moving to a new page puts focus on its heading, so a
  // screen reader says where you are (as a full page load would).
  const title = main.querySelector('h1');
  const name = title?.textContent.trim();
  document.title = name && path() ? `${name} · Liftbook` : 'Liftbook';
  const moved = shownPath !== null && !same;
  shownPath = path();
  // A redraw of the same page only moves focus if it took away the element that had it.
  if (title && (moved || hadFocus) && !main.contains(document.activeElement)) {
    title.setAttribute('tabindex', '-1');
    title.focus({ preventScroll: true });
  }
}

function renderSignedOut() {
  document.body.classList.add('signed-out');
  const p = path();
  show(authScreens({ client, onSignedIn: start, go }, p === 'signup' || p === 'forgot' ? p : 'signin'), '');
}

/* ---------------- signed in ---------------- */

async function start() {
  const user = client.auth.user();
  if (!user) return render();
  document.body.classList.remove('signed-out');
  const store = await Store.open(idbBackend(dbName(user.id)));
  const lb = new Liftbook(store, client, user.id);
  const sync = createSync({ store, db: client.db, userId: user.id });
  ctx = { lb, store, sync, client, user, go, toast, signOut, refresh: () => render() };

  sync.onStatus(paintPill);
  paintPill(sync.status());
  // Remote changes redraw screens that only show data (never one being typed in).
  store.subscribe(({ local }) => {
    if (!local && current?.live) {
      show.keepScroll = true;
      render();
    }
  });
  stopSync = startAutoSync(sync, store);
  lb.refreshShared();
  render();

  // The first sync on this device decides whether the account still needs a username.
  if (!store.getMeta('first_sync_done')) {
    const r = await sync.runOnce();
    if (!r.error) {
      await store.setMeta('first_sync_done', true);
      if (!lb.profile()) {
        const meta = user.user_metadata || {};
        if (meta.username && (await lb.usernameAvailable(meta.username).catch(() => false))) {
          await lb.saveProfile({ username: meta.username, full_name: meta.full_name || '' });
        }
      }
      render();
    }
  }
}

function paintPill(st) {
  if (!ctx) return;
  pill.hidden = false;
  pill.classList.remove('warn', 'busy');
  if (st.running) {
    pill.textContent = 'Syncing';
    pill.classList.add('busy');
  }
  else if (st.error === 'offline') {
    pill.textContent = st.pending ? `Offline · ${st.pending} to sync` : 'Offline';
    pill.classList.add('warn');
  } else if (st.error) {
    pill.textContent = 'Sync problem';
    pill.title = st.error;
    pill.classList.add('warn');
  } else if (st.pending) pill.textContent = `${st.pending} to sync`;
  else pill.textContent = `Synced ${ago(st.last_sync)}`;
}

// "Synced 3 min ago" keeps counting between syncs.
setInterval(() => { if (ctx && !pill.hidden) paintPill(ctx.sync.status()); }, 30000);

pill.addEventListener('click', async () => {
  if (!ctx) return;
  const r = await ctx.sync.runOnce();
  if (r.error === 'offline') toast('No connection. Your changes are kept on this device.');
  else if (r.error) toast(r.error, 5000);
  else toast(r.down ? `Up to date: ${r.down} change${r.down === 1 ? '' : 's'} from your other devices.` : 'Up to date.');
});

/** Sign out of this device. Changes not yet synced would be lost, so it asks first. */
async function signOut({ force = false } = {}) {
  if (!ctx) return;
  if (!force) {
    await ctx.sync.runOnce();
    const pending = ctx.store.pendingCount();
    if (pending && !confirm(`${pending} change${pending === 1 ? ' hasn’t' : 's haven’t'} reached the server yet (you’re offline?). Sign out anyway and lose ${pending === 1 ? 'it' : 'them'}?`)) return;
  }
  const uid = ctx.user.id;
  stopSync?.();
  await ctx.store.backend.close?.();
  ctx = null;
  pill.hidden = true;
  await client.auth.signOut();
  // This device keeps nothing of the account once signed out, the half-typed workout included.
  await deleteDatabase(dbName(uid)).catch(() => {});
  try {
    localStorage.removeItem(DRAFT_KEY);
  } catch {
    // storage blocked: nothing was kept
  }
  location.hash = '#/signin';
  render();
}

/* ---------------- start ---------------- */

async function boot() {
  if (!SUPABASE_ANON_KEY) {
    show(h('div', { class: 'card auth' }, h('h2', {}, 'Not set up yet'),
      h('p', { class: 'muted' }, 'Put the Supabase project’s anon key in web/config.js.')), '');
    return;
  }
  // Back from an emailed link: confirming the account or a new email, or resetting the password.
  if (/access_token=|error_description=|message=/.test(location.hash)) {
    // Asked for in the Android app: hand it on to the app, unless the person carries on here.
    if (wantsApp()) {
      const carriedOn = await new Promise((resolve) => show(appHandOff(h, location.hash, () => resolve(true)), ''));
      if (carriedOn) history.replaceState(null, '', location.pathname + location.hash);
    }
    try {
      // A new email confirmed from the old address only: Supabase asks for the other link too.
      const message = new URLSearchParams(location.hash.replace(/^#/, '')).get('message');
      const link = await client.auth.fromLink(location.hash);
      history.replaceState(null, '', location.pathname + (link && link.type === 'recovery' ? '#/reset' : link ? '#/' : '#/settings/account'));
      if (link?.type === 'email_change') toast('Your email has been changed.', 5000);
      else if (link && link.type !== 'recovery') toast('Email confirmed. Welcome to Liftbook.');
      else if (!link && message) toast(`${message}.`.replace(/\.\.$/, '.'), 8000);
    } catch (err) {
      history.replaceState(null, '', `${location.pathname}#/signin`);
      toast(err.message || 'That link has expired. Ask for a new one.', 6000);
    }
  }
  window.addEventListener('hashchange', render);
  // "Skip to content" for keyboards: the hash is the router's, so move focus instead of linking.
  document.querySelector('.skip')?.addEventListener('click', (e) => {
    e.preventDefault();
    main.focus();
  });
  // Signed out elsewhere (the sign-in was revoked): back to the sign-in page. The data here
  // stays, so signing in again picks up any changes not yet synced.
  client.auth.onChange((session) => {
    if (session || !ctx) return;
    stopSync?.();
    ctx = null;
    pill.hidden = true;
    toast('Your sign-in has expired. Sign in again.', 5000);
    render();
  });
  startNative({
    // An emailed link opened the app: start again from it, the way the website does.
    onLink(url) {
      const hash = String(url).includes('#') ? `#${String(url).split('#')[1]}` : '';
      try {
        if (!hash || sessionStorage.getItem('liftbook-link') === url) return;
        sessionStorage.setItem('liftbook-link', url);
      } catch {
        // storage blocked: the link is still opened once
      }
      history.replaceState(null, '', location.pathname + hash);
      location.reload();
    },
    onResume: () => ctx?.sync.runOnce(),
    onOnline: () => ctx?.sync.runOnce(),
    // Android's back button: back a screen, or out of the app from the home screen.
    onBack(canGoBack) {
      if (!path()) return false;
      if (canGoBack) history.back();
      else go('');
      return true;
    },
  });
  if (client.auth.session()) await start();
  else render();
}

// The offline copy is for the website; the Android app already carries every file.
if ('serviceWorker' in navigator && location.protocol !== 'file:' && !isNative) {
  // A new version takes over as soon as it has installed; reload once so this page runs it too
  // (the log draft is kept on the device, so nothing typed is lost). Not on the very first visit.
  const hadVersion = !!navigator.serviceWorker.controller;
  let reloaded = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (hadVersion && !reloaded) { reloaded = true; location.reload(); }
  });
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch((err) => console.warn('offline copy unavailable', err));
  });
}
// Ask the browser to keep this site's storage (Safari clears unused sites' data otherwise).
navigator.storage?.persist?.().catch(() => {});

boot();
