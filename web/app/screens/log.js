// Log: type (or paste) a workout, see what it reads as, save it. Works offline: the save is
// on this device at once and syncs later. An unsaved draft is kept if the app closes.

import { h, icon, pageHead, formatDay, busy, toast, autoGrow, rowItem } from '../ui.js';
import { attachSuggestions } from '../suggest.js';
import { attachPasteTidy, tidyPaste, showFromTop } from '../paste.js';
import { scrollBehavior } from '../motion.js';

export const DRAFT_KEY = 'liftbook-log-draft';

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
  // Each set ("140 x 5") stays on one line; a narrow screen scrolls the table instead of cutting it off.
  const keep = (sets) => String(sets ?? '').replace(/ x /g, '\u00a0x\u00a0');
  return h('div', { class: 'table-scroll' }, h('table', { class: 'summary' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Exercise'), h('th', {}, 'Best before'), h('th', {}, 'Today'), h('th', {}, ''))),
    h('tbody', {}, (summary || []).map((r) => h('tr', {},
      h('td', {}, r.name),
      h('td', { class: 'mono subtle' }, keep(r.old)),
      h('td', { class: 'mono' }, keep(r.new)),
      h('td', {}, r.status && r.status !== '-'
        ? h('span', { class: `pill ${r.status === 'ERROR' ? 'error' : r.class}` }, r.status === 'CONSISTENCY' ? 'MORE REPS' : r.status)
        : (r.performance_label ? h('span', { class: 'subtle' }, r.performance_label) : null)))))));
}

