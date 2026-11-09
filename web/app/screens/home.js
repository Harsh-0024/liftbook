// Home (a welcome: you, two ways in, the last few workouts), every workout, one workout, and
// editing it. The layout follows the original app's.

import { h, icon, rowItem, pageHead, softDay, formatDay, copyText, toast, busy, fmtNum, ask, autoGrow } from '../ui.js';
import { formatSetsDisplay } from '../../core/logging.js';
import { attachSuggestions } from '../suggest.js';
import { attachPasteTidy } from '../paste.js';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** The person's photo, or their initial until it loads (or when there is none). */
function avatar(ctx, cls, attrs = {}) {
  const p = ctx.lb.profile() || {};
  const name = p.full_name || p.username || ctx.user?.email || '?';
  const el = h(attrs.href ? 'a' : 'div', { class: `avatar ${cls}`, ...attrs }, name.trim().charAt(0).toUpperCase());
  if (p.avatar_path) {
    ctx.lb.avatarUrl().then((url) => {
      if (!url) return;
      const img = h('img', { src: url, alt: '' });
      img.addEventListener('load', () => el.replaceChildren(img));
    }).catch(() => {});
  }
  return el;
}
export { avatar };

const hello = (now = new Date()) => {
  const hr = now.getHours();
  return hr >= 5 && hr < 12 ? 'Good morning' : hr >= 12 && hr < 17 ? 'Good afternoon' : 'Good evening';
};

export function homeScreen(ctx) {
  const { lb } = ctx;
  const profile = lb.profile() || {};
  const workouts = lb.workouts();
  const recent = workouts.slice(0, 3);
  const first = (profile.full_name || profile.username || '').trim().split(/\s+/)[0] || 'there';
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  const doneToday = recent[0]?.day === todayIso;
  const o = lb.overview();

  const actions = workouts.length
    ? [doneToday
      ? h('a', { class: 'btn primary big', href: `#/workout/${recent[0].day}` }, icon('check'), 'Today’s workout')
      : h('a', { class: 'btn primary big', href: '#/log' }, icon('plus'), 'Log workout'),
    h('a', { class: 'btn big', href: '#/retrieve' }, icon('list'), 'Retrieve')]
    : [h('a', { class: 'btn primary big', href: '#/retrieve' }, icon('list'), 'Retrieve a plan'),
      h('a', { class: 'btn big', href: '#/log' }, icon('plus'), 'Log workout')];

  return h('div', { class: 'home' },
    h('section', { class: 'hello' },
      avatar(ctx, 'big', { href: '#/settings/profile', 'aria-label': 'Profile and settings' }),
      h('p', { class: 'greet' }, workouts.length ? hello(today) : 'Welcome'),
      h('h1', {}, first),
      doneToday ? h('p', { class: 'note' }, 'Nice work today.')
        : !workouts.length ? h('p', { class: 'note muted' }, 'Your workouts will show up here.') : null),
    h('div', { class: 'home-actions' }, actions),
    workouts.length ? h('section', { class: 'section', 'aria-label': 'Recent workouts' },
      h('div', { class: 'label' }, 'Recent'),
      h('div', { class: 'group' }, recent.map((w) => rowItem({
        href: `#/workout/${w.day}`, title: w.title, value: softDay(w.day, today),
      }))),
      h('div', { class: 'grid-3 home-stats' },
        h('div', { class: 'stat' }, h('span', {}, 'Workouts'), h('b', {}, o.total)),
        h('div', { class: 'stat' }, h('span', {}, 'This week'), h('b', { class: 'gold' }, o.thisWeek)),
        h('div', { class: 'stat' }, h('span', {}, 'Exercises'), h('b', {}, o.exercises))),
      h('a', { class: 'see-all', href: '#/history' }, 'See all workouts')) : null);
}

// A long history is drawn a page at a time; "Show more" adds the next page.
const PAGE = 60;

