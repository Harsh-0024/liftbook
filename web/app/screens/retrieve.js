// Retrieve: the next workout's targets from the plan and the last sets, as text to copy into
// the Log page (or a notes app) at the gym.

import { h, icon, rowItem, pageHead, copyText, busy, toast } from '../ui.js';
import { DRAFT_KEY } from './log.js';
import { muscleGroup } from '../../core/coach_tools.js';

function dayLabel(plans, category, dayName) {
  const id = dayName.slice(category.length).trim();
  const title = category === 'Session' ? plans.session_titles?.[id] : null;
  return { id, label: title ? `${dayName} · ${title}` : dayName };
}

/** The session after the last one logged ("Session 3 - Back" → 4), wrapping round; null if unknown. */
function nextSession(lb, ids) {
  for (const w of lb.workouts().slice(0, 10)) {
    const m = /\bsession\s*(\d+)/i.exec(w.title);
    if (m && ids.includes(Number(m[1]))) return ids[(ids.indexOf(Number(m[1])) + 1) % ids.length];
  }
  return null;
}

export function retrieveScreen(ctx) {
  const { lb } = ctx;
  const plans = lb.planDays();
  const cats = Object.entries(plans.workout || {});
  const following = lb.settings().follow_shared_plan && !lb.isAdmin();
  const sessions = plans.workout?.Session || {};
  const ids = Object.keys(sessions).map((n) => Number(n.slice('Session'.length).trim())).filter(Number.isFinite);
  const next = nextSession(lb, ids);

  const cell = (category, dayName) => {
    const { id } = dayLabel(plans, category, dayName);
    const title = category === 'Session' ? plans.session_titles?.[id] : null;
    return h('a', { href: `#/retrieve/day/${encodeURIComponent(category)}/${id}`, class: category === 'Session' && Number(id) === next ? 'next' : null,
      title: `${dayName}${title ? ` · ${title}` : ''} (${sessions[dayName]?.length ?? (plans.workout[category][dayName] || []).length} exercises)` },
    h('small', {}, category === 'Session' && Number(id) === next ? `Next · ${dayName}` : dayName),
    h('b', {}, title || `${(plans.workout[category][dayName] || []).length} exercises`));
  };

  const groups = [];
  // Sessions grouped by the plan's headings (Cycle 1, Cycle 2, ...), four to a row as before.
  const seen = new Set();
  for (const heading of plans.headings || []) {
    const nums = (plans.heading_sessions?.[heading] || []).filter((n) => sessions[`Session ${n}`]);
    if (!nums.length) continue;
    nums.forEach((n) => seen.add(`Session ${n}`));
    groups.push(h('section', { class: 'section' }, h('div', { class: 'label' }, heading),
      h('div', { class: 'group cycle', style: `--n:${Math.min(4, nums.length)}` }, nums.map((n) => cell('Session', `Session ${n}`)))));
  }
  for (const [category, days] of cats) {
    const rest = Object.keys(days).filter((d) => !seen.has(d));
    if (!rest.length) continue;
    for (let k = 0; k < rest.length; k += 4) {
      const chunk = rest.slice(k, k + 4);
      groups.push(h('section', { class: 'section' }, k === 0 ? h('div', { class: 'label' }, category === 'Session' ? 'Sessions' : category) : null,
        h('div', { class: 'group cycle', style: `--n:${chunk.length}` }, chunk.map((d) => cell(category, d)))));
    }
  }

  return h('div', { dataset: { wide: '1' }, class: 'retrieve' },
    pageHead('Retrieve', following ? 'Each session from the shared plan you follow, with your best numbers.' : 'Each plan comes with your best numbers.'),
    groups.length ? groups : h('div', { class: 'group empty' }, icon('plan'), h('p', {}, 'Your plan has no days yet.'),
      h('a', { class: 'btn primary', href: '#/settings/plan' }, 'Write your plan')),
    h('div', { class: 'group', style: 'margin-top:28px' },
      rowItem({ href: '#/retrieve/custom', ico: 'sliders', title: 'Custom workout', desc: 'Pick any exercises from your plan and history' }),
      rowItem({ href: '#/settings/plan', ico: 'plan', title: 'Change the plan', desc: 'Your days and the exercises in them' })));
}

