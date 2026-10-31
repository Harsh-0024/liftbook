// Home (the workout history), one workout, and editing it.

import { h, formatDay, copyText, toast, busy, fmtNum } from '../ui.js';
import { formatSetsDisplay } from '../../core/logging.js';
import { summaryTable } from './log.js';

const PAGE = 30;

export function homeScreen(ctx) {
  const { lb } = ctx;
  const profile = lb.profile();
  const o = lb.overview();
  const workouts = lb.workouts();
  let shown = PAGE;

  const list = h('ul', { class: 'list' });
  const more = h('button', { class: 'btn block', type: 'button' }, 'Show more');
  const paint = () => {
    list.replaceChildren(...workouts.slice(0, shown).map((w) => h('li', {},
      h('a', { class: 'item chev', href: `#/workout/${w.day}` },
        h('div', {},
          h('div', { style: 'font-weight:600' }, w.title),
          h('div', { class: 'meta' }, `${formatDay(w.day)} · ${w.logs.length} exercise${w.logs.length === 1 ? '' : 's'}`))))));
    more.hidden = shown >= workouts.length;
  };
  more.addEventListener('click', () => {
    shown += PAGE;
    paint();
  });
  paint();

  const first = (profile?.full_name || profile?.username || '').split(' ')[0];
  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, first ? `Hi, ${first}` : 'Your workouts'), h('p', { class: 'muted', style: 'margin:0' }, 'Type a workout, see what to lift next.')),
      h('a', { class: 'btn primary', href: '#/log' }, 'Log a workout')),
    h('div', { class: 'grid-3', style: 'margin-bottom:14px' },
      h('div', { class: 'stat' }, h('b', {}, o.total), h('span', {}, 'workouts')),
      h('div', { class: 'stat' }, h('b', {}, o.thisWeek), h('span', {}, 'this week')),
      h('div', { class: 'stat' }, h('b', {}, o.exercises), h('span', {}, 'exercises'))),
    workouts.length
      ? h('div', { class: 'card' }, h('h2', {}, 'History'), list, more)
      : h('div', { class: 'card center' },
        h('h2', {}, 'No workouts yet'),
        h('p', { class: 'muted' }, 'Log your first one: type the date and title, then each exercise with its sets.'),
        h('a', { class: 'btn primary', href: '#/log' }, 'Log a workout')));
}

export function workoutScreen(ctx, day) {
  const { lb } = ctx;
  const w = lb.workout(day);
  if (!w) {
    return h('div', { class: 'card' }, h('h2', {}, 'Workout not found'),
      h('p', { class: 'muted' }, 'It may have been deleted on another device.'), h('a', { class: 'btn', href: '#/' }, 'Back to history'));
  }
  const saved = ctx.lastSaved && ctx.lastSaved.day === day ? ctx.lastSaved : null;
  ctx.lastSaved = null;
  const bw = w.logs.find((l) => l.bodyweight)?.bodyweight;
  const del = h('button', { class: 'btn danger', type: 'button' }, 'Delete');
  del.addEventListener('click', busy(del, async () => {
    if (!confirm(`Delete ${w.title} on ${formatDay(day)}? This removes it from all your devices.`)) return;
    await lb.deleteWorkout(day);
    toast('Workout deleted.');
    ctx.go('');
  }));
  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, w.title), h('p', { class: 'muted', style: 'margin:0' }, formatDay(day), bw ? ` · bodyweight ${fmtNum(bw)}` : '')),
      h('a', { class: 'btn small', href: '#/' }, 'All workouts')),
    saved ? h('div', { class: 'card gold' },
      h('h2', {}, saved.appended ? 'Added to this workout' : 'Saved'),
      summaryTable(saved.summary),
      saved.skipped?.length ? h('ul', { class: 'errors' }, saved.skipped.map((s) => h('li', {}, s))) : null) : null,
    h('div', { class: 'card' },
      w.logs.map((log) => h('div', { class: 'exercise' },
        h('div', { class: 'name' }, log.exercise),
        h('div', { class: 'sets' }, formatSetsDisplay(log.sets) || String(log.exercise_string || '').split('\n').slice(1).join('\n'))))),
    h('div', { class: 'row' },
      h('a', { class: 'btn', href: `#/workout/${day}/edit` }, 'Edit'),
      h('button', { class: 'btn', type: 'button', onclick: () => copyText(lb.workoutText(w)) }, 'Copy as text'),
      del));
}

export function editScreen(ctx, day) {
  const { lb } = ctx;
  const w = lb.workout(day);
  if (!w) return workoutScreen(ctx, day);
  const ta = h('textarea', { id: 'workout_text', spellcheck: 'false', autocapitalize: 'off' }, lb.workoutText(w));
  const err = h('div', { role: 'alert' });
  const btn = h('button', { class: 'btn primary', type: 'button' }, 'Save changes');
  btn.addEventListener('click', busy(btn, async () => {
    const r = await lb.log(ta.value, { replaceDay: day });
    if (r.existing) {
      err.replaceChildren(h('p', { class: 'error' }, `There is already a workout on ${formatDay(r.existing.day)}. Change the date or edit that one.`));
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
    h('div', { class: 'page-head' }, h('h1', {}, 'Edit workout'), h('a', { class: 'btn small', href: `#/workout/${day}` }, 'Cancel')),
    h('div', { class: 'card' },
      h('label', { for: 'workout_text' }, 'The workout as text'),
      ta,
      h('div', { class: 'hint' }, 'The first line is the date and title. Change the date to move the workout.'),
      err,
      h('div', { class: 'row', style: 'margin-top:12px' }, btn)));
}
