// Exercise names: the normalised key two spellings of one exercise share, and how a typed name
// finds the names it was logged under. Ports services/exercise_matching.py and the name keys
// used by logging, bodyweight/timed settings and stats.
import { re, strip, title, unique, sortBy } from './py.js';

const DASH_CHARS = '-‐‑‒–—−';
const APOSTROPHES = '’`´';
const TOKEN_PLURAL_EXCEPTIONS = new Set(['oh', 'ui']);

function normalizeToken(tok) {
  let t = strip(tok || '').toLowerCase();
  if (!t) return '';
  if (t === 'oh' || t === 'overhead') return 'overhead';
  if (t === 'tricep' || t === 'triceps') return 'triceps';
  if (!TOKEN_PLURAL_EXCEPTIONS.has(t) && [...t].length > 3 && t.endsWith('s') && !t.endsWith('ss')) t = t.slice(0, -1);
  if (t === 'tricep' || t === 'triceps') t = 'triceps';
  if (t === 'oh' || t === 'overhead') t = 'overhead';
  return t;
}

function collapseWs(s) {
  return re('\\s+').sub(' ', strip(s || ''));
}

/** The key an exercise name matches under: case, dashes, apostrophes and plurals evened out. */
export function normalizeExerciseName(name) {
  let s = strip(name || '');
  if (!s) return '';
  for (const ch of APOSTROPHES) s = s.replaceAll(ch, "'");
  s = s.replaceAll('_', ' ');
  for (const ch of DASH_CHARS) s = s.replaceAll(ch, ' ');
  s = collapseWs(s).toLowerCase();
  return s.split(' ').filter(Boolean).map(normalizeToken).filter(Boolean).join(' ');
}

/** Every single word used in these names. */
export function compoundVocabulary(names) {
  const out = new Set();
  for (const name of names || []) {
    for (const t of normalizeExerciseName(name).split(' ')) if (t) out.add(t);
  }
  return out;
}

/** Join two neighbouring words whose joined form is a word in `vocabulary`. */
export function joinKnownCompounds(tokens, vocabulary) {
  tokens = [...tokens];
  if (!vocabulary || !vocabulary.size || tokens.length < 2) return tokens;
  const out = [];
  let i = 0;
  while (i < tokens.length) {
    if (i + 1 < tokens.length) {
      const joined = normalizeToken(tokens[i] + tokens[i + 1]);
      if (vocabulary.has(joined)) {
        out.push(joined);
        i += 2;
        continue;
      }
    }
    out.push(tokens[i]);
    i += 1;
  }
  return out;
}

// Python sorts strings by code point; JS's default sort compares UTF-16 units.
function codePointSort(values) {
  return sortBy(values, (v) => [...v].map((c) => c.codePointAt(0)));
}

/** Order-insensitive signature: the normalised words, sorted. */
export function tokenSignature(name, vocabulary = null) {
  const norm = normalizeExerciseName(name);
  if (!norm) return [];
  const tokens = joinKnownCompounds(norm.split(' ').filter(Boolean), vocabulary);
  return codePointSort(tokens);
}

function sigKey(sig) {
  return sig.join('\u0000');
}

/** Whether two names are the same exercise. */
export function sameExercise(a, b) {
  const vocabulary = compoundVocabulary([a, b]);
  const signature = tokenSignature(a, vocabulary);
  return signature.length > 0 && sigKey(signature) === sigKey(tokenSignature(b, vocabulary));
}

/** {by_norm, by_sig, names} for a list of logged names. */
export function buildNameIndex(names) {
  const byNorm = new Map();
  const bySig = new Map();
  const seen = [];
  for (const raw of names || []) {
    if (!raw) continue;
    seen.push(raw);
    const norm = normalizeExerciseName(raw);
    const sig = tokenSignature(raw);
    if (norm) {
      if (!byNorm.has(norm)) byNorm.set(norm, []);
      if (!byNorm.get(norm).includes(raw)) byNorm.get(norm).push(raw);
    }
    if (sig.length) {
      const k = sigKey(sig);
      if (!bySig.has(k)) bySig.set(k, []);
      if (!bySig.get(k).includes(raw)) bySig.get(k).push(raw);
    }
  }
  return { by_norm: byNorm, by_sig: bySig, names: unique(seen) };
}

/** The stored names a typed name stands for ([] when none, or when it is ambiguous). */
export function resolveEquivalentNames(inputName, index) {
  if (!inputName || !index) return [];
  const byNorm = index.by_norm || new Map();
  const bySig = index.by_sig || new Map();
  const sig = tokenSignature(inputName);
  const signatureMatches = sig.length ? [...(bySig.get(sigKey(sig)) || [])] : [];

  const norm = normalizeExerciseName(inputName);
  if (norm && byNorm.has(norm)) {
    const matches = [...byNorm.get(norm)];
    for (const match of signatureMatches) if (!matches.includes(match)) matches.push(match);
    return matches;
  }

  if (signatureMatches.length) {
    if (signatureMatches.length === 1) return [signatureMatches[0]];
    const normalized = new Set(signatureMatches.map(normalizeExerciseName).filter(Boolean));
    if (normalized.size === 1) return signatureMatches;
  }

  const joinedMatches = (index.names || []).filter((n) => sameExercise(inputName, n));
  if (joinedMatches.length) {
    const vocabulary = compoundVocabulary([inputName, ...joinedMatches]);
    const orders = new Set(joinedMatches.map((n) => joinKnownCompounds(normalizeExerciseName(n).split(' '), vocabulary).join(' ')));
    if (joinedMatches.length === 1 || orders.size === 1) return joinedMatches;
  }
  return [];
}

/** The spellings tried when no index matches (services.logging._exercise_candidates). */
export function exerciseCandidates(exerciseName) {
  if (!exerciseName) return [];
  const name = strip(exerciseName);
  return unique([
    name,
    title(name),
    name.replaceAll("'", '’'),
    title(name.replaceAll("'", '’')),
    name.replaceAll('’', "'"),
    title(name.replaceAll('’', "'")),
    name.replaceAll('-', '–'),
    name.replaceAll('–', '-'),
    name.replaceAll('-', ' '),
    name.replaceAll('–', ' '),
  ]);
}

/** Names to look up: matched through the index, else the candidate spellings. */
export function namesFor(exerciseName, index) {
  const viaIndex = index ? resolveEquivalentNames(exerciseName, index) : [];
  return viaIndex.length ? viaIndex : exerciseCandidates(exerciseName);
}

/** The key exercise_settings rows use (bodyweight and timed choices): normalised, no apostrophes. */
export function exerciseKey(exerciseName) {
  return strip(normalizeExerciseName(exerciseName || '').replaceAll("'", ''));
}

// --- Stats grouping (services/stats.py) ---

export function cleanExerciseText(exercise) {
  let value = strip(String(exercise ?? '')).toLowerCase();
  value = re('^\\s*\\d+\\s*[\\.)\\-:]\\s*').sub('', value);
  value = re('[-–—]+').sub(' ', value);
  value = re('[^a-z0-9\\s]+').sub(' ', value);
  return strip(re('\\s+').sub(' ', value));
}

/** The words in a user's exercise names, so "Push Down" groups with a logged "Pushdown". */
export function statsVocabulary(names) {
  return compoundVocabulary([...(names || [])].map(cleanExerciseText));
}

/** The key the Stats page groups an exercise under. */
export function statsExerciseKey(exercise, vocabulary = null) {
  const value = cleanExerciseText(exercise);
  const signature = tokenSignature(value, vocabulary);
  return signature.length ? signature.join(' ') : value;
}
