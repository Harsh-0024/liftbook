// Stats: overall progress (Strength Index or Improvement Rate) and each exercise's chart.

import { h, icon, pageHead, lineChart, fmtNum, formatDay, toast } from '../ui.js';
import { normalizeExerciseName } from '../../core/names.js';
import { addDays, deviceDay } from '../../core/dates.js';
import { overallView } from '../../core/overall_view.js';
import { consistencyYears, yearWindow, consistencyHero, consistencyTiles, yearGrid } from '../../core/consistency.js';

const VIEW_KEY = 'liftbook-stats-view';
const YEAR_KEY = 'liftbook-stats-year';
const remembered = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
const remember = (key, v) => { try { localStorage.setItem(key, String(v)); } catch { /* private browsing */ } };

/** One year of days as squares (Monday first), as the original Stats page drew it. */
function calendar(grid, onPick) {
  const W = Math.max(280, Math.min(1040, (globalThis.innerWidth || 640) - 88));
  const weeks = grid.weeks.length;
  const gap = 3;
  const daysW = 30;
  const fit = Math.floor((W - daysW - (weeks - 1) * gap) / weeks);
  const slides = fit < 10;
  const cell = slides ? 12 : Math.min(fit, 17);
  const cells = h('div', { class: 'cal-grid' });
  let picked = null;
  for (const week of grid.weeks) {
    for (const d of week) {
      const el = h('span', { class: `cal-cell${d.out ? ' out' : ''}${d.future ? ' future' : ''}${d.on ? ' on' : ''}${d.today ? ' today' : ''}`, dataset: d.on ? { l: String(d.level) } : {} });
      if (!d.out && !d.future) {
        el.tabIndex = -1;
        el.addEventListener('click', () => {
          picked?.classList.remove('hot');
          el.classList.add('hot');
          picked = el;
          onPick(d);
        });
      }
      cells.append(el);
    }
  }
  const months = h('div', { class: 'cal-months', 'aria-hidden': 'true', style: `width:${weeks * cell + (weeks - 1) * gap}px` },
    grid.months.map((m) => h('span', { style: `left:${m.col * (cell + gap)}px` }, m.name)));
  const scroll = h('div', { class: 'cal-scroll' }, months, cells);
  const box = h('div', { class: 'cal', style: `--cal-cell:${cell}px;--cal-gap:${gap}px;--cal-days-w:${daysW}px` },
    h('div', { class: 'cal-body' },
      h('div', { class: 'cal-days', 'aria-hidden': 'true' }, ['Mon', '', 'Wed', '', 'Fri', '', ''].map((t) => h('span', {}, t))),
      scroll),
    h('div', { class: 'cal-legend', 'aria-hidden': 'true' }, h('span', {}, 'Less'), [0, 1, 2, 3, 4].map((l) => h('i', { dataset: { l: String(l) } })), h('span', {}, 'More')));
  if (slides) {
    // A phone can't fit the year: open on the latest weeks.
    const col = Math.max(0, grid.weeks.findIndex((w) => w.some((d) => d.today)));
    setTimeout(() => { scroll.scrollLeft = Math.max(0, (col + 1) * (cell + gap) - scroll.clientWidth + cell * 2); }, 0);
  }
  return box;
}

const RANGES = [['30', '1M'], ['90', '3M'], ['180', '6M'], ['365', '1Y'], ['all', 'All']];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const METRICS = [['data', 'Estimated max'], ['weight', 'Top weight'], ['volume', 'Volume']];

