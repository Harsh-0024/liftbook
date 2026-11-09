// Share links: a link anyone can open, signed in or not, for one day's workout. The server part
// is "share links" in supabase/schema.sql: the link holds a random token, and opening it shows
// that day as it is now. Making and stopping a link needs the internet; the rest of the app doesn't.

import { h, icon, pageHead, formatDay, copyText, toast, busy, fmtNum, ask } from './ui.js';
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
      if (!await ask('The link stops working for everyone who has it.', { title: 'Stop sharing?', yes: 'Stop sharing', danger: true })) return;
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
      ? h('div', { class: 'row', style: 'margin-top:18px' }, h('a', { class: 'btn', href: '#/' }, icon('home'), 'Your workouts'))
      : h('section', { class: 'card share-cta' },
        h('div', { class: 'auth-brand' }, h('img', { class: 'logo', src: 'icons/icon-192.png', alt: '', width: 40, height: 40 }), h('span', {}, 'Liftbook')),
        h('h2', {}, w?.username ? `Train like ${w.username}.` : 'Your workouts, in one place.', h('br'), 'Log it in seconds.'),
        h('p', { class: 'muted' }, 'Keep writing your workouts in Notes. Paste one into Liftbook and it turns into personal bests and progress you can see, on every device, even offline.'),
        h('ul', { class: 'share-feats' },
          [['clipboard', 'Paste and done', 'No forms: paste your note, or type it the same way.'],
            ['medal', 'Automatic personal bests', 'A medal every time you beat your best.'],
            ['stats', 'Progress you can trust', 'Trends that see past one-off good or bad days.']]
            .map(([ico, t, d]) => h('li', {}, h('span', { class: 'share-feat-ico' }, icon(ico)), h('div', {}, h('b', {}, t), h('span', {}, d))))),
        h('div', { class: 'row' }, h('a', { class: 'btn primary', href: '#/signup' }, 'Start free'), h('a', { class: 'btn', href: '#/signin' }, 'Sign in')));
    if (!w) {
      document.title = 'Link not found · Liftbook';
      page.replaceChildren(pageHead('Link not found', 'This workout isn’t shared any more: its owner stopped sharing it, or deleted it. Ask them for a new link.'), after);
      return;
    }
    const ex = w.exercises || [];
    const sets = ex.reduce((n, e) => n + (Array.isArray(e.sets?.reps) ? e.sets.reps.length : 0), 0);
    const bests = ex.filter((e) => e.best).length;
    const url = location.href;
    const who = w.username || 'Someone';
    const plural = (n, word) => `${word}${n === 1 ? '' : 's'}`;
    document.title = `${w.workout_name || 'Workout'} · ${who} · Liftbook`;
    page.replaceChildren(
      h('section', { class: 'card share-hero' },
        h('div', { class: 'share-by' }, h('span', { class: 'share-avatar', 'aria-hidden': 'true' }, who.slice(0, 1).toUpperCase()),
          h('span', {}, h('b', {}, who), h('span', { class: 'muted' }, 'shared a workout'))),
        h('h1', {}, w.workout_name || 'Workout'),
        h('p', { class: 'muted' }, formatDay(w.day)),
        h('div', { class: 'nums', style: '--cols:3' },
          h('div', {}, h('b', {}, ex.length), h('span', {}, plural(ex.length, 'Exercise'))),
          h('div', {}, h('b', {}, sets), h('span', {}, plural(sets, 'Set'))),
          h('div', { class: bests ? 'gold' : 'zero' }, h('b', {}, bests), h('span', {}, plural(bests, 'New best'))))),
      h('div', { class: 'group share-list' },
        h('div', { class: 'share-list-head' }, h('span', {}, 'The workout'),
          h('button', { class: 'btn small', type: 'button', onclick: () => copyText(sharedText(w, url)) }, icon('copy'), 'Copy')),
        ex.map((e, i) => {
          const shown = formatSetsDisplay(e.sets) || String(e.exercise_string || '').split('\n').slice(1).join(', ');
          return h('div', { class: 'ex-row' },
            h('span', { class: 'share-num' }, String(i + 1).padStart(2, '0')),
            h('div', { class: 'main' },
              h('div', { class: 'title' }, e.exercise),
              h('div', { class: 'sets' }, String(shown).split(/,\s*/).filter(Boolean).map((t) => h('span', {}, t.replace(/ x /g, '×'))))),
            e.best ? h('div', { class: 'vs' }, h('span', { class: 'pill best', title: 'New personal best' }, icon('medal'),
              e.gain ? `+${fmtNum(e.gain)}%` : 'New best')) : null);
        })),
      h('div', { class: 'share-end', role: 'separator' }, h('span', {}, 'End of workout')),
      after);
  };
  load();
  return page;
}
