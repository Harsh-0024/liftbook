// Home (a welcome: you, two ways in, the last few workouts), every workout, one workout, and
// editing it. The layout follows the original app's.

import { h, icon, rowItem, pageHead, softDay, formatDay, copyText, toast, busy, fmtNum, autoGrow } from '../ui.js';
import { formatSetsDisplay } from '../../core/logging.js';
import { summaryTable } from './log.js';
import { attachSuggestions } from '../suggest.js';
import { attachPasteTidy } from '../paste.js';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** The person's photo, or their initial until it loads (or when there is none). */
function avatar(ctx, cls, attrs = {}) {
  const p = ctx.lb.profile() || {};
  const name = p.full_name || p.username || ctx.user?.email || '?';
  const el = h(attrs.href ? 'a' : 'div', { class: `avatar ${cls}`, ...attrs }, name.trim().charAt(0).toUpperCase());
  if (p.avatar_path) {
    ctx.lb.avatarUrl().then((url) => {
      if (!url) return;
      const img = h('img', { src: url, alt: '' });
      img.addEventListener('load', () => el.replaceChildren(img));
    }).catch(() => {});
  }
  return el;
}
export { avatar };

const hello = (now = new Date()) => {
  const hr = now.getHours();
  return hr >= 5 && hr < 12 ? 'Good morning' : hr >= 12 && hr < 17 ? 'Good afternoon' : 'Good evening';
};

export function homeScreen(ctx) {
  const { lb } = ctx;
  const profile = lb.profile() || {};
  const workouts = lb.workouts();
  const recent = workouts.slice(0, 3);
  const first = (profile.full_name || profile.username || '').trim().split(/\s+/)[0] || 'there';
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  const doneToday = recent[0]?.day === todayIso;
  const o = lb.overview();

  const actions = workouts.length
    ? [doneToday
      ? h('a', { class: 'btn primary big', href: `#/workout/${recent[0].day}` }, icon('check'), 'Today’s workout')
      : h('a', { class: 'btn primary big', href: '#/log' }, icon('plus'), 'Log workout'),
    h('a', { class: 'btn big', href: '#/retrieve' }, icon('list'), 'Retrieve')]
    : [h('a', { class: 'btn primary big', href: '#/retrieve' }, icon('list'), 'Retrieve a plan'),
      h('a', { class: 'btn big', href: '#/log' }, icon('plus'), 'Log workout')];

  return h('div', { class: 'home' },
    h('section', { class: 'hello' },
      avatar(ctx, 'big', { href: '#/settings/profile', 'aria-label': 'Profile and settings' }),
      h('p', { class: 'greet' }, workouts.length ? hello(today) : 'Welcome'),
      h('h1', {}, first),
      doneToday ? h('p', { class: 'note' }, 'Nice work today.')
        : !workouts.length ? h('p', { class: 'note muted' }, 'Your workouts will show up here.') : null),
    h('div', { class: 'home-actions' }, actions),
    workouts.length ? h('section', { class: 'section', 'aria-label': 'Recent workouts' },
      h('div', { class: 'label' }, 'Recent'),
      h('div', { class: 'group' }, recent.map((w) => rowItem({
        href: `#/workout/${w.day}`, title: w.title, value: softDay(w.day, today),
      }))),
      h('div', { class: 'grid-3 home-stats' },
        h('div', { class: 'stat' }, h('span', {}, 'Workouts'), h('b', {}, o.total)),
        h('div', { class: 'stat' }, h('span', {}, 'This week'), h('b', { class: 'gold' }, o.thisWeek)),
        h('div', { class: 'stat' }, h('span', {}, 'Exercises'), h('b', {}, o.exercises))),
      h('a', { class: 'see-all', href: '#/history' }, 'See all workouts')) : null);
}

