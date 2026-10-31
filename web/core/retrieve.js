// Retrieve: the text a person copies before training, with each exercise of a plan day (or a
// custom pick) and the sets to beat from their best log. Ports services/retrieve.py without the
// database: history, plan and rep ranges come in as plain values.
import { re, strip, lstrip, rstrip, split, split1, splitlines, toFloat, toInt, formatG, pyRound, isDict, maxBy, compareKeys } from './py.js';
import { BW_EXERCISES } from './defaults.js';
import { parsePlanExerciseLine, joinSetRows, parseBwWeight, parseSetRow } from './parser.js';
import { buildNameIndex, namesFor, normalizeExerciseName } from './names.js';
import { getWorkoutDays, parseRepRangesText, lookupRepTarget } from './plans.js';
import { bestWorkoutStrengthScore, coerceEqualLenSets, estimate1rm } from './scoring.js';
import { effectiveSetsForLog, inferLogUsesBodyweight, isBodyweightEnabled, makeSettings } from './bodyweight.js';
import { formatDateTime, parseDate, retrieveDateString } from './dates.js';

export const DEFAULT_CUSTOM_WORKOUT_TITLE = 'Custom Workout';

function formatValue(value) {
  return typeof value === 'number' ? formatG(value) : String(value);
}

function dateSortKey(value) {
  return value ? formatDateTime(parseDate(value)) : '';
}

function asSettings(settings) {
  if (settings && settings.bodyweight instanceof Map) return settings;
  return makeSettings(settings || []);
}

/** "Body Weight - 73 kg", or "" when no bodyweight is set. */
export function formatBodyweightLine(bodyweight, history = []) {
  if (bodyweight === null || bodyweight === undefined) return '';
  let value;
  try {
    value = toFloat(bodyweight);
  } catch {
    return '';
  }
  if (value <= 0) return '';
  return `Body Weight - ${formatValue(value)} ${inferWeightUnit(history)}`;
}

/** "lbs" when the person's last 50 logs write lbs more than kg, else "kg". */
export function inferWeightUnit(history = []) {
  const recent = history
    .map((log, order) => ({ log, order }))
    .sort((a, b) => compareKeys([dateSortKey(b.log.date), b.order], [dateSortKey(a.log.date), a.order]))
    .slice(0, 50);
  let kg = 0;
  let lbs = 0;
  for (const { log } of recent) {
    const text = String(log.exercise_string ?? '').toLowerCase();
    kg += re('\\bkg(?:s)?\\b').findall(text).length;
    lbs += re('\\blbs?\\b').findall(text).length;
  }
  return lbs > kg ? 'lbs' : 'kg';
}

function compressShorthandValues(values) {
  if (!values.length) return [];
  if (values.length === 1) return [...values];
  if (values.every((v) => v === values[0])) return [values[0]];
  if (values.slice(1).every((v) => v === values[1]) && values[0] !== values[1]) return [values[0], values[1]];
  return [...values];
}

function isBwExercise(settings, exercise) {
  if (isBodyweightEnabled(settings, exercise)) return true;
  if (BW_EXERCISES.includes(exercise)) return true;
  const n = (s) => strip(s).toLowerCase().replaceAll('-', ' ').replaceAll('_', ' ');
  const normalized = n(exercise);
  return BW_EXERCISES.some((bw) => bw.toLowerCase().replaceAll('-', ' ').replaceAll('_', ' ') === normalized);
}

function formatWeightToken(weight, bodyweight, { forceBw = false, currentBodyweight = null, renderAsBw = false } = {}) {
  const token = formatValue(weight);
  if (forceBw) return 'bw';
  if (!renderAsBw) return token;
  if ((bodyweight === null || bodyweight === undefined) && (currentBodyweight === null || currentBodyweight === undefined)) return token;
  let weightValue;
  try {
    weightValue = toFloat(weight);
  } catch {
    return token;
  }
  const asFloat = (v) => {
    if (v === null || v === undefined) return null;
    try {
      return toFloat(v);
    } catch {
      return null;
    }
  };
  const bwLogged = asFloat(bodyweight);
  const bwCurrent = asFloat(currentBodyweight);
  const base = bwCurrent !== null ? bwCurrent : bwLogged;
  if (base === null) return token;
  const offset = weightValue - base;
  if (Math.abs(offset) < 0.05) return 'bw';
  return `bw${offset > 0 ? '+' : '-'}${formatValue(Math.abs(pyRound(offset, 2)))}`;
}