/**
 * The workout to copy, as the old page had it: each exercise with your best numbers under it and
 * its target beside it, the title editable (the copied text follows), the text itself one tap away,
 * and Copy (Share where the phone has it) always in reach.
 */
function output(ctx, result, back, { kicker = '', number = '', name = '', fallback = '', edit = null } = {}) {
  const d = result.described;
  let text = result.text;
  const date = String(text.split('\n', 1)[0]).split(' - ', 1)[0];
  const pre = h('pre', { class: 'out' }, text);
  const title = h('input', { type: 'text', class: 'rp-title', maxlength: 80, autocomplete: 'off', value: name,
    placeholder: fallback || number || 'Workout', 'aria-label': 'Workout title' });
  title.addEventListener('input', () => {
    const lines = text.split('\n');
    lines[0] = [date, number, title.value.replace(/\s+/g, ' ').trim() || fallback].filter(Boolean).join(' - ');
    text = lines.join('\n');
    pre.textContent = text;
  });
  title.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); title.blur(); } });

  const copyBtn = h('button', { class: 'btn primary small', type: 'button' }, icon('copy'), 'Copy');
  let doneTimer = null;
  const copy = async () => {
    await copyText(text, { quiet: true });
    copyBtn.replaceChildren(icon('check'), 'Copied');
    copyBtn.classList.add('done');
    clearTimeout(doneTimer);
    doneTimer = setTimeout(() => { copyBtn.replaceChildren(icon('copy'), 'Copy'); copyBtn.classList.remove('done'); }, 1800);
  };
  copyBtn.addEventListener('click', copy);
  const share = navigator.share ? h('button', { class: 'btn small', type: 'button', onclick: async () => {
    try { await navigator.share({ text }); } catch { /* closed */ }
  }, 'aria-label': 'Share' }, icon('share'), h('span', { class: 'lbl' }, 'Share')) : null;
  const logIt = () => {
    try {
      localStorage.setItem(DRAFT_KEY, text);
    } catch {
      // nothing kept; the copy button still works
    }
    ctx.go('log');
  };
  // ⌘C / Ctrl+C copies the workout when nothing is selected and the title isn't being typed in.
  const onKey = (e) => {
    if (!(e.metaKey || e.ctrlKey) || (e.key || '').toLowerCase() !== 'c') return;
    if (!document.body.contains(pre)) { document.removeEventListener('keydown', onKey); return; }
    if (document.activeElement === title || String(window.getSelection() || '').length) return;
    e.preventDefault();
    copy();
  };
  document.addEventListener('keydown', onKey);

  const dock = h('div', { class: 'rp-dock' }, h('div', { class: `rp-bar${share && edit ? ' many' : ''}` },
      edit ? h('button', { class: 'btn ghost small', type: 'button', onclick: () => edit(title.value.replace(/\s+/g, ' ').trim()) }, icon('edit'), 'Edit') : h('span', { class: 'rp-bar-meta' }, 'Ready for Notes'),
      h('div', { class: 'row' },
        share,
        h('button', { class: 'btn small', type: 'button', onclick: logIt, title: 'Open on the Log page to fill in what you lift', 'aria-label': 'Log from this' }, icon('log'), h('span', { class: 'lbl' }, 'Log')),
        copyBtn)));
  // The dock fades the page out beneath it only while it floats; resting at the end it stays clear.
  const dockEnd = h('div', { 'aria-hidden': 'true' });
  if ('IntersectionObserver' in window) {
    setTimeout(() => {
      const offset = parseFloat(getComputedStyle(dock).bottom) || 0;
      new IntersectionObserver(([entry]) => dock.classList.toggle('floating', !entry.isIntersecting),
        { rootMargin: `0px 0px -${offset}px 0px` }).observe(dockEnd);
    }, 0);
  }
  const ex = d.exercises || [];
  const meta = `${result.exercises} exercise${result.exercises === 1 ? '' : 's'} · ${result.sets} set${result.sets === 1 ? '' : 's'}${d.bodyweight ? ` · Bodyweight ${d.bodyweight}` : ''}`;
  return h('div', { class: 'rp' },
    h('header', { class: 'page-head' }, h('div', {},
      back ? h('a', { class: 'back', href: back, 'aria-label': 'Back' }, icon('back')) : null,
      kicker ? h('p', { class: 'rp-kicker' }, kicker) : null,
      h('h1', { class: 'sr' }, name || fallback || number || 'Workout'),
      title,
      h('p', {}, meta))),
    h('section', { 'aria-label': 'Plan, with your best numbers under each exercise' },
      h('div', { class: 'group' }, ex.length ? ex.map((e) => h('div', { class: 'rp-row' },
        h('div', { class: 'rp-main' },
          h('span', { class: 'rp-name' }, e.name),
          h('span', { class: `rp-sets${e.fresh ? ' fresh' : ''}` }, e.fresh ? 'No history yet' : e.sets_label)),
        e.target ? h('span', { class: 'rp-target' }, e.target) : null))
        : h('pre', { class: 'out', style: 'padding:18px 20px' }, text)),
      h('details', { class: 'rp-text' },
        h('summary', {}, 'View as text', h('span', { class: 'ex-chev' }, icon('chev'))),
        h('div', { class: 'group' }, pre))),
    dock, dockEnd);
}

