// Stats: overall progress (Strength Index or Improvement Rate) and each exercise's chart.

import { h, icon, pageHead, lineChart, fmtNum, formatDay } from '../ui.js';
import { normalizeExerciseName } from '../../core/names.js';
import { overallView } from '../../core/overall_view.js';

const RANGES = [['30', '1M'], ['90', '3M'], ['180', '6M'], ['365', '1Y'], ['all', 'All']];
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
  if (String(prefs.stats_range) === '182') prefs.stats_range = '180'; // 6M was 182 days for a while
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

    // Overall: the Strength Index against your start (100), as the original page showed it
    // (core/overall_view.js): the headline is the 14-day average and doesn't change with the
    // range; the range changes the line under it, the chart and the tiles.
    let hero = null;
    let tiles = null;
    let chart;
    const view = mode === 'index' ? overallView(overall, range) : null;
    if (view) {
      const [fy, fm] = String(view.firstLabel).split('-').map(Number);
      const sinceText = view.direction === 'up' ? `stronger since ${MONTHS[fm - 1]} ${fy}`
        : view.direction === 'down' ? `below your ${MONTHS[fm - 1]} ${fy} start` : `level with your ${MONTHS[fm - 1]} ${fy} start`;
      hero = h('div', { class: 'hero' },
        h('b', { class: view.direction === 'down' ? 'down' : '' }, view.headline),
        h('span', {}, sinceText),
        view.change ? h('small', { class: `hero-change ${view.change.direction}` },
          view.change.amount ? h('strong', {}, `${view.change.direction === 'down' ? '↓' : '↑'} ${view.change.amount}`) : '', view.change.text) : '');
      chart = lineChart(view.labels.map(short), view.line, { base: 0, tag: view.headline, format: (v) => (Math.abs(v) < 0.5 ? 'Start' : pctText(v, 0)) });
      tiles = h('div', { class: 'grid-3', style: 'margin-top:14px' },
        view.best ? tile('Best', view.best.text, formatDay(view.best.day, { weekday: false, year: false })) : tile('Best', '–', ''),
        tile('New bests', String(view.newBests), view.rangeText, 'gold'),
        view.top ? tile('Most improved', view.top.text, view.top.name) : tile('Most improved', '–', 'nothing yet'));
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

    body.replaceChildren(...[
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
        exerciseCard)].filter(Boolean)); // replaceChildren would print a null as the word "null"
  }
  paint();
  return root;
}