const X_PAIRS = re('(bw(?:/\\d+(?:\\.\\d+)?)?(?:[+-]\\d+(?:\\.\\d+)?)?|-?\\d+(?:\\.\\d+)?)\\s*[x×]\\s*(\\d+)', 'i');
const UNIT_WORDS = re('(kg|lbs|lb)', 'i');

function expandShorthandTokens(tokens, targetSets = 3) {
  if (!tokens.length) return [];
  if (targetSets <= 0) return [...tokens];
  if (tokens.length === 1) return Array(targetSets).fill(tokens[0]);
  if (tokens.length === 2 && tokens.length < targetSets) return [tokens[0], ...Array(targetSets - 1).fill(tokens[1])];
  if (tokens.length < targetSets) return [...tokens, ...Array(targetSets - tokens.length).fill(tokens[tokens.length - 1])];
  return [...tokens];
}

function splitWeightsReps(setsLine) {
  const parts = split1(setsLine, ',');
  let weightsPart = strip(parts[0] ?? '');
  let repsPart = parts.length > 1 ? strip(parts[1]) : '';
  weightsPart = UNIT_WORDS.sub('', weightsPart);
  repsPart = UNIT_WORDS.sub('', repsPart);
  return [split(weightsPart.replaceAll(',', ' ')), split(repsPart.replaceAll(',', ' '))];
}

/** A sets line spelled out to the target count: "100, 5" -> "100 100 100, 5 5 5". */
export function normalizeSetsLine(setsLine, defaultWeight = '1', targetSets = 3) {
  if (!setsLine) return '';
  const xMatches = X_PAIRS.findall(setsLine);
  let weights;
  let reps;
  if (xMatches.length) {
    weights = xMatches.map((m) => m[0]);
    reps = xMatches.map((m) => m[1]);
  } else {
    [weights, reps] = splitWeightsReps(setsLine);
  }
  if (!weights.length && !reps.length) {
    weights = [defaultWeight];
    reps = ['1'];
  } else if (!weights.length) weights = Array(reps.length).fill(defaultWeight);
  else if (!reps.length) reps = Array(weights.length).fill('1');

  weights = expandShorthandTokens(weights, targetSets);
  reps = expandShorthandTokens(reps, targetSets);
  if (weights.length === 1 && reps.length > 1) weights = Array(reps.length).fill(weights[0]);
  else if (reps.length === 1 && weights.length > 1) reps = Array(weights.length).fill(reps[0]);
  else if (weights.length < reps.length && weights.length) weights = [...weights, ...Array(reps.length - weights.length).fill(weights[weights.length - 1])];
  else if (reps.length < weights.length && reps.length) reps = [...reps, ...Array(weights.length - reps.length).fill(reps[reps.length - 1])];

  const n = Math.min(weights.length, reps.length);
  if (xMatches.length) return Array.from({ length: n }, (_, i) => `${weights[i]} x ${reps[i]}`).join(', ');
  return `${weights.join(' ')}, ${reps.join(' ')}`;
}

function parseSetsLineTokens(setsLine, targetSets = 3) {
  const normalized = normalizeSetsLine(setsLine, '1', targetSets);
  const xMatches = X_PAIRS.findall(normalized);
  if (xMatches.length) return [xMatches.map((m) => m[0]), xMatches.map((m) => m[1])];
  return splitWeightsReps(normalized);
}

function isDefaultNumericSets(value) {
  const normalized = strip(value || '').toLowerCase().replaceAll('  ', ' ');
  return normalized === '1 1 1, 1 1 1' || normalized === '1, 1';
}

const DATA_LIKE = (s) => Boolean(re('^(?:bw|,|-?\\d)').match(strip(s || '').toLowerCase()));