/** ("Session 4 · Cycle 1", "Legs") as the old page header had it. */
function sessionPlace(plans, category, id) {
  if (String(category).trim().toLowerCase() === 'session') {
    let kicker = `Session ${id}`;
    for (const [heading, ids] of Object.entries(plans.heading_sessions || {})) {
      if ((ids || []).map(Number).includes(Number(id))) {
        kicker += ` · ${heading}`;
        break;
      }
    }
    return { kicker, number: `Session ${id}`, name: plans.session_titles?.[id] || '' };
  }
  return { kicker: `Day ${id}`, number: '', name: category };
}

export function retrieveDayScreen(ctx, category, id) {
  const cat = decodeURIComponent(category);
  const result = ctx.lb.retrieveDay(cat, Number(id));
  const place = sessionPlace(ctx.lb.planDays(), cat, id);
  const picks = ctx.lb.planDayPicks(cat, Number(id));
  // Edit: the same exercises and sets on the Custom page, to add, drop or reorder some for today.
  const edit = picks.length ? (name) => {
    ctx.customPrefill = { picks, number: place.number, kicker: place.kicker, title: name };
    ctx.go('retrieve/custom');
  } : null;
  return output(ctx, result, '#/retrieve', { ...place, edit });
}

const GROUPS = ['Chest', 'Back', 'Shoulders', 'Biceps', 'Triceps', 'Forearms', 'Legs', 'Abs', 'Other'];

const MAX_PICKS = 30;
const DRAFT_HOURS = 12;
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const repsText = (reps) => {
  const clean = String(reps || '').trim();
  if (!clean) return '';
  return /^[\d–\-\s]+$/.test(clean) ? `${clean.replace('-', '–')} reps` : clean;
};

/**
 * Custom workout: pick exercises by muscle, set their order and sets, get the targets.
 * Phones: the picks open as a sheet above the bar. Wide screens: a column on the right.
 */
