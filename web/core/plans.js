// The plan text (days and their exercises) and the rep-range text ("Bench Press: 3, 6–10"), and
// the set counts and ranges read from them. Ports list_of_exercise.get_workout_days,
// services/rep_ranges.py and the plan/rep readers in services/logging.py, retrieve.py, stats.py.
import { re, strip, rstrip, split1, rsplit1, splitlines, title, toInt, compareKeys } from './py.js';
import { DEFAULT_PLAN, DEFAULT_REP_RANGES, PREVIOUS_DEFAULT_PLANS } from './defaults.js';
import { normalizeExerciseName } from './names.js';
import { parsePlanExerciseLine, extractSetsFromBracket, extractDeclaredSets, titleCase } from './parser.js';

// --- Plan text ---

function normPlanLine(s) {
  s = String(s ?? '');
  s = s.replaceAll('•', ' ').replaceAll('–', '-').replaceAll('—', '-').replaceAll('’', "'");
  return strip(re('\\s+').sub(' ', s));
}

function parseHeader(line) {
  line = normPlanLine(line);
  if (!line) return null;
  let m = re('^session\\s+(\\d+)\\s*[-:]\\s*(.+)$', 'i').match(line);
  if (m) {
    const dayId = toInt(m.group(1));
    return { category: 'Session', day_id: dayId, day_name: `Session ${dayId}`, session_title: normPlanLine(m.group(2)) };
  }
  m = re('^session\\s+(\\d+)\\s*$', 'i').match(line);
  if (m) {
    const dayId = toInt(m.group(1));
    return { category: 'Session', day_id: dayId, day_name: `Session ${dayId}`, session_title: '' };
  }
  m = re('^(.+?)\\s+(\\d+)$').match(line);
  if (m) {
    const dayId = toInt(m.group(2));
    const category = normPlanLine(m.group(1));
    return { category, day_id: dayId, day_name: `${category} ${dayId}`, session_title: null };
  }
  return null;
}

/**
 * Plan text -> {workout: {category: {dayName: [exercise lines]}}, session_titles?, headings?,
 * heading_sessions?}. Objects keep the plan's order (category and day names are never plain
 * numbers, so JavaScript keeps their insertion order).
 */
export function getWorkoutDays(rawText) {
  const workoutDays = { workout: {} };
  let currentHeader = null;
  let currentExercises = [];
  let currentHeading = null;
  const headings = [];
  const headingSessions = {};

  const flush = () => {
    if (!currentHeader) return;
    const cat = currentHeader.category;
    const dayName = currentHeader.day_name;
    if (!cat || !dayName) {
      currentHeader = null;
      currentExercises = [];
      return;
    }
    (workoutDays.workout[cat] ??= {})[dayName] = [...currentExercises];
    if (cat === 'Session') {
      const titles = (workoutDays.session_titles ??= {});
      if (Number.isInteger(currentHeader.day_id) && currentHeader.session_title) {
        titles[String(currentHeader.day_id)] = String(currentHeader.session_title);
      }
    }
    currentHeader = null;
    currentExercises = [];
  };

  for (const rawLine of String(rawText ?? '').split('\n')) {
    const line = normPlanLine(rawLine);
    if (!line) continue;
    const m = re('^(cycle|heading)\\s+(\\d+)\\s*$', 'i').match(line);
    if (m) {
      flush();
      const prefix = title(strip(String(m.group(1) || '')));
      currentHeading = `${prefix} ${toInt(m.group(2))}`;
      if (!headings.includes(currentHeading)) headings.push(currentHeading);
      headingSessions[currentHeading] ??= [];
      continue;
    }
    const header = parseHeader(line);
    if (header) {
      flush();
      currentHeader = header;
      currentExercises = [];
      if (currentHeading && header.category === 'Session' && Number.isInteger(header.day_id)) {
        const list = (headingSessions[currentHeading] ??= []);
        if (!list.includes(header.day_id)) list.push(header.day_id);
      }
      continue;
    }
    if (currentHeader) currentExercises.push(line);
  }
  flush();
  if (headings.length) {
    workoutDays.headings = [...headings];
    workoutDays.heading_sessions = { ...headingSessions };
  }
  return workoutDays;
}

function normalizeText(text) {
  return splitlines(strip(text || '')).map((l) => rstrip(l)).join('\n');
}

