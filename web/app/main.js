// Starting the app: the sign-in, the account's own database on this device, sync, and the
// screens (one page, addresses after "#").

import { SUPABASE_URL, SUPABASE_ANON_KEY } from '../config.js';
import { createClient } from './supabase.js';
import { Store, idbBackend, deleteDatabase } from './store.js';
import { createSync, startAutoSync } from './sync.js';
import { Liftbook } from './data.js';
import { h, toast, ago } from './ui.js';
import { authScreens, welcomeScreen, resetScreen } from './screens/auth.js';
import { homeScreen, workoutScreen, editScreen } from './screens/home.js';
import { logScreen } from './screens/log.js';
import { retrieveScreen, retrieveDayScreen, retrieveCustomScreen } from './screens/retrieve.js';
import { statsScreen } from './screens/stats.js';
import { settingsScreen } from './screens/settings.js';
import { coachScreen } from './screens/coach.js';

const main = document.getElementById('app');
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

function show(el, nav) {
  main.replaceChildren(el);
  for (const a of document.querySelectorAll('[data-nav]')) a.classList.toggle('active', a.dataset.nav === nav);
  if (!show.keepScroll) window.scrollTo(0, 0);
  show.keepScroll = false;
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
  pill.classList.remove('warn');
  if (st.running) pill.textContent = 'Syncing…';
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
  // This device keeps nothing of the account once signed out.
  await deleteDatabase(dbName(uid)).catch(() => {});
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
  // Back from an emailed link: confirming the account, or resetting the password.
  if (/access_token=|error_description=/.test(location.hash)) {
    try {
      const link = await client.auth.fromLink(location.hash);
      history.replaceState(null, '', location.pathname + (link && link.type === 'recovery' ? '#/reset' : '#/'));
      if (link && link.type !== 'recovery') toast('Email confirmed. Welcome to Liftbook.');
    } catch (err) {
      history.replaceState(null, '', `${location.pathname}#/signin`);
      toast(err.message || 'That link has expired. Ask for a new one.', 6000);
    }
  }
  window.addEventListener('hashchange', render);
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
  if (client.auth.session()) await start();
  else render();
}

if ('serviceWorker' in navigator && location.protocol !== 'file:') {
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
