// Bodyweight exercises: which ones count the lifter's bodyweight, and the weights they really
// moved. Ports the pure parts of services/bodyweight.py. The person's own choices come from
// exercise_settings rows; see makeSettings().
import { re, toFloat, isDict } from './py.js';
import { BW_EXERCISES } from './defaults.js';
import { exerciseKey } from './names.js';

export const BODYWEIGHT_TOKEN_RE = re(
  '(?:\\bbw(?:\\s*/\\s*\\d+(?:\\.\\d+)?)?(?:\\s*[+-]\\s*\\d+(?:\\.\\d+)?)?\\b|\\bbody\\s*weight\\b|\\bbodyweight\\b)',
  'i',
);

export function hasBodyweightToken(text) {
  return BODYWEIGHT_TOKEN_RE.test(String(text ?? ''));
}

const DEFAULT_BODYWEIGHT_KEYS = new Set(BW_EXERCISES.map(exerciseKey).filter(Boolean));

export function isDefaultBodyweightExercise(exerciseName) {
  const key = exerciseKey(exerciseName);
  return Boolean(key && DEFAULT_BODYWEIGHT_KEYS.has(key));
}

/**
 * The person's choices per exercise, from exercise_settings rows
 * ({exercise_key, is_bodyweight, is_timed}). null means no choice was made.
 * Python keeps these in two tables; both are keyed the same way (exerciseKey()).
 */
export function makeSettings(rows = []) {
  const bodyweight = new Map();
  const timed = new Map();
  for (const row of rows || []) {
    if (!row || !row.exercise_key || row.deleted_at) continue;
    if (row.is_bodyweight !== null && row.is_bodyweight !== undefined) bodyweight.set(row.exercise_key, Boolean(row.is_bodyweight));
    if (row.is_timed !== null && row.is_timed !== undefined) timed.set(row.exercise_key, Boolean(row.is_timed));
  }
  return { bodyweight, timed };
}

export function bodyweightPreference(settings, exerciseName) {
  const key = exerciseKey(exerciseName);
  if (!key || !settings) return null;
  return settings.bodyweight.has(key) ? settings.bodyweight.get(key) : null;
}

export function isBodyweightEnabled(settings, exerciseName, exerciseText = '') {
  if (hasBodyweightToken(exerciseText)) return true;
  const pref = bodyweightPreference(settings, exerciseName);
  if (pref !== null) return pref;
  return isDefaultBodyweightExercise(exerciseName);
}

export function setsOfLog(log) {
  const sets = log?.sets ?? log?.sets_json;
  return isDict(sets) ? sets : null;
}

/** Whether a stored log counts bodyweight. Pass settings=null to use only the defaults. */
export function inferLogUsesBodyweight(settings, log) {
  const explicit = log?.uses_bodyweight;
  if (explicit !== null && explicit !== undefined) return Boolean(explicit);
  const text = log?.exercise_string || '';
  if (hasBodyweightToken(text)) return true;
  const exercise = log?.exercise || '';
  const enabled = settings ? isBodyweightEnabled(settings, exercise, '') : isDefaultBodyweightExercise(exercise);
  if (!enabled) return false;
  // Old default-bodyweight logs used 1 as a bodyweight placeholder.
  const weights = [...(setsOfLog(log)?.weights || [])];
  if (!weights.length) return true;
  try {
    return weights.filter((w) => w !== null && w !== undefined).every((w) => toFloat(w) <= 1);
  } catch {
    return false;
  }
}

export function resolveBodyweightSets(setsJson, bodyweight, usesBodyweight) {
  if (!isDict(setsJson)) return {};
  const weights = [...(setsJson.weights || [])];
  const reps = [...(setsJson.reps || [])];
  if (!weights.length || !reps.length) return { weights, reps };
  if (!usesBodyweight || bodyweight === null || bodyweight === undefined) return { weights, reps };
  const resolved = weights.map((w) => {
    try {
      return toFloat(bodyweight) + toFloat(w);
    } catch {
      return w;
    }
  });
  return { weights: resolved, reps };
}

function resolveLegacyBodyweightSets(log) {
  const setsJson = setsOfLog(log);
  if (!setsJson) return {};
  const weights = [...(setsJson.weights || [])];
  const reps = [...(setsJson.reps || [])];
  if (!weights.length || !reps.length) return { weights, reps };
  const bodyweight = log.bodyweight;
  if (bodyweight === null || bodyweight === undefined) return { weights, reps };
  if (hasBodyweightToken(log.exercise_string || '')) return { weights, reps };
  try {
    if (weights.filter((w) => w !== null && w !== undefined).every((w) => toFloat(w) <= 1)) {
      return { weights: weights.map(() => toFloat(bodyweight)), reps };
    }
  } catch {
    // fall through
  }
  return { weights, reps };
}

/** The sets a stored log really moved: bodyweight added for bodyweight exercises. */
export function effectiveSetsForLog(settings, log) {
  const explicit = log?.uses_bodyweight;
  if (explicit === null || explicit === undefined) {
    if (inferLogUsesBodyweight(settings, log)) return resolveLegacyBodyweightSets(log);
    return setsOfLog(log) || {};
  }
  return resolveBodyweightSets(setsOfLog(log), log.bodyweight ?? null, Boolean(explicit));
}

export function effectiveSetsForCurrent(setsJson, bodyweight, usesBodyweight) {
  return resolveBodyweightSets(setsJson, bodyweight, usesBodyweight);
}
