// Saving a workout: a parsed workout -> the workout_logs rows to store (sets, top weight and
// reps, estimated 1RM, bodyweight) and the summary shown after saving ("New best", "Below
// best", ...). Ports services/logging.py without the database: the person's history comes in
// as plain rows, and everything to store comes back for the caller to save.
import { re, strip, lstrip, split1, splitlines, toFloat, toInt, formatG, formatFixed, isDict, maxBy, compareKeys } from './py.js';
import { alignSets, extractNumbers, isTimeOnlyExercise, TIME_TOKEN } from './parser.js';
import { getSetStats, getTimedSetStats, compareStrengthWorkouts, compareTimedWorkouts } from './scoring.js';
import { buildNameIndex, namesFor, normalizeExerciseName, exerciseKey } from './names.js';
import { parseRepTargetSets, parsePlanTargetSets, resolveTargetSets, extractExplicitTargetSets } from './plans.js';
import {
  hasBodyweightToken, isBodyweightEnabled, effectiveSetsForLog, effectiveSetsForCurrent, makeSettings,
} from './bodyweight.js';
import { applyRenamesToParsed, redirectsFrom } from './renames.js';
import { formatDateTime, parseDate } from './dates.js';

const PERFORMANCE_LABELS = {
  gold_strength: { label: '🥇 New best', short: 'New best' },
  silver_strength: { label: '🥈 New best', short: 'New best' },
  bronze_strength: { label: '🥉 New best', short: 'New best' },
  gold_load: { label: '🥇 New best', short: 'New best' },
  silver_load: { label: '🥈 New best', short: 'New best' },
  bronze_load: { label: '🥉 New best', short: 'New best' },
  consistent: { label: '= Matches best', short: 'Matches best' },
  slightly_off: { label: 'Below best', short: 'Below best' },
  moderately_off: { label: 'Below best', short: 'Below best' },
  significantly_off: { label: 'Below best', short: 'Below best' },
  first_log: { label: '✦ First log', short: 'First log' },
};

export const KNOWN_TIMED_EXERCISES = ['plank', 'dead hang', "farmer's walk", "trap bar farmer's walk", "dumbbell farmer's walk", 'wall sit', 'hanging'];
const KNOWN_TIMED_KEYS = new Set(KNOWN_TIMED_EXERCISES.map(exerciseKey).filter(Boolean));

function performancePayload(key, summaryMode = false) {
  let normalized = strip(String(key || 'consistent')).toLowerCase();
  if (!(normalized in PERFORMANCE_LABELS)) normalized = 'consistent';
  let displayKey = normalized;
  if (summaryMode && ['gold_load', 'silver_load', 'bronze_load'].includes(normalized)) displayKey = 'consistent';
  const meta = PERFORMANCE_LABELS[displayKey] || PERFORMANCE_LABELS.consistent;
  return { key: displayKey, label: meta.label, short: meta.short };
}

function rankVectorsForSets(setsJson, topN = 3, isTimed = false) {
  const result = isTimed ? compareTimedWorkouts(setsJson || {}, setsJson || {}, { top_n: topN })
    : compareStrengthWorkouts(setsJson || {}, setsJson || {}, { top_n: topN });
  const vectors = result.current || {};
  return { scores: [...(vectors.scores || [])], weights: [...(vectors.weights || [])] };
}

function firstScoreDiffIndex(left, right, topN = 3, eps = 1e-6) {
  const n = Math.max(1, Number.isInteger(topN) && topN > 0 ? topN : 3);
  for (let idx = 0; idx < n; idx++) {
    const lv = idx < left.length ? left[idx] : 0.0;
    const rv = idx < right.length ? right[idx] : 0.0;
    if (Math.abs(lv - rv) <= eps) continue;
    return lv > rv ? [idx, 1] : [idx, -1];
  }
  return [null, 0];
}

/** {weights: floats, reps: ints}, or null when there are no sets (services.logging._normalize_sets). */
export function normalizeSets(setsJson) {
  if (!isDict(setsJson) || !Object.keys(setsJson).length) return null;
  let weights = setsJson.weights || [];
  let reps = setsJson.reps || [];
  try {
    weights = weights.map(toFloat);
    reps = reps.map(toInt);
  } catch {
    return null;
  }
  if (!weights.length && !reps.length) return null;
  return { weights, reps };
}

