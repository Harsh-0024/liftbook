// Exercise renames: which name a log is saved under once an exercise was renamed, and how a
// rename rewrites names in logs, the plan and rep ranges. Ports the pure parts of
// services/exercise_rename.py. Renames are exercise_renames rows: {old_key, new_name}.
import { re, strip, rstrip, lstrip } from './py.js';
import { normalizeExerciseName, sameExercise } from './names.js';
import { TAG_RE, parseRepEntries, repEntriesToText, getWorkoutDays } from './plans.js';
import { parsePlanExerciseLine } from './parser.js';

export const MAX_NAME_LENGTH = 100;

function clean(name) {
  return strip(re('\\s+').sub(' ', String(name ?? '')));
}

function same(name, key) {
  return normalizeExerciseName(name) === key || sameExercise(name, key);
}

function splitTag(name, oldKey) {
  let current = clean(name);
  if (same(current, oldKey)) return '';
  const full = current;
  while (true) {
    const m = TAG_RE.match(current);
    if (!m) return null;
    current = strip(rstrip(m.group('base'), ' -–—'));
    if (same(current, oldKey)) return full.slice(current.length);
  }
}

/** The new name for `name` when it is the renamed exercise (or a gym-tagged version of it), else null. */
export function renamedName(name, oldKey, newName) {
  const suffix = splitTag(name, oldKey);
  return suffix === null ? null : newName + suffix;
}

/** exercise_renames rows -> {old_key: new_name}. */
export function redirectsFrom(rows = []) {
  const out = new Map();
  for (const row of rows || []) if (row && row.old_key && !row.deleted_at) out.set(row.old_key, row.new_name);
  return out;
}

/** The name to save a log under: the new name if this one (or its base) was renamed. */
export function resolveRenamedExercise(name, redirects) {
  if (!redirects || !redirects.size || !name) return name;
  let current = clean(name);
  const full = current;
  while (current) {
    let newName = redirects.get(normalizeExerciseName(current));
    if (!newName) {
      for (const [key, value] of redirects) {
        if (same(current, key)) {
          newName = value;
          break;
        }
      }
    }
    if (newName) return newName + full.slice(current.length);
    const m = TAG_RE.match(current);
    if (!m) break;
    current = strip(rstrip(m.group('base'), ' -–—'));
  }
  return name;
}

/** The logged text starts with the exercise's name; give it the new one. */
export function renameInExerciseString(text, oldName, newName) {
  const stripped = lstrip(text);
  if (oldName && stripped.toLowerCase().startsWith(oldName.toLowerCase())) {
    const rest = stripped.slice(oldName.length);
    if (!rest || !/^[\p{L}\p{N}]/u.test(rest)) return text.slice(0, text.length - stripped.length) + newName + rest;
  }
  return text;
}

/** Point parsed exercises logged under an old name at the new one (changes `parsed` in place). */
export function applyRenamesToParsed(parsed, redirects) {
  const exercises = parsed?.exercises || [];
  if (!exercises.length || !redirects || !redirects.size) return;
  for (const item of exercises) {
    const old = item.name || '';
    const renamed = resolveRenamedExercise(old, redirects);
    if (renamed !== old) {
      item.name = renamed;
      item.exercise_string = renameInExerciseString(item.exercise_string || '', old, renamed);
    }
  }
}

/** An error to show for a rename, or null. */
export function validateRename(oldName, newName) {
  oldName = clean(oldName);
  newName = clean(newName);
  if (!oldName || !normalizeExerciseName(oldName)) return 'Choose the exercise to rename.';
  if (!newName || !normalizeExerciseName(newName)) return 'Type the new name.';
  if (newName.length > MAX_NAME_LENGTH) return `Keep the name under ${MAX_NAME_LENGTH} characters.`;
  if (oldName === newName) return "That's already its name.";
  return null;
}

/** The plan text with the exercise renamed wherever it appears. */
export function renameInPlanText(text, oldKey, newName) {
  const lines = (text || '').split('\n');
  lines.forEach((raw, i) => {
    const stripped = strip(raw);
    if (!stripped) return;
    const name = parsePlanExerciseLine(stripped).name || '';
    const renamed = name ? renamedName(name, oldKey, newName) : null;
    if (renamed !== null && stripped.startsWith(name)) {
      const lead = raw.slice(0, raw.length - lstrip(raw).length);
      lines[i] = lead + renamed + stripped.slice(name.length);
    }
  });
  return lines.join('\n');
}

/** Rep ranges with the exercise renamed; a range the new name already has is kept. */
export function renameInRepText(text, oldKey, newName) {
  const order = [];
  const slots = new Map();
  for (const [name, value] of parseRepEntries(text)) {
    const renamed = renamedName(name, oldKey, newName);
    const key = normalizeExerciseName(renamed || name);
    if (!slots.has(key)) {
      order.push(key);
      slots.set(key, { name: renamed || name, own: null, moved: null });
    }
    const slot = slots.get(key);
    if (renamed !== null) {
      if (value) slot.moved = value;
    } else {
      slot.name = name;
      if (value || slot.own === null) slot.own = value;
    }
  }
  return repEntriesToText(order.map((k) => [slots.get(k).name, slots.get(k).own || slots.get(k).moved || '']));
}

/** The exercises in a plan, in order. */
export function planExerciseNames(text) {
  const names = [];
  for (const days of Object.values(getWorkoutDays(text || '').workout || {})) {
    for (const lines of Object.values(days)) {
      for (const line of lines) {
        const name = parsePlanExerciseLine(line).name || '';
        if (name) names.push(name);
      }
    }
  }
  return names;
}

export function repExerciseNames(text) {
  return parseRepEntries(text).map(([name]) => name);
}
