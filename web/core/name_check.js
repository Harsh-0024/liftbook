// Is a typed exercise name one you've used, and if not, did you mean one you have? As the old
// Log check did it (services/log_check.py: _KnownNames and the exercise states).

import { normalizeExerciseName, buildNameIndex, resolveEquivalentNames } from './names.js';
import { getCloseMatches, changedChars } from './coach_tools.js';

/** Lower-case letters and digits only, for typo distance (no plural stripping). */
const plain = (name) => String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

export class KnownNames {
  /** logged: every logged exercise name, one per log; planNames: the names in your plan. */
  constructor(logged, planNames = []) {
    const counts = new Map();
    for (const n of logged) if (n && n !== 'Unknown Exercise') counts.set(n, (counts.get(n) || 0) + 1);
    this.historyIndex = buildNameIndex([...counts.keys()]);
    this.planNorms = new Set(planNames.map(normalizeExerciseName).filter(Boolean));
    // Suggestion candidates: the most-logged spelling wins for each plain name.
    this.candidates = new Map();
    for (const n of [...counts.keys()].sort((a, b) => counts.get(a) - counts.get(b))) {
      const k = plain(n);
      if (k) this.candidates.set(k, n);
    }
    for (const n of planNames) {
      const k = plain(n);
      if (k && !this.candidates.has(k)) this.candidates.set(k, n);
    }
  }

  isKnown(name) {
    return resolveEquivalentNames(name, this.historyIndex).length > 0 || this.planNorms.has(normalizeExerciseName(name));
  }

  suggestion(name) {
    // "A1 Back Squat": a superset label in front of a name you know.
    const labelled = /^[A-Ha-h][1-9]\s+(\S.*)$/.exec(name || '');
    if (labelled && this.isKnown(labelled[1])) return this.candidates.get(plain(labelled[1])) || labelled[1];
    const key = plain(name);
    if (!key) return null;
    let best = null;
    let bestChanges = null;
    for (const c of getCloseMatches(key, [...this.candidates.keys()], 3, 0.8)) {
      const changes = changedChars(key, c);
      if (changes <= Math.max(2, Math.floor(key.length / 7)) && (bestChanges === null || changes < bestChanges)) {
        best = c;
        bestChanges = changes;
      }
    }
    return best ? this.candidates.get(best) : null;
  }
}

/**
 * A note for each readable exercise: {state, note, suggestion?, fixLine?}. States: 'twice' (also
 * earlier in the text), 'dup' (already in that day's workout), 'suggest' (new, but close to a name
 * you know), 'new', or 'ok'. lines are the text's lines, for the fixed line.
 */
export function nameNotes(exercises, known, { lines = [], dayNames = null } = {}) {
  const firstAt = new Map();
  let number = 0;
  return exercises.map((e) => {
    if (e.valid === false || e.missing_name) return null;
    number += 1;
    const name = e.name || '';
    const key = normalizeExerciseName(name) || name.toLowerCase();
    if (!firstAt.has(key)) firstAt.set(key, number);
    if (dayNames && dayNames.has(normalizeExerciseName(name))) return { state: 'dup', note: 'Already in that day’s workout' };
    if (firstAt.get(key) !== number) return { state: 'twice', note: `Also at no. ${firstAt.get(key)}: saved as a second entry` };
    if (known.isKnown(name)) return { state: 'ok' };
    const suggestion = known.suggestion(name);
    if (!suggestion) return { state: 'new', note: 'New exercise' };
    const raw = lines[(e.line || 0) - 1] ?? '';
    const source = e.source_name || '';
    const fixLine = source && raw.includes(source) ? raw.replace(source, () => suggestion) : null;
    return { state: 'suggest', note: `New name. Did you mean ${suggestion}?`, suggestion, fixLine };
  });
}
