// Share links: a link anyone can open, signed in or not, for one day's workout. The server part
// is "share links" in supabase/schema.sql: the link holds a random token, and opening it shows
// that day as it is now. Making and stopping a link needs the internet; the rest of the app doesn't.

import { h, icon, pageHead, formatDay, copyText, toast, busy } from './ui.js';
import { formatSetsDisplay } from '../core/logging.js';
import { WEB_APP_URL } from '../config.js';
import { isNative } from './native.js';

export const SHARE_PATH = /^s\/([0-9a-f]{32})$/;

/** The address to send: this website, or the public one from inside the phone app. */
export function shareUrl(token, { native = isNative, loc = globalThis.location } = {}) {
  const base = native ? WEB_APP_URL : `${loc.origin}${loc.pathname}`;
  return `${base}#/s/${token}`;
}

/** The text "Copy as text" gives on a shared workout, like the owner's own copy. */
export function sharedText(w, url = '') {
  const [y, m, d] = String(w.day).split('-').map(Number);
  const lines = [`${d}/${m}/${String(y % 100).padStart(2, '0')} ${w.workout_name || 'Workout'}`, ''];
  for (const e of w.exercises || []) lines.push(String(e.exercise_string || `${e.exercise}\n${formatSetsDisplay(e.sets)}`).trim(), '');
  if (url) lines.push(`Shared from Liftbook: ${url}`);
  return lines.join('\n').trim();
}

const offlineError = (err) => (err?.status === 0 ? new Error('Share links need the internet. Try again when you’re online.') : err);

// The day's link as last seen, so a redraw (a sync) doesn't flicker it away while it's checked again.
const seen = new Map();

/**
 * The "Share link" part of a workout page: a button, and once shared, the link with Copy,
 * Share and Stop sharing. ctx: the signed-in app.
 */
export function shareLinkBox(ctx, day, title) {
  const db = ctx.client.db;
  const box = h('div', { class: 'share-box' });
  const make = h('button', { class: 'btn', type: 'button' }, icon('share'), 'Share link');

  const paint = (token) => {
    seen.set(day, token || null);
    if (!token) return box.replaceChildren();
    const url = shareUrl(token);
    const stop = h('button', { class: 'btn small danger', type: 'button' }, 'Stop sharing');
    stop.addEventListener('click', busy(stop, async () => {
      if (!confirm('Stop sharing? The link stops working for everyone who has it.')) return;
      try {
        await db.rpc('stop_sharing_day', { share_day: day });
      } catch (err) {
        throw offlineError(err);
      }
      paint(null);
      make.hidden = false;
      toast('The link no longer works.');
    }));
    const send = navigator.share
      ? h('button', { class: 'btn small', type: 'button', onclick: () => navigator.share({ title: `${title} · ${formatDay(day)}`, url }).catch(() => {}) }, icon('share'), 'Send')
      : null;
    make.hidden = true;
    box.replaceChildren(h('div', { class: 'card share-card' },
      h('p', { class: 'muted', style: 'margin:0 0 8px' }, 'Anyone with this link can see this workout: the exercises, sets and new bests, and your username.'),
      h('a', { class: 'share-url mono', href: url, target: '_blank', rel: 'noopener' }, url),
      h('div', { class: 'row', style: 'margin-top:12px' },
        h('button', { class: 'btn small', type: 'button', onclick: () => copyText(url) }, icon('copy'), 'Copy link'),
        send, stop)));
  };

  make.addEventListener('click', busy(make, async () => {
    let token;
    try {
      await ctx.sync.runOnce(); // the workout has to be on the server for the link to show it
      token = await db.rpc('share_day', { share_day: day });
    } catch (err) {
      throw offlineError(err);
    }
    paint(token);
    if (navigator.share) {
      try {
        await navigator.share({ title: `${title} · ${formatDay(day)}`, url: shareUrl(token) });
      } catch {
        // Closed the share sheet: the link is still on the page to copy.
      }
    } else copyText(shareUrl(token));
  }));

  if (seen.get(day)) paint(seen.get(day));
  if (navigator.onLine !== false) {
    db.select(`share_links?select=token&day=eq.${day}`)
      .then((rows) => {
        const token = rows?.[0]?.token || null;
        if (token !== (seen.get(day) || null)) paint(token);
        if (!token) make.hidden = false;
      })
      .catch(() => {});
  }
  return { button: make, box };
}

/** The page a share link opens. signedIn: whether there's an app to go back to. */
export function sharedScreen(client, token, { signedIn = false } = {}) {
  const page = h('div', {}, pageHead('Shared workout', 'Loading…'));
  const load = async () => {
    let w;
    try {
      w = await client.db.rpcAnon('shared_workout', { share_token: token });
    } catch (err) {
      const retry = h('button', { class: 'btn', type: 'button' }, 'Try again');
      retry.addEventListener('click', busy(retry, load));
      page.replaceChildren(pageHead('Shared workout', err?.status === 0
        ? 'Couldn’t load it: no connection. A shared workout needs the internet.'
        : 'Couldn’t load it just now.'), retry);
      return;
    }
    const after = signedIn
      ? h('a', { class: 'btn', href: '#/' }, 'Your workouts')
      : h('div', { class: 'card', style: 'margin-top:18px' },
        h('h2', {}, 'Liftbook'),
        h('p', { class: 'muted' }, 'Log your workouts by pasting them from Notes, and see how each lift is going.'),
        h('div', { class: 'row' }, h('a', { class: 'btn primary', href: '#/signup' }, 'Create an account'), h('a', { class: 'btn', href: '#/signin' }, 'Sign in')));
    if (!w) {
      document.title = 'Link not found · Liftbook';
      page.replaceChildren(pageHead('Link not found', 'This workout isn’t shared any more: its owner stopped sharing it, or deleted it.'), after);
      return;
    }
    const ex = w.exercises || [];
    const sets = ex.reduce((n, e) => n + (Array.isArray(e.sets?.reps) ? e.sets.reps.length : 0), 0);
    const bests = ex.filter((e) => e.best).length;
    const url = location.href;
    document.title = `${w.workout_name || 'Workout'} · Liftbook`;
    page.replaceChildren(
      h('h1', { class: 'wo-title' }, w.workout_name || 'Workout'),
      h('p', { class: 'wo-meta' }, h('span', {}, w.username ? `Shared by ${w.username}` : 'Shared'), h('span', {}, formatDay(w.day)),
        h('span', {}, `${ex.length} exercise${ex.length === 1 ? '' : 's'}`), sets ? h('span', {}, `${sets} set${sets === 1 ? '' : 's'}`) : null,
        bests ? h('span', {}, `${bests} new best${bests === 1 ? '' : 's'}`) : null),
      h('div', { class: 'group', style: 'margin-top:18px' }, ex.map((e) => {
        const shown = formatSetsDisplay(e.sets) || String(e.exercise_string || '').split('\n').slice(1).join(', ');
        return h('div', { class: 'ex-row' },
          h('div', { class: 'main' },
            h('div', { class: 'title' }, e.exercise),
            h('div', { class: 'sets' }, String(shown).split(/,\s*/).filter(Boolean).map((t) => h('span', {}, t.replace(/ x /g, '×'))))),
          e.best ? h('div', { class: 'vs' }, h('span', { class: 'pill best' }, icon('medal'), 'New best')) : null);
      })),
      h('div', { class: 'row', style: 'margin-top:6px' },
        h('button', { class: 'btn', type: 'button', onclick: () => copyText(sharedText(w, url)) }, icon('copy'), 'Copy as text')),
      after);
  };
  load();
  return page;
}