function setCountFromSetsJson(setsJson) {
  const n = normalizeSets(setsJson);
  return n ? Math.max(n.weights.length, n.reps.length) : 0;
}

function alignSetsToCount(setsJson, targetCount) {
  const n = normalizeSets(setsJson);
  if (!n) return null;
  const target = Number.isInteger(targetCount) && targetCount > 0 ? targetCount : 3;
  const [weights, reps] = alignSets([...n.weights], [...n.reps], target);
  return { weights, reps };
}

/** How many sets two workouts are compared over. */
export function comparisonSetCount(setsJson, exerciseString = '') {
  const jsonCount = setCountFromSetsJson(setsJson);
  const explicit = extractExplicitTargetSets(exerciseString);
  if (Number.isInteger(explicit) && explicit > 0) return Math.max(explicit, jsonCount);
  return jsonCount > 3 ? jsonCount : 3;
}

/** Whether an exercise's text writes a time: a bracket with seconds, or times under the name. */
export function hasTimeHint(exerciseString) {
  const text = String(exerciseString ?? '');
  if (!text) return false;
  for (const part of re('\\[([^\\]]*)\\]').findall(text)) {
    const token = strip(String(part || '')).toLowerCase();
    if (!token) continue;
    if (re('(?:\\b(?:s|sec|secs|second|seconds)\\b|\\d+\\s*s(?:ec(?:onds?)?)?\\b)').test(token)) return true;
  }
  return splitlines(text).slice(1).some((line) => TIME_TOKEN.test(line));
}

// The database pre-filter Python applies before looking for a time hint in old logs.
function mightBeTimed(text) {
  return text.includes('[') || text.includes(':') || /[0-9] ?[sS]/.test(text);
}

/**
 * Whether an exercise is timed: written as a time, the person's choice, a known timed exercise
 * (asking once), or timed in its history. {is_timed, prompt_needed, reason}.
 */
export function resolveTimedStatus({ exerciseName, exerciseString = '', settings = null, history = [], nameIndex = null }) {
  if (hasTimeHint(exerciseString || '')) return { is_timed: true, prompt_needed: false, reason: 'explicit_hint' };
  const key = exerciseKey(exerciseName);
  if (key && settings && settings.timed.has(key)) {
    return { is_timed: settings.timed.get(key), prompt_needed: false, reason: 'stored_preference' };
  }
  if (key && KNOWN_TIMED_KEYS.has(key)) return { is_timed: true, prompt_needed: true, reason: 'known_timed_fallback' };
  const candidates = new Set(namesFor(exerciseName, nameIndex));
  const timed = candidates.size > 0 && history.some((log) => candidates.has(log.exercise)
    && mightBeTimed(log.exercise_string || '') && hasTimeHint(log.exercise_string || ''));
  return { is_timed: timed, prompt_needed: false, reason: timed ? 'time_history' : 'default_strength' };
}

function extractTimeSeconds(exerciseString, expectedSets) {
  const text = String(exerciseString ?? '');
  if (!text) return [];
  const lines = splitlines(text).map((l) => strip(l)).filter(Boolean);
  if (!lines.length) return [];
  const toSeconds = (values) => values.map((v) => Math.max(1, roundHalfEven(v)));
  for (const line of lines) {
    if (line.includes(',')) {
      const values = extractNumbers(strip(split1(line, ',')[1]));
      if (values.length) return toSeconds(values);
    }
  }
  const numericLines = lines.filter((l) => /[0-9]/.test(l));
  if (numericLines.length >= 2) {
    const values = extractNumbers(numericLines[numericLines.length - 1]);
    if (values.length) return toSeconds(values);
  }
  const values = extractNumbers(text);
  if (expectedSets > 0 && values.length === expectedSets * 2) return toSeconds(values.slice(expectedSets));
  return [];
}