function since(range) {
  if (range === 'all') return '';
  return addDays(deviceDay(), -Number(range));
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
  let mode = remembered(VIEW_KEY) === 'consistency' ? 'consistency' : 'index';
  let year = Number(remembered(YEAR_KEY)) || null;
  let exercise = null;
  let wanted = new URLSearchParams(location.hash.split('?')[1] || '').get('exercise');

  const body = h('div', {});
  // Search an exercise, as the old Stats page had: picking one opens it in the Exercise card.
  const list = h('datalist', { id: 'stats-exercises' });
  const search = h('input', { id: 'stats-search', type: 'search', list: 'stats-exercises', placeholder: 'Search an exercise',
    'aria-label': 'Search an exercise', autocapitalize: 'off', autocomplete: 'off', enterkeyhint: 'go' });
  const jump = () => {
    const q = search.value.trim().toLowerCase();
    if (!q) return;
    const opts = lb.statsOptions();
    const hit = opts.find((o) => o.label.toLowerCase() === q) || opts.find((o) => o.label.toLowerCase().startsWith(q))
      || opts.find((o) => o.label.toLowerCase().includes(q));
    if (!hit) return toast(`No exercise called “${search.value.trim()}” in your workouts.`);
    exercise = hit.value;
    lb.countView(exercise);
    search.value = '';
    search.blur();
    paint();
    body.querySelector('#exercise-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  // A pick from the suggestions fires "input" with the full name; Enter jumps on whatever was typed.
  search.addEventListener('input', () => {
    if (lb.statsOptions().some((o) => o.label === search.value)) jump();
  });
  search.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      jump();
    }
  });
  const root = h('div', { dataset: { wide: '1' } }, pageHead('Stats', 'How your lifts are moving.'),
    h('div', { class: 'search', style: 'margin-bottom:18px' }, icon('search'), search, list), body);

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
    const overall = lb.overall(mode === 'rate' ? 'rate' : 'index');
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

    let yearTabs = null;
    let foot = mode === 'index'
      ? 'All your lifts together, against where they were at the start. Exercises you stopped fade out after two months.'
      : 'How fast your lifts are improving, on average.';
    if (mode === 'consistency') {
      // Consistency: the days you trained, one calendar year at a time.
      const dayList = [...(overall.workout_days || [])].sort();
      const years = consistencyYears(dayList);
      if (!years.includes(year)) year = years[years.length - 1];
      const win = yearWindow(year);
      foot = 'A square for every day of the year. Gold days are days you trained; the deeper the gold, the more sets you did.';
      if (!dayList.length) {
        hero = null;
        tiles = null;
        chart = h('div', { class: 'empty' }, icon('calendar'), 'Log a few workouts to see the days you trained.');
      } else {
        const c = consistencyHero(dayList, win);
        hero = h('div', { class: 'hero' }, h('b', {}, c.value), h('span', {}, c.caption),
          c.change ? h('small', { class: `hero-change ${c.change.direction}` },
            c.change.amount ? h('strong', {}, `${c.change.direction === 'down' ? '↓' : '↑'} ${c.change.amount}`) : '', c.change.text) : '');
        yearTabs = tabs(years.map((y) => [y, String(y)]), year, (y) => {
          year = y;
          remember(YEAR_KEY, y);
          paint();
        });
        const tip = h('p', { class: 'cal-tip', 'aria-live': 'polite' }, 'Tap a day to see it.');
        const g = yearGrid(win, dayList, { titles: overall.day_titles || {}, daySets: overall.day_sets || {} });
        chart = h('div', {}, calendar(g, (d) => {
          const when = formatDay(d.iso);
          tip.replaceChildren(...(d.on
            ? [h('b', {}, d.title), ` · ${when}${d.sets ? ` · ${d.sets} set${d.sets === 1 ? '' : 's'}` : ''} `, h('a', { href: `#/workout/${d.iso}` }, 'Open')]
            : [`${when} · Rest day`]));
        }), tip);
        const narrow = (globalThis.innerWidth || 640) < 480;
        const t = consistencyTiles(dayList, win, { short: narrow });
        tiles = h('div', { class: 'grid-3', style: 'margin-top:14px' },
          tile('Workouts', t.workouts.value, t.workouts.sub, 'gold'),
          tile('Busiest month', t.month.value, t.month.sub),
          tile('Favourite day', t.day.value, t.day.sub));
      }
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
    list.replaceChildren(...opts.map((o) => h('option', { value: o.label })));
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
        h('div', { class: 'card-head' }, h('h2', {}, mode === 'index' ? 'Overall strength' : mode === 'rate' ? 'Improvement rate' : 'Consistency'),
          tabs([['index', 'Strength'], ['rate', 'Rate'], ['consistency', 'Consistency']], mode, (v) => {
            mode = v;
            if (v !== 'rate') remember(VIEW_KEY, v === 'consistency' ? 'consistency' : 'strength');
            paint();
          })),
        hero,
        mode === 'consistency'
          ? (yearTabs ? h('div', { class: 'card-head', style: 'justify-content:flex-end;margin:4px 0 0' }, yearTabs) : '')
          : h('div', { class: 'card-head', style: 'justify-content:flex-end;margin:4px 0 0' }, rangeTabs),
        chart,
        tiles || '',
        h('p', { class: 'foot', style: 'margin:12px 2px 0' }, foot)),
      h('div', { class: 'card', id: 'exercise-card', style: 'scroll-margin-top:90px' },
        h('div', { class: 'card-head', style: 'margin-bottom:12px' }, h('h2', {}, 'Exercise'), sortSel),
        opts.length ? h('div', { class: 'field' }, select) : null,
        exerciseCard)].filter(Boolean)); // replaceChildren would print a null as the word "null"
  }
  paint();
  return root;
}
