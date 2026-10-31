// The Stats page's numbers: each exercise's history chart (estimated 1RM, top set, volume,
// quality), its summary and bests, the overall progress lines and the exercise list. Ports
// services/stats.py (and the list built in liftbook/routes/stats.py) without the database.
// Days are the person's local days: log times are moved by tzOffsetMinutes (India, +5:30, by
// default, as the Python app's TIMEZONE_OFFSET does).
import { re, strip, toFloat, toInt, isDict, fsum, formatG, pyRound, maxBy, compareKeys, sortBy } from './py.js';
import { calculateWorkoutScore, calculateTimedWorkoutScore, getSetStats, timedSetScore } from './scoring.js';
import { effectiveSetsForLog, hasBodyweightToken, isBodyweightEnabled, makeSettings, setsOfLog } from './bodyweight.js';
import { statsVocabulary, statsExerciseKey } from './names.js';
import { buildRepRangeMap } from './plans.js';
import { hasTimeHint, resolveTimedStatus, logMetrics } from './logging.js';
import { localDay, daysBetween, addDays, formatDateTime, parseDate } from './dates.js';

export const DEFAULT_TZ_OFFSET_MINUTES = 330;

function asSettings(settings) {
  if (settings && settings.bodyweight instanceof Map) return settings;
  return makeSettings(settings || []);
}

function dateSortKey(value) {
  return value ? formatDateTime(parseDate(value)) : '';
}

// Logs oldest first; equal times keep the order they were created in.
function byDate(logs) {
  return logs.map((log, order) => ({ log, order }))
    .sort((a, b) => compareKeys([dateSortKey(a.log.date), a.order], [dateSortKey(b.log.date), b.order]))
    .map(({ log }) => log);
}

/** [weights, reps] of the sets with both a weight and reps (services.stats._normalize_sets). */
function statsSets(setsJson) {
  if (!isDict(setsJson)) return [[], []];
  const weights = setsJson.weights || [];
  const reps = setsJson.reps || [];
  const pairs = [];
  for (let i = 0; i < Math.min(weights.length, reps.length); i++) {
    const w = weights[i];
    const r = reps[i];
    if (w === null || w === undefined || r === null || r === undefined) continue;
    try {
      pairs.push([toFloat(w), toInt(r)]);
    } catch {
      continue;
    }
  }
  return [pairs.map((p) => p[0]), pairs.map((p) => p[1])];
}

function topWeight(weights, reps) {
  if (!weights.length || !reps.length) return [0, 0];
  const top = weights.reduce((a, b) => (b > a ? b : a));
  const idx = weights.indexOf(top);
  return [top, idx < reps.length ? reps[idx] : reps[0]];
}

function logMetricsForStats(settings, log) {
  let [weights, reps] = statsSets(effectiveSetsForLog(settings, log));
  if ((!weights.length || !reps.length) && log.top_weight !== null && log.top_weight !== undefined
      && log.top_reps !== null && log.top_reps !== undefined) {
    weights = [toFloat(log.top_weight)];
    reps = [toInt(log.top_reps)];
  }
  if (weights.length && reps.length) {
    let [peak] = getSetStats({ weights, reps });
    const [tw, tr] = topWeight(weights, reps);
    if (!peak && log.estimated_1rm) peak = toFloat(log.estimated_1rm);
    return [peak, tw, tr];
  }
  return [
    log.estimated_1rm ? toFloat(log.estimated_1rm) : 0,
    log.top_weight ? toFloat(log.top_weight) : 0,
    log.top_reps ? toInt(log.top_reps) : 0,
  ];
}

const TIMED_NAME = re([
  '\\bdead\\s*hang\\b',
  '\\bplank\\b',
  '\\bforearm\\s*roller\\b',
  "\\b(?:trap\\s*bar\\s*)?farmer(?:[’']\\s*s)?\\s*walk\\b",
  '\\b(?:trap\\s*bar\\s*)?farmers?\\s*walk\\b',
].join('|'), 'i');

