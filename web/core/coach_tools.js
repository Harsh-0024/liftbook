// Read-only views of one person's training that the AI coach can call as tools
// (services/coach_tools.py).
//
// Every tool takes the person's data and its arguments and returns a small JSON-able object.
// They never write, and cap what they return so a long history can't blow up the model's context.
//
// data: {
//   history:      the person's workout_logs rows, oldest first (as Liftbook.history() gives them)
//   settings:     exercise_settings rows
//   planText:     the plan they train from (their own or the shared one)
//   repRangesText: the rep ranges they train from
//   today:        "YYYY-MM-DD", the person's own date
// }

import { effectiveSetsForLog, makeSettings } from './bodyweight.js';
import { resolveTimedStatus } from './logging.js';
import { buildRepRangeMap } from './plans.js';
import { resolveExerciseAliases, setsDisplay } from './stats.js';
import { addDays, daysBetween } from './dates.js';
import { formatG, fsum, pyRound, split } from './py.js';

export const MAX_ROWS = 40;
export const PLAN_TEXT_LIMIT = 4000;
export const MAX_E1RM_REPS = 12; // rep-max formulas overshoot past this, so ranking counts at most this many
const DEFAULT_REP_RANGE = [6, 10];

/** A tool was called with arguments it can't answer; the message goes back to the model. */
export class ToolError extends Error {}

/* ---------------- helpers ---------------- */