/** Every workout, a month at a time, with a search, and Select to delete several at once. */
export function historyScreen(ctx) {
  const { lb } = ctx;
  const workouts = lb.workouts();
  // Selecting survives a synced redraw of this page, not a visit to another one.
  // '#/history?select' (from Sync and data) opens it already picking.
  const fromSettings = /[?&]select\b/.test(location.hash);
  const pick = ctx.redrawing && ctx.historyPick ? ctx.historyPick : { on: fromSettings, days: new Set(), limit: PAGE };
  ctx.historyPick = pick;
  for (const d of [...pick.days]) if (!lb.workout(d)) pick.days.delete(d);
  const search = h('input', { type: 'search', placeholder: 'Search workouts or exercises', 'aria-label': 'Search workouts', autocomplete: 'off' });
  const body = h('div', {});
  const toggle = h('button', { class: 'btn small ghost', type: 'button' });
  const count = h('span', { class: 'count', 'aria-live': 'polite' });
  const all = h('button', { class: 'btn small ghost', type: 'button' }, 'Select all');
  const del = h('button', { class: 'btn small danger', type: 'button' }, icon('trash'), 'Delete');
  const bar = h('div', { class: 'pick-dock', role: 'region', 'aria-label': 'Selected workouts' }, count, h('span', { class: 'row' }, all, del));
  let shown = workouts;

  const paintBar = () => {
    toggle.textContent = pick.on ? 'Cancel' : 'Select';
    toggle.hidden = !workouts.length;
    bar.classList.toggle('on', pick.on);
    body.classList.toggle('picking-pad', pick.on); // room for the bar under the last row
    count.textContent = pick.days.size ? `${pick.days.size} selected` : 'Select workouts';
    del.disabled = !pick.days.size;
    const everyShown = shown.length && shown.every((w) => pick.days.has(w.day));
    all.textContent = everyShown ? 'Select none' : 'Select all';
  };
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    shown = q
      ? workouts.filter((w) => w.title.toLowerCase().includes(q) || w.logs.some((l) => String(l.exercise).toLowerCase().includes(q)) || w.day.includes(q))
      : workouts;
    const months = new Map();
    const inMonth = new Map();
    shown.forEach((w, i) => {
      const k = w.day.slice(0, 7);
      inMonth.set(k, (inMonth.get(k) || 0) + 1);
      if (i >= pick.limit) return;
      if (!months.has(k)) months.set(k, []);
      months.get(k).push(w);
    });
    const left = shown.length - pick.limit;
    const more = left > 0 ? h('button', { class: 'btn more-btn', type: 'button', onclick: () => { pick.limit += PAGE; paint(); } },
      ...(left > PAGE ? [`Show ${PAGE} more`, h('span', { class: 'subtle' }, `·\u2002${left} left`)] : [`Show the last ${left}`])) : null;
    body.replaceChildren(...(shown.length ? [...months].map(([k, ws]) => {
      const [y, m] = k.split('-').map(Number);
      const n = inMonth.get(k);
      return h('section', { class: 'section' },
        h('div', { class: 'label' }, `${MONTHS[m - 1]} ${y}`, h('span', {}, `${n} workout${n === 1 ? '' : 's'}`)),
        h('div', { class: `group${pick.on ? ' picking' : ''}` }, ws.map((w) => {
          const [yy, mm, dd] = w.day.split('-').map(Number);
          const inner = [
            h('span', { class: 'datebox' }, h('b', {}, dd), h('small', {}, WD[new Date(Date.UTC(yy, mm - 1, dd)).getUTCDay()])),
            h('span', { class: 'main' }, h('span', { class: 'title' }, w.title),
              h('span', { class: 'desc ellipsis' }, w.logs.map((l) => l.exercise).join(' · ')))];
          if (!pick.on) return h('a', { class: 'rowi', href: `#/workout/${w.day}` }, ...inner, h('span', { class: 'chev-i' }, icon('chev')));
          const on = pick.days.has(w.day);
          const row = h('button', { class: `rowi${on ? ' picked' : ''}`, type: 'button', role: 'checkbox', 'aria-checked': String(on) },
            ...inner, h('span', { class: 'tick', 'aria-hidden': 'true' }, icon('check')));
          row.addEventListener('click', () => {
            const now = !pick.days.has(w.day);
            if (now) pick.days.add(w.day);
            else pick.days.delete(w.day);
            row.classList.toggle('picked', now);
            row.setAttribute('aria-checked', String(now));
            paintBar();
          });
          return row;
        })));
    }).concat(more || []) : [h('div', { class: 'group empty' }, icon('search'), q ? `Nothing matches “${search.value.trim()}”.` : 'No workouts yet.')]));
    paintBar();
  };
  toggle.addEventListener('click', () => {
    pick.on = !pick.on;
    pick.days.clear();
    paint();
  });
  all.addEventListener('click', () => {
    const everyShown = shown.every((w) => pick.days.has(w.day));
    for (const w of shown) {
      if (everyShown) pick.days.delete(w.day);
      else pick.days.add(w.day);
    }
    paint();
  });
  del.addEventListener('click', busy(del, async () => {
    const days = [...pick.days];
    if (!days.length) return;
    const what = days.length === 1 ? `${lb.workout(days[0])?.title || 'this workout'} on ${formatDay(days[0])}` : `${days.length} workouts`;
    if (!(await ask(`This removes ${days.length === 1 ? 'it' : 'them'} from all your devices.`, { title: `Delete ${what}?`, yes: 'Delete', danger: true }))) return;
    const ids = await lb.deleteWorkouts(days);
    pick.on = false;
    pick.days.clear();
    const n = days.length;
    toast(n === 1 ? 'Workout deleted.' : `${n} workouts deleted.`, { ms: 8000, action: 'Undo', onAction: async () => {
      await lb.restoreLogs(ids);
      toast(n === 1 ? 'Workout back.' : `${n} workouts back.`);
      ctx.refresh();
    } });
    ctx.go('history');
  }));
  // Escape leaves Select, as on the old list.
  const onKey = (e) => {
    if (!body.isConnected) return document.removeEventListener('keydown', onKey);
    if (e.key === 'Escape' && pick.on) toggle.click();
  };
  document.addEventListener('keydown', onKey);
  search.addEventListener('input', (e) => {
    // A new search starts from the first page; the app putting back your search after a redraw doesn't.
    if (e.isTrusted) pick.limit = PAGE;
    paint();
  });
  paint();
  return h('div', {},
    pageHead('All workouts', `${workouts.length} workout${workouts.length === 1 ? '' : 's'} logged.`, { back: fromSettings ? '#/settings' : '#/', aside: toggle }),
    h('div', { class: 'search' }, icon('search'), search),
    body, bar);
}