/** Every workout, a month at a time, with a search. */
export function historyScreen(ctx) {
  const { lb } = ctx;
  const workouts = lb.workouts();
  const search = h('input', { type: 'search', placeholder: 'Search workouts or exercises', 'aria-label': 'Search workouts', autocomplete: 'off' });
  const body = h('div', {});
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    const shown = q
      ? workouts.filter((w) => w.title.toLowerCase().includes(q) || w.logs.some((l) => String(l.exercise).toLowerCase().includes(q)) || w.day.includes(q))
      : workouts;
    const months = new Map();
    for (const w of shown) {
      const k = w.day.slice(0, 7);
      if (!months.has(k)) months.set(k, []);
      months.get(k).push(w);
    }
    body.replaceChildren(...(shown.length ? [...months].map(([k, ws]) => {
      const [y, m] = k.split('-').map(Number);
      return h('section', { class: 'section' },
        h('div', { class: 'label' }, `${MONTHS[m - 1]} ${y}`, h('span', {}, `${ws.length} workout${ws.length === 1 ? '' : 's'}`)),
        h('div', { class: 'group' }, ws.map((w) => {
          const [yy, mm, dd] = w.day.split('-').map(Number);
          return h('a', { class: 'rowi', href: `#/workout/${w.day}` },
            h('span', { class: 'datebox' }, h('b', {}, dd), h('small', {}, WD[new Date(Date.UTC(yy, mm - 1, dd)).getUTCDay()])),
            h('span', { class: 'main' }, h('span', { class: 'title' }, w.title),
              h('span', { class: 'desc ellipsis' }, w.logs.map((l) => l.exercise).join(' · '))),
            h('span', { class: 'chev-i' }, icon('chev')));
        })));
    }) : [h('div', { class: 'group empty' }, icon('search'), q ? `Nothing matches “${search.value.trim()}”.` : 'No workouts yet.')]));
  };
  search.addEventListener('input', paint);
  paint();
  return h('div', {},
    pageHead('All workouts', `${workouts.length} workout${workouts.length === 1 ? '' : 's'} logged.`, { back: '#/' }),
    h('div', { class: 'search' }, icon('search'), search),
    body);
}

const signed = (v, digits = 1) => (v === null || v === undefined ? '' : `${v > 0 ? '+' : v < 0 ? '−' : '±'}${fmtNum(Math.abs(v), digits)}%`);

function vsRecent(c) {
  if (c.status === 'first') return h('span', { class: 'flat' }, 'First time');
  if (c.vsRecent === null) return h('span', { class: 'flat' }, '—');
  if (Math.abs(c.vsRecent) < 0.5) return h('span', { class: 'flat' }, icon('right'), ' Steady');
  return h('span', { class: c.vsRecent > 0 ? 'up' : 'down' }, icon(c.vsRecent > 0 ? 'up' : 'down'), ` ${fmtNum(Math.abs(c.vsRecent), 1)}%`);
}

function vsBest(c) {
  if (c.status === 'first' || c.vsBest === null) return h('span', { class: 'flat' }, '');
  if (c.vsBest > 0.05) return h('span', {}, h('span', { class: 'pill best' }, icon('medal'), signed(c.vsBest)));
  if (Math.abs(c.vsBest) <= 0.05) return h('span', { class: 'flat' }, '= Best');
  return h('span', { class: 'flat' }, signed(c.vsBest));
}