/** Python's repr() of a string, for messages ("No logged exercise matches 'x'."). */
export function pyRepr(value) {
  const s = String(value);
  const q = s.includes("'") && !s.includes('"') ? '"' : "'";
  const body = s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t');
  return q + (q === "'" ? body.replace(/'/g, "\\'") : body) + q;
}

const iso = (value) => (value ? String(value).slice(0, 10) : null);
const dayStart = (day) => `${day}T00:00:00`;

function num(value) {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? pyRound(n, 1) : null;
}

/** Python's int() for a tool argument: whole numbers and numeric text; anything else -> NaN. */
function toInt(value) {
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'number') return Number.isFinite(value) ? Math.trunc(value) : NaN;
  if (typeof value === 'string' && /^\s*[-+]?\d+\s*$/.test(value)) return parseInt(value, 10);
  return NaN;
}

function clamp(value, low, high, fallback) {
  const n = toInt(value);
  return Number.isNaN(n) ? fallback : Math.max(low, Math.min(high, n));
}

function parseDateArg(value) {
  if (!value) return null;
  const s = String(value).trim().slice(0, 10);
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (m) {
    const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
    const dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d) {
      return `${m[1]}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    }
  }
  throw new ToolError(`Dates must be YYYY-MM-DD, got ${pyRepr(value)}.`);
}

const setsOf = (log) => (log.sets && typeof log.sets === 'object' && !Array.isArray(log.sets) ? log.sets : {});
const finite = (x) => x !== null && x !== undefined && x !== '' && Number.isFinite(Number(x));

function setCount(log) {
  const reps = (setsOf(log).reps || []).filter((r) => r !== null && r !== undefined);
  return reps.length || (log.top_reps ? 1 : 0);
}

/** Weight x reps over the logged sets (bodyweight-only sets count as 0). */
function volume(log) {
  const sets = setsOf(log);
  const weights = sets.weights || [];
  const reps = sets.reps || [];
  let total = 0;
  for (let i = 0; i < Math.min(weights.length, reps.length); i++) {
    const w = Number(weights[i] || 0);
    const r = Number(reps[i] || 0);
    if (Number.isFinite(w) && Number.isFinite(r)) total += w * r;
  }
  if (!total && log.top_weight && log.top_reps) total = Number(log.top_weight) * Number(log.top_reps);
  return total;
}

/* Muscle group by name (services/workout_title.py classify_by_name). First match wins. */
const KEYWORD_RULES = [
  [/crunch|leg raise|knee raise|v ?tuck|\babs?\b|plank|pallof|oblique|sit ?up|ab wheel|ab roller|hollow|dead ?bug|russian twist|toe touch|flutter kick|woodchop|mountain climber/, ['Abs']],
  [/wrist|forearm|farmer|reverse (?:\w+ )?curl|ulnar|radial|dead hang|gripper|arm wrestl/, ['Forearms']],
  [/squat|leg press|lunge|leg curl|leg extension|calf|hip thrust|adduct|abduct|romanian|\brdl\b|glute|hack|step ?up|good morning|split squat|hamstring|quad/, ['Legs']],
  [/rear delt|lateral raise|face pull|overhead press|shoulder (?:\w+ )?press|\boh press|military press|upright row|front raise|arnold|\bdelt|shrug/, ['Shoulders']],
  [/\bdips?\b/, ['Chest', 'Triceps']],
  [/tricep|pushdown|push down|skull ?crusher|overhead extension|\boh extension|kickback|close ?grip (?:bench|press)|french press|jm press/, ['Triceps']],
  [/curl/, ['Biceps']],
  [/\brows?\b|pull ?ups?|chin ?ups?|pulldown|pull down|pullover|deadlift|hyper ?extension|back extension|\blats?\b|\bt ?bar\b|superman/, ['Back']],
  [/bench|chest press|\bpress\b|\bfly\b|\bflyes?\b|flies|push ?ups?|\bpec\b|crossover/, ['Chest']],
];

export function classifyByName(exerciseName) {
  const name = String(exerciseName || '').replace(/[–—]/g, '-').replace(/’/g, "'").replace(/\s+/g, ' ').trim()
    .toLowerCase().replace(/-/g, ' ');
  for (const [pattern, muscles] of KEYWORD_RULES) if (pattern.test(name)) return new Set(muscles);
  return new Set();
}

export function muscleGroup(name) {
  const groups = classifyByName(name || '');
  for (const g of ['Chest', 'Back', 'Shoulders', 'Biceps', 'Triceps', 'Forearms', 'Legs', 'Abs']) if (groups.has(g)) return g;
  return 'Other';
}

/* difflib.get_close_matches, as Python does it (no junk: names are far under 200 characters). */
/** difflib's matching blocks of two character lists, as [i, j, size], in order. */
function matchingBlocks(a, b) {
  const b2j = new Map();
  b.forEach((c, j) => (b2j.has(c) ? b2j.get(c).push(j) : b2j.set(c, [j])));
  const longest = (alo, ahi, blo, bhi) => {
    let [besti, bestj, bestsize] = [alo, blo, 0];
    let j2len = new Map();
    for (let i = alo; i < ahi; i++) {
      const next = new Map();
      for (const j of b2j.get(a[i]) || []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) || 0) + 1;
        next.set(j, k);
        if (k > bestsize) [besti, bestj, bestsize] = [i - k + 1, j - k + 1, k];
      }
      j2len = next;
    }
    return [besti, bestj, bestsize];
  };
  const blocks = [];
  const queue = [[0, a.length, 0, b.length]];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop();
    const [i, j, k] = longest(alo, ahi, blo, bhi);
    if (!k) continue;
    blocks.push([i, j, k]);
    if (alo < i && blo < j) queue.push([alo, i, blo, j]);
    if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
  }
  return blocks.sort((p, q) => p[0] - q[0] || p[1] - q[1]);
}

const matchingCharacters = (a, b) => matchingBlocks(a, b).reduce((n, [, , k]) => n + k, 0);

/** Characters that differ between two strings: each replaced, inserted or deleted run counts its longer side. */
export function changedChars(a, b) {
  const x = Array.from(a);
  const y = Array.from(b);
  let [i0, j0, n] = [0, 0, 0];
  for (const [i, j, k] of [...matchingBlocks(x, y), [x.length, y.length, 0]]) {
    n += Math.max(i - i0, j - j0);
    [i0, j0] = [i + k, j + k];
  }
  return n;
}

export function similarity(a, b) {
  const x = Array.from(a);
  const y = Array.from(b);
  const length = x.length + y.length;
  return length ? (2 * matchingCharacters(x, y)) / length : 1;
}

export function getCloseMatches(word, possibilities, n = 3, cutoff = 0.6) {
  const scored = [];
  for (const x of possibilities) {
    const score = similarity(x, word);
    if (score >= cutoff) scored.push([score, x]);
  }
  scored.sort((p, q) => q[0] - p[0] || (p[1] < q[1] ? 1 : p[1] > q[1] ? -1 : 0));
  return scored.slice(0, n).map(([, x]) => x);
}

/* ---------------- the person's data ---------------- */

class Data {
  constructor({ history = [], settings = [], planText = '', repRangesText = '', today }) {
    // Each log's place in the history stands in for the old app's row id (later logs, higher id).
    this.history = history.filter((l) => !l.deleted_at).map((l, i) => ({ ...l, _n: i }));
    this.rawSettings = settings;
    this.settings = makeSettings(settings);
    this.planText = planText || '';
    this.repRangesText = repRangesText || '';
    this.today = today;
    this.timedCache = new Map();
  }

  /** Every logged name once, in name order (as the old app's database listed them). */
  loggedNames() {
    this.names ??= [...new Set(this.history.map((l) => l.exercise).filter(Boolean))].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    return this.names;
  }

  /** The logged names that mean this exercise: same words in any order, else the closest spelling. */
  resolve(exercise) {
    exercise = String(exercise || '').trim();
    if (!exercise) throw new ToolError('Name an exercise.');
    const names = this.loggedNames();
    const aliasSet = new Set(resolveExerciseAliases(this.history, exercise));
    const aliases = names.filter((n) => aliasSet.has(n));
    if (aliases.length) return aliases;
    const lowered = new Map();
    for (const n of names) lowered.set(n.toLowerCase(), n);
    const low = exercise.toLowerCase();
    const contains = [...lowered].filter(([l]) => l.includes(low)).map(([, n]) => n);
    if (contains.length === 1) return contains;
    const close = getCloseMatches(low, [...lowered.keys()], 3, 0.8); // 0.6 took "bench press" for "Leg Press"
    if (close.length) return [lowered.get(close[0])];
    const words = new Set(split(low));
    const sharing = [...lowered].filter(([l]) => split(l).some((w) => words.has(w))).map(([, n]) => n)
      .sort((a, b) => [...a].length - [...b].length);
    let hint = contains.slice(0, 5);
    if (!hint.length) hint = sharing.slice(0, 5);
    if (!hint.length) hint = getCloseMatches(low, [...lowered.keys()], 5, 0.3).map((c) => lowered.get(c));
    const suffix = hint.length ? ` Did you mean one of: ${hint.join(', ')}?` : ' Call list_exercises to see what\'s logged.';
    throw new ToolError(`No logged exercise matches ${pyRepr(exercise)}.${suffix}`);
  }

  logsFor(names) {
    const set = new Set(names);
    return this.history.filter((l) => set.has(l.exercise));
  }

  /** Holds like planks log seconds as reps, and their 'e1RM' column is a weight*sqrt(seconds) score. */
  isTimed(name) {
    if (!this.timedCache.has(name)) {
      let timed = false;
      try {
        timed = Boolean(resolveTimedStatus({ exerciseName: name || '', exerciseString: '', settings: this.settings, history: this.history }).is_timed);
      } catch {
        timed = false;
      }
      this.timedCache.set(name, timed);
    }
    return this.timedCache.get(name);
  }

  /** Best Epley e1RM over the log's sets with reps capped at MAX_E1RM_REPS. */
  rankingE1rm(log) {
    const sets = effectiveSetsForLog(this.settings, log) || {};
    const weights = sets.weights || [];
    const reps = sets.reps || [];
    let best = 0;
    for (let i = 0; i < Math.min(weights.length, reps.length); i++) {
      if (!finite(weights[i]) || !finite(reps[i])) continue;
      best = Math.max(best, Number(weights[i]) * (1 + Math.min(Math.trunc(Number(reps[i])), MAX_E1RM_REPS) / 30));
    }
    return best || Number(log.estimated_1rm || 0);
  }
}

const byNewest = (a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b._n - a._n);
const byOldest = (a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a._n - b._n);

/** Python's max(): the first item with the largest key. Keys are arrays compared in order. */
function maxBy(items, key) {
  let best = null;
  let bestKey = null;
  for (const item of items) {
    const k = key(item);
    if (best === null || compare(k, bestKey) > 0) [best, bestKey] = [item, k];
  }
  return best;
}

function compare(a, b) {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

function logRow(log, timed = false) {
  const row = { date: iso(log.date), sets: setsDisplay(log), top_weight_kg: num(log.top_weight) };
  if (timed) {
    row.top_seconds = log.top_reps ?? null;
    row.hold_score = num(log.estimated_1rm);
  } else {
    row.top_reps = log.top_reps ?? null;
    row.e1rm_kg = num(log.estimated_1rm);
    if ((log.top_reps || 0) > MAX_E1RM_REPS) row.e1rm_unreliable = true;
  }
  if (log.uses_bodyweight) {
    row.includes_bodyweight = true; // top_weight_kg is bodyweight + added load
    if (log.bodyweight && log.top_weight) {
      // Spelled out: models read a bare flag as "plus bodyweight" on top of the total.
      const total = Number(log.top_weight);
      const bw = Number(log.bodyweight);
      row.load = `${formatG(total)} kg total = ${formatG(bw)} kg bodyweight + ${formatG(total - bw)} kg added`;
    }
  }
  return row;
}

/** Counter.most_common(): by count, largest first, ties in the order first counted. */
function mostCommon(counter, n = Infinity) {
  return [...counter].sort((a, b) => b[1] - a[1]).slice(0, n);
}

const count = (map, key, by = 1) => map.set(key, (map.get(key) || 0) + by);

/* ---------------- tools ---------------- */

function listExercises(d, { query = '', limit = 30 } = {}) {
  limit = clamp(limit, 1, 80, 30);
  const rows = new Map();
  for (const l of d.history) {
    const r = rows.get(l.exercise) || { count: 0, last: null };
    r.count += 1;
    if (!r.last || l.date > r.last) r.last = l.date;
    rows.set(l.exercise, r);
  }
  const q = String(query || '').trim().toLowerCase();
  const items = [...rows]
    .filter(([name]) => name && (!q || name.toLowerCase().includes(q) || q === muscleGroup(name).toLowerCase()))
    .map(([name, r]) => ({ exercise: name, sessions: r.count, last_logged: iso(r.last), muscle_group: muscleGroup(name) }));
  items.sort((a, b) => b.sessions - a.sessions || (a.exercise < b.exercise ? -1 : a.exercise > b.exercise ? 1 : 0));
  return { total_matching: items.length, exercises: items.slice(0, limit) };
}

function getExerciseHistory(d, { exercise, limit = 12, since_days: sinceDays = 0 } = {}) {
  const names = d.resolve(exercise);
  limit = clamp(limit, 1, MAX_ROWS, 12);
  let logs = d.logsFor(names);
  const since = clamp(sinceDays, 0, 3650, 0);
  if (since) logs = logs.filter((l) => l.date >= dayStart(addDays(d.today, -since)));
  const timed = d.isTimed(names[0]);
  return {
    exercise: names[0],
    also_logged_as: names.slice(1),
    timed_hold: timed,
    total_sessions: logs.length,
    sessions_newest_first: logs.sort(byNewest).slice(0, limit).map((l) => logRow(l, timed)),
  };
}

function getPersonalRecords(d, { exercise = '', limit = 10 } = {}) {
  if (exercise) {
    const names = d.resolve(exercise);
    const logs = d.logsFor(names);
    if (!logs.length) throw new ToolError(`Nothing logged for ${pyRepr(exercise)}.`);
    const bestE1rm = maxBy(logs, (l) => [d.rankingE1rm(l), l.date]);
    const heaviest = maxBy(logs, (l) => [Number(l.top_weight || 0), Math.trunc(Number(l.top_reps || 0))]);
    const mostVolume = maxBy(logs, (l) => [volume(l)]);
    const timed = d.isTimed(names[0]);
    return {
      exercise: names[0],
      timed_hold: timed,
      [timed ? 'best_hold_score' : 'best_estimated_1rm']: logRow(bestE1rm, timed),
      heaviest_top_set: logRow(heaviest, timed),
      most_volume_session: { date: iso(mostVolume.date), volume_kg: pyRound(volume(mostVolume)), sets: setsDisplay(mostVolume) },
      sessions_logged: logs.length,
    };
  }
  limit = clamp(limit, 1, 30, 10);
  const best = new Map();
  for (const log of d.history) {
    if (log.estimated_1rm === null || log.estimated_1rm === undefined) continue;
    const score = d.rankingE1rm(log);
    const cur = best.get(log.exercise);
    if (!cur || score > cur[0]) best.set(log.exercise, [score, log]);
  }
  // Timed holds have no e1RM, so they'd rank on a score in different units.
  const ranked = [...best.values()].filter(([, l]) => !d.isTimed(l.exercise)).sort((a, b) => b[0] - a[0]).slice(0, limit);
  return {
    records_by_estimated_1rm: ranked.map(([score, l]) => ({ exercise: l.exercise, ...logRow(l), ranking_e1rm_kg: pyRound(score, 1) })),
    note: `Ranked by e1RM counting at most ${MAX_E1RM_REPS} reps a set; timed holds are left out. `
      + 'On includes_bodyweight rows top_weight_kg is bodyweight + added load.',
  };
}

function getWorkouts(d, { start_date: startDate = '', end_date: endDate = '', limit = 5 } = {}) {
  limit = clamp(limit, 1, 14, 5);
  const start = parseDateArg(startDate);
  const end = parseDateArg(endDate);
  let logs = d.history;
  if (start) logs = logs.filter((l) => l.date >= dayStart(start));
  if (end) logs = logs.filter((l) => l.date < dayStart(addDays(end, 1)));
  const days = [...new Set(logs.map((l) => iso(l.date)))].sort().reverse().slice(0, limit);
  return {
    workouts_newest_first: days.map((day) => {
      const dayLogs = d.history.filter((l) => iso(l.date) === day).sort((a, b) => a._n - b._n);
      return {
        date: day,
        title: dayLogs.find((l) => l.workout_name)?.workout_name ?? null,
        exercises: dayLogs.map((l) => ({ exercise: l.exercise, sets: setsDisplay(l), e1rm_kg: num(l.estimated_1rm) })),
      };
    }),
  };
}

const GROUPS_TRACKED = ['Chest', 'Back', 'Shoulders', 'Biceps', 'Triceps', 'Legs', 'Abs'];

function getTrainingSummary(d, { days = 28 } = {}) {
  days = clamp(days, 7, 365, 28);
  const today = d.today;
  const start = addDays(today, -(days - 1));
  const logs = d.history.filter((l) => l.date >= dayStart(start));
  const trainedDays = [...new Set(logs.map((l) => iso(l.date)))].sort();

  const setsByGroup = new Map();
  const sessionsByExercise = new Map();
  let vol = 0;
  for (const log of logs) {
    count(setsByGroup, muscleGroup(log.exercise), setCount(log));
    count(sessionsByExercise, log.exercise);
    vol += volume(log);
  }
  const gaps = trainedDays.slice(1).map((b, i) => daysBetween(trainedDays[i], b));
  const lastAny = d.history.reduce((m, l) => (!m || l.date > m ? l.date : m), null);
  const weeks = days / 7;
  const out = {
    window: { from: start, to: today, days },
    workout_days: trainedDays.length,
    workouts_per_week: pyRound(trainedDays.length / weeks, 1),
    longest_gap_days: gaps.length ? Math.max(...gaps) : null,
    days_since_last_workout: lastAny ? daysBetween(iso(lastAny), today) : null,
    total_volume_kg: pyRound(vol),
    weekly_sets_by_muscle_group: Object.fromEntries(mostCommon(setsByGroup).map(([g, n]) => [g, pyRound(n / weeks, 1)])),
    most_trained_exercises: mostCommon(sessionsByExercise, 10).map(([e, n]) => ({ exercise: e, sessions: n })),
    muscle_groups_not_trained: GROUPS_TRACKED.filter((g) => !setsByGroup.get(g)),
  };
  if (!trainedDays.length && lastAny) {
    // An empty window says nothing about balance or habits; point at the last block instead.
    out.note = `Nothing logged in this window; the latest workout was ${iso(lastAny)}. Call again with `
      + `days=${Math.min(365, days + daysBetween(iso(lastAny), today) + 60)} to describe their recent training.`;
  }
  return out;
}

function getProgressTrend(d, { exercise, days = 90 } = {}) {
  const names = d.resolve(exercise);
  days = clamp(days, 14, 3650, 90);
  const start = addDays(d.today, -days);
  const logs = d.logsFor(names).filter((l) => l.estimated_1rm !== null && l.estimated_1rm !== undefined).sort(byOldest);
  if (!logs.length) throw new ToolError(`No strength data logged for ${names[0]}.`);
  const metric = d.isTimed(names[0]) ? 'hold_score' : 'e1rm_kg';

  // One point per day: the day's best e1RM (or hold score).
  const perDay = new Map();
  for (const log of logs) {
    const day = iso(log.date);
    perDay.set(day, Math.max(perDay.get(day) ?? 0, Number(log.estimated_1rm || 0)));
  }
  const allPoints = [...perDay].sort((a, b) => (a[0] < b[0] ? -1 : 1));
  const points = allPoints.filter(([day]) => day >= start);
  const lastPoint = allPoints[allPoints.length - 1];
  if (points.length < 2) {
    return {
      exercise: names[0],
      note: `Fewer than two sessions in the last ${days} days.`,
      last_session: { date: lastPoint[0], [metric]: pyRound(lastPoint[1], 1) },
    };
  }
  const xs = points.map(([day]) => daysBetween(points[0][0], day));
  const ys = points.map(([, v]) => v);
  const n = points.length;
  const meanX = fsum(xs) / n;
  const meanY = fsum(ys) / n;
  const denom = fsum(xs.map((x) => (x - meanX) ** 2)) || 1;
  const slopePerDay = fsum(xs.map((x, i) => (x - meanX) * (ys[i] - meanY))) / denom;

  let runningBest = 0;
  let lastPr = null;
  for (const [day, v] of allPoints) {
    if (v > runningBest) [runningBest, lastPr] = [v, day];
  }
  const first = points[0];
  const last = points[n - 1];
  const changePct = first[1] ? ((last[1] - first[1]) / first[1]) * 100 : null;
  // Counted to the latest session, not today, so a break from training doesn't read as a stall.
  const weeksSincePr = lastPr ? Math.floor(daysBetween(lastPr, lastPoint[0]) / 7) : null;
  return {
    exercise: names[0],
    metric,
    window_days: days,
    sessions_in_window: n,
    first: { date: first[0], [metric]: pyRound(first[1], 1) },
    latest: { date: last[0], [metric]: pyRound(last[1], 1) },
    change_pct: changePct !== null ? pyRound(changePct, 1) : null,
    trend_kg_per_week: pyRound(slopePerDay * 7, 2),
    all_time_best: { date: lastPr, [metric]: pyRound(runningBest, 1) },
    weeks_from_best_to_latest_session: weeksSincePr,
    days_since_latest_session: daysBetween(lastPoint[0], d.today),
    looks_stalled: Boolean(weeksSincePr !== null && weeksSincePr >= 6 && n >= 4),
    recent_points: points.slice(-12).map(([day, v]) => ({ date: day, [metric]: pyRound(v, 1) })),
  };
}

function reviewLifts(d, { days = 180, limit = 8 } = {}) {
  days = clamp(days, 90, 3650, 180);
  limit = clamp(limit, 1, 15, 8);
  const since = dayStart(addDays(d.today, -days));
  const sessions = new Map();
  for (const l of d.history) {
    if (l.date < since || l.estimated_1rm === null || l.estimated_1rm === undefined) continue;
    if (!sessions.has(l.exercise)) sessions.set(l.exercise, new Set());
    sessions.get(l.exercise).add(iso(l.date));
  }
  // Most trained first; ties in reverse name order, as the old app's database gave them.
  const rows = [...sessions].map(([name, s]) => [name, s.size])
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0));
  const lifts = [];
  for (const [name, n] of rows) {
    if (lifts.length >= limit) break;
    if (n < 3 || d.isTimed(name)) continue;
    const trend = getProgressTrend(d, { exercise: name, days });
    if (!('trend_kg_per_week' in trend)) continue;
    lifts.push({
      exercise: name,
      sessions: trend.sessions_in_window,
      first: trend.first,
      latest: trend.latest,
      change_pct: trend.change_pct,
      trend_kg_per_week: trend.trend_kg_per_week,
      all_time_best: trend.all_time_best,
      weeks_from_best_to_latest_session: trend.weeks_from_best_to_latest_session,
      looks_stalled: trend.looks_stalled,
    });
  }
  lifts.sort((a, b) => Number(!a.looks_stalled) - Number(!b.looks_stalled) || a.trend_kg_per_week - b.trend_kg_per_week);
  // A stall comes with what to do about it, so the answer can give targets instead of offering to.
  for (const lift of lifts.filter((l) => l.looks_stalled).slice(0, 4)) {
    try {
      const next = suggestNextSession(d, { exercise: lift.exercise });
      lift.next_session_target = { target: next.target, rule: next.rule, last_session: next.last_session };
    } catch (err) {
      if (!(err instanceof ToolError)) throw err;
    }
  }
  const out = { window_days: days, lifts_stalled_first: lifts };
  if (!lifts.length) out.note = `No lift was logged 3+ times with weights in the last ${days} days; try a longer window.`;
  return out;
}

function comparePeriods(d, { period_days: periodDays = 28, exercise = '' } = {}) {
  periodDays = clamp(periodDays, 7, 180, 28);
  const today = d.today;
  const curStart = addDays(today, -(periodDays - 1));
  const prevStart = addDays(curStart, -periodDays);
  let scoped = d.history;
  let label = 'all exercises';
  if (exercise) {
    const names = d.resolve(exercise);
    scoped = d.logsFor(names);
    label = names[0];
  }
  const logs = scoped.filter((l) => l.date >= dayStart(prevStart));
  const summarize = (lo, hi) => {
    const sel = logs.filter((l) => iso(l.date) >= lo && iso(l.date) <= hi);
    const best = sel.reduce((m, l) => Math.max(m, Number(l.estimated_1rm || 0)), 0);
    return {
      from: lo,
      to: hi,
      workout_days: new Set(sel.map((l) => iso(l.date))).size,
      sets: sel.reduce((s, l) => s + setCount(l), 0),
      volume_kg: pyRound(fsum(sel.map(volume))),
      best_e1rm_kg: num(best) || null,
    };
  };
  const out = { scope: label, current: summarize(curStart, today), previous: summarize(prevStart, addDays(curStart, -1)) };
  if (!out.current.workout_days) {
    const last = [...scoped].sort(byNewest)[0];
    if (last) {
      // Coming back from a break: point the model at their last block rather than an empty window.
      out.note = `Nothing logged in the current period; the latest workout was ${iso(last.date)}. `
        + 'For stalls or progress, use review_lifts (or get_progress_trend) over a longer window, e.g. days=180.';
    }
  }
  return out;
}

function getPlan(d) {
  const text = d.planText.trim();
  const chars = Array.from(text);
  const lastByTitle = new Map();
  for (const l of d.history) {
    if (l.workout_name === null || l.workout_name === undefined) continue;
    const cur = lastByTitle.get(l.workout_name);
    if (!cur || l.date > cur) lastByTitle.set(l.workout_name, l.date);
  }
  const recent = [...lastByTitle].sort((a, b) => (a[1] < b[1] ? 1 : a[1] > b[1] ? -1 : 0)).slice(0, 15);
  return {
    plan_text: chars.slice(0, PLAN_TEXT_LIMIT).join('') + (chars.length > PLAN_TEXT_LIMIT ? '\n…(truncated)' : ''),
    last_done_by_workout_title: Object.fromEntries(recent.map(([title, last]) => [title, iso(last)])),
  };
}

function sessionSets(log) {
  const sets = setsOf(log);
  const weights = sets.weights || [];
  const reps = sets.reps || [];
  const out = [];
  for (let i = 0; i < Math.min(weights.length, reps.length); i++) {
    if (!finite(reps[i])) continue;
    const w = Number(weights[i] || 0);
    if (!Number.isFinite(w)) continue;
    out.push([w, Math.trunc(Number(reps[i]))]);
  }
  if (!out.length && log.top_reps) out.push([Number(log.top_weight || 0), Math.trunc(Number(log.top_reps))]);
  return out;
}

const roundTo = (value, step) => pyRound(pyRound(value / step) * step, 2);

/** Double progression: fill the rep range at a weight, then add weight and start at the bottom.
 * Two sessions in a row under the range at the same weight -> a ~10% back-off. */
function suggestNextSession(d, { exercise } = {}) {
  const names = d.resolve(exercise);
  const logs = d.logsFor(names).sort(byNewest).slice(0, 4);
  if (!logs.length) throw new ToolError(`Nothing logged for ${names[0]}.`);

  const ranges = buildRepRangeMap(d.repRangesText || '');
  let repRange = null;
  for (const n of names) {
    if (Object.hasOwn(ranges, n.toLowerCase())) {
      repRange = ranges[n.toLowerCase()];
      break;
    }
  }
  let rangeSource = 'your rep ranges';
  if (!repRange) [repRange, rangeSource] = [DEFAULT_REP_RANGE, 'a default (no rep range set for this exercise)'];
  const [lo, hi] = repRange;

  const last = sessionSets(logs[0]);
  if (!last.length) throw new ToolError(`The last ${names[0]} session has no sets to work from.`);
  const topWeight = Math.max(...last.map(([w]) => w));
  const working = last.filter(([w]) => w === topWeight).map(([, r]) => r);

  let target;
  let rule;
  if (topWeight <= 0) {
    target = { weight_kg: null, reps: working.map((r) => r + 1) };
    rule = 'Bodyweight movement: add a rep to each set.';
  } else if (Math.min(...working) >= hi) {
    const step = topWeight < 20 ? 1 : 2.5;
    target = { weight_kg: roundTo(topWeight + step, 0.5), reps: working.map(() => lo) };
    rule = `Every working set reached the top of the range (${hi}), so add ${formatG(step)} kg and restart at ${lo} reps.`;
  } else {
    const prev = logs.length > 1 ? sessionSets(logs[1]) : [];
    const prevTop = prev.length ? Math.max(...prev.map(([w]) => w)) : null;
    const prevWorking = prev.filter(([w]) => w === prevTop).map(([, r]) => r);
    if (Math.max(...working) < lo && prevTop === topWeight && prevWorking.length && Math.max(...prevWorking) < lo) {
      target = { weight_kg: roundTo(topWeight * 0.9, 2.5), reps: working.map(() => lo) };
      rule = `Two sessions in a row below ${lo} reps at ${formatG(topWeight)} kg: back off ~10% and build up again.`;
    } else {
      target = { weight_kg: topWeight, reps: working.map((r) => (r < hi ? Math.min(r + 1, hi) : r)) };
      rule = `Stay at ${formatG(topWeight)} kg and add a rep to sets below ${hi}.`;
    }
  }
  return {
    exercise: names[0],
    rep_range: { low: lo, high: hi, source: rangeSource },
    last_session: { date: iso(logs[0].date), sets: setsDisplay(logs[0]) },
    target,
    rule,
    recent_sessions: logs.slice(1).map((l) => ({ date: iso(l.date), sets: setsDisplay(l) })),
  };
}

/* ---------------- registry ---------------- */

const STR = { type: 'string' };
const INT = { type: 'integer' };

export const TOOLS = {
  list_exercises: {
    fn: listExercises,
    description: 'List the exercises the user has logged, with session counts, last date and muscle group. '
      + "Optional query filters by name substring or muscle group (e.g. 'Back').",
    parameters: { type: 'object', properties: { query: STR, limit: INT } },
  },
  get_exercise_history: {
    fn: getExerciseHistory,
    description: 'Recent sessions for one exercise (newest first): date, every set, top set and estimated 1RM.',
    parameters: { type: 'object', properties: { exercise: STR, limit: INT, since_days: INT }, required: ['exercise'] },
  },
  get_personal_records: {
    fn: getPersonalRecords,
    description: 'Personal records. With an exercise: best e1RM, heaviest top set and biggest-volume session. '
      + "Without: the user's strongest lifts ranked by e1RM.",
    parameters: { type: 'object', properties: { exercise: STR, limit: INT } },
  },
  get_workouts: {
    fn: getWorkouts,
    description: 'Full workouts (all exercises and sets) grouped by day, newest first, optionally within a '
      + "YYYY-MM-DD date range. Use for 'what did I do on/last ...' questions.",
    parameters: { type: 'object', properties: { start_date: STR, end_date: STR, limit: INT } },
  },
  get_training_summary: {
    fn: getTrainingSummary,
    description: 'Training overview for the last N days: workouts per week, gaps, volume, weekly sets per '
      + 'muscle group, most trained exercises and neglected muscle groups.',
    parameters: { type: 'object', properties: { days: INT } },
  },
  get_progress_trend: {
    fn: getProgressTrend,
    description: 'Strength trend for one exercise over N days: first vs latest e1RM, % change, kg/week trend '
      + 'line, all-time best and whether progress looks stalled.',
    parameters: { type: 'object', properties: { exercise: STR, days: INT }, required: ['exercise'] },
  },
  review_lifts: {
    fn: reviewLifts,
    description: 'Progress check on every lift trained regularly in the last N days (default 180, at least 90) in one '
      + 'call: per lift first/latest e1RM, % change, kg/week trend, all-time best and looks_stalled. '
      + 'Stalled lifts come first, each with its next-session target (weight and reps). Use it for '
      + "'what's stalling / progressing / how are my lifts'.",
    parameters: { type: 'object', properties: { days: INT, limit: INT } },
  },
  compare_periods: {
    fn: comparePeriods,
    description: 'Compare the last N days with the N days before: workout days, sets, volume, best e1RM. '
      + 'Optionally for one exercise.',
    parameters: { type: 'object', properties: { period_days: INT, exercise: STR } },
  },
  suggest_next_session: {
    fn: suggestNextSession,
    description: 'Concrete target for the next session of one exercise (weight and reps per set) using double '
      + "progression against the user's rep range. Use for 'what should I aim for/lift next time'.",
    parameters: { type: 'object', properties: { exercise: STR }, required: ['exercise'] },
  },
  get_plan: {
    fn: getPlan,
    description: "The user's workout plan text and when each workout title was last done. Use for "
      + "'what should I train today' and programming questions.",
    parameters: { type: 'object', properties: {} },
  },
};

export function functionDeclarations() {
  return Object.entries(TOOLS).map(([name, spec]) => {
    const decl = { name, description: spec.description };
    if (Object.keys(spec.parameters.properties || {}).length) decl.parameters = spec.parameters;
    return decl;
  });
}

/** The person's data, ready for the tools (built once per question). */
export const coachData = (data) => new Data(data);

export function runTool(data, name, args) {
  const spec = Object.hasOwn(TOOLS, name) ? TOOLS[name] : null;
  if (!spec) return { error: `Unknown tool ${pyRepr(name)}.` };
  const d = data instanceof Data ? data : new Data(data);
  const allowed = new Set(Object.keys(spec.parameters.properties || {}));
  const kwargs = {};
  for (const [k, v] of Object.entries(args || {})) if (allowed.has(k) && v !== null && v !== undefined && v !== '') kwargs[k] = v;
  try {
    return spec.fn(d, kwargs);
  } catch (err) {
    if (err instanceof ToolError) return { error: err.message };
    throw err;
  }
}

/** Starter questions built from what this person actually trains. */
export function suggestions(data) {
  const top = runTool(data, 'list_exercises', { limit: 3 }).exercises || [];
  const out = ['How has my training gone over the last 4 weeks?'];
  if (top.length) out.push(`How is my ${top[0].exercise} progressing?`);
  out.push('Which of my lifts are stalling?');
  if (top.length > 1) out.push(`What should I aim for next time on ${top[1].exercise}?`);
  out.push('What should I train today?', 'Which muscle groups am I neglecting?', 'What are my strongest lifts?');
  return out.slice(0, 6);
}