/** Whether a log is a timed exercise: seconds in its brackets, or a known timed name. */
export function isTimedLog(log) {
  const text = String(log.exercise_string ?? '');
  for (const part of re('\\[([^\\]]*)\\]').findall(text)) {
    const token = strip(String(part || '')).toLowerCase();
    if (!token) continue;
    if (re('(?:\\b(?:s|sec|secs|second|seconds)\\b|\\d+\\s*s(?:ec(?:onds?)?)?\\b)').test(token)) return true;
  }
  return TIMED_NAME.test(String(log.exercise ?? '').toLowerCase());
}

/** A log's estimated max (or timed score) for the progress lines. */
export function peakForLog(settings, log) {
  let [weights, reps] = statsSets(effectiveSetsForLog(settings, log));
  if ((!weights.length || !reps.length) && log.top_weight !== null && log.top_weight !== undefined
      && log.top_reps !== null && log.top_reps !== undefined) {
    weights = [toFloat(log.top_weight)];
    reps = [toInt(log.top_reps)];
  }
  if (!weights.length || !reps.length) return log.estimated_1rm ? toFloat(log.estimated_1rm) : 0.0;
  if (isTimedLog(log)) {
    let best = 0.0;
    let any = false;
    for (let i = 0; i < Math.min(weights.length, reps.length); i++) {
      if (weights[i] > 0 && reps[i] > 0) {
        const s = timedSetScore(weights[i], reps[i]);
        if (!any || s > best) best = s;
        any = true;
      }
    }
    return any ? best : 0.0;
  }
  return calculateWorkoutScore({ weights, reps }, null).peak_1rm || 0.0;
}

function cleanWorkoutTitle(title) {
  return strip(String(title ?? '')) || 'Workout';
}

/** The logged names grouped with this one on the Stats page. */
export function resolveExerciseAliases(history, exerciseName) {
  const names = [...new Set(history.map((log) => log.exercise))];
  const vocabulary = statsVocabulary([...names, exerciseName]);
  const key = statsExerciseKey(exerciseName, vocabulary);
  if (!key) return [];
  const aliases = names.filter((n) => statsExerciseKey(n, vocabulary) === key);
  return aliases.length ? aliases : [exerciseName];
}

function anyLogIsTimed(history, settings, logs) {
  if (logs.some((log) => hasTimeHint(log.exercise_string || ''))) return true;
  const names = [...new Set(logs.map((log) => log.exercise || ''))];
  return names.some((name) => resolveTimedStatus({ exerciseName: name, exerciseString: '', settings, history }).is_timed);
}

/**
 * One exercise's chart (services.stats.get_chart_data).
 * ownRepRanges: the person's own rep-range text (its ranges score how well reps hit the target).
 */