const signed = (v, digits = 1) => (v === null || v === undefined ? '' : `${v > 0 ? '+' : v < 0 ? '−' : '±'}${fmtNum(Math.abs(v), digits)}%`);

function vsRecent(c) {
  const chip = c.trend
    ? h('span', { class: `chip ${c.trend.direction}`, title: 'Vs your recent average' }, c.trend.text)
    : h('span', { class: 'chip none', title: 'No earlier sessions yet' }, '—');
  return h('span', { class: 'cell' }, chip);
}

function vsBest(c) {
  const b = c.best;
  return h('span', { class: 'cell' },
    h('span', { class: `chip ${b.kind}${b.tier ? ` ${b.tier}` : ''}`, title: b.explain }, b.emoji ? h('span', { class: 'emoji' }, b.emoji) : null, b.chip));
}

/** A small "i" that opens a few lines explaining a block. */
function infoPop(label, items) {
  return h('details', { class: 'info-pop' },
    h('summary', { 'aria-label': label }, icon('info')),
    h('div', { class: 'pop' }, h('ul', {}, items.filter(Boolean).map((x) => h('li', {}, x)))));
}

const SVG = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, v);
  return el;
}

/** The last few sessions as a line: slide across (or hover) to see each one, tap its card to open it. */
function sparkChart(ctx, sp, first, today) {
  const svg = svgEl('svg', { class: 'spark', viewBox: `0 0 ${sp.width} ${sp.height}`, role: 'img', 'aria-label': `Last ${sp.dots.length} sessions. Slide across to see each session.` });
  if (sp.average_y !== null) svg.append(svgEl('line', { class: 'avg', x1: 0, x2: sp.width, y1: sp.average_y, y2: sp.average_y }));
  svg.append(svgEl('path', { class: 'line', d: sp.path }));
  for (const d of sp.dots) {
    if (d.is_today) svg.append(svgEl('circle', { class: 'today', cx: d.x, cy: d.y, r: 7 }));
    else {
      svg.append(svgEl('circle', { class: 'dot', cx: d.x, cy: d.y, r: 4 }));
      if (d.is_best) svg.append(svgEl('circle', { class: 'best', cx: d.x, cy: d.y, r: 9 }));
    }
  }
  const guide = svgEl('line', { class: 'guide', x1: 0, x2: 0, y1: 0, y2: sp.height, visibility: 'hidden' });
  const focus = svgEl('circle', { class: 'focus', cx: 0, cy: 0, r: 9, visibility: 'hidden' });
  svg.append(guide, focus);
  const tipDate = h('div', { class: 'tip-date' });
  const tipSets = h('div', { class: 'tip-sets' });
  const tip = h('div', { class: 'spark-tip', role: 'status', hidden: true }, tipDate, tipSets);
  const wrap = h('div', { class: 'spark-wrap' }, svg, h('div', { class: 'spark-axis' }, h('span', {}, first), h('span', {}, 'Today')), tip);
  let active = -1;
  let pointer = 'mouse';
  const open = () => {
    const p = sp.dots[active];
    if (p && !p.is_today) ctx.go(`workout/${p.day}?from=${today}`);
  };
  const hide = () => {
    active = -1;
    tip.hidden = true;
    guide.setAttribute('visibility', 'hidden');
    focus.setAttribute('visibility', 'hidden');
  };
  const showAt = (i) => {
    if (i === active) return;
    active = i;
    const p = sp.dots[i];
    for (const [k, v] of [['x1', p.x], ['x2', p.x]]) guide.setAttribute(k, v);
    focus.setAttribute('cx', p.x);
    focus.setAttribute('cy', p.y);
    guide.setAttribute('visibility', 'visible');
    focus.setAttribute('visibility', 'visible');
    tipDate.textContent = p.is_today ? `${p.date_text} · today` : p.date_text;
    tipSets.textContent = p.sets;
    tip.classList.toggle('touch', pointer !== 'mouse' && !p.is_today);
    tip.hidden = false;
    // Above the point, below it near the top; always inside the chart's width.
    const rect = svg.getBoundingClientRect();
    const px = (p.x * rect.width) / sp.width;
    const py = (p.y * rect.height) / sp.height;
    const left = Math.max(0, Math.min(px - tip.offsetWidth / 2, wrap.clientWidth - tip.offsetWidth));
    const top = py - tip.offsetHeight - 14 >= -8 ? py - tip.offsetHeight - 14 : py + 16;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  };
  const track = (e) => {
    pointer = e.pointerType || 'mouse';
    const rect = svg.getBoundingClientRect();
    const x = ((e.clientX - rect.left) * sp.width) / rect.width;
    let best = 0;
    sp.dots.forEach((p, i) => { if (Math.abs(p.x - x) < Math.abs(sp.dots[best].x - x)) best = i; });
    showAt(best);
  };
  svg.addEventListener('pointerdown', track);
  svg.addEventListener('pointermove', track);
  svg.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') hide(); });
  // Mouse: a click opens that session. Touch: a tap moves the card, and tapping the card opens it.
  svg.addEventListener('click', () => { if (pointer === 'mouse') open(); });
  tip.addEventListener('click', open);
  const away = (e) => {
    if (!wrap.isConnected) return document.removeEventListener('pointerdown', away);
    if (!wrap.contains(e.target)) hide();
  };
  document.addEventListener('pointerdown', away);
  const best = sp.dots.some((d) => d.is_best);
  return h('div', {}, wrap,
    h('div', { class: 'spark-legend' },
      h('span', {}, h('i', { class: 'key today' }), 'Today'),
      best ? h('span', {}, h('i', { class: 'key best' }), 'Your best') : null,
      sp.average_y !== null ? h('span', {}, h('i', { class: 'key avg' }), 'Recent average') : null));
}