function extractSetsLine(bestString, exercise) {
  const trimmed = strip(bestString || '');
  if (!trimmed) return '';
  const lines = splitlines(trimmed).map((l) => strip(l)).filter(Boolean);
  const n = lines.length;
  if (n >= 3 && DATA_LIKE(lines[n - 2]) && DATA_LIKE(lines[n - 1]) && !lines[n - 2].includes(',')) {
    return strip(`${lines[n - 2]}, ${lines[n - 1]}`);
  }
  if (n >= 2 && DATA_LIKE(lines[n - 1])) return lines[n - 1];
  if (trimmed.includes(' - [') && trimmed.includes(']')) {
    const tail = strip(lstrip(strip(split1(trimmed, ']')[1]), '-:'));
    if (tail) return tail;
  }
  if (trimmed.toLowerCase().startsWith(exercise.toLowerCase())) {
    const tail = strip(lstrip(strip(trimmed.slice(exercise.length)), '-:'));
    if (tail) return tail;
  }
  return trimmed;
}

function logUsesBwNotation(log, exercise) {
  if (inferLogUsesBodyweight(null, log)) return true;
  const setsLine = extractSetsLine(log.exercise_string || '', exercise);
  if (!setsLine) return false;
  return re('\\bbw(?:/\\d+(?:\\.\\d+)?)?(?:[+-]\\d+(?:\\.\\d+)?)?\\b', 'i').test(setsLine);
}

function normalizeBw(value) {
  value = re('\\bbw/', 'i').sub('bw/', value);
  value = re('\\bbw(?=[+-])', 'i').sub('bw', value);
  return re('\\bbw\\b', 'i').sub('bw', value);
}

function extractOriginalBwTokens(log, exercise, targetSets = 3) {
  const setsLine = extractSetsLine(log.exercise_string || '', exercise);
  if (!setsLine) return [];
  const [weights] = parseSetsLineTokens(setsLine, targetSets);
  return weights.map((token) => {
    token = normalizeBw(strip(String(token || '')));
    return parseBwWeight(token, log.bodyweight ?? null) !== null ? token : '';
  });
}

function formatRetrievedWeightToken(weight, { loggedBodyweight = null, currentBodyweight = null, renderAsBw = false, originalToken = '' } = {}) {
  if (!renderAsBw) return formatValue(weight);
  originalToken = normalizeBw(strip(String(originalToken || '')));
  if (originalToken) {
    let current = null;
    let stored = null;
    try {
      current = parseBwWeight(originalToken, currentBodyweight);
      stored = toFloat(weight);
    } catch {
      current = null;
      stored = null;
    }
    if (current !== null && stored !== null && Math.abs(current - stored) < 0.05) return originalToken;
  }
  return formatWeightToken(weight, loggedBodyweight || currentBodyweight, { currentBodyweight, renderAsBw: true });
}

function rebaseBwSetsLine(log, setsLine, { currentBodyweight = null, targetSets = 3 } = {}) {
  if (!setsLine) return '';
  const [weights, reps] = parseSetsLineTokens(setsLine, targetSets);
  if (!weights.length || !reps.length) return normalizeBw(setsLine);
  const logged = log.bodyweight ?? null;
  const tokens = weights.map((raw) => {
    const token = normalizeBw(strip(String(raw || '')));
    const parsed = parseBwWeight(token, logged);
    if (parsed === null) return token;
    return formatRetrievedWeightToken(parsed, { loggedBodyweight: logged, currentBodyweight, renderAsBw: true, originalToken: token });
  });
  return `${compressShorthandValues(tokens).join(' ')}, ${compressShorthandValues(reps).join(' ')}`;
}