export function getChartData(exerciseName, { history = [], settings = [], ownRepRanges = '', tzOffsetMinutes = DEFAULT_TZ_OFFSET_MINUTES } = {}) {
  settings = asSettings(settings);
  const aliases = new Set(resolveExerciseAliases(history, exerciseName));
  const logs = aliases.size ? byDate(history.filter((log) => aliases.has(log.exercise))) : [];

  const labels = [];
  const data1rm = [];
  const dataWeight = [];
  const dataReps = [];
  const dataVolume = [];
  const dataEffVolume = [];
  const dataQuality = [];
  const dataQualityAdjusted = [];
  const dataBwOffset = [];
  const titles = [];

  const targetRange = buildRepRangeMap(ownRepRanges)[strip(exerciseName || '').toLowerCase()] || null;
  const isTimed = anyLogIsTimed(history, settings, logs);
  const timedTarget = isTimed ? targetRange : null;

  for (const log of logs) {
    const label = log.date ? localDay(log.date, tzOffsetMinutes) : '';
    const title = cleanWorkoutTitle(log.workout_name);
    const [qw, qr] = statsSets(effectiveSetsForLog(settings, log));
    const setsForQuality = qw.length && qr.length ? { weights: qw, reps: qr } : {};
    let quality;
    let e1rm;
    if (isTimed) {
      quality = calculateTimedWorkoutScore(setsForQuality, timedTarget);
      e1rm = quality.peak_1rm || 0;
    } else {
      const [oneRm] = logMetricsForStats(settings, log);
      quality = calculateWorkoutScore(setsForQuality, targetRange);
      e1rm = quality.peak_1rm || oneRm;
    }
    let tw = 0;
    let tr = 0;
    const [wr, rr] = statsSets(effectiveSetsForLog(settings, log));
    if (wr.length && rr.length) [tw, tr] = topWeight(wr, rr);
    else if (log.top_weight !== null && log.top_weight !== undefined) {
      tw = toFloat(log.top_weight);
      tr = toInt(log.top_reps || 0);
    }
    const totalVol = quality.total_volume || 0;
    const effVol = quality.effective_volume || 0;
    const qIndex = quality.quality_index || 0;
    let offset = null;
    if (log.uses_bodyweight && log.bodyweight && tw) offset = pyRound(toFloat(tw) - toFloat(log.bodyweight), 2);
    const point = [toFloat(e1rm || 0), toFloat(tw || 0), Math.trunc(tr || 0), qIndex * 100.0, (e1rm || 0) * (qIndex || 0), offset];
    if (label && labels.length && labels[labels.length - 1] === label) {
      // The same exercise twice in a day is one point: the stronger entry, the day's volume added up.
      dataVolume[dataVolume.length - 1] += totalVol || 0;
      dataEffVolume[dataEffVolume.length - 1] += effVol || 0;
      if (point[0] <= data1rm[data1rm.length - 1]) continue;
      for (const series of [data1rm, dataWeight, dataReps, dataQuality, dataQualityAdjusted, dataBwOffset]) series.pop();
    } else {
      labels.push(label);
      titles.push(title);
      dataVolume.push(totalVol || 0);
      dataEffVolume.push(effVol || 0);
    }
    data1rm.push(point[0]);
    dataWeight.push(point[1]);
    dataReps.push(point[2]);
    dataQuality.push(point[3]);
    dataQualityAdjusted.push(point[4]);
    dataBwOffset.push(point[5]);
  }

  let stats = {};
  if (data1rm.length) {
    const first = data1rm[0];
    const last = data1rm[data1rm.length - 1];
    stats = {
      current_1rm: last,
      max_1rm: Math.max(...data1rm),
      min_1rm: Math.min(...data1rm),
      improvement: data1rm.length > 1 ? last - first : 0,
      improvement_pct: data1rm.length > 1 && first > 0 ? ((last - first) / first) * 100 : 0,
    };
  }
  return {
    labels,
    data: data1rm,
    workout_days: labels,
    weight: dataWeight,
    reps: dataReps,
    bodyweight_offset: dataBwOffset,
    volume: dataVolume,
    effective_volume: dataEffVolume,
    quality: dataQuality,
    quality_adjusted_1rm: dataQualityAdjusted,
    workout_titles: titles,
    is_timed: isTimed,
    series: {
      e1rm: data1rm,
      top_weight: dataWeight,
      top_reps: dataReps,
      tonnage: dataVolume,
      effective_tonnage: dataEffVolume,
      quality: dataQuality,
      quality_adjusted_1rm: dataQualityAdjusted,
    },
    exercise: exerciseName,
    stats,
  };
}

/** Sessions, first/latest date, current and best 1RM, heaviest set for one logged name. */
export function getExerciseSummary(exerciseName, { history = [], settings = [] } = {}) {
  settings = asSettings(settings);
  const logs = byDate(history.filter((log) => log.exercise === exerciseName));
  if (!logs.length) return {};
  const metrics = logs.map((log) => [log, ...logMetricsForStats(settings, log)]);
  const [firstLog, first1rm] = metrics[0];
  const [latestLog, latest1rm] = metrics[metrics.length - 1];
  const [max1rmLog, max1rmValue] = maxBy(metrics, (m) => m[1]);
  const [, , maxWeightValue, maxWeightReps] = maxBy(metrics, (m) => m[2]);
  return {
    total_sessions: logs.length,
    first_date: firstLog.date,
    latest_date: latestLog.date,
    current_1rm: latest1rm || 0,
    pr_1rm: max1rmValue || 0,
    pr_weight: maxWeightValue || 0,
    pr_reps: maxWeightReps || 0,
    pr_date: max1rmLog.date,
    improvement: (latest1rm || 0) - (first1rm || 0),
    improvement_pct: first1rm ? (((latest1rm || 0) - (first1rm || 0)) / (first1rm || 1)) * 100 : 0,
  };
}

