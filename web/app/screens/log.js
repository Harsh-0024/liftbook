// Log: type (or paste) a workout, see what it reads as, save it. Works offline: the save is
// on this device at once and syncs later. An unsaved draft is kept if the app closes.

import { h, formatDay, busy, toast } from '../ui.js';

const DRAFT_KEY = 'liftbook-log-draft';

function readDraft() {
  try {
    return localStorage.getItem(DRAFT_KEY) || '';
  } catch {
    return '';
  }
}

function writeDraft(text) {
  try {
    if (text.trim()) localStorage.setItem(DRAFT_KEY, text);
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    // Private browsing: no draft kept.
  }
}

/** The table shown after saving: each exercise, best before, today, and how it went. */
export function summaryTable(summary) {
  return h('table', { class: 'summary' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Exercise'), h('th', {}, 'Best before'), h('th', {}, 'Today'), h('th', {}, ''))),
    h('tbody', {}, (summary || []).map((r) => h('tr', {},
      h('td', {}, r.name),
      h('td', { class: 'mono subtle' }, r.old),
      h('td', { class: 'mono' }, r.new),
      h('td', {}, r.status && r.status !== '-'
        ? h('span', { class: `pill ${r.status === 'ERROR' ? 'error' : r.class}` }, r.status === 'CONSISTENCY' ? 'MORE REPS' : r.status)
        : (r.performance_label ? h('span', { class: 'subtle' }, r.performance_label) : null))))));
}

export function logScreen(ctx) {
  const { lb } = ctx;
  const now = new Date();
  const today = `${now.getDate()}/${now.getMonth() + 1}/${String(now.getFullYear()).slice(2)}`;
  const ta = h('textarea', {
    id: 'workout_text', spellcheck: 'false', autocapitalize: 'sentences',
    placeholder: `${today} - Session 1 - Chest & Biceps\n\nFlat Barbell Press - [5-8]\n32.5 27.5 25, 6 7 8\n\nBarbell Curl - [6-10]\n20 17.5, 8 10`,
  }, readDraft());
  const preview = h('div', { class: 'subtle', 'aria-live': 'polite' });
  const problems = h('div', { role: 'alert' });
  const save = h('button', { class: 'btn primary', type: 'button' }, 'Save workout');

  let timer = null;
  const check = () => {
    const text = ta.value;
    writeDraft(text);
    if (!text.trim()) {
      preview.textContent = '';
      problems.replaceChildren();
      return;
    }
    const c = lb.check(text);
    preview.textContent = c.parsed
      ? `${formatDay(c.day)} · ${c.parsed.workout_name || 'Workout'} · ${c.exercise_count} exercise${c.exercise_count === 1 ? '' : 's'}, ${c.set_count} set${c.set_count === 1 ? '' : 's'}`
      : '';
    problems.replaceChildren(c.errors.length ? h('ul', { class: 'errors' }, c.errors.map((e) => h('li', {}, e))) : '');
    if (c.existing) preview.append(h('span', { class: 'ok' }, ` · adds to ${c.existing.title} that day if you choose`));
  };
  ta.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(check, 250);
  });

  async function doSave(append = false) {
    const r = await lb.log(ta.value, { append });
    if (r.existing) {
      problems.replaceChildren(h('div', { class: 'card gold', style: 'margin-top:12px' },
        h('p', {}, `You already logged ${r.existing.title} on ${formatDay(r.existing.day)}.`),
        h('div', { class: 'row' },
          h('button', { class: 'btn primary small', type: 'button', onclick: (e) => busy(e.currentTarget, () => doSave(true))(e) }, 'Add these to it'),
          h('a', { class: 'btn small', href: `#/workout/${r.existing.day}` }, 'Open it'))));
      return;
    }
    if (r.error) {
      problems.replaceChildren(h('ul', { class: 'errors' }, (r.errors || [r.error]).map((e) => h('li', {}, e))));
      return;
    }
    writeDraft('');
    ctx.lastSaved = r;
    for (const name of r.timedPrompts || []) {
      if (confirm(`Is ${name} done for time (seconds) rather than reps?`)) await lb.setExerciseSetting(name, { is_timed: true });
      else await lb.setExerciseSetting(name, { is_timed: false });
    }
    toast(ctx.sync.status().error === 'offline' ? 'Saved on this device. It syncs when you’re back online.' : 'Workout saved.');
    ctx.go(`workout/${r.day}`);
  }
  save.addEventListener('click', busy(save, () => doSave(false)));

  if (ta.value) queueMicrotask(check);
  return h('div', {},
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Log a workout'),
      h('p', { class: 'muted', style: 'margin:0' }, 'Date and title first, then each exercise with its sets underneath.'))),
    h('div', { class: 'card' },
      h('label', { for: 'workout_text', class: 'sr' }, 'Workout'),
      ta, h('div', { style: 'margin-top:8px' }, preview), problems,
      h('div', { class: 'row', style: 'margin-top:12px' }, save,
        h('a', { class: 'btn', href: '#/retrieve' }, 'Get today’s targets'))),
    h('details', { class: 'card' },
      h('summary', { style: 'cursor:pointer;font-weight:600' }, 'How to write sets'),
      h('div', { class: 'stack muted', style: 'margin-top:10px;font-size:.92rem' },
        h('p', {}, h('span', { class: 'mono' }, '100 x 5, 5, 4'), ' — three sets of 100 for 5, 5 and 4 reps.'),
        h('p', {}, h('span', { class: 'mono' }, '32.5 27.5 25, 6 7 8'), ' — weights, then the reps for each.'),
        h('p', {}, h('span', { class: 'mono' }, 'bw x 8, 8'), ' or ', h('span', { class: 'mono' }, 'bw+10 x 6'), ' — bodyweight exercises.'),
        h('p', {}, h('span', { class: 'mono' }, '1:00, 45s'), ' — timed sets.'),
        h('p', {}, h('span', { class: 'mono' }, 'Bodyweight - 72'), ' on its own line updates your bodyweight.'))));
}