/** The sets to beat for an exercise, as "100 95, 5 6", from its best log; "" when there is none. */
export function bestSetsLine({ history, settings, exercise, targetSets = 3, nameIndex = null, bodyweight = null }) {
  settings = asSettings(settings);
  const candidates = namesFor(exercise, nameIndex);
  if (!candidates.length) return '';
  const names = new Set(candidates);
  const logs = history
    .map((log, order) => ({ log, order }))
    .filter(({ log }) => names.has(log.exercise))
    .sort((a, b) => compareKeys(dateSortKey(b.log.date), dateSortKey(a.log.date)) || a.order - b.order)
    .map(({ log }) => log);
  if (!logs.length) return '';

  const required = Number.isInteger(targetSets) && targetSets > 0 ? targetSets : 3;
  const preferred = [];
  const fallback = [];
  for (const log of logs) {
    const setsJson = effectiveSetsForLog(settings, log);
    if (!isDict(setsJson) || !Object.keys(setsJson).length) continue;
    if (!(setsJson.weights || []).length && !(setsJson.reps || []).length) continue;
    const metrics = bestWorkoutStrengthScore(setsJson, { top_n: required });
    const score = metrics.score || 0.0;
    const setCount = Math.trunc(metrics.set_count || 0);
    if (score <= 0) continue;
    (setCount >= required ? preferred : fallback).push([log, score, setCount]);
  }
  const pool = preferred.length ? preferred : fallback;
  if (!pool.length) return '';
  const [bestLog] = maxBy(pool, (row) => [row[1], row[2], dateSortKey(row[0].date)]);

  const useBw = logUsesBwNotation(bestLog, exercise);
  const setsJson = effectiveSetsForLog(settings, bestLog);
  const fromText = () => {
    if (useBw && bestLog.exercise_string) {
      return rebaseBwSetsLine(bestLog, extractSetsLine(bestLog.exercise_string, bestLog.exercise), { currentBodyweight: bodyweight, targetSets: required });
    }
    return '';
  };
  if (!isDict(setsJson) || !Object.keys(setsJson).length) return fromText();
  const [weights, reps] = coerceEqualLenSets(setsJson.weights || [], setsJson.reps || []);
  if (!weights.length || !reps.length) return fromText();

  let scored = [];
  weights.forEach((w, idx) => {
    const r = reps[idx];
    if (r <= 0) return;
    scored.push([estimate1rm(w, r), w, r, idx]);
  });
  if (!scored.length) return '';
  // Heaviest first; at the same weight, more reps first.
  scored = scored.map((t, i) => [t, i]).sort((a, b) => compareKeys([b[0][1], b[0][2], b[0][0]], [a[0][1], a[0][2], a[0][0]]) || a[1] - b[1]).map((x) => x[0]);
  const top = scored.slice(0, Math.min(required, scored.length));

  const logBodyweight = bestLog.bodyweight ?? null;
  const originalBw = useBw ? extractOriginalBwTokens(bestLog, exercise, Math.max(required, weights.length, reps.length)) : [];
  let weightTokens = top.map((t) => formatRetrievedWeightToken(t[1], {
    loggedBodyweight: logBodyweight, currentBodyweight: bodyweight, renderAsBw: useBw,
    originalToken: t[3] < originalBw.length ? originalBw[t[3]] : '',
  }));
  let repTokens = top.map((t) => String(Math.trunc(t[2])));
  weightTokens = compressShorthandValues(weightTokens);
  repTokens = compressShorthandValues(repTokens);
  const weightsPart = strip(weightTokens.join(' '));
  const repsPart = strip(repTokens.join(' '));
  if (!weightsPart || !repsPart) return '';
  return `${weightsPart}, ${repsPart}`;
}

/** One set per line ("45, 3" then "40, 4"), shorthand spelled out. */
export function setsLineAsRows(setsLine, targetSets = 3) {
  const [weights, reps] = parseSetsLineTokens(setsLine, targetSets);
  if (!weights.length || weights.length !== reps.length) return [setsLine];
  return weights.map((w, i) => `${w}, ${reps[i]}`);
}

/** How many sets a retrieve line stands for. */
export function countSetsFromLine(setsLine, targetSets = 3) {
  if (!setsLine) return 0;
  const atLeastTarget = (raw) => (targetSets && raw < targetSets ? targetSets : raw);
  const xMatches = re('(bw(?:/\\d+(?:\\.\\d+)?)?(?:[+-]\\d+(?:\\.\\d+)?)?|-?\\d+(?:\\.\\d+)?)\\s*x\\s*\\d+', 'i').findall(setsLine);
  if (xMatches.length) return atLeastTarget(xMatches.length);
  const dropUnits = (s) => s.replaceAll('kg', '').replaceAll('lbs', '').replaceAll('lb', '');
  if (setsLine.includes(',')) {
    const parts = split1(setsLine, ',');
    const weightCount = split(strip(dropUnits(strip(parts[0])))).length;
    const repCount = split(strip(dropUnits(parts.length > 1 ? strip(parts[1]) : ''))).length;
    return atLeastTarget(Math.max(weightCount, repCount));
  }
  return atLeastTarget(split(strip(dropUnits(setsLine))).length);
}

/**
 * Retrieve text for a list of exercise lines (plan lines like "Squat - [3, 6-8]").
 * Returns [text, exercise count, set count] (services.retrieve._generate_retrieve_output_for_exercises).
 */