/** Every logged name's summary, latest first. */
export function getAllExercisesSummary({ history = [], settings = [] } = {}) {
  const names = [...new Set(history.map((log) => log.exercise))];
  const summaries = names.map((name) => ({ ...getExerciseSummary(name, { history, settings }), exercise: name }));
  return sortBy(summaries, (s) => (s.latest_date ? dateSortKey(s.latest_date) : ''), true);
}

function emptyGrowth() {
  return { labels: [], data: [], workout_days: [], weight: [], reps: [], exercise: 'Overall Progress', stats: {}, unit: 'percent' };
}

/** Average change in estimated max per day, across exercises, weighted by each one's start. */
export function getAverageGrowthData({ history = [], settings = [], tzOffsetMinutes = DEFAULT_TZ_OFFSET_MINUTES } = {}) {
  settings = asSettings(settings);
  const logs = byDate(history);
  if (!logs.length) return emptyGrowth();
  const logsByExercise = new Map();
  const titleByDate = new Map();
  const vocabulary = statsVocabulary(new Set(logs.map((l) => l.exercise)));
  for (const log of logs) {
    const key = statsExerciseKey(log.exercise, vocabulary);
    if (!key) continue;
    if (log.date) {
      const day = localDay(log.date, tzOffsetMinutes);
      if (!titleByDate.has(day)) titleByDate.set(day, cleanWorkoutTitle(log.workout_name));
    }
    if (!logsByExercise.has(key)) logsByExercise.set(key, []);
    logsByExercise.get(key).push(log);
  }
  const byDateMap = new Map();
  for (const exerciseLogs of logsByExercise.values()) {
    const bestByDay = new Map();
    for (const log of exerciseLogs) {
      if (!log.date) continue;
      const oneRm = peakForLog(settings, log);
      if (!oneRm || oneRm <= 0) continue;
      const day = localDay(log.date, tzOffsetMinutes);
      bestByDay.set(day, Math.max(bestByDay.has(day) ? bestByDay.get(day) : 0.0, oneRm));
    }
    if (!bestByDay.size) continue;
    const base = bestByDay.get([...bestByDay.keys()].sort()[0]);
    for (const [day, oneRm] of bestByDay) {
      let pct = ((oneRm - base) / base) * 100.0;
      pct = Math.max(-300.0, Math.min(300.0, pct));
      if (!byDateMap.has(day)) byDateMap.set(day, { weighted_sum: 0.0, weight_sum: 0.0 });
      const entry = byDateMap.get(day);
      entry.weighted_sum += pct * base;
      entry.weight_sum += base;
    }
  }
  if (!byDateMap.size) return emptyGrowth();
  const labels = [];
  const dataPct = [];
  const titles = [];
  for (const day of [...byDateMap.keys()].sort()) {
    const values = byDateMap.get(day);
    labels.push(day);
    titles.push(titleByDate.get(day) ?? 'Workout');
    dataPct.push(values.weight_sum ? values.weighted_sum / values.weight_sum : 0);
  }
  let stats = {};
  if (dataPct.some((v) => v !== 0)) {
    stats = {
      current_1rm: dataPct[dataPct.length - 1],
      max_1rm: Math.max(...dataPct),
      min_1rm: Math.min(...dataPct),
      improvement: dataPct.length > 1 ? dataPct[dataPct.length - 1] - dataPct[0] : 0,
      improvement_pct: fsum(dataPct) / dataPct.length,
    };
  }
  return { labels, data: dataPct, workout_days: labels, weight: [], reps: [], exercise: 'Overall Progress', stats, unit: 'percent', workout_titles: titles };
}

function fadeMultiplier(daysSince, fadeStart, fadeEnd) {
  if (daysSince <= fadeStart) return 1.0;
  if (daysSince >= fadeEnd) return 0.0;
  return Math.max(0.0, Math.min(1.0, (fadeEnd - daysSince) / (fadeEnd - fadeStart)));
}

/** How many sets a log holds (at least 1), for how full a day looks in Consistency. */
export function loggedSetCount(log) {
  let data = log.sets ?? log.sets_json;
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data);
    } catch {
      data = null;
    }
  }
  if (isDict(data)) {
    for (const key of ['reps', 'weights']) {
      const values = data[key];
      if (Array.isArray(values) && values.length) return values.length;
    }
  }
  return 1;
}