/** An account's own plan, or "" when it has none (an untouched copy of an old built-in plan counts as none). */
export function ownPlanText(text) {
  text = text || '';
  if (!strip(text)) return '';
  const previous = new Set(PREVIOUS_DEFAULT_PLANS.map(normalizeText));
  return previous.has(normalizeText(text)) ? '' : text;
}

/** The built-in rep ranges as text, one "Exercise: range" per line. */
export function defaultRepRangesText() {
  return Object.entries(DEFAULT_REP_RANGES).map(([ex, rng]) => `${ex}: ${rng}`).join('\n');
}

/**
 * The plan a person trains from: the plan owner's when following it (and not the owner),
 * otherwise their own; the built-in plan when that is empty.
 */
export function effectivePlanText({ ownPlan = '', followOwner = false, isOwner = false, ownerPlan = '' } = {}) {
  if (followOwner && !isOwner) return ownPlanText(ownerPlan) || DEFAULT_PLAN || '';
  return ownPlanText(ownPlan) || DEFAULT_PLAN || '';
}

/** Same for rep ranges. */
export function effectiveRepRangesText({ ownRepRanges = '', followOwner = false, isOwner = false, ownerRepRanges = '' } = {}) {
  const own = (t) => (t && strip(t) ? t : '');
  if (followOwner && !isOwner) return own(ownerRepRanges) || defaultRepRangesText();
  return own(ownRepRanges) || defaultRepRangesText();
}

// --- Rep-range text (services/rep_ranges.py) ---

const VALUE = '(?:(?P<sets>\\d+)\\s*(?:,|x|×|\\*)\\s*)?'
  + '(?P<lo>\\d+)(?:\\s*(?:-|–|—|to)\\s*(?P<hi>\\d+))?'
  + '\\s*(?P<unit>s|secs?|seconds)?';
const VALUE_RE = re(`^\\s*${VALUE}\\s*$`, 'i');
// [^\W\d_] in Python: a letter (or a number that isn't a digit, like "²").
const TRAILING_VALUE_RE = re(`^(?P<name>.*?[\\p{L}\\p{Nl}\\p{No}].*?)\\s+(?P<value>${VALUE})\\s*$`, 'i');
const NO_RANGE_WORDS = new Set(['blank', 'empty', 'none', 'nil', 'null', 'na', 'n/a', 'tbd', 'tba', '?', '-', '–', '—']);

/** True for an empty range, or a word standing in for one ("(blank)", "n/a", "-"). */
export function isNoRange(value) {
  const text = strip(strip(re('\\s+').sub(' ', strip(value || '')), '()[]<>{}')).toLowerCase();
  return !text || NO_RANGE_WORDS.has(text);
}

/** "6 - 10" -> "6–10", "3,6-8" -> "3, 6–8", "10-6" -> "6–10", "30-60 sec" -> "30–60s". */
export function formatRepValue(value) {
  if (isNoRange(value)) return '';
  const text = re('\\s+').sub(' ', strip(value || ''));
  const m = VALUE_RE.match(text);
  if (!m) return text;
  let lo = toInt(m.group('lo'));
  let hi = toInt(m.group('hi') || m.group('lo'));
  [lo, hi] = [Math.min(lo, hi), Math.max(lo, hi)];
  let reps = hi !== lo ? `${lo}–${hi}` : `${lo}`;
  if (m.group('unit')) reps += 's';
  return m.group('sets') ? `${toInt(m.group('sets'))}, ${reps}` : reps;
}

function cleanName(name) {
  return titleCase(strip(re('\\s+').sub(' ', strip(name || '')), ' :=-–—\t'));
}

/** Rep ranges however they are written -> [[name, value]] in order ("" for a name with no range). */
export function parseRepEntries(text) {
  const entries = [];
  let pending = null;
  const flush = () => {
    if (pending) entries.push([pending, '']);
    pending = null;
  };
  for (const raw of splitlines(text || '')) {
    const line = strip(raw);
    if (!line || line.startsWith('#')) continue;
    let name = null;
    let value = null;
    for (const sep of [':', '=', '\t']) {
      if (line.includes(sep)) {
        [name, value] = sep !== '\t' ? split1(line, sep) : rsplit1(line, sep);
        break;
      }
    }
    if (name === null) {
      if (VALUE_RE.match(line)) {
        if (pending) {
          entries.push([pending, formatRepValue(line)]);
          pending = null;
        }
        continue;
      }
      const m = TRAILING_VALUE_RE.match(line);
      if (m) {
        name = m.group('name');
        value = m.group('value');
      }
    }
    flush();
    if (name === null) {
      pending = cleanName(line) || null;
      continue;
    }
    name = cleanName(name);
    if (!name) continue;
    value = formatRepValue(value);
    if (value) entries.push([name, value]);
    else pending = name;
  }
  flush();
  return entries;
}