function roundHalfEven(x) {
  const f = Math.floor(x);
  const d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

/** "26 x 7, 22.5 x 15". */
export function formatSetsDisplay(setsJson) {
  if (!isDict(setsJson)) return '';
  const weights = setsJson.weights || [];
  const reps = setsJson.reps || [];
  if (!weights.length && !reps.length) return '';
  const pairs = [];
  for (let i = 0; i < Math.min(weights.length, reps.length); i++) {
    const w = weights[i];
    const r = reps[i];
    if (w === null || w === undefined || r === null || r === undefined) continue;
    pairs.push(`${typeof w === 'number' ? formatG(w) : typeof w === 'boolean' ? String(Number(w)) : String(w)} x ${toInt(r)}`);
  }
  return pairs.join(', ');
}

function formatBestString(log) {
  if (!log) return '-';
  const setsJson = log.sets ?? log.sets_json;
  if (setsJson && isDict(setsJson) && Object.keys(setsJson).length) {
    const formatted = formatSetsDisplay(setsJson);
    if (formatted) return formatted;
  }
  if (log.exercise_string) return log.exercise_string;
  return '-';
}

function dateSortKey(value) {
  return value ? formatDateTime(parseDate(value)) : '';
}

// Logs of an exercise, oldest first (as the database returns them ordered by date, then id).
function logsFor(history, candidates) {
  const names = new Set(candidates);
  return history
    .map((log, order) => ({ log, order }))
    .filter(({ log }) => names.has(log.exercise))
    .sort((a, b) => compareKeys([dateSortKey(a.log.date), a.order], [dateSortKey(b.log.date), b.order]))
    .map(({ log }) => log);
}

/** The log to beat for an exercise: the strongest that reached the target sets. */
export function getBestLog({ history, settings, exerciseName, targetSets = 3, strictTargetSets = false, nameIndex = null, isTimed = false }) {
  const candidates = namesFor(exerciseName, nameIndex);
  if (!candidates.length) return null;
  const names = new Set(candidates);
  const logs = history.filter((log) => names.has(log.exercise));
  if (!logs.length) return null;
  const required = Number.isInteger(targetSets) && targetSets > 0 ? targetSets : 3;
  const preferred = [];
  const fallback = [];
  for (const log of logs) {
    const normalized = normalizeSets(effectiveSetsForLog(settings, log));
    if (!normalized) continue;
    const setCount = comparisonSetCount(normalized, log.exercise_string || '');
    const scoring = alignSetsToCount(normalized, setCount) || normalized;
    const vectors = rankVectorsForSets(scoring, required, isTimed);
    if (!vectors.scores.length) continue;
    const row = [log, [vectors.scores, vectors.weights], setCount];
    (setCount >= required ? preferred : fallback).push(row);
  }
  const pool = strictTargetSets ? preferred : (preferred.length ? preferred : fallback);
  if (!pool.length) return null;
  return maxBy(pool, (row) => [row[1], row[2], dateSortKey(row[0].date)])[0];
}

/** Today's exercise against all its logs: {key, label, short, ...} (services.logging.classify_exercise_performance). */
export function classifyPerformance({
  history, settings, exerciseName, currentSets, targetSets = 3, strictTargetSets = false, nameIndex = null,
  isTimed = false, currentLogId = null, currentExerciseString = '', summaryMode = false,
}) {
  const normalizedCurrent = normalizeSets(currentSets);
  if (!normalizedCurrent) return performancePayload('consistent', summaryMode);
  const candidates = namesFor(exerciseName, nameIndex);
  if (!candidates.length) return performancePayload('first_log', summaryMode);

  const topN = Math.max(1, Number.isInteger(targetSets) && targetSets > 0 ? targetSets : 3);
  const currentSetCount = comparisonSetCount(normalizedCurrent, currentExerciseString || '');
  let compareN = topN;
  let minRequired = topN;
  if (strictTargetSets && currentSetCount > 0 && currentSetCount < topN) {
    compareN = currentSetCount;
    minRequired = currentSetCount;
  }

  const rows = [];
  let hadHistoricalWithSets = false;
  for (const log of logsFor(history, candidates)) {
    const logSets = normalizeSets(effectiveSetsForLog(settings, log));
    if (!logSets) continue;
    if (currentLogId === null || log.id !== currentLogId) hadHistoricalWithSets = true;
    const logSetCount = comparisonSetCount(logSets, log.exercise_string || '');
    if (strictTargetSets && logSetCount < minRequired) continue;
    const aligned = alignSetsToCount(logSets, logSetCount) || logSets;
    const vectors = rankVectorsForSets(aligned, compareN, isTimed);
    if (!vectors.scores.length) continue;
    rows.push({ id: log.id ?? null, scores: vectors.scores, weights: vectors.weights, set_count: logSetCount, date: dateSortKey(log.date), is_current: false });
  }

  let currentRow = null;
  if (currentLogId !== null) {
    currentRow = rows.find((row) => row.id === currentLogId) || null;
    if (currentRow) currentRow.is_current = true;
  }
  if (currentRow === null) {
    const aligned = alignSetsToCount(normalizedCurrent, Math.max(currentSetCount, compareN)) || normalizedCurrent;
    const vectors = rankVectorsForSets(aligned, compareN, isTimed);
    if (!vectors.scores.length) return performancePayload('consistent', summaryMode);
    currentRow = { id: currentLogId, scores: vectors.scores, weights: vectors.weights, date: '9999', is_current: true };
    rows.push(currentRow);
  }

  let competitors = rows.filter((row) => !row.is_current);
  if (!competitors.length) {
    if (strictTargetSets && currentSetCount > 0 && currentSetCount < topN && hadHistoricalWithSets) {
      return { key: 'first_log', label: 'No Comparable Baseline', short: 'No Comparable Baseline' };
    }
    return performancePayload('first_log', summaryMode);
  }
  if (!strictTargetSets) {
    const full = competitors.filter((row) => (row.set_count || 0) >= topN);
    if (full.length) competitors = full;
  }
  const reference = maxBy(competitors, (row) => [row.scores, row.weights, row.set_count || 0, row.date || '']);

  const result = (key, diffIdx = null, vector = 'scores') => {
    const payload = performancePayload(key, summaryMode);
    payload.reference_log_id = reference.id;
    payload.diff_index = diffIdx;
    payload.diff_pct = null;
    if (diffIdx !== null) {
      const cur = currentRow[vector] || [];
      const ref = reference[vector] || [];
      const curVal = diffIdx < cur.length ? cur[diffIdx] : 0.0;
      const refVal = diffIdx < ref.length ? ref[diffIdx] : 0.0;
      if (refVal > 0) payload.diff_pct = ((curVal - refVal) / refVal) * 100.0;
    }
    return payload;
  };

  const [diffIdx, cmp] = firstScoreDiffIndex(currentRow.scores || [], reference.scores || [], Math.min(compareN, 3));
  if (cmp > 0) return result(diffIdx === 0 ? 'gold_strength' : diffIdx === 1 ? 'silver_strength' : 'bronze_strength', diffIdx);
  if (cmp < 0) return result(diffIdx === 0 ? 'significantly_off' : diffIdx === 1 ? 'moderately_off' : 'slightly_off', diffIdx);

  const cw = currentRow.weights || [];
  const rw = reference.weights || [];
  for (let idx = 0; idx < Math.min(compareN, 3); idx++) {
    const c = idx < cw.length ? cw[idx] : 0.0;
    const r = idx < rw.length ? rw[idx] : 0.0;
    if (c > r) return result(idx === 0 ? 'gold_load' : idx === 1 ? 'silver_load' : 'bronze_load', idx, 'weights');
  }
  return result('consistent');
}

function newLogId() {
  return globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `log-${Date.now()}-${Math.random()}`;
}

/**
 * Save a parsed workout (services.logging.handle_workout_log, without the database).
 *
 * parsed: the parser's result (workoutParser()). It is changed in place by renames, as in Python.
 * context:
 *   history          the person's workout_logs rows, oldest first (as created)
 *   settings         makeSettings(exercise_settings rows), or the rows themselves
 *   renames          exercise_renames rows ({old_key, new_name})
 *   ownRepRanges     the person's own rep-range text (not the plan owner's)
 *   planText         the plan they train from (effectivePlanText())
 *   bodyweight       their current bodyweight (profile)
 *   loggedBodyweight the bodyweight an edited workout was first logged with, if any
 *   newId            makes ids for new rows
 *
 * Returns {logs, summary, bodyweight, bodyweightSettings}: rows to insert, the summary rows the
 * page shows, the new current bodyweight (or null to leave it), and exercises to mark as
 * bodyweight exercises ({exercise_key, exercise_name, is_bodyweight, source}).
 */
export function handleWorkoutLog(parsed, context = {}) {
  const {
    renames = [], ownRepRanges = '', planText = '', bodyweight: profileBodyweight = null,
    loggedBodyweight = null, newId = newLogId,
  } = context;
  const history = [...(context.history || [])];
  const settings = context.settings instanceof Object && context.settings.bodyweight instanceof Map
    ? { bodyweight: new Map(context.settings.bodyweight), timed: new Map(context.settings.timed) }
    : makeSettings(context.settings || []);
  const summary = [];
  const logs = [];
  const bodyweightSettings = [];
  let newBodyweight = null;

  const workoutDate = parsed.date ?? formatDateTime(parseDate());
  const workoutName = parsed.workout_name ?? null;
  let workoutBodyweight = loggedBodyweight || profileBodyweight;
  if (parsed.bodyweight !== null && parsed.bodyweight !== undefined) {
    let value = null;
    try {
      value = toFloat(parsed.bodyweight);
    } catch {
      value = null;
    }
    if (value !== null && Number.isFinite(value) && value >= 1 && value <= 500) {
      workoutBodyweight = value;
      const latest = history.reduce((acc, log) => (log.date && (!acc || dateSortKey(log.date) > acc) ? dateSortKey(log.date) : acc), '');
      if (!latest || dateSortKey(workoutDate) >= latest) newBodyweight = value;
    }
  }
  const repTargetSets = parseRepTargetSets(ownRepRanges || '');
  const planTargetSets = parsePlanTargetSets(planText || '');
  const nameIndex = buildNameIndex([...new Set(history.map((log) => log.exercise))]);

  if (!parsed.exercises || !parsed.exercises.length) {
    return { logs, summary, bodyweight: newBodyweight, bodyweightSettings };
  }
  applyRenamesToParsed(parsed, redirectsFrom(renames));

  for (const item of parsed.exercises) {
    const exName = item.name;
    let newSets = { weights: item.weights, reps: item.reps };
    const newStr = item.exercise_string;
    const isValid = item.valid ?? true;
    let timeBased = false;
    let timedStatus = { is_timed: false, prompt_needed: false };
    if (isValid) {
      timedStatus = resolveTimedStatus({ exerciseName: exName, exerciseString: newStr, settings, history, nameIndex });
      timeBased = Boolean(timedStatus.is_timed);
      const currentReps = (newSets.reps || []).filter((r) => r !== null && r !== undefined).map(toInt);
      if (timeBased && currentReps.length && currentReps.every((r) => r <= 1)) {
        const nWeights = (newSets.weights || []).length;
        const seconds = extractTimeSeconds(newStr, nWeights);
        if (seconds.length) {
          const [weights, reps] = alignSets([...(newSets.weights || [])], seconds.map(toInt), nWeights || null);
          newSets = { weights, reps };
        }
      }
    }

    const inferred = setCountFromSetsJson(newSets);
    const [targetSets, strict] = resolveTargetSets({
      exerciseName: exName, exerciseString: newStr, repTargetSets, planTargetSets, inferredSetCount: inferred, defaultSets: 3,
    });
    if (isValid && setCountFromSetsJson(newSets) > 0) {
      const aligned = alignSetsToCount(newSets, targetSets);
      if (aligned) newSets = aligned;
    }

    const usesBodyweight = isValid
      ? Boolean(isBodyweightEnabled(settings, exName, newStr) || isTimeOnlyExercise(newStr, item.source_name || exName))
      : false;
    if (isValid && hasBodyweightToken(newStr)) {
      const key = exerciseKey(exName);
      const cleanName = strip(String(exName ?? ''));
      if (key && cleanName) {
        settings.bodyweight.set(key, true);
        bodyweightSettings.push({ exercise_key: key, exercise_name: cleanName, is_bodyweight: true, source: 'auto' });
      }
    }
    const effectiveNew = effectiveSetsForCurrent(newSets, workoutBodyweight, usesBodyweight);
    const formattedDisplay = isValid ? formatSetsDisplay(newSets) : newStr;
    let [peak] = getSetStats(effectiveNew);

    let dailyMaxWeight = 0;
    let dailyMaxReps = 0;
    const effWeights = [...(effectiveNew?.weights || [])];
    const effReps = [...(effectiveNew?.reps || [])];
    if (isValid && effWeights.length) {
      dailyMaxWeight = effWeights.reduce((a, b) => (b > a ? b : a));
      const idx = effWeights.indexOf(dailyMaxWeight);
      dailyMaxReps = idx < effReps.length ? effReps[idx] : 0;
    }

    const bestLog = getBestLog({ history, settings, exerciseName: exName, targetSets, strictTargetSets: strict, nameIndex, isTimed: timeBased });
    const bestLogSets = bestLog ? normalizeSets(effectiveSetsForLog(settings, bestLog)) : null;

    const row = {
      name: exName, old: '-', new: formattedDisplay, status: '-', class: 'neutral', valid: isValid,
      is_timed: isValid ? timeBased : false,
      timed_prompt_needed: isValid ? Boolean(timedStatus.prompt_needed) : false,
      timed_prompt_exercise: exName, performance_key: null, performance_label: null,
    };

    if (isValid) {
      if (timeBased) [peak] = getTimedSetStats(effectiveNew);
      const log = {
        id: newId(),
        date: workoutDate,
        workout_name: workoutName,
        exercise: exName,
        exercise_string: newStr,
        sets: newSets,
        bodyweight: workoutBodyweight ?? null,
        uses_bodyweight: usesBodyweight,
        top_weight: dailyMaxWeight > 0 ? dailyMaxWeight : null,
        top_reps: dailyMaxReps > 0 ? dailyMaxReps : null,
        estimated_1rm: peak > 0 ? peak : null,
      };
      history.push(log);
      logs.push(log);

      const perf = classifyPerformance({
        history, settings, exerciseName: exName, currentSets: effectiveNew, targetSets, strictTargetSets: strict,
        nameIndex, isTimed: timeBased, currentLogId: log.id, currentExerciseString: newStr, summaryMode: true,
      });
      row.performance_key = perf.key;
      row.performance_label = perf.label;

      let improvement = null;
      const currentCount = comparisonSetCount(newSets, newStr);
      const canCompare = !strict || currentCount >= targetSets;
      if (bestLogSets && canCompare) {
        row.old = formatBestString(bestLog);
        const comparison = timeBased
          ? compareTimedWorkouts(bestLogSets, effectiveNew, { top_n: targetSets })
          : compareStrengthWorkouts(bestLogSets, effectiveNew, { top_n: targetSets });
        if ((comparison.cmp || 0) > 0) {
          improvement = comparison.reason === 'peak' ? `PEAK (+${formatFixed(comparison.diff || 0.0, 1)})` : 'CONSISTENCY';
        }
      } else if (bestLogSets) {
        row.old = formatBestString(bestLog);
        row.status = '-';
        row.class = 'neutral';
      } else {
        row.old = 'First Log';
        row.status = 'NEW';
        row.class = 'new';
      }
      if (improvement) {
        row.status = improvement;
        row.class = 'improved';
      }
    } else {
      row.status = 'ERROR';
    }
    summary.push(row);
  }
  return { logs, summary, bodyweight: newBodyweight, bodyweightSettings };
}

/** The values a stored log's numbers are recalculated from (services.bodyweight.recalculate_log_metrics). */
export function logMetrics(log, { settings = null, isTimed = false } = {}) {
  const effective = effectiveSetsForLog(settings, log);
  const [peak] = isTimed ? getTimedSetStats(effective) : getSetStats(effective);
  const weights = [...(effective?.weights || [])];
  const reps = [...(effective?.reps || [])];
  let topWeight = null;
  let topReps = null;
  if (weights.length && reps.length) {
    try {
      const values = weights.filter((w) => w !== null && w !== undefined).map(toFloat);
      topWeight = values.reduce((a, b) => (b > a ? b : a));
      const idx = weights.map(toFloat).indexOf(topWeight);
      topReps = idx < reps.length ? toInt(reps[idx]) : null;
    } catch {
      topWeight = null;
      topReps = null;
    }
  }
  return { top_weight: topWeight, top_reps: topReps, estimated_1rm: peak && peak > 0 ? peak : null };
}

export { normalizeExerciseName, lstrip };
