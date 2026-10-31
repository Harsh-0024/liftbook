// Stats: overall progress (Strength Index or Improvement Rate) and each exercise's chart.

import { h, lineChart, fmtNum, formatDay } from '../ui.js';

const RANGES = [['30', '1 month'], ['90', '3 months'], ['365', '1 year'], ['all', 'All']];
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

  const body = h('div', {});
  const root = h('div', {},
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Stats'), h('p', { class: 'muted', style: 'margin:0' }, 'How your lifts are moving.'))),
    body);

  const options = () => {
    const list = lb.statsOptions();
    if (sort === 'alpha') return list.sort((a, b) => a.label.localeCompare(b.label));
    if (sort === 'most') return list.sort((a, b) => b.sessions - a.sessions || b.views - a.views);
    if (sort === 'viewed') return list.sort((a, b) => b.views - a.views || (b.last > a.last ? 1 : -1));
    return list.sort((a, b) => (b.last > a.last ? 1 : b.last < a.last ? -1 : 0));
  };

  function paint() {
    const from = since(range);
    const overall = lb.overall(mode);
    const [oLabels, oValues] = clip(overall.labels, overall.data, from);
    const warnings = lb.bodyweightWarnings();

    const opts = options();
    if (!exercise && opts.length) exercise = opts[0].value;
    const select = h('select', { id: 'exercise' }, opts.map((o) => h('option', { value: o.value, selected: o.value === exercise }, `${o.label} (${o.sessions})`)));
    select.addEventListener('change', () => {
      exercise = select.value;
      lb.countView(exercise);
      paint();
    });
    const sortSel = h('select', { id: 'sort', 'aria-label': 'Sort exercises' },
      [['recent', 'Recently trained'], ['most', 'Most trained'], ['viewed', 'Most viewed'], ['alpha', 'A to Z']].map(([v, l]) => h('option', { value: v, selected: v === sort }, l)));
    sortSel.addEventListener('change', () => {
      sort = sortSel.value;
      lb.setSetting('stats_sort', sort);
      paint();
    });

    let exerciseCard = h('p', { class: 'muted' }, 'Log a workout to see charts here.');
    if (exercise) {
      const c = lb.chart(exercise);
      const values = metric === 'volume' ? c.volume : metric === 'weight' ? c.weight : c.data;
      const [labels, vals] = clip(c.labels, values || [], from);
      const st = c.stats || {};
      exerciseCard = h('div', {},
        tabs(METRICS, metric, (v) => {
          metric = v;
          paint();
        }),
        lineChart(labels.map((l) => formatDay(l, { weekday: false, year: false })), vals, { unit: c.is_timed && metric !== 'volume' ? 's' : '' }),
        h('div', { class: 'grid-3', style: 'margin-top:12px' },
          h('div', { class: 'stat' }, h('b', {}, fmtNum(st.current_1rm)), h('span', {}, c.is_timed ? 'current score' : 'current est. max')),
          h('div', { class: 'stat' }, h('b', {}, fmtNum(st.max_1rm)), h('span', {}, 'best')),
          h('div', { class: 'stat' }, h('b', {}, `${st.improvement_pct >= 0 ? '+' : ''}${fmtNum(st.improvement_pct)}%`), h('span', {}, 'since first'))),
        h('p', { class: 'subtle', style: 'margin-top:10px' }, `${c.labels.length} session${c.labels.length === 1 ? '' : 's'}`,
          c.labels.length ? ` · last ${formatDay(c.labels[c.labels.length - 1])}` : ''));
    }

    body.replaceChildren(
      tabs(RANGES, range, (v) => {
        range = v;
        lb.setSetting('stats_range', v);
        paint();
      }),
      warnings.length ? h('div', { class: 'card gold' }, h('p', { style: 'margin:0' },
        'Set your bodyweight in ', h('a', { href: '#/settings/profile' }, 'Settings'), ` so ${warnings.slice(0, 3).join(', ')}${warnings.length > 3 ? '…' : ''} count your bodyweight.`)) : null,
      h('div', { class: 'card' },
        h('div', { class: 'row spread' }, h('h2', { style: 'margin:0' }, 'Overall'),
          tabs([['index', 'Strength Index'], ['rate', 'Improvement Rate']], mode, (v) => {
            mode = v;
            paint();
          })),
        lineChart(oLabels.map((l) => formatDay(l, { weekday: false, year: false })), oValues, { unit: overall.unit === 'percent' && mode === 'rate' ? '%' : '' }),
        h('p', { class: 'subtle', style: 'margin:8px 0 0' }, mode === 'index'
          ? 'Your lifts together, 100 = where you started. Exercises you stopped fade out after two months.'
          : 'How fast your lifts are improving, on average.')),
      h('div', { class: 'card' },
        h('div', { class: 'row spread', style: 'margin-bottom:10px' }, h('h2', { style: 'margin:0' }, 'Exercise'), sortSel),
        opts.length ? h('div', { class: 'field' }, select) : null,
        exerciseCard));
  }
  paint();
  return root;
}