/** Just saved: a short note (the rows below already show what was saved), and anything to answer. */
function savedNote(ctx, saved) {
  const note = h('div', { class: 'saved-note', role: 'status' }, icon('check'),
    h('div', { class: 'main' },
      h('strong', {}, saved.appended ? 'Added to this day' : 'Saved'),
      (saved.skipped || []).map((line) => h('p', {}, String(line).replace("won't be saved", "wasn't saved"))),
      saved.needsBodyweight ? h('p', {}, 'Set your bodyweight in ', h('a', { href: '#/settings/account' }, 'Settings'), ' so BW sets are counted correctly.') : null,
      (saved.timedPrompts || []).map((name) => {
        saved.answered ||= {};
        const done = (isTimed) => h('span', { class: 'muted' }, `${name}: ${isTimed ? 'counted in seconds' : 'counted in reps'}.`);
        if (name in saved.answered) return h('div', { class: 'ask' }, done(saved.answered[name]));
        const ask = h('div', { class: 'ask' }, h('span', {}, 'Is ', h('strong', {}, name), ' timed, in seconds?'));
        const answer = (isTimed) => async () => {
          saved.answered[name] = isTimed;
          ask.replaceChildren(done(isTimed));
          await ctx.lb.setExerciseSetting(name, { is_timed: isTimed });
        };
        ask.append(h('span', { class: 'row' },
          h('button', { class: 'btn small', type: 'button', onclick: answer(true) }, 'Yes, seconds'),
          h('button', { class: 'btn small', type: 'button', onclick: answer(false) }, 'No, reps')));
        return ask;
      })));
  return note;
}

