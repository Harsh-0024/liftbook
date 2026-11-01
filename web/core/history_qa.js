// The coach's built-in answers, used when no AI can answer (services/history_qa.py with
// use_ai=False): when did I last hit 100kg bench, best pull day in the last 30 days, my biggest
// jump on squat vs previous, why did the graph drop on 30 Jan.
//
// data: {history, settings, ownRepRanges, today}: as for coach_tools.js, but the person's own rep
// ranges (as the stats charts use them). Needs no internet, so the app can answer these offline too.

import { getAverageGrowthData, getChartData } from './stats.js';
import { addDays } from './dates.js';
import { floatRepr, formatFixed, formatG, title, unique } from './py.js';

const MONTHS = {
  jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4, may: 5,
  jun: 6, june: 6, jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9, september: 9,
  oct: 10, october: 10, nov: 11, november: 11, dec: 12, december: 12,
};
const MONTH_RE = /\b(\d{1,2})\s*(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b/i;

const iso = (value) => (value ? String(value).slice(0, 10) : null);
const e1rm = (l) => Number(l.estimated_1rm || 0) || 0;
// Python's f"{x or ''}": a float prints as 100.0, a missing one as nothing.
const pyStr = (x) => (x ? String(x) : '');
const weightStr = (x) => (x === null || x === undefined || x === 0 ? '' : floatRepr(Number(x)));

function exerciseCandidates(name) {
  if (!name) return [];
  const n = name.trim();
  const cands = [n, title(n), n.replaceAll("'", '’'), title(n.replaceAll("'", '’')), n.replaceAll('’', "'"),
    title(n.replaceAll('’', "'")), n.replaceAll('-', '–'), n.replaceAll('–', '-')];
  return unique(cands.filter((c) => c && c.trim()));
}

function validDay(y, m, d) {
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d
    ? `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}` : null;
}

function parseIsoDate(text) {
  if (typeof text !== 'string' || !text.trim()) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(text.trim().slice(0, 10));
  return m ? validDay(Number(m[1]), Number(m[2]), Number(m[3])) : null;
}

/** "30 jan": that day this year, or last year if it hasn't come yet. */
function parseDayMonth(text, today) {
  if (typeof text !== 'string' || !text.trim()) return null;
  const m = MONTH_RE.exec(text.trim().toLowerCase());
  if (!m) return null;
  const month = MONTHS[m[2].toLowerCase()];
  const year = Number(today.slice(0, 4));
  let d = validDay(year, month, Number(m[1]));
  if (d && d > today) d = validDay(year - 1, month, Number(m[1])) || d;
  return d;
}

const parseAnyDate = (text, today) => parseIsoDate(text) || parseDayMonth(text, today);

function seriesFor(data, metric) {
  if (!data || typeof data !== 'object') return [];
  const nums = (xs) => (xs || []).map((x) => Number(x || 0));
  if (data.unit === 'percent') return nums(data.data);
  const series = data.series || {};
  if (metric in series) return nums(series[metric]);
  return nums(data.data);
}

function matchExerciseFromOptions(question, options) {
  if (!question || !options?.length) return null;
  const q = String(question).toLowerCase();
  let best = null;
  for (const opt of options) {
    const cand = typeof opt === 'string' ? opt.trim() : '';
    if (!cand) continue;
    const low = cand.toLowerCase();
    const esc = low.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (new RegExp(`(^|[^a-z0-9])${esc}($|[^a-z0-9])`).test(q) && low.length > (best?.length || 0)) best = cand;
  }
  return best;
}

const pullLike = (s) => ['pull', 'row', 'deadlift', 'lat', 'chin', 'curl', 'pulldown', 'face pull', 'rear delt', 'shrug'].some((k) => s.includes(k));
const pushLike = (s) => ['press', 'bench', 'dip', 'fly', 'flye', 'push', 'lateral raise', 'front raise', 'tricep', 'skull'].some((k) => s.includes(k));
const legsLike = (s) => ['squat', 'leg press', 'leg extension', 'leg curl', 'lunge', 'calf', 'hamstring', 'quad', 'glute',
  'hip thrust', 'romanian', 'rdl', 'step up', 'hack'].some((k) => s.includes(k));
const low = (name) => String(name || '').trim().toLowerCase();
const DAY_TYPES = {
  pull: (n) => pullLike(low(n)),
  push: (n) => pushLike(low(n)) && !legsLike(low(n)),
  legs: (n) => legsLike(low(n)),
  lower: (n) => legsLike(low(n)),
  upper: (n) => (pullLike(low(n)) || pushLike(low(n))) && !legsLike(low(n)),
};

const entry = (l) => ({ exercise: l.exercise, top_weight: l.top_weight, top_reps: l.top_reps, estimated_1rm: l.estimated_1rm });
const byE1rmDesc = (logs) => logs.map((l, i) => [l, i]).sort((a, b) => e1rm(b[0]) - e1rm(a[0]) || a[1] - b[1]).map(([l]) => l);

/* ---------------- the answers ---------------- */

function lastHit(d, { exercise, weightKg }) {
  const cands = exerciseCandidates(exercise);
  if (!cands.length) return { ok: false, error: 'Please specify an exercise.' };
  const logs = d.history.filter((l) => cands.includes(l.exercise)).map((l, i) => [l, i])
    .sort((a, b) => (a[0].date < b[0].date ? 1 : a[0].date > b[0].date ? -1 : b[1] - a[1])).map(([l]) => l);
  if (!logs.length) return { ok: false, error: `No logs found for ${exercise}.` };
  const picked = weightKg === null ? logs[0] : logs.find((l) => l.top_weight !== null && l.top_weight !== undefined && Number(l.top_weight) >= weightKg);
  if (!picked) return { ok: true, answer: `You haven't logged ${exercise} at ${formatG(weightKg)}kg yet.`, results: [] };
  const day = iso(picked.date);
  const set = `(Top set: ${weightStr(picked.top_weight)} x ${pyStr(picked.top_reps)})`;
  const answer = weightKg !== null
    ? `Last time you hit ${formatG(weightKg)}kg+ on ${exercise} was ${day || 'an unknown date'}. ${set}`
    : `Last time you logged ${exercise} was ${day || 'an unknown date'}. ${set}`;
  return {
    ok: true, answer,
    results: [{ date: day, workout_name: picked.workout_name, ...entry(picked) }],
    workout_day: day,
  };
}

function bestDay(d, { dayType, sinceDays }) {
  const type = low(dayType);
  const since = Math.max(1, Math.min(Number(sinceDays) || 30, 365));
  const cutoff = addDays(d.today, -since);
  const byDay = new Map();
  for (const l of d.history) {
    const day = iso(l.date);
    if (!day || day < cutoff) continue;
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(l);
  }
  if (!byDay.size) return { ok: false, error: `No workouts found in the last ${since} days.` };
  const keep = DAY_TYPES[type];
  const scored = [];
  for (const [day, logs] of byDay) {
    const kept = keep ? logs.filter((l) => keep(l.exercise)) : logs;
    if (kept.length) scored.push([kept.reduce((s, l) => s + e1rm(l), 0), day, kept]);
  }
  if (!scored.length) return { ok: false, error: `No ${type || 'matching'} workouts found in the last ${since} days.` };
  scored.sort((a, b) => b[0] - a[0] || (a[1] < b[1] ? 1 : -1));
  const [score, day, logs] = scored[0];
  const label = type ? title(type) : 'Best';
  return {
    ok: true,
    answer: `Your best ${label} day in the last ${since} days was ${day} (score ${formatFixed(score, 1)}).`,
    results: byE1rmDesc(logs).slice(0, 8).map(entry),
    workout_day: day,
  };
}

function resolveExercise(d, exercise) {
  const cands = exerciseCandidates(exercise);
  const logged = new Set(d.history.map((l) => l.exercise));
  return cands.filter((c) => logged.has(c)).sort()[0] || null;
}

const chartFor = (d, name) => getChartData(name, { history: d.history, settings: d.settings, ownRepRanges: d.ownRepRanges || '' });

function pointAt(series, labels, day) {
  const idx = labels.indexOf(day);
  if (idx < 0) return null;
  const cur = idx < series.length ? Number(series[idx] || 0) : 0;
  const prev = idx - 1 >= 0 && idx - 1 < series.length ? Number(series[idx - 1] || 0) : null;
  return { cur, delta: prev === null ? null : cur - prev };
}
const signed = (x) => `${x >= 0 ? '+' : ''}${formatFixed(x, 1)}`;

function explainDrop(d, { day, exercise, metric }) {
  metric = low(metric) || 'e1rm';
  const dayLogs = d.history.filter((l) => iso(l.date) === day);
  if (!exercise) {
    const data = getAverageGrowthData({ history: d.history, settings: d.settings });
    const p = pointAt(seriesFor(data, 'data'), data.labels || [], day);
    if (!p) return { ok: true, answer: `I don't have a plotted point for ${day} on Overall Progress (no logs that day).`, results: [] };
    const answer = p.delta === null
      ? `On ${day}, Overall Progress was ${formatFixed(p.cur, 1)}%.`
      : `On ${day}, Overall Progress was ${formatFixed(p.cur, 1)}% (${signed(p.delta)}% vs previous point).`;
    return { ok: true, answer, results: byE1rmDesc(dayLogs).slice(0, 8).map(entry), workout_day: dayLogs.length ? day : null };
  }
  const name = resolveExercise(d, exercise) || exercise;
  const data = chartFor(d, name);
  const p = pointAt(seriesFor(data, metric), data.labels || [], day);
  if (!p) return { ok: true, answer: `I don't have a plotted point for ${day} on ${name} (${metric}).`, results: [] };
  const cands = new Set(exerciseCandidates(exercise));
  const matching = dayLogs.filter((l) => cands.has(String(l.exercise || '').trim()));
  const answer = p.delta === null
    ? `On ${day}, ${name} (${metric}) was ${formatFixed(p.cur, 1)}.`
    : `On ${day}, ${name} (${metric}) was ${formatFixed(p.cur, 1)} (${signed(p.delta)} vs previous point).`;
  return { ok: true, answer, results: byE1rmDesc(matching).slice(0, 6).map(entry), workout_day: dayLogs.length ? day : null };
}

function bestRelative(d, { exercise, metric = 'e1rm' }) {
  exercise = String(exercise || '').trim();
  if (!exercise) return { ok: false, error: 'Please specify an exercise.' };
  const name = resolveExercise(d, exercise) || exercise;
  const data = chartFor(d, name);
  const labels = data.labels || [];
  const series = seriesFor(data, metric);
  if (!labels.length || series.length < 2) return { ok: false, error: `Not enough data to compare days for ${name}.` };
  let best = null;
  for (let i = 1; i < Math.min(labels.length, series.length); i++) {
    const delta = series[i] - series[i - 1];
    if (best === null || delta > best.delta) best = { i, delta };
  }
  const day = labels[best.i];
  const cur = series[best.i];
  const prev = series[best.i - 1];
  return {
    ok: true,
    answer: `Your biggest day-to-day change on ${name} was on ${day}: ${formatFixed(cur, 1)} (${signed(best.delta)} vs previous logged day ${formatFixed(prev, 1)}).`,
    results: [{ date: day, exercise: name, estimated_1rm: cur }],
    workout_day: day,
  };
}

/** What kind of question this is, from its words alone. */
export function heuristicIntent(question, today) {
  const q = String(question || '').trim();
  const ql = q.toLowerCase();
  let m = /\blast\s+hit\s+(\d+(?:\.\d+)?)\s*(?:kg)?\s*(.+)$/.exec(ql);
  if (m) return ['last_hit', { exercise: m[2].trim().replace(/\?$/, '').trim(), weightKg: Number(m[1]) }];
  m = /\bwhen\s+did\s+i\s+last\s+(?:do|train|log)\s+(.+?)\??$/.exec(ql);
  if (m) return ['last_hit', { exercise: m[1].trim(), weightKg: null }];
  m = /\bbest\s+(pull|push|legs|upper|lower)\s+day\s+in\s+the\s+last\s+(\d{1,3})\s+days\b/.exec(ql)
    || /\bbest\s+(pull|push|legs)\s+day\s+last\s+(\d{1,3})\s+days\b/.exec(ql);
  if (m) return ['best_day', { dayType: m[1], sinceDays: Number(m[2]) }];
  if (ql.includes('relative to previous') || ql.includes('vs previous') || ql.includes('compared to previous')) {
    m = /\b(?:in|for)\s+(.+?)\s+(?:relative|vs|compared)\b/.exec(ql) || /\b(?:in|for)\s+(.+?)\??$/.exec(ql);
    if (m) return ['best_relative', { exercise: m[1].trim(), metric: 'e1rm' }];
  }
  if (ql.includes('graph') && (ql.includes('down') || ql.includes('drop'))) {
    const day = parseAnyDate(q, today);
    if (day) return ['explain_drop', { day }];
  }
  return [null, {}];
}

/**
 * Answer a question without AI.
 * Returns {ok, answer, results, workout_day} or {ok: false, error}.
 */
export function answerHistoryQuestion(data, question, context = {}) {
  const d = { history: data.history || [], settings: data.settings || [], ownRepRanges: data.ownRepRanges || '', today: data.today };
  question = String(question || '').trim().slice(0, 400);
  if (!question) return { ok: false, error: 'Please enter a question.' };
  const [intent, p] = heuristicIntent(question, d.today);
  const ctxExercise = String(context.exercise || '').trim() || null;
  const ctxMetric = String(context.metric || '').trim() || 'e1rm';
  if (intent === 'last_hit') return lastHit(d, p);
  if (intent === 'best_day') return bestDay(d, { dayType: p.dayType || 'pull', sinceDays: p.sinceDays || 30 });
  if (intent === 'explain_drop') return explainDrop(d, { day: p.day, exercise: ctxExercise, metric: ctxMetric });
  if (intent === 'best_relative') {
    const options = unique(d.history.map((l) => l.exercise).filter(Boolean));
    return bestRelative(d, { exercise: matchExerciseFromOptions(question, options) || p.exercise || ctxExercise || '', metric: p.metric || ctxMetric });
  }
  const ctxDay = context.date ? parseIsoDate(String(context.date)) : null;
  const ql = question.toLowerCase();
  if (ctxDay && ['down', 'drop', 'low', 'dip'].some((w) => ql.includes(w))) {
    return explainDrop(d, { day: ctxDay, exercise: ctxExercise, metric: ctxMetric });
  }
  return { ok: false, error: 'I can only answer a few kinds of questions without AI.' };
}

/** The coach's reply for a built-in answer (ai_coach._rules_answer): the answer, then up to 6 sets. */
export function rulesReply(data, question, context, note) {
  const r = answerHistoryQuestion(data, question, context);
  if (!r.ok) return { ok: false, error: `${note} ${r.error || ''}`.trim(), source: 'rules' };
  const lines = [String(r.answer || '')];
  for (const row of (r.results || []).slice(0, 6)) {
    const bits = [row.exercise || row.date || ''];
    if (row.top_weight !== null && row.top_weight !== undefined && row.top_reps !== null && row.top_reps !== undefined) {
      bits.push(`${formatG(Number(row.top_weight))} x ${row.top_reps}`);
    }
    if (row.estimated_1rm) bits.push(`e1RM ${formatFixed(Number(row.estimated_1rm), 1)}`);
    lines.push(`- ${bits.filter(Boolean).join(' — ')}`);
  }
  const links = r.workout_day ? [{ label: 'Open workout', url: `#/workout/${r.workout_day}` }] : [];
  return { ok: true, answer: lines.join('\n'), steps: [], links, source: 'rules', note };
}