export function retrieveForExercises(exercises, { headerLine, history = [], settings = [], repRangesText = '', bodyweight = null, setOverrides = null }) {
  settings = asSettings(settings);
  const lines = (exercises || []).map((e) => strip(String(e ?? ''))).filter(Boolean);
  if (!lines.length) return ['No exercises selected.', 0, 0];
  const nameIndex = buildNameIndex([...new Set(history.map((log) => log.exercise))]);
  const [customRanges, customSets] = parseRepRangesText(repRangesText);

  const output = [headerLine, ''];
  const bodyweightLine = formatBodyweightLine(bodyweight, history);
  if (bodyweightLine) output.push(bodyweightLine, '');

  let setCount = 0;
  const overrides = new Map();
  for (const [key, value] of Object.entries(setOverrides || {})) {
    const normalizedKey = normalizeExerciseName(String(key ?? ''));
    let n;
    try {
      n = toInt(value);
    } catch {
      continue;
    }
    if (normalizedKey && n > 0) overrides.set(normalizedKey, n);
  }

  for (const ex of lines) {
    const plan = parsePlanExerciseLine(ex);
    const exName = strip(String(plan.name || ex));
    const exKey = normalizeExerciseName(exName);
    let [rng, repRangeSets] = lookupRepTarget(exName, customRanges, customSets);
    if (!rng && plan.inline_range) rng = plan.inline_range;
    let declared = plan.declared_sets;
    if (declared === null) declared = repRangeSets;
    if (overrides.has(exKey)) declared = overrides.get(exKey);
    let fmtRange = '';
    if (rng && declared) fmtRange = ` - [${declared}, ${rng}]`;
    else if (declared) fmtRange = ` - [${declared}]`;
    else if (rng) fmtRange = ` - [${rng}]`;

    const targetSets = Number.isInteger(declared) && declared > 0 ? declared : 3;
    let setsLine = bestSetsLine({ history, settings, exercise: exName, targetSets, nameIndex, bodyweight });
    if (isBwExercise(settings, exName)) {
      if (!setsLine) setsLine = 'bw/4, 1';
      setsLine = normalizeBw(setsLine);
    } else if (!setsLine) {
      setsLine = '1, 1';
    }
    if (setsLine) setCount += countSetsFromLine(setsLine, targetSets);
    output.push(`${exName}${fmtRange}`);
    if (setsLine) output.push(...setsLineAsRows(setsLine, targetSets));
    output.push('');
  }
  return [rstrip(output.join('\n')), lines.length, setCount];
}

/**
 * Retrieve text for one plan day ("Session", 2). Returns [text, exercise count, set count].
 * planText and repRangesText are the ones the person trains from (effectivePlanText() etc.);
 * today is the header date ("31/10/26"), today in India by default.
 */
export function retrieveDay(category, dayId, { planText, today = retrieveDateString(), ...rest }) {
  const dayKey = `${category} ${dayId}`;
  if (!planText) return ['Plan not found.', 0, 0];
  const plans = getWorkoutDays(planText);
  const exercises = plans.workout?.[category]?.[dayKey];
  if (!Object.hasOwn(plans.workout, category) || !Object.hasOwn(plans.workout[category], dayKey)) {
    return [`Day '${dayKey}' not found in plan.`, 0, 0];
  }
  let headerLine = `${today} - ${dayKey}`;
  if (strip(String(category)).toLowerCase() === 'session') {
    const sessionTitle = plans.session_titles?.[String(dayId)];
    if (sessionTitle) headerLine = `${today} - Session ${dayId} - ${sessionTitle}`;
  }
  return retrieveForExercises(exercises, { headerLine, ...rest });
}

/** A custom workout's title, one line, at most 80 characters. */
export function cleanCustomWorkoutTitle(title) {
  const cleaned = strip(re('\\s+').sub(' ', String(title ?? '')), ' -\u2013\u2014');
  return strip(cleaned.slice(0, 80));
}

/** Retrieve text for exercises picked by hand. */
export function retrieveCustom(exercises, { title = null, today = retrieveDateString(), ...rest }) {
  const name = cleanCustomWorkoutTitle(title) || DEFAULT_CUSTOM_WORKOUT_TITLE;
  return retrieveForExercises(exercises, { headerLine: `${today} - ${name}`, ...rest });
}

