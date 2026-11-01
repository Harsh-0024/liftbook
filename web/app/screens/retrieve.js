// Retrieve: the next workout's targets from the plan and the last sets, as text to copy into
// the Log page (or a notes app) at the gym.

import { h, copyText, busy, toast } from '../ui.js';
import { DRAFT_KEY } from './log.js';

function dayLabel(plans, category, dayName) {
  const id = dayName.slice(category.length).trim();
  const title = category === 'Session' ? plans.session_titles?.[id] : null;
  return { id, label: title ? `${dayName} · ${title}` : dayName };
}

export function retrieveScreen(ctx) {
  const { lb } = ctx;
  const plans = lb.planDays();
  const cats = Object.entries(plans.workout || {});
  const following = lb.settings().follow_shared_plan && !lb.isAdmin();

  const sections = cats.map(([category, days]) => h('div', { class: 'card' },
    h('h2', {}, category),
    h('ul', { class: 'list' }, Object.keys(days).map((dayName) => {
      const { id, label } = dayLabel(plans, category, dayName);
      return h('li', {}, h('a', { class: 'item chev', href: `#/retrieve/day/${encodeURIComponent(category)}/${id}` },
        h('div', {}, h('div', { style: 'font-weight:600' }, label),
          h('div', { class: 'meta' }, `${days[dayName].length} exercise${days[dayName].length === 1 ? '' : 's'}`))));
    }))));

  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Retrieve'),
        h('p', { class: 'muted', style: 'margin:0' }, following ? 'From the shared plan you follow.' : 'From your plan.')),
      h('a', { class: 'btn', href: '#/retrieve/custom' }, 'Pick exercises')),
    sections.length ? sections : h('div', { class: 'card' }, h('p', { class: 'muted' }, 'Your plan has no days yet.'),
      h('a', { class: 'btn', href: '#/settings/plan' }, 'Write your plan')),
    h('p', { class: 'subtle' }, 'Change the plan in ', h('a', { href: '#/settings/plan' }, 'Settings › Plan'), '.'));
}

function output(ctx, result, back) {
  const logIt = () => {
    try {
      localStorage.setItem(DRAFT_KEY, result.text);
    } catch {
      // nothing kept; the copy button still works
    }
    ctx.go('log');
  };
  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, result.described.header.replace(/^\S+\s+-\s+/, '') || 'Targets'),
        h('p', { class: 'muted', style: 'margin:0' }, `${result.exercises} exercise${result.exercises === 1 ? '' : 's'}, ${result.sets} set${result.sets === 1 ? '' : 's'}`)),
      h('a', { class: 'btn small', href: back }, 'Back')),
    h('div', { class: 'card' }, h('pre', { class: 'out' }, result.text)),
    h('div', { class: 'row' },
      h('button', { class: 'btn primary', type: 'button', onclick: () => copyText(result.text) }, 'Copy'),
      h('button', { class: 'btn', type: 'button', onclick: logIt }, 'Log from this')),
    h('p', { class: 'subtle', style: 'margin-top:12px' }, 'Each exercise shows your best recent sets as the starting point. Change the numbers to what you actually lift.'));
}

export function retrieveDayScreen(ctx, category, id) {
  const result = ctx.lb.retrieveDay(decodeURIComponent(category), Number(id));
  return output(ctx, result, '#/retrieve');
}

export function retrieveCustomScreen(ctx) {
  const { lb } = ctx;
  const catalog = lb.exerciseCatalog();
  const title = h('input', { id: 'title', type: 'text', placeholder: 'Custom Workout', maxlength: 80 });
  const search = h('input', { id: 'search', type: 'search', placeholder: 'Search exercises', autocapitalize: 'off' });
  const chosen = new Set();
  const picker = h('div', { class: 'picker' });
  const count = h('span', { class: 'subtle' }, 'None picked');
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    picker.replaceChildren(...catalog.filter((c) => !q || c.name.toLowerCase().includes(q)).slice(0, 200).map((c) => {
      const box = h('input', { type: 'checkbox', checked: chosen.has(c.name) });
      box.addEventListener('change', () => {
        if (box.checked) chosen.add(c.name);
        else chosen.delete(c.name);
        count.textContent = chosen.size ? `${chosen.size} picked` : 'None picked';
      });
      return h('label', {}, box, h('span', {}, c.name), c.count ? h('span', { class: 'subtle', style: 'margin-left:auto' }, `${c.count}×`) : null);
    }));
  };
  search.addEventListener('input', paint);
  paint();

  const go = h('button', { class: 'btn primary', type: 'button' }, 'Get targets');
  const holder = h('div', {});
  go.addEventListener('click', busy(go, async () => {
    if (!chosen.size) {
      toast('Pick at least one exercise.');
      return;
    }
    const names = [...chosen];
    const result = lb.retrieveCustom(names, title.value);
    await lb.recordRetrievals(names);
    holder.replaceChildren(output(ctx, result, '#/retrieve/custom'));
    holder.scrollIntoView({ behavior: 'smooth' });
  }));

  return h('div', {},
    h('div', { class: 'page-head' }, h('h1', {}, 'Pick exercises'), h('a', { class: 'btn small', href: '#/retrieve' }, 'Back')),
    h('div', { class: 'card' },
      h('div', { class: 'field' }, h('label', { for: 'title' }, 'Title'), title),
      h('div', { class: 'field' }, h('label', { for: 'search' }, 'Exercises'), search),
      picker,
      h('div', { class: 'row spread', style: 'margin-top:12px' }, count, go)),
    holder);
}
