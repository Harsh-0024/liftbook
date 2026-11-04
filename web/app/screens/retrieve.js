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
  const names = (result.described.exercises || []).map((e) => e.name);
  // Edit: the same exercises on the Custom page, to add or drop some for today.
  const edit = names.length ? (name) => {
    ctx.customPrefill = { names, number: place.number, kicker: place.kicker, title: name };
    ctx.go('retrieve/custom');
  } : null;
  return output(ctx, result, '#/retrieve', { ...place, edit });
}

const GROUPS = ['Chest', 'Back', 'Shoulders', 'Biceps', 'Triceps', 'Forearms', 'Legs', 'Abs', 'Other'];

export function retrieveCustomScreen(ctx) {
  const { lb } = ctx;
  const catalog = lb.exerciseCatalog().map((c) => ({ ...c, group: muscleGroup(c.name) }));
  const title = h('input', { id: 'title', type: 'text', placeholder: 'Custom Workout', maxlength: 80 });
  const search = h('input', { id: 'search', type: 'search', placeholder: 'Search exercises', autocapitalize: 'off', 'aria-label': 'Search exercises' });
  const catalogNames = new Map(catalog.map((c) => [c.name.toLowerCase(), c.name]));
  const prefill = ctx.customPrefill;
  ctx.customPrefill = null;
  const chosen = prefill ? prefill.names.map((n) => catalogNames.get(n.toLowerCase()) || n) : [];
  if (prefill?.title) title.value = prefill.title;
  const open = new Set();
  const picker = h('div', { class: 'group picker-groups' });
  const picked = h('div', { class: 'group picked' });
  // Two bars with the same button: beside the picked list on wide screens, under the list on phones.
  const counts = [h('span', { class: 'editor-meta' }), h('span', { class: 'editor-meta' })];
  const gos = [h('button', { class: 'btn primary small', type: 'button' }, 'Get targets'), h('button', { class: 'btn primary small', type: 'button' }, 'Get targets')];
  const holder = h('div', {});

  const toggle = (name) => {
    const i = chosen.indexOf(name);
    if (i >= 0) chosen.splice(i, 1);
    else chosen.push(name);
    paint();
  };
  const option = (c) => h('label', { class: 'pick' },
    h('input', { type: 'checkbox', checked: chosen.includes(c.name), onchange: () => toggle(c.name) }),
    h('span', {}, c.name), c.count ? h('span', { class: 'subtle' }, `${c.count}×`) : null);

  const paint = () => {
    const q = search.value.trim().toLowerCase();
    if (q) {
      const hits = catalog.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 200);
      picker.replaceChildren(...(hits.length ? hits.map(option) : [h('p', { class: 'subtle', style: 'padding:16px 20px;margin:0' }, 'No exercise by that name.')]));
    } else {
      // By muscle group, as the old page had it; a tap opens the group.
      picker.replaceChildren(...GROUPS.map((g) => {
        const items = catalog.filter((c) => c.group === g);
        if (!items.length) return null;
        const n = items.filter((c) => chosen.includes(c.name)).length;
        const head = h('button', { type: 'button', class: `rowi${open.has(g) ? ' open' : ''}`, 'aria-expanded': String(open.has(g)),
          onclick: () => { if (open.has(g)) open.delete(g); else open.add(g); paint(); } },
        h('span', { class: 'main' }, h('span', { class: 'title' }, g)),
        h('span', { class: 'value' }, n ? `${n} picked` : `${items.length}`),
        h('span', { class: 'chev-i' }, icon('chev')));
        return h('div', { class: 'pick-group' }, head, open.has(g) ? h('div', { class: 'pick-list' }, items.map(option)) : null);
      }).filter(Boolean));
    }
    picked.replaceChildren(...(chosen.length ? chosen.map((n, i) => h('div', { class: 'rowi' },
      h('span', { class: 'main' }, h('span', { class: 'title' }, `${i + 1}. ${n}`)),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Remove ${n}`, onclick: () => toggle(n) }, icon('trash'))))
      : [h('p', { class: 'subtle', style: 'padding:18px 20px;margin:0;text-align:center' }, 'Nothing picked yet.')]));
    for (const c of counts) c.textContent = chosen.length ? `${chosen.length} picked` : 'Pick exercises from the list';
    for (const g of gos) g.disabled = !chosen.length;
  };
  search.addEventListener('input', paint);
  paint();

  for (const go of gos) go.addEventListener('click', busy(go, async () => {
    if (!chosen.length) {
      toast('Pick at least one exercise.');
      return;
    }
    const names = [...chosen];
    const name = title.value.replace(/\s+/g, ' ').trim();
    // Edited from a plan session: it keeps its number in the copied title ("Session 4 - Legs").
    const number = prefill?.number || '';
    const result = lb.retrieveCustom(names, number ? [number, name].filter(Boolean).join(' - ') : title.value);
    await lb.recordRetrievals(names);
    holder.replaceChildren(output(ctx, result, null, { kicker: prefill?.kicker || 'Custom workout', number, name, fallback: number ? '' : 'Custom Workout' }));
    holder.scrollIntoView({ behavior: 'smooth' });
  }));

  return h('div', { dataset: { wide: '1' } },
    pageHead('Custom workout', 'Each exercise comes with your best numbers.', { back: '#/retrieve' }),
    h('div', { class: 'split' },
      h('div', {}, h('div', { class: 'search' }, icon('search'), search), picker,
        h('div', { class: 'group pick-bar' }, h('div', { class: 'editor-bar' }, counts[1], gos[1]))),
      h('div', { class: 'split-side' },
        h('div', { class: 'label' }, 'Your workout'),
        h('div', { class: 'field' }, title),
        picked,
        h('div', { class: 'group side-bar' }, h('div', { class: 'editor-bar' }, counts[0], gos[0])))),
    holder);
}