/** [[picker key, sets]] for a plan day's lines (what Edit loads). */
export function picksForPlanLines(lines, repRangesText = '') {
  const [ranges, sets] = parseRepRangesText(repRangesText);
  const picks = [];
  const seen = new Set();
  for (const line of lines || []) {
    const parsed = parsePlanExerciseLine(String(line ?? ''));
    const name = strip(String(parsed.name || line || ''));
    const key = normalizeExerciseName(name);
    if (!key || key === 'unknown exercise' || seen.has(key)) continue;
    seen.add(key);
    let n = parsed.declared_sets;
    if (n === null) n = lookupRepTarget(name, ranges, sets)[1];
    picks.push([key, Number.isInteger(n) && n > 0 ? n : 3]);
  }
  return picks;
}

function targetLabel(declared, inlineRange) {
  let rng = strip(inlineRange || '');
  const timed = re('[\\d\\s\\-–—]+s', 'i').fullmatch(rng);
  if (timed) rng = `${strip(rng.slice(0, -1))} s`;
  else if (rng && !re('[\\d\\s\\-–—]+').fullmatch(rng)) rng = rng.slice(0, 1).toLowerCase() + rng.slice(1);
  if (declared && rng) return `${declared} × ${rng}`;
  if (declared) return `${declared} set${declared === 1 ? '' : 's'}`;
  if (rng && re('[\\d\\s\\-–—]+').fullmatch(rng)) return `${rng} reps`;
  return rng;
}

function prettyLoad(token) {
  token = strip(String(token ?? ''));
  if (token.toLowerCase().startsWith('bw')) return 'BW' + token.slice(2).replaceAll('-', '−');
  try {
    return formatG(toFloat(token));
  } catch {
    return token;
  }
}

/** Retrieve text -> what the plan page shows: {header, bodyweight, exercises: [{name, target, sets_label, fresh}]}. */
export function describeRetrieveOutput(output) {
  const blocks = re('\\n\\s*\\n').split(strip(output || '')).filter((b) => strip(b));
  const described = { header: '', bodyweight: null, exercises: [] };
  if (!blocks.length) return described;
  described.header = strip(split1(blocks[0], '\n')[0]);
  for (const block of blocks.slice(1)) {
    const lines = block.split('\n').map((l) => strip(l)).filter(Boolean);
    const bw = re('^body\\s*weight\\s*[-:]\\s*(.+)$', 'i').match(lines[0]);
    if (bw && lines.length === 1) {
      described.bodyweight = strip(bw.group(1));
      continue;
    }
    const plan = parsePlanExerciseLine(lines[0]);
    const declared = plan.declared_sets;
    const inlineRange = plan.inline_range;
    const targetSets = declared ? declared : 3;
    const rows = lines.slice(1);
    let fresh;
    let setsLine;
    if (rows.length > 1 && rows.every((row) => parseSetRow(row))) {
      fresh = rows.every((row) => ['1,1', 'bw/4,1'].includes(row.toLowerCase().replaceAll(' ', '')));
      setsLine = joinSetRows(rows);
    } else {
      setsLine = rows.length ? rows[0] : '';
      fresh = !setsLine || isDefaultNumericSets(setsLine) || setsLine.toLowerCase().replaceAll(' ', '') === 'bw/4,1';
    }
    let setsLabel = '';
    if (!fresh) {
      try {
        const normalized = normalizeSetsLine(setsLine, '1', targetSets);
        let pairs;
        if (normalized.includes(' x ')) {
          pairs = normalized.split(', ').map((pair) => pair.split(' x '));
        } else {
          const parts = split1(normalized, ',');
          if (parts.length < 2) throw new Error('no comma');
          const ws = split(parts[0]);
          const rs = split(parts[1]);
          pairs = ws.slice(0, Math.min(ws.length, rs.length)).map((w, i) => [w, rs[i]]);
        }
        if (pairs.some((p) => p.length !== 2)) throw new Error('not a pair');
        const timed = Boolean(inlineRange && re('\\d\\s*s$', 'i').search(strip(String(inlineRange))));
        setsLabel = pairs.map(([w, r]) => `${prettyLoad(w)}×${r}${timed ? 's' : ''}`).join(' · ');
      } catch {
        setsLabel = setsLine;
      }
    }
    described.exercises.push({ name: plan.name || lines[0], target: targetLabel(declared, inlineRange), sets_label: setsLabel, fresh });
  }
  return described;
}