/** One line per exercise: first place and spelling kept, last range given wins. */
export function mergeRepEntries(entries) {
  const order = [];
  const merged = new Map();
  for (const [name, value] of entries) {
    const key = normalizeExerciseName(name);
    if (!key) continue;
    if (!merged.has(key)) {
      order.push(key);
      merged.set(key, [name, value || '']);
    } else if (value) {
      merged.set(key, [merged.get(key)[0], value]);
    }
  }
  return order.map((k) => merged.get(k));
}

// A gym or machine tag at the end of a name: "Preacher Curl (Wellness)".
export const TAG_RE = re('^(?P<base>.*?\\S)[\\s\\-–—]*\\([^()]*\\)\\s*$');

/** Where to look for an exercise's rep range: the name, then without its bracket tags. */
export function repRangeNames(name) {
  const names = [];
  let current = strip(re('\\s+').sub(' ', name || ''));
  while (current) {
    names.push(current);
    const m = TAG_RE.match(current);
    if (!m) break;
    current = strip(rstrip(m.group('base'), ' -–—'));
  }
  return names;
}

/** [range, set count] for an exercise from parsed ranges, falling back from a tagged name to its base. */
export function lookupRepTarget(name, ranges, sets) {
  for (const candidate of repRangeNames(name)) {
    for (const key of [candidate.toLowerCase(), normalizeExerciseName(candidate)]) {
      const repRange = ranges[key] || '';
      const setCount = sets[key] ?? null;
      if (repRange || setCount) return [repRange, setCount];
    }
  }
  return ['', null];
}

export function repEntriesToText(entries) {
  return entries.map(([name, value]) => rstrip(`${name}: ${value}`)).join('\n');
}

/** Whatever was typed, stored the same clean way. */
export function canonicalRepText(text) {
  return repEntriesToText(mergeRepEntries(parseRepEntries(text)));
}

/**
 * Rep-range text -> [ranges, setCounts], each keyed by the lower-case and the normalised name
 * (services.retrieve._parse_rep_ranges_text). Objects without a prototype, so any name is a safe key.
 */
export function parseRepRangesText(repText) {
  const ranges = Object.create(null);
  const sets = Object.create(null);
  for (const line of (repText || '').split('\n')) {
    if (!line.includes(':')) continue;
    const [k, v] = split1(line, ':');
    const raw = strip(k);
    const key = raw.toLowerCase();
    const norm = normalizeExerciseName(raw);
    const value = isNoRange(v) ? '' : strip(v);
    const m = re('^(\\d+)\\s*,\\s*(.+)$').match(value);
    if (m) {
      const setCount = toInt(m.group(1));
      const rangeValue = strip(m.group(2));
      sets[key] = setCount;
      ranges[key] = rangeValue;
      if (norm) {
        sets[norm] = setCount;
        ranges[norm] = rangeValue;
      }
    } else {
      ranges[key] = value;
      if (norm) ranges[norm] = value;
    }
  }
  return [ranges, sets];
}

/** "Exercise: 2, 8-15" lines -> {normalised name: set count} (services.logging._parse_rep_target_sets). */
export function parseRepTargetSets(repText) {
  const out = Object.create(null);
  if (!repText) return out;
  for (const raw of splitlines(repText)) {
    const line = strip(raw || '');
    if (!line || !line.includes(':')) continue;
    const [name, valueRaw] = split1(line, ':');
    const key = normalizeExerciseName(name || '');
    if (!key) continue;
    const m = re('^(\\d+)\\s*,').match(strip(valueRaw || ''));
    if (!m) continue;
    const n = toInt(m.group(1));
    if (n > 0) out[key] = n;
  }
  return out;
}