/** One exercise: a row that opens to its recent form and how its sets compare. */
function exerciseRow(ctx, c, day) {
  const missing = c.log.exercise === 'Unknown Exercise';
  const sets = c.setsRanked.length ? c.setsRanked : [c.setsLine || formatSetsDisplay(c.log.sets) || ''];
  const form = c.spark ? h('div', { class: 'ex-block' },
    h('div', { class: 'ex-block-head' }, h('span', { class: 'kicker' }, 'Recent form'),
      infoPop('About recent form', [
        c.trend ? h('span', {}, h('b', {}, 'Recent average'), ` is the average of your last ${c.trend.count} session${c.trend.count === 1 ? '' : 's'}: ${c.trendDates}.`) : null,
        'Each session is scored on your strongest set, plus a quarter credit for your next-best sets.',
        h('span', {}, 'Within ±1% counts as ', h('b', {}, 'Steady'), '.'),
        `The line shows your last ${c.spark.dots.length} sessions. The gold ring marks your best.`,
      ])),
    c.trend ? h('div', { class: 'trend-head' }, h('span', { class: `trend-value ${c.trend.direction}` }, c.trend.text), h('span', { class: 'muted' }, 'vs your recent average')) : null,
    sparkChart(ctx, c.spark, c.sparkFirst, day)) : null;

  const head = (label, side) => h('th', {}, h('a', { href: `#/workout/${side.day}?from=${day}` }, label), h('span', { class: 'date' }, side.date_text));
  const table = c.table.length ? h('table', { class: 'ex-table' },
    h('thead', {}, h('tr', {}, h('th', { class: 'rank' }), h('th', {}, 'Today'),
      head(c.bestIsLast ? 'Last · best' : 'Last', c.last),
      c.bestCmp && !c.bestIsLast ? head('Best', c.bestCmp) : null)),
    h('tbody', {}, c.table.map((r) => h('tr', {},
      h('td', { class: 'rank' }, r.rank), h('td', { class: 'today' }, r.today),
      [r.last, r.best].filter(Boolean).map((cell) => h('td', {}, h('span', { class: 'val' }, cell.label),
        cell.pct_text ? h('span', { class: `delta ${cell.direction || ''}` }, cell.pct_text) : null)))))) : null;

  const compare = h('div', { class: 'ex-block' },
    h('div', { class: 'ex-block-head' }, h('span', { class: 'kicker' }, table ? 'Vs last session & best' : 'Vs best'),
      infoPop('How this is compared', [
        `${c.best.emoji ? `${c.best.emoji} ` : ''}${c.best.explain}`,
        table ? h('span', {}, 'Sets are matched ', h('b', {}, 'strongest to strongest'), ', whatever order you did them in.') : null,
        table ? 'Strength is estimated 1RM: weight × (1 + reps ÷ 30). It rates high-rep sets a little generously, so a lighter set with many reps can rank above a heavier one.' : null,
        h('span', {}, h('b', {}, 'Medals'), ' mean a new best: 🥇 your strongest set beat it, 🥈 strongest matched and your 2nd set beat it, 🥉 top two matched and your 3rd set beat it. A medal can also come from lifting heavier at the same strength.'),
        c.bodyweightNote,
      ])),
    table || h('p', { class: 'muted', style: 'margin:0' }, c.best.explain),
    h('div', { class: 'ex-foot' }, h('a', { href: `#/stats?exercise=${encodeURIComponent(c.log.exercise)}` }, 'Full progress →')));

  return h('details', { class: `ex-row ex-open${missing ? ' missing' : ''}` },
    h('summary', {},
      h('div', { class: 'main' },
        h('div', { class: 'title' }, missing ? 'No exercise name' : c.log.exercise),
        h('div', { class: 'sets' }, sets.filter(Boolean).map((t) => h('span', {}, t)))),
      h('div', { class: 'vs' }, vsRecent(c), vsBest(c)),
      h('span', { class: 'ex-chev', 'aria-hidden': 'true' }, icon('chev'))),
    h('div', { class: 'ex-body' }, form, compare));
}

