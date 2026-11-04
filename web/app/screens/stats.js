// Stats: overall progress (Strength Index or Improvement Rate) and each exercise's chart.

import { h, icon, pageHead, lineChart, fmtNum, formatDay } from '../ui.js';
import { normalizeExerciseName } from '../../core/names.js';

const RANGES = [['30', '1M'], ['90', '3M'], ['182', '6M'], ['365', '1Y'], ['all', 'All']];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const METRICS = [['data', 'Estimated max'], ['weight', 'Top weight'], ['volume', 'Volume']];

function since(range) {
  if (range === 'all') return '';
  return new Date(Date.now() - Number(range) * 86400000).toISOString().slice(0, 10);
}

/** Only the points from `from` on (labels are "YYYY-MM-DD"). */
function clip(labels, values, from) {
  if (!from) return [labels, values];
  const i = labels.findIndex((l) => String(l) >= from);
  return i < 0 ? [[], []] : [labels.slice(i), values.slice(i)];
}

const pctText = (v, digits = 1) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${fmtNum(Math.abs(v), digits)}%`;

/** New bests in the range (a session beating every earlier one of that exercise), and the most
 *  improved main lift (the heavier half, three sessions or more in the range). */
function highlights(history, from) {
  const byEx = new Map();
  for (const l of history) {
    const v = Number(l.estimated_1rm);
    if (!(v > 0)) continue;
    const k = normalizeExerciseName(l.exercise);
    if (!byEx.has(k)) byEx.set(k, { name: l.exercise, logs: [] });
    byEx.get(k).logs.push({ day: String(l.date).slice(0, 10), v });
  }
  let newBests = 0;
  const moves = [];
  for (const { name, logs } of byEx.values()) {
    logs.sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));
    let best = null;
    const inRange = [];
    for (const x of logs) {
      const shown = !from || x.day >= from;
      if (shown && best !== null && x.v > best * 1.001) newBests += 1;
      if (shown) inRange.push(x);
      best = best === null ? x.v : Math.max(best, x.v);
    }
    if (inRange.length >= 3) moves.push({ name, pct: ((inRange[inRange.length - 1].v - inRange[0].v) / inRange[0].v) * 100, top: Math.max(...inRange.map((x) => x.v)) });
  }
  moves.sort((a, b) => b.top - a.top);
  const main = moves.slice(0, Math.max(1, Math.ceil(moves.length / 2)));
  const top = main.sort((a, b) => b.pct - a.pct)[0];
  return { newBests, top: top && top.pct > 0 ? top : null };
}

function tile(label, value, sub, cls = '') {
  return h('div', { class: 'stat' }, h('span', {}, label), h('b', { class: cls }, value), sub ? h('small', {}, sub) : null);
}

function tabs(options, value, onPick) {
  return h('div', { class: 'tabs', role: 'tablist' }, options.map(([v, label]) =>
    h('button', { type: 'button', class: v === value ? 'on' : '', role: 'tab', 'aria-selected': String(v === value), onclick: () => onPick(v) }, label)));
}

export function statsScreen(ctx) {
  const { lb } = ctx;
  const prefs = lb.settings();
  let range = prefs.stats_range && RANGES.some(([v]) => v === String(prefs.stats_range)) ? String(prefs.stats_range) : '90';
  let sort = prefs.stats_sort || 'recent';
  let metric = 'data';
  let mode = 'index';
  let exercise = null;
  let wanted = new URLSearchParams(location.hash.split('?')[1] || '').get('exercise');

  const body = h('div', {});
  const root = h('div', { dataset: { wide: '1' } }, pageHead('Stats', 'How your lifts are moving.'), body);

  const options = () => {
    const list = lb.statsOptions();
    if (sort === 'alpha') return list.sort((a, b) => a.label.localeCompare(b.label));
    if (sort === 'most') return list.sort((a, b) => b.sessions - a.sessions || b.views - a.views);
    if (sort === 'viewed') return list.sort((a, b) => b.views - a.views || (b.last > a.last ? 1 : -1));
    return list.sort((a, b) => (b.last > a.last ? 1 : b.last < a.last ? -1 : 0));
  };
  const short = (l) => formatDay(l, { weekday: false, year: false });

  function paint() {
    const from = since(range);
    const overall = lb.overall(mode);
    const [oLabels, oValues] = clip(overall.labels, overall.data, from);
    const warnings = lb.bodyweightWarnings();
    const rangeTabs = tabs(RANGES, range, (v) => {
      range = v;
      lb.setSetting('stats_range', v);
      paint();
    });

    // Overall: the Strength Index as "% stronger" since the first day shown, as the original app.
    const nums = oValues.map(Number).filter(Number.isFinite);
    let hero = null;
    let tiles = null;
    let chart;
    if (mode === 'index' && nums.length) {
      const first = nums[0];
      const asPct = oValues.map((v) => (Number.isFinite(Number(v)) && first ? (Number(v) / first - 1) * 100 : null));
      const last = asPct.filter((v) => v !== null).pop() ?? 0;
      const [fy, fm] = String(oLabels[oValues.findIndex((v) => Number.isFinite(Number(v)))]).split('-').map(Number);
      hero = h('div', { class: 'hero' }, h('b', { class: last < 0 ? 'down' : '' }, pctText(last, Math.abs(last) < 10 ? 1 : 0)),
        h('span', {}, `${last >= 0 ? 'stronger' : 'weaker'} since ${MONTHS[fm - 1]} ${fy}`));
      chart = lineChart(oLabels.map(short), asPct, { base: 0, tag: pctText(last), format: (v) => (Math.abs(v) < 0.5 ? 'Start' : pctText(v, 0)) });
      let bestIdx = 0;
      asPct.forEach((v, k) => { if (v !== null && v > (asPct[bestIdx] ?? -Infinity)) bestIdx = k; });
      const hl = highlights(lb.history(), from);
      tiles = h('div', { class: 'grid-3', style: 'margin-top:14px' },
        tile('Best', pctText(asPct[bestIdx] ?? 0, Math.abs(asPct[bestIdx] ?? 0) < 10 ? 1 : 0), formatDay(oLabels[bestIdx], { weekday: false, year: false })),
        tile('New bests', String(hl.newBests), range === 'all' ? 'all time' : `in ${RANGES.find(([v]) => v === range)[1]}`, 'gold'),
        hl.top ? tile('Most improved', pctText(hl.top.pct, 0), hl.top.name) : tile('Most improved', '–', 'nothing yet'));
    } else {
      chart = lineChart(oLabels.map(short), oValues, { unit: overall.unit === 'percent' && mode === 'rate' ? '%' : '' });
    }

    const opts = options();
    if (!exercise && wanted) {
      // Opened from a workout's "Full progress": that exercise, and its chart in view.
      const key = normalizeExerciseName(wanted);
      exercise = opts.find((o) => o.value === wanted || normalizeExerciseName(o.value) === key || normalizeExerciseName(o.label) === key)?.value || null;
      if (exercise) setTimeout(() => root.querySelector('#exercise')?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 350);
      wanted = null;
    }
    if (!exercise && opts.length) exercise = opts[0].value;
    const select = h('select', { id: 'exercise', 'aria-label': 'Exercise' }, opts.map((o) => h('option', { value: o.value, selected: o.value === exercise }, `${o.label} (${o.sessions})`)));
    select.addEventListener('change', () => {
      exercise = select.value;
      lb.countView(exercise);
      paint();
    });
    const sortSel = h('select', { id: 'sort', 'aria-label': 'Sort exercises', style: 'width:auto' },
      [['recent', 'Recently trained'], ['most', 'Most trained'], ['viewed', 'Most viewed'], ['alpha', 'A to Z']].map(([v, l]) => h('option', { value: v, selected: v === sort }, l)));
    sortSel.addEventListener('change', () => {
      sort = sortSel.value;
      lb.setSetting('stats_sort', sort);
      paint();
    });

    let exerciseCard = h('div', { class: 'empty' }, icon('stats'), 'Log a workout to see charts here.');
    if (exercise) {
      const c = lb.chart(exercise);
      const values = metric === 'volume' ? c.volume : metric === 'weight' ? c.weight : c.data;
      const [labels, vals] = clip(c.labels, values || [], from);
      const st = c.stats || {};
      const unit = c.is_timed && metric !== 'volume' ? 's' : '';
      exerciseCard = h('div', {},
        tabs(METRICS, metric, (v) => {
          metric = v;
          paint();
        }),
        lineChart(labels.map(short), vals, { unit, tag: vals.length ? `${fmtNum(vals[vals.length - 1])}${unit}` : null }),
        h('div', { class: 'grid-3', style: 'margin-top:14px' },
          tile(c.is_timed ? 'Current score' : 'Current est. max', fmtNum(st.current_1rm)),
          tile('Best', fmtNum(st.max_1rm), null, 'gold'),
          tile('Since first', pctText(st.improvement_pct || 0, Math.abs(st.improvement_pct || 0) < 10 ? 1 : 0), null, (st.improvement_pct || 0) < 0 ? '' : '')),
        h('p', { class: 'foot', style: 'margin:12px 2px 0' }, `${c.labels.length} session${c.labels.length === 1 ? '' : 's'}`,
          c.labels.length ? ` · last ${formatDay(c.labels[c.labels.length - 1])}` : ''));
    }

    body.replaceChildren(
      warnings.length ? h('div', { class: 'notice' }, icon('info'), h('div', {},
        'Set your bodyweight in ', h('a', { href: '#/settings/profile' }, 'Settings'), ` so ${warnings.slice(0, 3).join(', ')}${warnings.length > 3 ? '…' : ''} count your bodyweight.`)) : null,
      h('div', { class: 'card' },
        h('div', { class: 'card-head' }, h('h2', {}, mode === 'index' ? 'Overall strength' : 'Improvement rate'),
          tabs([['index', 'Strength'], ['rate', 'Rate']], mode, (v) => {
            mode = v;
            paint();
          })),
        hero,
        h('div', { class: 'card-head', style: 'justify-content:flex-end;margin:4px 0 0' }, rangeTabs),
        chart,
        tiles,
        h('p', { class: 'foot', style: 'margin:12px 2px 0' }, mode === 'index'
          ? 'All your lifts together, against where they were at the start. Exercises you stopped fade out after two months.'
          : 'How fast your lifts are improving, on average.')),
      h('div', { class: 'card' },
        h('div', { class: 'card-head', style: 'margin-bottom:12px' }, h('h2', {}, 'Exercise'), sortSel),
        opts.length ? h('div', { class: 'field' }, select) : null,
        exerciseCard));
  }
  paint();
  return root;
}