function median(values) {
  const s = [...values].sort((a, b) => a - b);
  const n = s.length;
  if (n % 2 === 1) return s[(n - 1) / 2];
  return (s[n / 2 - 1] + s[n / 2]) / 2;
}

/** The Strength Index (mode "index") or Improvement Rate (mode "rate") over every day trained. */
export function getOverallProgressData({
  history = [], settings = [], mode = 'index', baselineSessionsTarget = 5, minSessions = 3,
  fadeStartDays = 60, fadeEndDays = 90, tzOffsetMinutes = DEFAULT_TZ_OFFSET_MINUTES,
} = {}) {
  settings = asSettings(settings);
  const empty = { labels: [], data: [], log_data: [], workout_days: [], weight: [], reps: [], exercise: 'Overall', stats: {}, unit: 'percent', overall_mode: mode };
  const logs = byDate(history);
  if (!logs.length) return empty;

  const exerciseDayValues = new Map();
  const workoutDays = new Set();
  const titleByDay = new Map();
  const nameByKey = new Map();
  const setsByDay = new Map();
  const vocabulary = statsVocabulary(new Set(logs.map((l) => l.exercise)));
  for (const log of logs) {
    if (!log.date) continue;
    const key = statsExerciseKey(log.exercise, vocabulary);
    if (!key) continue;
    const day = localDay(log.date, tzOffsetMinutes);
    workoutDays.add(day);
    if (!titleByDay.has(day)) titleByDay.set(day, cleanWorkoutTitle(log.workout_name));
    nameByKey.set(key, strip(String(log.exercise ?? '')) || key);
    setsByDay.set(day, (setsByDay.get(day) || 0) + loggedSetCount(log));
    const value = peakForLog(settings, log);
    if (!value || value <= 0) continue;
    if (!exerciseDayValues.has(key)) exerciseDayValues.set(key, new Map());
    const perDay = exerciseDayValues.get(key);
    perDay.set(day, Math.max(perDay.has(day) ? perDay.get(day) : 0.0, value));
  }
  if (!exerciseDayValues.size || !workoutDays.size) return empty;

  const daysSorted = [...workoutDays].sort();
  const startDay = daysSorted[0];
  const endDay = daysSorted[daysSorted.length - 1];

  const baseline = new Map();
  const sessionsBy = new Map();
  for (const [key, dayMap] of exerciseDayValues) {
    const items = [...dayMap.entries()].sort((a, b) => compareKeys(a[0], b[0]));
    sessionsBy.set(key, items.length);
    const positive = items.map((i) => i[1]).filter((v) => v && v > 0);
    const samples = positive.slice(0, Math.min(Math.trunc(baselineSessionsTarget), positive.length));
    if (!samples.length) continue;
    const base = samples.length >= 3 ? median(samples) : fsum(samples) / samples.length;
    if (base > 0) baseline.set(key, base);
  }
  const universe = [...baseline.keys()].filter((key) => (sessionsBy.get(key) || 0) >= Math.trunc(minSessions));
  const dayTitles = Object.fromEntries(daysSorted.map((d) => [d, titleByDay.get(d) ?? 'Workout']));
  const daySets = Object.fromEntries(daysSorted.map((d) => [d, Math.trunc(setsByDay.get(d) || 0)]));
  if (!universe.length) {
    return { ...empty, workout_days: daysSorted, day_titles: dayTitles, day_sets: daySets, exercises: [] };
  }

  const timelines = new Map();
  for (const key of universe) {
    const items = [...exerciseDayValues.get(key).entries()].sort((a, b) => compareKeys(a[0], b[0]));
    timelines.set(key, { days: items.map((i) => i[0]), values: items.map((i) => i[1]) });
  }
  const labels = [];
  const series = [];
  const logSeries = [];
  const titles = [];
  const pointers = new Map(universe.map((k) => [k, -1]));
  const lastValues = new Map(universe.map((k) => [k, null]));
  const lastDays = new Map(universe.map((k) => [k, null]));
  const rateSegment = new Map(universe.map((k) => [k, 0]));

  for (let day = startDay; day <= endDay; day = addDays(day, 1)) {
    labels.push(day);
    titles.push(titleByDay.get(day) ?? 'Workout');
    let weightedSum = 0.0;
    let weightSum = 0.0;
    let dailyLogSum = 0.0;
    let dailyLogWeightSum = 0.0;
    for (const key of universe) {
      const { days, values } = timelines.get(key);
      let idx = pointers.get(key);
      while (idx + 1 < days.length && days[idx + 1] <= day) {
        idx += 1;
        lastValues.set(key, values[idx]);
        lastDays.set(key, days[idx]);
      }
      pointers.set(key, idx);
      const lastVal = lastValues.get(key);
      const lastDay = lastDays.get(key);
      if (lastVal === null || !lastDay) continue;
      const fade = fadeMultiplier(daysBetween(lastDay, day), Math.trunc(fadeStartDays), Math.trunc(fadeEndDays));
      if (fade <= 0) continue;
      const base = baseline.get(key) || 0.0;
      if (base <= 0) continue;
      const weight = base * fade;
      if (mode === 'rate') {
        let seg = rateSegment.get(key);
        while (seg + 1 < days.length && day > days[seg + 1]) seg += 1;
        rateSegment.set(key, seg);
        let dailyL = 0.0;
        if (seg + 1 < days.length) {
          const d1 = days[seg];
          const d2 = days[seg + 1];
          const v1 = values[seg];
          const v2 = values[seg + 1];
          const span = daysBetween(d1, d2);
          if (span > 0 && v1 > 0 && v2 > 0 && day > d1 && day <= d2) {
            const ratio = v2 / v1;
            if (ratio > 0) dailyL = Math.log(ratio) / span;
          }
        }
        dailyLogSum += dailyL * weight;
        dailyLogWeightSum += weight;
      } else {
        weightedSum += (lastVal / base) * 100.0 * weight;
        weightSum += weight;
      }
    }
    if (mode === 'rate') {
      const overall = dailyLogWeightSum ? dailyLogSum / dailyLogWeightSum : 0.0;
      logSeries.push(overall);
      series.push((Math.exp(overall) - 1.0) * 100.0);
    } else {
      logSeries.push(0.0);
      series.push(weightSum ? weightedSum / weightSum : 0.0);
    }
  }

  let stats = {};
  if (series.some((v) => v !== 0)) {
    stats = {
      current_1rm: series[series.length - 1],
      max_1rm: Math.max(...series),
      min_1rm: Math.min(...series),
      improvement: series.length > 1 ? series[series.length - 1] - series[0] : 0,
      improvement_pct: fsum(series) / series.length,
    };
  }
  return {
    labels,
    data: series,
    log_data: logSeries,
    workout_days: daysSorted,
    day_titles: dayTitles,
    day_sets: daySets,
    exercises: universe.map((key) => ({
      name: nameByKey.get(key) ?? key,
      baseline: pyRound(baseline.get(key), 2),
      days: [...timelines.get(key).days],
      values: timelines.get(key).values.map((v) => pyRound(v, 2)),
    })),
    weight: [],
    reps: [],
    workout_titles: titles,
    exercise: mode !== 'rate' ? 'Strength Index (vs baseline)' : 'Improvement Rate (per day)',
    stats,
    unit: 'percent',
    overall_mode: mode,
    baseline_sessions: Math.trunc(baselineSessionsTarget),
    min_sessions: Math.trunc(minSessions),
  };
}