export function workoutScreen(ctx, day) {
  const { lb } = ctx;
  const w = lb.workout(day);
  if (!w) {
    return h('div', {}, pageHead('Workout not found', 'It may have been deleted on another device.', { back: '#/history' }),
      h('a', { class: 'btn', href: '#/history' }, 'All workouts'));
  }
  const saved = ctx.lastSaved && ctx.lastSaved.day === day ? ctx.lastSaved : null;
  ctx.lastSaved = null;
  const bw = w.logs.find((l) => l.bodyweight)?.bodyweight;
  const cmp = lb.compareWorkout(day);
  const count = (s) => cmp.filter((c) => c.status === s).length;
  const moved = (sign) => cmp.filter((c) => c.status !== 'first' && c.vsRecent !== null && sign * c.vsRecent > 0.5).length;
  const sets = w.logs.reduce((n, l) => n + (Array.isArray(l.sets?.reps) ? l.sets.reps.length : 0), 0);

  const del = h('button', { class: 'btn danger', type: 'button' }, icon('trash'), 'Delete');
  del.addEventListener('click', busy(del, async () => {
    if (!confirm(`Delete ${w.title} on ${formatDay(day)}? This removes it from all your devices.`)) return;
    await lb.deleteWorkout(day);
    toast('Workout deleted.');
    ctx.go('history');
  }));
  const share = async () => {
    const text = lb.workoutText(w);
    if (navigator.share) {
      try {
        await navigator.share({ title: `${w.title} · ${formatDay(day)}`, text });
        return;
      } catch (err) {
        if (err && err.name === 'AbortError') return;
      }
    }
    copyText(text);
  };

  const nums = [['New bests', count('best'), 'gold'], ['Improving', moved(1), 'good'], ['Dipping', moved(-1), 'bad'],
    ['Steady', cmp.filter((c) => c.status !== 'first' && (c.vsRecent === null || Math.abs(c.vsRecent) <= 0.5)).length, '']];
  return h('div', {},
    h('div', { class: 'wo-head' },
      h('a', { class: 'back', href: '#/history', 'aria-label': 'All workouts' }, icon('back')),
      h('div', { class: 'tools' },
        h('a', { class: 'icon-btn', href: `#/workout/${day}/edit`, 'aria-label': 'Edit', title: 'Edit' }, icon('edit')),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Share', title: 'Share', onclick: share }, icon('share')))),
    h('h1', { class: 'wo-title' }, w.title),
    h('p', { class: 'wo-meta' }, h('span', {}, formatDay(day)), h('span', {}, `${w.logs.length} exercise${w.logs.length === 1 ? '' : 's'}`),
      sets ? h('span', {}, `${sets} set${sets === 1 ? '' : 's'}`) : null, bw ? h('span', {}, `bodyweight ${fmtNum(bw)}`) : null),
    saved ? h('div', { class: 'card gold', style: 'margin-top:18px' },
      h('h2', {}, saved.appended ? 'Added to this workout' : 'Saved'),
      summaryTable(saved.summary),
      saved.skipped?.length ? h('ul', { class: 'errors' }, saved.skipped.map((s) => h('li', {}, s))) : null) : null,
    h('div', { class: 'group', style: 'margin-top:18px' },
      cmp.some((c) => c.status !== 'first')
        ? h('div', { class: 'nums', style: 'border-bottom:1px solid var(--hair)' }, nums.map(([label, n, cls]) =>
          h('div', { class: n ? cls : 'zero' }, h('b', {}, n), h('span', {}, label))))
        : null,
      h('div', { class: 'ex-cols', 'aria-hidden': 'true' }, h('span', {}, 'Exercise'), h('span', {}, 'vs recent'), h('span', {}, 'vs best')),
      cmp.map((c) => {
        const shown = formatSetsDisplay(c.log.sets) || String(c.log.exercise_string || '').split('\n').slice(1).join(', ');
        return h('div', { class: 'ex-row' },
          h('div', { class: 'main' },
            h('div', { class: 'title' }, c.log.exercise),
            h('div', { class: 'sets' }, String(shown).split(/,\s*/).filter(Boolean).map((t) => h('span', {}, t.replace(/ x /g, '×'))))),
          h('div', { class: 'vs' }, vsRecent(c), vsBest(c)));
      })),
    h('div', { class: 'row', style: 'margin-top:6px' },
      h('a', { class: 'btn', href: `#/workout/${day}/edit` }, icon('edit'), 'Edit'),
      h('button', { class: 'btn', type: 'button', onclick: () => copyText(lb.workoutText(w)) }, icon('copy'), 'Copy as text'),
      del));
}

export function editScreen(ctx, day) {
  const { lb } = ctx;
  const w = lb.workout(day);
  if (!w) return workoutScreen(ctx, day);
  const ta = h('textarea', { id: 'workout_text', class: 'editor', spellcheck: 'false', autocapitalize: 'off', 'aria-label': 'The workout as text' }, lb.workoutText(w));
  autoGrow(ta);
  const suggest = attachSuggestions(ta, () => lb.exerciseCatalog().map((e) => e.name));
  attachPasteTidy(ta);
  const err = h('div', { role: 'alert' });
  const btn = h('button', { class: 'btn primary small', type: 'button' }, 'Save');
  btn.addEventListener('click', busy(btn, async () => {
    const r = await lb.log(ta.value, { replaceDay: day });
    if (r.existing) {
      err.replaceChildren(h('p', { class: 'errors' }, `There is already a workout on ${formatDay(r.existing.day)}. Change the date or edit that one.`));
      return;
    }
    if (r.error) {
      err.replaceChildren(h('ul', { class: 'errors' }, (r.errors || [r.error]).map((e) => h('li', {}, e))));
      return;
    }
    ctx.lastSaved = r;
    toast('Workout updated.');
    ctx.go(`workout/${r.day}`);
  }));
  return h('div', {},
    pageHead('Edit workout', 'The first line is the date and title. Change the date to move the workout.', { back: `#/workout/${day}` }),
    h('div', { class: 'group editor-wrap' },
      ta,
      suggest,
      h('div', { class: 'editor-bar' },
        h('span', { class: 'editor-meta' }, w.title),
        h('div', { class: 'row' }, h('a', { class: 'btn small', href: `#/workout/${day}` }, 'Cancel'), btn))),
    err);
}