export function logScreen(ctx) {
  const { lb } = ctx;
  const now = new Date();
  const today = `${now.getDate()}/${now.getMonth() + 1}/${String(now.getFullYear()).slice(2)}`;
  const ta = h('textarea', {
    id: 'workout_text', class: 'editor', spellcheck: 'false', autocapitalize: 'sentences', autocomplete: 'off',
    placeholder: `${today} - Session 1 - Chest & Biceps\n\nFlat Barbell Press - [5-8]\n32.5 27.5 25, 6 7 8\n\nBarbell Curl - [6-10]\n20 17.5, 8 10`,
  }, readDraft());
  // Opened for a given day ("#/log?day=2026-11-20", from a day with no workout): an empty box
  // starts with that day's date line; an unsaved draft is never replaced.
  const askedDay = /[?&]day=(\d{4}-\d{2}-\d{2})(?:&|$)/.exec(location.hash)?.[1];
  if (askedDay && !Number.isNaN(Date.parse(`${askedDay}T12:00:00`))) {
    const [y, m, d] = askedDay.split('-').map(Number);
    const dateLine = `${d}/${m}/${String(y).slice(2)}`;
    if (!ta.value.trim()) ta.value = `${dateLine} - `;
    // The box already on that day (this page drawn again, or a draft for that day): just place the
    // cursor at the end. A draft for another day stays as it is, with a word about the date.
    if (ta.value.trimStart().startsWith(`${dateLine} `)) {
      setTimeout(() => {
        if (!ta.isConnected) return;
        ta.focus({ preventScroll: true });
        ta.setSelectionRange(ta.value.length, ta.value.length);
      }, 50);
    } else {
      setTimeout(() => { if (ta.isConnected) toast(`Your unsaved workout is still here. Change its first line to ${dateLine} for that day.`); }, 0);
    }
  }
  const fit = autoGrow(ta);
  const suggest = attachSuggestions(ta, () => lb.exerciseCatalog().map((e) => e.name));
  attachPasteTidy(ta);
  // The count under the box: tapping it goes to the check list, as on the old page.
  const preview = h('button', { type: 'button', class: 'editor-meta meta-btn', 'aria-live': 'polite' }, 'Nothing to check yet');
  const checkHead = h('span', {});
  const checkList = h('div', { class: 'group' });
  const checkBox = h('section', { class: 'section', hidden: true, 'aria-label': 'Check before saving' },
    h('div', { class: 'label' }, 'Check', checkHead), checkList);
  const problems = h('div', { role: 'alert' });
  const save = h('button', { class: 'btn primary small', type: 'button' }, 'Save');
  const paste = h('button', { class: 'btn small', type: 'button' });
  // An empty box offers the next session from the plan, with your last numbers, to fill in
  // (what Retrieve's "Log" button does, one tap from here). Not on the day a workout is logged.
  let startRow = null;
  try {
    const workouts = lb.workouts();
    const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    const next = workouts.length && workouts[0].day !== iso ? lb.nextSession() : null;
    if (next) {
      const name = `Session ${next.id}${next.title ? ` · ${next.title}` : ''}`;
      startRow = h('div', { class: 'group log-start' }, rowItem({
        ico: 'list', title: `Start from ${name}`,
        desc: `Next in your plan${next.exercises ? `: ${next.exercises} exercise${next.exercises === 1 ? '' : 's'}` : ''}, with your last numbers to fill in`,
        onclick: () => {
          const r = lb.retrieveDay('Session', next.id);
          if (!r.exercises) return toast('That session has no exercises in your plan.');
          ta.value = r.text;
          check();
          showFromTop(ta);
        },
      }));
    }
  } catch {
    startRow = null;
  }
  const paintPaste = () => {
    paste.replaceChildren(...(ta.value.trim() ? [icon('trash'), 'Clear'] : [icon('clipboard'), 'Paste']));
    if (startRow) startRow.hidden = Boolean(ta.value.trim());
  };

  let timer = null;
  const check = () => {
    const text = ta.value;
    writeDraft(text);
    paintPaste();
    fit();
    if (!text.trim()) {
      preview.textContent = 'Nothing to check yet';
      problems.replaceChildren();
      checkBox.hidden = true;
      return;
    }
    const c = lb.check(text);
    const exercises = (c.parsed?.exercises || []);
    // Only the first line so far (the date and title): still being written, so no complaints yet.
    const started = text.split('\n').filter((l) => l.trim()).length > 1;
    preview.replaceChildren(c.parsed
      ? h('span', { class: c.errors.length && started ? 'error' : 'ok' }, `${c.exercise_count} exercise${c.exercise_count === 1 ? '' : 's'} · ${c.set_count} set${c.set_count === 1 ? '' : 's'}`)
      : 'Nothing to check yet');
    checkHead.textContent = c.parsed ? `${formatDay(c.day)} · ${c.parsed.workout_name || 'Workout'}` : '';
    checkBox.hidden = !exercises.length;
    // Rows count the exercises 1, 2, 3 and say how many sets each has, as the old check did.
    let order = 0;
    checkList.replaceChildren(...exercises.map((e, i) => {
      const bad = e.valid === false || e.missing_name;
      // Names you haven't used, close misspellings ("Use it" puts the known name on that line), repeats.
      const n = c.notes?.[i];
      const flagged = n && n.state !== 'ok';
      const fix = n?.state === 'suggest' && n.fixLine !== null
        ? h('button', { class: 'btn small', type: 'button', 'aria-label': `Use it: ${n.suggestion} on line ${e.line}`, onclick: () => useLine(e.line, n.fixLine) }, 'Use it')
        : null;
      const sets = (e.reps || []).length;
      const tag = bad || fix ? null : n?.state === 'new' ? 'New' : `${sets} set${sets === 1 ? '' : 's'}`;
      // A tap on the row puts the cursor on that exercise's line in the box.
      const row = h('div', { class: `rowi check-row${flagged && n.state !== 'new' ? ' warn' : ''}`, role: 'button', tabindex: '0' },
        bad ? h('span', { class: 'ico', style: 'color:var(--bad)' }, icon('info')) : h('span', { class: 'num', 'aria-hidden': 'true' }, String(order += 1)),
        h('span', { class: 'main' }, h('span', { class: 'title' }, e.name),
          h('span', { class: 'desc mono' }, !bad ? e.sets_label
            : String(e.exercise_string || '').split('\n').slice(1).join('').trim() ? 'Couldn’t read these sets' : 'No sets under it'),
          // "New" is said by the tag on the right.
          flagged && tag !== 'New' ? h('span', { class: `desc name-note is-${n.state}` }, n.note) : null),
        fix,
        tag ? h('span', { class: `tag${tag === 'New' ? ' is-new' : ''}` }, tag) : null);
      const jump = (ev) => {
        if (ev.target.closest('button')) return;
        if (ev.type === 'keydown') {
          if (ev.key !== 'Enter' && ev.key !== ' ') return;
          ev.preventDefault();
        }
        jumpToLine(e.line);
      };
      row.addEventListener('click', jump);
      row.addEventListener('keydown', jump);
      return row;
    }));
    problems.replaceChildren(
      c.future && c.day ? h('p', { class: 'wo-note log-future' }, icon('calendar'),
        h('span', {}, `This is dated ${formatDay(c.day)}, after today. Check the year on the first line.`)) : '',
      c.errors.length && started ? h('ul', { class: 'errors' }, c.errors.map((e) => h('li', {}, e))) : '');
    if (c.existing) checkHead.textContent += ` · adds to ${c.existing.title} if you choose`;
  };
  // The check reads the text trimmed, so its line 1 is the first line that isn't blank.
  const lineIndex = (lineNo) => lineNo - 1 + (ta.value.match(/^\s*/)[0].match(/\n/g) || []).length;
  const jumpToLine = (lineNo) => {
    const lines = ta.value.split('\n');
    const k = lineIndex(lineNo);
    if (!lineNo || k < 0 || k >= lines.length) return;
    // The cursor goes to the start of the line (nothing selected, so typing can't wipe the line).
    const start = lines.slice(0, k).reduce((n, l) => n + l.length + 1, 0);
    ta.focus({ preventScroll: true });
    ta.setSelectionRange(start, start);
    const cs = getComputedStyle(ta);
    const lineHeight = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.5;
    const y = (parseFloat(cs.paddingTop) || 0) + k * lineHeight;
    if (ta.scrollHeight > ta.clientHeight + 1) ta.scrollTop = Math.max(0, y - lineHeight);
    const top = ta.getBoundingClientRect().top + y - ta.scrollTop;
    // Bring the line a little below the header if it is off the screen.
    if (top < 90 || top > innerHeight - 140) window.scrollBy({ top: top - Math.min(200, innerHeight / 3), behavior: scrollBehavior() });
  };
  const useLine = (lineNo, text) => {
    const lines = ta.value.split('\n');
    const k = lineIndex(lineNo);
    if (k < 0 || k >= lines.length) return;
    lines[k] = text;
    ta.value = lines.join('\n');
    check();
  };
  ta.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(check, 250);
  });
  let cleared = null;
  const undo = h('button', { class: 'btn small', type: 'button', hidden: true }, 'Undo');
  undo.addEventListener('click', () => {
    ta.value = cleared;
    cleared = null;
    undo.hidden = true;
    check();
    ta.scrollTop = 0;
  });
  ta.addEventListener('input', () => {
    if (cleared !== null && ta.value.trim()) {
      cleared = null;
      undo.hidden = true;
    }
  });
  preview.addEventListener('click', () => {
    if (!checkBox.hidden) checkBox.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
  });
  paste.addEventListener('click', async () => {
    if (ta.value.trim()) {
      // Clear everything at once; Undo, beside the count, brings it back until new text arrives.
      cleared = ta.value;
      ta.value = '';
      check();
      preview.textContent = 'Cleared';
      undo.hidden = false;
      ta.focus();
      return;
    }
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        ta.value = tidyPaste(text);
        check();
        showFromTop(ta);
      } else toast('Nothing to paste.');
    } catch {
      ta.focus();
      toast('Press and hold in the box to paste.');
    }
  });

  async function doSave(append = false) {
    const r = await lb.log(ta.value, { append });
    if (r.existing) {
      problems.replaceChildren(h('div', { class: 'notice', style: 'margin-top:14px' },
        icon('calendar'),
        h('div', {},
          h('strong', {}, 'That day already has a workout.'),
          h('p', { style: 'margin:4px 0 10px' }, `${r.existing.title} is logged on ${formatDay(r.existing.day)}. Add these exercises to it, or open it.`),
          h('div', { class: 'row' },
            h('button', { class: 'btn primary small', type: 'button', onclick: (e) => busy(e.currentTarget, () => doSave(true))(e) }, 'Add to that day'),
            h('a', { class: 'btn small', href: `#/workout/${r.existing.day}` }, 'Open it')))));
      return;
    }
    if (r.error) {
      problems.replaceChildren(h('ul', { class: 'errors' }, (r.errors || [r.error]).map((e) => h('li', {}, e))));
      return;
    }
    writeDraft('');
    ctx.lastSaved = r;
    // The workout page says "Saved" (and asks about timed exercises); offline gets a word on syncing.
    if (!navigator.onLine || ctx.sync.status().error === 'offline') toast('Saved on this device. It syncs when you’re back online.');
    ctx.go(`workout/${r.day}`);
  }
  save.addEventListener('click', busy(save, () => doSave(false)));
  // Cmd+Enter (Ctrl+Enter elsewhere) saves from the box.
  ta.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      save.click();
    }
  });

  paintPaste();
  if (ta.value) queueMicrotask(check);
  return h('div', {},
    pageHead('Log workout', 'Paste your workout from Notes, or type it: the date and title first, then each exercise with its sets underneath.'),
    // The count and Save float at the bottom of the screen while the text and the check list
    // scroll under them (as on the old Log page), so Save is always one tap away.
    startRow,
    h('div', { class: 'log-flow' },
      h('div', { class: 'group editor-wrap' },
        h('label', { for: 'workout_text', class: 'sr' }, 'Workout'),
        ta,
        suggest),
      problems,
      checkBox,
      h('div', { class: 'group log-bar' },
        h('div', { class: 'editor-bar' }, preview, h('div', { class: 'row' }, undo, paste, save)))),
    h('details', { class: 'card', style: 'margin-top:14px' },
      h('summary', {}, 'How to write sets'),
      h('div', { class: 'stack muted', style: 'margin-top:12px;font-size:.9rem' },
        h('p', {}, h('span', { class: 'mono' }, '100 x 5, 5, 4'), ' — three sets of 100 for 5, 5 and 4 reps.'),
        h('p', {}, h('span', { class: 'mono' }, '32.5 27.5 25, 6 7 8'), ' — weights, then the reps for each.'),
        h('p', {}, h('span', { class: 'mono' }, 'bw x 8, 8'), ' or ', h('span', { class: 'mono' }, 'bw+10 x 6'), ' — bodyweight exercises.'),
        h('p', {}, h('span', { class: 'mono' }, '1:00, 45s'), ' — timed sets.'),
        h('p', {}, h('span', { class: 'mono' }, 'Bodyweight - 72'), ' on its own line updates your bodyweight.'))));
}