/** A log's sets as the history shows them ("100 x 5, 90 x 8"); WorkoutLog.sets_display. */
export function setsDisplay(log) {
  let trimmed = null;
  const exercise = log.exercise || '';
  if (log.exercise_string) {
    trimmed = strip(log.exercise_string);
    if (trimmed.toLowerCase().startsWith(exercise.toLowerCase())) {
      trimmed = strip(trimmed.slice(exercise.length));
      trimmed = strip(trimmed.replace(/^[-:]+/, ''));
    }
    if (trimmed && trimmed.toLowerCase().includes('bw')) return trimmed;
  }
  const sets = setsOfLog(log);
  if (sets) {
    const weights = sets.weights || [];
    const reps = sets.reps || [];
    const pairs = [];
    for (let i = 0; i < Math.min(weights.length, reps.length); i++) {
      if (weights[i] === null || weights[i] === undefined || reps[i] === null || reps[i] === undefined) continue;
      pairs.push(`${formatG(toFloat(weights[i]))} x ${toInt(reps[i])}`);
    }
    if (pairs.length) return pairs.join(', ');
  }
  if (trimmed) return trimmed;
  if (log.top_weight && log.top_reps) return `${formatG(toFloat(log.top_weight))} x ${log.top_reps}`;
  return null;
}