/** {normalised name: the set count the plan writes most often for it} (ties: the larger count). */
export function parsePlanTargetSets(planText) {
  const counters = new Map();
  let workoutMap = {};
  try {
    workoutMap = getWorkoutDays(planText || '').workout || {};
  } catch {
    workoutMap = {};
  }
  for (const days of Object.values(workoutMap)) {
    for (const exercises of Object.values(days)) {
      for (const rawExercise of exercises) {
        const line = strip(String(rawExercise ?? ''));
        if (!line) continue;
        if (extractSetsFromBracket(line) === null) continue;
        const parsed = parsePlanExerciseLine(line);
        const key = normalizeExerciseName(parsed.name || '');
        if (!key || !parsed.declared_sets) continue;
        if (!counters.has(key)) counters.set(key, new Map());
        const counter = counters.get(key);
        counter.set(parsed.declared_sets, (counter.get(parsed.declared_sets) || 0) + 1);
      }
    }
  }
  const resolved = Object.create(null);
  for (const [key, counter] of counters) {
    let best = null;
    for (const [count, times] of counter) {
      if (best === null || compareKeys([times, count], [best[1], best[0]]) > 0) best = [count, times];
    }
    if (best && best[0] > 0) resolved[key] = best[0];
  }
  return resolved;
}

/** "Exercise: 6-10" lines -> {lower-case name: [lo, hi]} (services.stats._build_rep_range_map). */
export function buildRepRangeMap(repText) {
  const mapping = Object.create(null);
  for (const line of splitlines(repText || '')) {
    if (!line.includes(':')) continue;
    const [k, v] = split1(line, ':');
    const key = strip(k || '').toLowerCase();
    let value = strip(v || '');
    if (!key || !value) continue;
    if (value.includes(',')) value = strip(split1(value, ',')[1]);
    const nums = re('\\d+').findall(value);
    if (nums.length >= 2) mapping[key] = [toInt(nums[0]), toInt(nums[1])];
    else if (nums.length === 1) mapping[key] = [toInt(nums[0]), toInt(nums[0])];
  }
  return mapping;
}

/** [lo, hi] from a range like "6–10" (the first two numbers), or null. */
export function parseRepRange(value) {
  if (!value) return null;
  const nums = re('\\d+').findall(String(value));
  if (nums.length >= 2) return [toInt(nums[0]), toInt(nums[1])];
  if (nums.length === 1) return [toInt(nums[0]), toInt(nums[0])];
  return null;
}

/** A set count written into an exercise's own text ("[3]", "[3, 6-8]", "3 sets"), or null. */
export function extractExplicitTargetSets(exerciseString) {
  const text = strip(String(exerciseString ?? ''));
  if (!text) return null;
  for (const rawLine of splitlines(text)) {
    const line = strip(rawLine || '');
    if (!line) continue;
    const bracketSets = extractSetsFromBracket(line);
    if (Number.isInteger(bracketSets) && bracketSets > 0) return bracketSets;
    const [declared] = extractDeclaredSets(line);
    if (Number.isInteger(declared) && declared > 0) return declared;
  }
  return null;
}

/**
 * [target set count, strict] for comparing an exercise: its own text first, then the rep-range
 * set count (a tagged name takes its base's), then the plan, then what was logged when over 3.
 */
export function resolveTargetSets({ exerciseName, exerciseString, repTargetSets = null, planTargetSets = null, inferredSetCount = 0, defaultSets = 3 }) {
  const explicit = extractExplicitTargetSets(exerciseString);
  const inferred = Number.isInteger(inferredSetCount) ? inferredSetCount : 0;
  if (Number.isInteger(explicit) && explicit > 0) return [Math.max(explicit, inferred), true];
  const key = normalizeExerciseName(exerciseName || '');
  if (key && repTargetSets && Object.keys(repTargetSets).length) {
    for (const name of repRangeNames(exerciseName)) {
      const mapped = repTargetSets[normalizeExerciseName(name)];
      if (Number.isInteger(mapped) && mapped > 0) return [mapped, true];
    }
  }
  if (key && planTargetSets && Object.keys(planTargetSets).length) {
    const mapped = planTargetSets[key];
    if (Number.isInteger(mapped) && mapped > 0) return [mapped, true];
  }
  const defaultN = Number.isInteger(defaultSets) && defaultSets > 0 ? defaultSets : 3;
  return inferred > defaultN ? [inferred, false] : [defaultN, false];
}

export { DEFAULT_PLAN, DEFAULT_REP_RANGES };