export function retrieveCustomScreen(ctx) {
  const { lb } = ctx;
  const catalog = lb.exerciseCatalog().map((c) => ({ ...c, group: muscleGroup(c.name) }));
  const byName = new Map(catalog.map((c) => [c.name.toLowerCase(), c]));
  const info = (name) => byName.get(name.toLowerCase()) || { name, sets: 3, reps: '' };
  const title = h('input', { id: 'title', type: 'text', placeholder: 'Custom Workout', maxlength: 80, autocomplete: 'off' });
  const search = h('input', { id: 'search', type: 'search', placeholder: 'Search exercises', autocapitalize: 'off', 'aria-label': 'Search exercises' });
  const prefill = ctx.customPrefill;
  ctx.customPrefill = null;
  // A plan session being edited keeps its own draft, so an unfinished custom pick isn't lost.
  const draftKey = `liftbook-custom-draft${prefill?.number ? `:${prefill.number}` : ''}`;
  const clampSets = (n, fallback) => Math.min(10, Math.max(1, Number(n) || fallback || 3));
  const load = () => {
    try {
      const d = JSON.parse(localStorage.getItem(draftKey) || 'null');
      if (!d || !Array.isArray(d.picks) || Date.now() - d.t > DRAFT_HOURS * 3600000) return null;
      return d;
    } catch {
      return null;
    }
  };
  /** [{ name, sets }] in workout order. */
  let picks;
  if (prefill) {
    picks = prefill.picks.map(([n, sets]) => ({ name: info(n).name, sets: clampSets(sets, info(n).sets) }));
    if (prefill.title) title.value = prefill.title;
  } else {
    const d = load();
    picks = (d?.picks || []).map((p) => ({ name: info(p.name).name, sets: clampSets(p.sets, info(p.name).sets) }));
    if (d?.title) title.value = d.title;
  }
  picks = picks.slice(0, MAX_PICKS);
  const save = () => {
    try {
      if (picks.length) localStorage.setItem(draftKey, JSON.stringify({ t: Date.now(), picks, title: title.value }));
      else localStorage.removeItem(draftKey);
    } catch {
      // private browsing: fine without
    }
  };
  title.addEventListener('input', save);

  const open = new Set();
  const openLess = new Set();
  const picker = h('div', { class: 'group picker-groups' });
  const pickedList = h('div', { class: 'cr-picked' });
  const empty = h('p', { class: 'subtle cr-empty' }, 'Nothing picked yet.');
  const clearBtn = h('button', { class: 'btn ghost small cr-clear', type: 'button' }, 'Clear');
  const page = h('div', { dataset: { wide: '1' }, class: 'cr' });
  const backdrop = h('div', { class: 'cr-backdrop', onclick: () => setSheet(false) });
  // Two bars with the same button: beside the picked list on wide screens, floating on phones.
  const mkBar = (phone) => {
    const count = h('b', {});
    const sets = h('small', {});
    const chev = phone ? h('span', { class: 'cr-bar-chev' }, icon('chev')) : null;
    const infoEl = phone
      ? h('button', { class: 'cr-bar-info', type: 'button', 'aria-label': 'Show your workout', onclick: () => setSheet(!page.classList.contains('sheet-open')) }, h('span', {}, count, sets), chev)
      : h('span', { class: 'cr-bar-info' }, h('span', {}, count, sets));
    const go = h('button', { class: 'btn primary small', type: 'button' }, 'Get workout');
    go.addEventListener('click', busy(go, getWorkout));
    return { el: h('div', { class: 'editor-bar' }, infoEl, go), count, sets, go };
  };
  const bars = [mkBar(false), mkBar(true)];
  const holder = h('div', { class: 'cr-out' });

  const has = (name) => picks.some((p) => p.name === name);
  const toggle = (name) => {
    const i = picks.findIndex((p) => p.name === name);
    if (i >= 0) picks.splice(i, 1);
    else if (picks.length >= MAX_PICKS) {
      toast(`Up to ${MAX_PICKS} exercises.`);
      return;
    } else picks.push({ name, sets: info(name).sets || 3 });
    paint();
  };
  const option = (c) => h('button', { type: 'button', class: `pick${has(c.name) ? ' on' : ''}${c.often ? '' : ' other'}`, 'aria-pressed': String(has(c.name)), onclick: () => toggle(c.name) },
    h('span', { class: 'pick-name' }, c.name),
    h('span', { class: 'pick-tick' }, icon('check')));

  const rowFor = (p, i) => {
    const c = info(p.name);
    const step = (d) => () => {
      p.sets = clampSets(p.sets + d);
      paint();
    };
    return h('div', { class: 'cr-row', dataset: { i: String(i) } },
      h('span', { class: 'cr-grip', 'aria-hidden': 'true' }, h('i', {}), h('i', {}), h('i', {})),
      h('span', { class: 'main' }, h('span', { class: 'title' }, p.name), c.reps ? h('span', { class: 'desc' }, repsText(c.reps)) : null),
      h('span', { class: `cr-sets${p.sets !== (c.sets || 3) ? ' changed' : ''}` },
        h('button', { type: 'button', 'aria-label': `Fewer sets of ${p.name}`, disabled: p.sets <= 1, onclick: step(-1) }, '−'),
        h('span', {}, h('b', {}, String(p.sets)), p.sets === 1 ? ' set' : ' sets'),
        h('button', { type: 'button', 'aria-label': `More sets of ${p.name}`, disabled: p.sets >= 10, onclick: step(1) }, '+')),
      h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Remove ${p.name}`, onclick: () => toggle(p.name) }, icon('trash')));
  };

  const paint = () => {
    const q = search.value.trim().toLowerCase();
    if (q) {
      const hits = catalog.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 200);
      picker.replaceChildren(...(hits.length ? [h('div', { class: 'pick-list' }, hits.map(option))] : [h('p', { class: 'subtle', style: 'padding:16px 20px;margin:0' }, 'No exercise by that name.')]));
    } else {
      // By muscle group, as the old page had it; a tap opens the group. What you train often
      // first, the rest folded under "Less often" (unfolded when nothing in the group is often).
      picker.replaceChildren(...GROUPS.map((g) => {
        const items = catalog.filter((c) => c.group === g).sort((a, b) => a.name.localeCompare(b.name));
        if (!items.length) return null;
        const n = items.filter((c) => has(c.name)).length;
        const often = items.filter((c) => c.often);
        const less = items.filter((c) => !c.often);
        const fold = often.length > 0 && less.length > 0;
        const head = h('button', { type: 'button', class: `rowi${open.has(g) ? ' open' : ''}`, 'aria-expanded': String(open.has(g)),
          onclick: () => { if (open.has(g)) open.delete(g); else open.add(g); paint(); } },
        h('span', { class: 'main' }, h('span', { class: 'title' }, g)),
        h('span', { class: `value${n ? ' gold' : ''}` }, n ? `${n} picked` : `${items.length}`),
        h('span', { class: 'chev-i' }, icon('chev')));
        if (!open.has(g)) return h('div', { class: 'pick-group' }, head);
        const lessOpen = openLess.has(g) || less.some((c) => has(c.name));
        return h('div', { class: 'pick-group' }, head,
          h('div', { class: 'pick-list' }, (fold ? often : items).map(option)),
          fold ? h('button', { type: 'button', class: `rowi sub${lessOpen ? ' open' : ''}`, 'aria-expanded': String(lessOpen),
            onclick: () => { if (openLess.has(g)) openLess.delete(g); else openLess.add(g); paint(); } },
          h('span', { class: 'main' }, h('span', { class: 'title' }, 'Less often ', h('span', { class: 'subtle' }, String(less.length)))),
          h('span', { class: 'chev-i' }, icon('chev'))) : null,
          fold && lessOpen ? h('div', { class: 'pick-list less' }, less.map(option)) : null);
      }).filter(Boolean));
    }
    pickedList.replaceChildren(...picks.map(rowFor));
    empty.hidden = picks.length > 0;
    clearBtn.hidden = !picks.length;
    const total = picks.reduce((a, p) => a + p.sets, 0);
    for (const b of bars) {
      b.count.textContent = picks.length ? plural(picks.length, 'exercise') : 'No exercises';
      b.sets.textContent = picks.length ? plural(total, 'set') : 'Pick from the list';
      b.go.disabled = !picks.length;
    }
    page.classList.toggle('has-picks', picks.length > 0);
    if (!picks.length) setSheet(false);
    save();
  };

  function setSheet(on) {
    const wide = window.matchMedia('(min-width: 760px)').matches;
    page.classList.toggle('sheet-open', Boolean(on) && !wide && picks.length > 0);
  }
  const onKey = (e) => {
    if (!document.body.contains(page)) { document.removeEventListener('keydown', onKey); return; }
    if (e.key === 'Escape') setSheet(false);
  };
  document.addEventListener('keydown', onKey);

  clearBtn.addEventListener('click', () => {
    const before = picks.map((p) => ({ ...p }));
    picks = [];
    paint();
    // One tap to bring them back.
    toast('Cleared', { action: 'Undo', onAction: () => { picks = before; paint(); } });
  });

  // Drag the grip to change the order. Rows only slide while dragging (moving one in the page
  // would drop the finger's capture); the new order is applied on lift-off.
  let drag = null;
  const onMove = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    e.preventDefault();
    const dy = e.clientY - drag.startY;
    const mid = drag.rects[drag.from].top + drag.rects[drag.from].height / 2 + dy;
    let to = drag.from;
    drag.rects.forEach((r, i) => {
      if (i < drag.from && mid < r.top + r.height / 2) to = Math.min(to, i);
      if (i > drag.from && mid > r.top + r.height / 2) to = Math.max(to, i);
    });
    drag.to = to;
    drag.rows.forEach((row, i) => {
      if (i === drag.from) row.style.transform = `translateY(${dy}px)`;
      else if (i > drag.from && i <= to) row.style.transform = `translateY(${-drag.h}px)`;
      else if (i < drag.from && i >= to) row.style.transform = `translateY(${drag.h}px)`;
      else row.style.transform = '';
    });
  };
  const endDrag = (e) => {
    if (!drag || (e && e.pointerId !== drag.id)) return;
    const [moved] = picks.splice(drag.from, 1);
    picks.splice(drag.to, 0, moved);
    drag = null;
    pickedList.classList.remove('sorting');
    paint();
  };
  pickedList.addEventListener('pointerdown', (e) => {
    const grip = e.target.closest('.cr-grip');
    if (!grip || drag) return;
    e.preventDefault();
    const rows = [...pickedList.children];
    const row = grip.closest('.cr-row');
    const from = rows.indexOf(row);
    drag = { id: e.pointerId, startY: e.clientY, rows, from, to: from, h: row.offsetHeight, rects: rows.map((r) => r.getBoundingClientRect()) };
    row.classList.add('dragging');
    pickedList.classList.add('sorting');
    grip.setPointerCapture(e.pointerId);
  });
  pickedList.addEventListener('pointermove', onMove);
  pickedList.addEventListener('pointerup', endDrag);
  pickedList.addEventListener('pointercancel', endDrag);

  search.addEventListener('input', paint);

  async function getWorkout() {
    if (!picks.length) {
      toast('Pick at least one exercise.');
      return;
    }
    const names = picks.map((p) => p.name);
    const overrides = Object.fromEntries(picks.map((p) => [p.name, p.sets]));
    const name = title.value.replace(/\s+/g, ' ').trim();
    // Edited from a plan session: it keeps its number in the copied title ("Session 4 - Legs").
    const number = prefill?.number || '';
    const result = lb.retrieveCustom(names, number ? [number, name].filter(Boolean).join(' - ') : title.value, overrides);
    await lb.recordRetrievals(names);
    setSheet(false);
    holder.replaceChildren(output(ctx, result, null, { kicker: prefill?.kicker || 'Custom workout', number, name, fallback: number ? '' : 'Custom Workout' }));
    // Land the workout just below the app header, not under it.
    const head = document.querySelector('.topbar')?.offsetHeight || 0;
    window.scrollTo({ top: holder.getBoundingClientRect().top + window.scrollY - head - 12, behavior: 'smooth' });
  }

  // Opened from Edit: the groups holding the picks start open.
  for (const p of picks) open.add(info(p.name).group || muscleGroup(p.name));
  if (!prefill) open.clear();
  paint();

  page.append(
    pageHead('Custom workout', 'Each exercise comes with your best numbers.', { back: '#/retrieve' }),
    h('div', { class: 'split' },
      h('div', {}, h('div', { class: 'search' }, icon('search'), search), picker,
        h('div', { class: 'group pick-bar' }, bars[1].el)),
      h('div', { class: 'split-side cr-mine' },
        h('div', { class: 'label cr-mine-head' }, h('span', {}, 'Your workout'), clearBtn),
        h('div', { class: 'field' }, title),
        h('div', { class: 'group picked' }, pickedList, empty),
        h('div', { class: 'group side-bar' }, bars[0].el))),
    backdrop,
    holder);
  return page;
}