export function workoutScreen(ctx, day) {
  const { lb } = ctx;
  const w = lb.workout(day);
  if (!w) {
    return h('div', {}, pageHead('Workout not found', 'It may have been deleted on another device.', { back: '#/history' }),
      h('a', { class: 'btn', href: '#/history' }, 'All workouts'));
  }
  // Opened from another workout's chart or table: the back arrow goes back there.
  const from = /^\d{4}-\d{2}-\d{2}$/.exec(new URLSearchParams(location.hash.split('?')[1] || '').get('from') || '')?.[0] || null;
  const saved = ctx.lastSaved && ctx.lastSaved.day === day ? ctx.lastSaved : null;
  const bw = w.logs.find((l) => l.bodyweight)?.bodyweight;
  const cmp = lb.compareWorkout(day);
  const dir = (d) => cmp.filter((c) => c.trend?.direction === d).length;
  const sets = w.logs.reduce((n, l) => n + (Array.isArray(l.sets?.reps) ? l.sets.reps.length : 0), 0);

  const del = h('button', { class: 'btn danger', type: 'button' }, icon('trash'), 'Delete');
  del.addEventListener('click', busy(del, async () => {
    if (!(await ask('This removes it from all your devices.', { title: `Delete ${w.title} on ${formatDay(day)}?`, yes: 'Delete', danger: true }))) return;
    const ids = await lb.deleteWorkout(day);
    toast('Workout deleted.', { ms: 8000, action: 'Undo', onAction: async () => {
      await lb.restoreLogs(ids);
      toast('Workout back.');
      ctx.go(`workout/${day}`);
    } });
    ctx.go('history');
  }));
  const share = async () => {
    const text = lb.workoutText(w);
    if (navigator.share) {
      try {
        await navigator.share({ title: `${w.title} · ${formatDay(day)}`, text });
        return;
      } catch (err) {
        if (err && err.name === 'AbortError') return;
      }
    }
    copyText(text);
  };

  const bests = cmp.filter((c) => c.medal).length;
  const nums = [[bests === 1 ? 'New best' : 'New bests', bests, 'gold'], ['Improving', dir('up'), 'good'], ['Dipping', dir('down'), 'bad'], ['Steady', dir('steady'), '']];
  return h('div', {},
    h('div', { class: 'wo-head' },
      h('a', { class: 'back', href: from ? `#/workout/${from}` : '#/history', 'aria-label': from ? `Back to ${formatDay(from)}` : 'All workouts' }, icon('back')),
      h('div', { class: 'tools' },
        h('a', { class: 'icon-btn', href: `#/workout/${day}/edit`, 'aria-label': 'Edit', title: 'Edit' }, icon('edit')),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Share', title: 'Share', onclick: share }, icon('share')))),
    h('h1', { class: 'wo-title' }, w.title),
    h('p', { class: 'wo-meta' }, h('span', {}, formatDay(day)), h('span', {}, `${w.logs.length} exercise${w.logs.length === 1 ? '' : 's'}`),
      sets ? h('span', {}, `${sets} set${sets === 1 ? '' : 's'}`) : null, bw ? h('span', {}, `bodyweight ${fmtNum(bw)}`) : null),
    saved ? savedNote(ctx, saved) : null,
    !saved && !lb.profile()?.bodyweight && cmp.some((c) => c.usesBw)
      ? h('p', { class: 'wo-note' }, icon('info'), h('span', {}, 'Set your bodyweight in ', h('a', { href: '#/settings/account' }, 'Settings'),
        ` for accurate comparisons on ${[...new Set(cmp.filter((c) => c.usesBw).map((c) => c.log.exercise))].sort().join(', ')}.`))
      : null,
    h('div', { class: 'group', style: 'margin-top:18px' },
      nums.some(([, n]) => n)
        ? h('div', { class: 'nums', style: 'border-bottom:1px solid var(--hair)' }, nums.map(([label, n, cls]) =>
          h('div', { class: n ? cls : 'zero' }, h('b', {}, n), h('span', {}, label))))
        : null,
      h('div', { class: 'ex-cols', 'aria-hidden': 'true' }, h('span', {}, 'Exercise'), h('span', {}, 'vs recent'), h('span', {}, 'vs best'), h('i')),
      cmp.map((c) => exerciseRow(ctx, c, day))),
    h('div', { class: 'row', style: 'margin-top:6px' },
      h('a', { class: 'btn', href: `#/workout/${day}/edit` }, icon('edit'), 'Edit'),
      h('button', { class: 'btn', type: 'button', onclick: () => copyText(lb.workoutText(w)) }, icon('copy'), 'Copy as text'),
      del));
}

export function editScreen(ctx, day) {
  const { lb } = ctx;
  const w = lb.workout(day);
  if (!w) return workoutScreen(ctx, day);
  // Title and date in their own fields, as the old page had; the box holds the exercises.
  const lines = lb.workoutText(w).split('\n');
  const title = h('input', { id: 'edit_title', type: 'text', value: w.title, autocomplete: 'off', 'aria-label': 'Title' });
  const date = h('input', { id: 'edit_date', type: 'date', value: day, required: true, 'aria-label': 'Date' });
  const ta = h('textarea', { id: 'workout_text', class: 'editor', spellcheck: 'false', autocapitalize: 'off', 'aria-label': 'The exercises and their sets' },
    lines.slice(1).join('\n').trim());
  autoGrow(ta);
  // Name suggestions while typing; here the box starts with an exercise, not the title.
  const suggest = attachSuggestions(ta, () => lb.exerciseCatalog().map((e) => e.name), { firstLineIsTitle: false });
  attachPasteTidy(ta);
  const text = () => {
    const [y, m, d] = (date.value || day).split('-').map(Number);
    return `${d}/${m}/${String(y % 100).padStart(2, '0')} ${title.value.trim() || 'Workout'}\n\n${ta.value.trim()}`;
  };
  const meta = h('span', { class: 'editor-meta', 'aria-live': 'polite' });
  const checkList = h('div', { class: 'group' });
  const checkBox = h('section', { class: 'section', 'aria-label': 'Check before saving' }, h('div', { class: 'label' }, 'Check'), checkList);
  const err = h('div', { role: 'alert' });
  const check = () => {
    const c = lb.check(text());
    const exercises = c.parsed?.exercises || [];
    meta.replaceChildren(h('span', { class: c.errors.length ? 'error' : 'ok' },
      `${c.exercise_count || 0} exercise${c.exercise_count === 1 ? '' : 's'} · ${c.set_count || 0} set${c.set_count === 1 ? '' : 's'}`));
    checkBox.hidden = !exercises.length;
    checkList.replaceChildren(...exercises.map((e) => {
      const bad = e.valid === false || e.missing_name;
      const sets = (e.reps || []).map((r, k) => `${e.weights?.[k] ?? ''}${e.weights?.[k] !== undefined && e.weights?.[k] !== null ? '×' : ''}${r}`);
      return h('div', { class: 'rowi' },
        h('span', { class: 'ico', style: bad ? 'color:var(--bad)' : '' }, icon(bad ? 'info' : 'check')),
        h('span', { class: 'main' }, h('span', { class: 'title' }, e.name),
          h('span', { class: 'desc mono' }, bad ? 'Couldn’t read these sets' : sets.join('  ·  '))));
    }));
  };
  let timer = null;
  for (const el of [title, date, ta]) el.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(check, 200); });
  check();
  const btn = h('button', { class: 'btn primary small', type: 'button' }, 'Save');
  btn.addEventListener('click', busy(btn, async () => {
    if (!date.value) {
      err.replaceChildren(h('p', { class: 'errors' }, 'Pick a date.'));
      return;
    }
    const r = await lb.log(text(), { replaceDay: day });
    if (r.existing) {
      err.replaceChildren(h('p', { class: 'errors' }, `There is already a workout on ${formatDay(r.existing.day)}. Change the date or edit that one.`));
      return;
    }
    if (r.error) {
      err.replaceChildren(h('ul', { class: 'errors' }, (r.errors || [r.error]).map((e) => h('li', {}, e))));
      return;
    }
    ctx.lastSaved = r; // the workout page says "Saved"
    ctx.go(`workout/${r.day}`);
  }));
  return h('div', {},
    pageHead('Edit workout', 'Fix names or numbers. Change the date to move the workout.', { back: `#/workout/${day}` }),
    h('div', { class: 'edit-fields' },
      h('label', { class: 'field' }, h('span', {}, 'Title'), title),
      h('label', { class: 'field date' }, h('span', {}, 'Date'), date)),
    h('div', { class: 'group editor-wrap' },
      ta,
      suggest,
      h('div', { class: 'editor-bar' }, meta,
        h('div', { class: 'row' }, h('a', { class: 'btn small', href: `#/workout/${day}` }, 'Cancel'), btn))),
    err, checkBox);
}