function codePoints(s) {
  return [...s].map((c) => c.codePointAt(0));
}

/**
 * The Stats page's exercise list: one entry per exercise (names grouped as the charts group
 * them), with sessions, views and the last day trained. views: {stats key: count}.
 */
export function statsExerciseOptions({ history = [], views = {}, tzOffsetMinutes = DEFAULT_TZ_OFFSET_MINUTES } = {}) {
  const logs = [...history].map((log, order) => ({ log, order }))
    .sort((a, b) => compareKeys([dateSortKey(b.log.date), b.order], [dateSortKey(a.log.date), a.order]))
    .map(({ log }) => log);
  const usage = new Map();
  const keyByName = new Map();
  const vocabulary = statsVocabulary(new Set(logs.map((l) => l.exercise)));
  for (const log of logs) {
    if (!keyByName.has(log.exercise)) keyByName.set(log.exercise, statsExerciseKey(log.exercise, vocabulary));
    const key = keyByName.get(log.exercise);
    if (!key || !log.date) continue;
    if (!usage.has(key)) usage.set(key, new Set());
    usage.get(key).add(localDay(log.date, tzOffsetMinutes));
  }
  const exercises = sortBy([...new Set(logs.map((l) => l.exercise).filter(Boolean))], codePoints);
  const options = [];
  const seen = new Set();
  for (const ex of exercises) {
    const label = strip(re('^\\s*\\d+\\s*[\\.)]\\s*').sub('', ex)) || ex;
    const key = statsExerciseKey(label, vocabulary);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const days = usage.get(key) || new Set();
    options.push({ value: label, label, sessions: days.size, views: views[key] || 0, last: days.size ? [...days].sort().pop() : '' });
  }
  return options;
}

/** Exercises written with "bw" while no bodyweight is set (the Stats page warns about them). */
export function bodyweightWarningExercises({ history = [], bodyweight = null } = {}) {
  if (bodyweight !== null && bodyweight !== undefined) return [];
  return sortBy([...new Set(history.filter((log) => (log.exercise_string || '').toLowerCase().includes('bw')
    || (setsDisplay(log) || '').toLowerCase().includes('bw')).map((log) => log.exercise))], codePoints);
}

/**
 * The one-off fixes the Python app applies to old logs before showing stats: a missing
 * bodyweight filled in from the profile, and a bodyweight flag (with recalculated top set and
 * 1RM) for logs saved before the flag existed. Returns copies of the logs that changed.
 */
export function backfillLogs({ history = [], settings = [], bodyweight = null } = {}) {
  settings = asSettings(settings);
  const changed = new Map();
  const logs = history.map((log) => ({ ...log }));
  if (bodyweight) {
    for (const log of logs) {
      if (log.bodyweight === null || log.bodyweight === undefined) {
        log.bodyweight = bodyweight;
        changed.set(log, true);
      }
    }
  }
  for (const log of logs) {
    if (log.uses_bodyweight !== null && log.uses_bodyweight !== undefined) continue;
    const text = log.exercise_string || '';
    const explicit = hasBodyweightToken(text);
    let usesOffsets;
    if (explicit && storedWeightsLookEffective(log)) usesOffsets = false;
    else if (explicit) usesOffsets = true;
    else usesOffsets = isBodyweightEnabled(settings, log.exercise || '', '');
    log.uses_bodyweight = Boolean(usesOffsets);
    const isTimed = resolveTimedStatus({ exerciseName: log.exercise || '', exerciseString: text, settings, history: logs }).is_timed;
    Object.assign(log, logMetrics(log, { settings, isTimed }));
    changed.set(log, true);
  }
  return logs.filter((log) => changed.has(log));
}

function storedWeightsLookEffective(log) {
  const bw = log.bodyweight;
  const sets = setsOfLog(log);
  if (bw === null || bw === undefined || !sets) return false;
  const weights = sets.weights || [];
  if (!weights.length) return false;
  try {
    const b = toFloat(bw);
    return weights.filter((w) => w !== null && w !== undefined).some((w) => toFloat(w) >= b * 0.5);
  } catch {
    return false;
  }
}
