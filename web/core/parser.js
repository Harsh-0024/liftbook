// The workout text parser: the text people type to log a workout, as structured data.
// A line-for-line port of parsers/workout.py; the golden tests check it gives the same results.
import { re, split, strip, lstrip, rstrip, split1, splitlines, toInt, toFloat, isSpace } from './py.js';
import { unescapeHtml } from './html.js';
import { parseDate, makeDate, isValidDate, formatDateTime } from './dates.js';

export function normalize(values) {
  return values && values.length ? [...values] : [];
}

function repeat(value, n) {
  return Array.from({ length: Math.max(0, n) }, () => value);
}

export function alignSets(weights, reps, targetSets = null) {
  weights = weights || [];
  reps = reps || [];
  if (!weights.length && !reps.length) return [[], []];

  const expandShorthand = (values, desired) => {
    if (!values.length) return [];
    if (desired <= 0) return [...values];
    if (values.length === 1) return repeat(values[0], desired);
    if (values.length === 2 && values.length < desired) return [values[0], ...repeat(values[1], desired - 1)];
    if (values.length < desired) return [...values, ...repeat(values[values.length - 1], desired - values.length)];
    return values;
  };

  if (!reps.length && weights.length) reps = repeat(1, weights.length);
  if (!weights.length && reps.length) weights = repeat(1.0, reps.length);

  let desired = Number.isInteger(targetSets) && targetSets > 0 ? targetSets : 3;
  desired = Math.max(desired, weights.length, reps.length);

  weights = expandShorthand(weights, desired);
  reps = expandShorthand(reps, desired);

  if (weights.length === 1 && reps.length > 1) weights = repeat(weights[0], reps.length);
  else if (reps.length === 1 && weights.length > 1) reps = repeat(reps[0], weights.length);
  else if (weights.length < reps.length && weights.length) weights = [...weights, ...repeat(weights[weights.length - 1], reps.length - weights.length)];
  else if (reps.length < weights.length && reps.length) reps = [...reps, ...repeat(reps[reps.length - 1], weights.length - reps.length)];

  reps = reps.map((r) => toInt(r));
  return [weights, reps];
}

export function extractDeclaredSets(line) {
  if (!line) return [null, line];
  const m = re('(?:\\s*[-–—:]\\s*)?(\\d+)\\s*sets?\\s*$', 'i').search(line);
  if (!m) return [null, line];
  const count = toInt(m.group(1));
  if (count <= 0) return [null, line];
  let cleaned = rstrip(line.slice(0, m.start));
  cleaned = rstrip(re('[-–—:]\\s*$').sub('', cleaned));
  return [count, cleaned];
}

function bracketInside(line) {
  return split1(split1(line, '[')[1], ']')[0];
}

export function extractSetsFromBracket(line) {
  if (!line || !line.includes('[') || !line.includes(']')) return null;
  const inside = strip(bracketInside(line));
  if (!inside) return null;
  const first = strip(split1(inside, ',')[0]);
  if (!re('^\\d+$').match(first)) return null;
  const count = toInt(first);
  return count > 0 ? count : null;
}

/** Plan lines: "Exercise", "Exercise - [n]", "Exercise - [a-b]", "Exercise - [n, a-b]", "Exercise [n]". */
export function parsePlanExerciseLine(rawLine) {
  const line = strip(String(rawLine ?? ''));
  let name = line;
  let declaredSets = null;
  let inlineRange = null;

  let inside = null;
  if (line.includes(' - [') && line.includes(']')) {
    name = strip(split1(line, ' - [')[0]);
    inside = strip(bracketInside(line));
  } else {
    const m = re('^(.*?\\S)\\s*(?:[-–—:]\\s*)?\\[\\s*(\\d[^\\[\\]]*)\\]\\s*$').match(line);
    if (m) {
      name = strip(m.group(1));
      inside = strip(m.group(2));
    }
  }

  if (inside) {
    const firstToken = strip(split1(inside, ',')[0]);
    if (re('^\\d+$').match(firstToken)) {
      declaredSets = toInt(firstToken);
      const remainder = inside.includes(',') ? strip(split1(inside, ',')[1]) : '';
      if (remainder) inlineRange = remainder;
    } else {
      inlineRange = inside;
    }
  }

  if (!declaredSets) {
    const bracketSets = extractSetsFromBracket(line);
    if (Number.isInteger(bracketSets) && bracketSets > 0) declaredSets = bracketSets;
  }

  const [explicitSets, cleaned] = extractDeclaredSets(name);
  if (Number.isInteger(explicitSets) && explicitSets > 0) {
    declaredSets = explicitSets;
    name = cleaned;
  }

  return {
    name: strip(name),
    declared_sets: Number.isInteger(declaredSets) && declaredSets > 0 ? declaredSets : null,
    inline_range: strip(inlineRange || '') || null,
  };
}

function hasTimeRangeHint(line) {
  if (!line || !line.includes('[') || !line.includes(']')) return false;
  return strip(bracketInside(line)).toLowerCase().includes('s');
}

export function parseBodyweightLine(line) {
  line = strip(line || '');
  if (!line) return [null, null];
  const m = re('^(?:body\\s*weight|bodyweight)\\s*[-:]\\s*(\\d+(?:\\.\\d+)?)\\s*(kg|kgs|lb|lbs)?\\s*$', 'i').match(line);
  if (!m) return [null, null];
  const value = toFloat(m.group(1));
  let unit = (m.group(2) || '').toLowerCase();
  if (unit === 'kgs') unit = 'kg';
  if (unit === 'lb') unit = 'lbs';
  return [value, unit || null];
}

const UNITS = re('(kg|lbs|lb)');

export function parseWeightXReps(segment, baseWeight = null) {
  segment = dropSecondsSuffix(segment).replaceAll('×', 'x').replaceAll('*', 'x').toLowerCase();
  segment = re('\\bbody\\s*weight\\b').sub('bw', segment);
  segment = UNITS.sub('', segment);
  const bareReps = setsWithBareReps(segment, baseWeight);
  if (bareReps) return bareReps;
  const matches = re('(?:(bw(?:/\\d+(?:\\.\\d+)?)?(?:[+-]\\d+(?:\\.\\d+)?)?|-?\\d+(?:\\.\\d+)?)\\s*)?x\\s*(\\d+)').findall(segment);
  if (!matches.length) return [null, null];

  const weights = [];
  const reps = [];
  let lastWeight = null;
  for (const [w, r] of matches) {
    if (w) {
      const bwWeight = parseBwWeight(w, baseWeight);
      lastWeight = bwWeight !== null ? bwWeight : toFloat(w);
    }
    if (lastWeight === null) return [null, null];
    weights.push(lastWeight);
    reps.push(toInt(r));
  }
  return [weights, reps];
}

// A number as people write one. float() also takes "nan", "inf", "1e5" and other scripts' digits.
const PLAIN_NUMBER = re('^[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)$');

class NotANumber extends Error {}

function plainFloat(token) {
  if (!PLAIN_NUMBER.match(token || '')) throw new NotANumber(token);
  return toFloat(token);
}

function tryPlainFloat(token) {
  return PLAIN_NUMBER.match(token || '') ? toFloat(token) : null;
}

const SECONDS_SUFFIX = re('(\\d)\\s*(?:seconds?|secs?|s)\\b', 'i');

function dropSecondsSuffix(segment) {
  return SECONDS_SUFFIX.sub('\\1', segment || '');
}

export function extractNumbers(segment) {
  segment = dropSecondsSuffix(segment);
  segment = UNITS.sub('', segment.toLowerCase());
  segment = segment.replaceAll(',', ' ');
  const numbers = [];
  for (const t of split(segment)) {
    const v = tryPlainFloat(t);
    if (v !== null) numbers.push(v);
  }
  return numbers;
}

export function parseBwWeight(token, baseWeight = null) {
  token = strip(token).toLowerCase();
  token = re('^body\\s*weight').sub('bw', token);
  token = re('^bodyweight').sub('bw', token);
  if (!token.startsWith('bw')) return null;
  token = token.replace('bw', '');
  token = strip(UNITS.sub('', token));
  const base = baseWeight !== null && baseWeight !== undefined ? baseWeight : 0.0;

  let divisor = 1.0;
  if (token.startsWith('/')) {
    const m = re('^/(\\d+(?:\\.\\d+)?)(.*)$').match(token);
    if (m) {
      divisor = toFloat(m.group(1));
      token = strip(m.group(2) || '');
    }
  }
  if (divisor === 0) divisor = 1.0;

  const effectiveBase = base / divisor;
  if (token === '' || token === '+' || token === '-') return effectiveBase;

  const adjustment = tryPlainFloat(token);
  if (adjustment === null) return effectiveBase;

  if (token.startsWith('+') || token.startsWith('-')) return effectiveBase + adjustment;
  return baseWeight !== null && baseWeight !== undefined ? effectiveBase + adjustment : adjustment;
}

export function extractWeights(segment, baseWeight = null) {
  segment = UNITS.sub('', segment.toLowerCase());
  segment = re('\\bbody\\s*weight\\b').sub('bw', segment);
  segment = segment.replaceAll(',', ' ');
  const numbers = [];
  for (const t of split(segment)) {
    const bw = parseBwWeight(t, baseWeight);
    if (bw !== null) {
      numbers.push(bw);
      continue;
    }
    const v = tryPlainFloat(t);
    if (v !== null) numbers.push(v);
  }
  return numbers;
}

export const SET_WORD = re('^(?:x\\d*|kgs?|lbs?|bw\\S*|at|@|for|secs?|seconds?)[,;:]?$', 'i');
const NAME_NUMBER_WORDS = '(?:arms?|legs?|hands?|handed|degrees?|deg|ways?|point|count|inch(?:es)?)\\b';

/** Drop a list number in front of a name ("1. Squat", "2) Row", "3 - Curl", "4 Dips"). */
export function stripListNumber(line) {
  line = strip(line || '');
  line = re('^[A-Ha-h][1-9]\\s*(?:[.):]|\\s[-–—])\\s*(?=[A-Za-z])').sub('', line);
  let stripped = re('^\\d+\\s*[.)]\\s*').sub('', line);
  if (stripped === line) stripped = re('^\\d+\\s*[:\\-–—]\\s+').sub('', line);
  if (stripped === line) stripped = re(`^\\d+\\s+(?!${NAME_NUMBER_WORDS})(?=[A-Za-z])`, 'i').sub('', line);
  return stripped;
}

const WEIGHT = '(?:bw(?:/\\d+(?:\\.\\d+)?)?(?:[+-]\\d+(?:\\.\\d+)?)?|-?\\d+(?:\\.\\d+)?)';
const SETS_LINE = re(`^(?:\\s*(?:${WEIGHT})?\\s*x\\s*\\d+\\s*[,;]?)+\\s*$`);
const SETS_AT_WEIGHT = re(`^(\\d+)\\s*x\\s*(\\d+)\\s*(?:@|\\bat\\b)\\s*(${WEIGHT})$`);
const SETS_THEN_WEIGHT = re(`^(\\d+)\\s*x\\s*(\\d+)\\s+(${WEIGHT})$`);
const WEIGHT_THEN_SETS = re(`^(${WEIGHT})\\s+(\\d+)\\s*x\\s*(\\d+)$`);
const THREE_NUMBERS = re(`^(${WEIGHT})\\s*x\\s*(\\d+)\\s*x\\s*(${WEIGHT})$`);
const ONE_SET = re(`^(${WEIGHT})?\\s*x\\s*(\\d+)$`);
const MOST_SETS = 10;

const SETS_OF = re('\\b(\\d+)\\s*sets?\\s*(?:of|x|×)\\s*(\\d+)(?:\\s*reps?\\b)?(?=\\s*(?:@|at\\b|\\d|bw|body))', 'i');

function setsOf(text) {
  return SETS_OF.sub('\\1x\\2', text || '');
}

function setText(line) {
  let text = setsOf(line).toLowerCase().replaceAll('×', 'x').replaceAll('*', 'x');
  text = re('\\bbody\\s*weight\\b').sub('bw', text);
  return re('\\s*(?:kgs?|lbs?)\\b').sub('', text);
}

export function isSetsLine(line) {
  return Boolean(SETS_LINE.match(setText(line)));
}

const SECONDS_WORD = '(?:seconds?|secs?|s)';
export const TIME_TOKEN = re(`\\b\\d+:[0-5]\\d\\b|\\b\\d+(?:\\.\\d+)?\\s*${SECONDS_WORD}\\b`, 'i');
const SETS_OF_SECONDS = re(`^(\\d+)\\s*x\\s*(\\d+)\\s*${SECONDS_WORD}$`, 'i');
const SECONDS_TIMES_SETS = re(`^(\\d+)\\s*${SECONDS_WORD}\\s*x\\s*(\\d+)$`, 'i');

function tokenSeconds(token) {
  token = strip(token).toLowerCase();
  if (token.includes(':')) {
    const [minutes, seconds] = split1(token, ':');
    return toInt(minutes) * 60 + toInt(seconds);
  }
  return pyRoundInt(toFloat(re('\\d+(?:\\.\\d+)?').match(token).group(0)));
}

// round() to a whole number, halves to even.
function pyRoundInt(x) {
  const f = Math.floor(x);
  const d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

/** Sets written only as times: (count or null, seconds per set), else null. */
export function parseTimeSets(segment) {
  const text = strip(segment || '').toLowerCase().replaceAll('×', 'x').replaceAll('*', 'x');
  if (!text) return null;
  for (const [pattern, setsAt, secondsAt] of [[SETS_OF_SECONDS, 1, 2], [SECONDS_TIMES_SETS, 2, 1]]) {
    const m = pattern.match(text);
    if (m) {
      const sets = toInt(m.group(setsAt));
      const seconds = toInt(m.group(secondsAt));
      if (sets > 0 && sets <= MOST_SETS && seconds > 0) return [sets, repeat(seconds, sets)];
      return null;
    }
  }
  const times = TIME_TOKEN.findall(text);
  if (!times.length || re('[\\s,;]+').sub('', TIME_TOKEN.sub('', text))) return null;
  const seconds = times.map(tokenSeconds);
  return seconds.every((v) => v > 0) ? [null, seconds] : null;
}

export function isTimeOnlyExercise(exerciseString, name = '') {
  const lines = splitlines(exerciseString || '').map((l) => strip(l)).filter(Boolean);
  if (!lines.length) return false;
  let data;
  if (lines.length === 1) {
    if (!name || !lines[0].toLowerCase().startsWith(name.toLowerCase())) return false;
    data = lines[0].slice(name.length);
  } else {
    data = lines.slice(1).join(', ');
  }
  return Boolean(parseTimeSets(strip(data, ' -–—:')));
}

function weightValue(token, baseWeight) {
  const w = parseBwWeight(token, baseWeight);
  return w !== null ? w : plainFloat(token);
}

function setGroup(piece, hasUnit) {
  let m = SETS_AT_WEIGHT.match(piece);
  if (m) return [toInt(m.group(1)), toInt(m.group(2)), m.group(3)];
  m = SETS_THEN_WEIGHT.match(piece);
  if (m && (hasUnit || m.group(3).startsWith('bw'))) return [toInt(m.group(1)), toInt(m.group(2)), m.group(3)];
  m = WEIGHT_THEN_SETS.match(piece);
  if (m && (hasUnit || m.group(1).startsWith('bw'))) return [toInt(m.group(2)), toInt(m.group(3)), m.group(1)];
  m = THREE_NUMBERS.match(piece);
  if (m) {
    const first = m.group(1);
    const reps = toInt(m.group(2));
    const last = m.group(3);
    if (re('\\d+').fullmatch(last) && toInt(last) <= MOST_SETS) return [toInt(last), reps, first];
    if (re('\\d+').fullmatch(first) && toInt(first) <= MOST_SETS) return [toInt(first), reps, last];
  }
  return null;
}

/** "3x5 @ 100", "3x5 100kg", "100kg 3x5", "100x5x3", "2x10 @ 60, 1x8 @ 70": [count, weights, reps] or null. */
export function parseSetsAtWeight(segment, baseWeight = null) {
  const pieces = re('[,;]').split(segment || '').map((p) => strip(p)).filter(Boolean);
  if (!pieces.length) return null;
  const weights = [];
  const reps = [];
  let grouped = false;
  for (const rawPiece of pieces) {
    const hasUnit = re('\\d\\s*(?:kgs?|lbs?)\\b', 'i').test(rawPiece);
    const piece = strip(setText(rawPiece));
    const group = setGroup(piece, hasUnit);
    let sets;
    let repCount;
    let weightToken;
    if (group) {
      [sets, repCount, weightToken] = group;
      if (!(sets > 0 && sets <= MOST_SETS) || repCount <= 0) return null;
      grouped = true;
    } else {
      const m = ONE_SET.match(piece);
      if (!m || !m.group(1)) return null;
      [sets, repCount, weightToken] = [1, toInt(m.group(2)), m.group(1)];
    }
    let weight;
    try {
      weight = weightValue(weightToken, baseWeight);
    } catch (e) {
      if (e instanceof NotANumber) return null;
      throw e;
    }
    weights.push(...repeat(weight, sets));
    reps.push(...repeat(repCount, sets));
  }
  if (!grouped) return null;
  return [weights.length, weights, reps];
}

const REPS_LIST = '\\d+(?:(?:\\s*,\\s*|\\s+)\\d+)+';
const UNIT = '(?:kgs?|lbs?)';
const WEIGHT_THEN_REPS = [
  re(`^(${WEIGHT})\\s*${UNIT}\\s*[:\\-–—]?\\s*(${REPS_LIST}|\\d+)$`, 'i'),
  re('^(bw(?:/\\d+(?:\\.\\d+)?)?(?:[+-]\\d+(?:\\.\\d+)?)?)\\s+(\\d+(?:\\s+\\d+)+)$', 'i'),
  re(`^(${WEIGHT})\\s*(?:${UNIT})?\\s*(?::|\\s[-–—]|\\sfor)\\s*(${REPS_LIST})$`, 'i'),
];
const REPS_THEN_WEIGHT = re(`^(${REPS_LIST}|\\d+)\\s*(?:reps?)?\\s*(?:@|\\bat\\b)\\s*(${WEIGHT})\\s*(?:${UNIT})?$`, 'i');

/** "100kg 5 5 5", "100 kg: 5, 5, 5", "100 - 5 5 5", "100 for 5, 5, 5", "5 5 5 @ 100": [weights, reps] or null. */
export function parseRepsAtWeight(segment, baseWeight = null, maxRepValue = 30) {
  const text = re('\\bbody\\s*weight\\b', 'i').sub('bw', strip(segment || '').replaceAll('×', 'x'));
  if (!text) return null;
  let found = null;
  for (const pattern of WEIGHT_THEN_REPS) {
    const m = pattern.match(text);
    if (m) {
      found = [m.group(1), m.group(2)];
      break;
    }
  }
  if (!found) {
    const m = REPS_THEN_WEIGHT.match(text);
    if (m) found = [m.group(2), m.group(1)];
  }
  if (!found) return null;
  const [weightToken, repsText] = found;
  const separators = new Set(re('\\s*,\\s*|\\s+').findall(strip(repsText)));
  if (new Set([...separators].map((sep) => (sep.includes(',') ? ',' : ' '))).size > 1) return null;
  const reps = re('\\d+').findall(repsText).map((v) => toInt(v));
  if (!reps.every((v) => v > 0 && v <= maxRepValue)) return null;
  if (repsText.includes(',') && reps.length < 3 && !re('[:\\-–—@]|\\bfor\\b|\\bat\\b').test(text)) return null;
  let weight;
  try {
    weight = weightValue(weightToken.toLowerCase(), baseWeight);
  } catch (e) {
    if (e instanceof NotANumber) return null;
    throw e;
  }
  return [repeat(weight, reps.length), reps];
}

function setsWithBareReps(segment, baseWeight = null) {
  const pieces = re('[,;]').split(segment).map((p) => strip(p)).filter(Boolean);
  if (pieces.length < 2) return null;
  const weights = [];
  const reps = [];
  let lastWeight = null;
  let bare = false;
  for (const piece of pieces) {
    const m = ONE_SET.match(piece);
    if (m) {
      if (m.group(1)) {
        try {
          lastWeight = weightValue(m.group(1), baseWeight);
        } catch (e) {
          if (e instanceof NotANumber) return null;
          throw e;
        }
      }
      if (lastWeight === null) return null;
      weights.push(lastWeight);
      reps.push(toInt(m.group(2)));
    } else if (re('\\d+').fullmatch(piece) && lastWeight !== null) {
      weights.push(lastWeight);
      reps.push(toInt(piece));
      bare = true;
    } else {
      return null;
    }
  }
  return bare ? [weights, reps] : null;
}

export function isDataLine(line) {
  if (!line) return false;
  const stripped = setsOf(strip(line));
  if (parseSetRow(stripped)) return true;
  if (re('^\\d+(?:[.)\\-:])\\s*[A-Za-z]').match(stripped)) return false;
  const tokens = split(stripped);
  if (tokens.length > 1 && re('^\\d+[.)]$').match(tokens[0]) && re('[A-Za-z]').test(stripped)) return false;
  if (tokens.length > 2 && re('^\\d+$').match(tokens[0]) && ['-', '–', '—', ':'].includes(tokens[1])
      && re('^[A-Za-z]').match(tokens[2])) return false;
  if (tokens.length > 1 && re('^\\d').match(tokens[0]) && re('^[A-Za-z]').match(tokens[1])) {
    let setWord = Boolean(SET_WORD.match(tokens[1]));
    if (setWord && tokens[1].toLowerCase() === 'x') setWord = tokens.length > 2 && Boolean(re('^\\d').match(tokens[2]));
    if (!setWord) return false;
  }
  return Boolean(re('^(?:,|-?\\d|bw|body\\s*weight|bodyweight)').match(stripped.toLowerCase()));
}

export function isProbableDataSegment(segment) {
  segment = strip(segment || '');
  if (!segment) return false;
  if (parseTimeSets(segment) || parseRepsAtWeight(segment)) return true;
  const lowered = re('\\bbody\\s*weight\\b').sub('bw', setsOf(segment).toLowerCase());
  if (re('[x×*]').test(lowered)) return true;
  if (lowered.includes(',')) return true;
  for (const token of re('\\s+').split(lowered)) {
    if (!token) continue;
    let cleaned = re('[,:]+$').sub('', token);
    if (cleaned.startsWith('bw') || cleaned.startsWith('bodyweight') || cleaned === 'body') continue;
    cleaned = UNITS.sub('', cleaned);
    if (re('^-?\\d+(?:\\.\\d+)?$').match(cleaned)) continue;
    return false;
  }
  return true;
}

function weightOrNull(token, baseWeight) {
  const bw = parseBwWeight(token, baseWeight);
  if (bw !== null) return bw;
  return tryPlainFloat(token);
}

export function parseWeightRepsPairs(segment, baseWeight = null, maxRepValue = 30) {
  segment = re('\\bbody\\s*weight\\b', 'i').sub('bw', strip(segment || ''));
  if (!segment) return [null, null];
  if (segment.includes(',')) return [null, null];
  if (re('[x×*]', 'i').test(segment)) return [null, null];
  const tokens = split(segment);
  if (tokens.length < 2) return [null, null];
  if (tokens.length !== 2 && tokens.length % 2 !== 0) return [null, null];
  const repsToken = (token) => (re('^\\d+$').match(token) ? toInt(token) : null);

  if (tokens.length === 2) {
    const [wToken, rToken] = tokens;
    const wVal = weightOrNull(wToken, baseWeight);
    const rVal = repsToken(rToken);
    if (wVal === null || rVal === null) return [null, null];
    if (rVal <= 0 || rVal > maxRepValue) return [null, null];
    const weightHint = wToken.includes('.') || wToken.toLowerCase().startsWith('bw') || wToken.startsWith('-') || wToken !== rToken;
    if (!weightHint) return [null, null];
    return [[wVal], [rVal]];
  }

  const weights = [];
  const reps = [];
  for (let idx = 0; idx < tokens.length; idx += 2) {
    const w = weightOrNull(tokens[idx], baseWeight);
    const r = repsToken(tokens[idx + 1]);
    if (w === null || r === null) return [null, null];
    if (r <= 0 || r > maxRepValue) return [null, null];
    weights.push(w);
    reps.push(r);
  }
  return [weights, reps];
}

export function parseWeightRepsHalves(segment, baseWeight = null, maxRepValue = 30) {
  segment = re('\\bbody\\s*weight\\b', 'i').sub('bw', strip(segment || ''));
  if (!segment) return [null, null];
  if (segment.includes(',')) return [null, null];
  if (re('[x×*]', 'i').test(segment)) return [null, null];
  const tokens = split(segment);
  if (tokens.length < 4 || tokens.length % 2 !== 0) return [null, null];
  const half = tokens.length / 2;
  const reps = [];
  for (const tok of tokens.slice(half)) {
    if (!re('^\\d+$').match(tok)) return [null, null];
    const val = toInt(tok);
    if (val <= 0 || val > maxRepValue) return [null, null];
    reps.push(val);
  }
  const weights = [];
  for (const tok of tokens.slice(0, half)) {
    const w = weightOrNull(tok, baseWeight);
    if (w === null) return [null, null];
    weights.push(w);
  }
  return [weights, reps];
}

const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, sept: 9, oct: 10, nov: 11, dec: 12 };
const FULL_MONTHS = { january: 1, february: 2, march: 3, april: 4, june: 6, july: 7, august: 8, september: 9, october: 10, november: 11, december: 12 };
const MONTH_WORD = '([A-Za-z]{3,9})\\.?';
const DAY_WORD = '(\\d{1,2})(?:st|nd|rd|th)?';
const YEAR_WORD = '(?:,?\\s+(\\d{4}|\\d{2}))?';
const TITLE_END = '(?=\\s|$|[-–—:,])';
const MONTH_NAME_DATES = [
  [re(`^\\s*${DAY_WORD}\\s+${MONTH_WORD}${YEAR_WORD}${TITLE_END}`), 1, 2],
  [re(`^\\s*${MONTH_WORD}\\s+${DAY_WORD}${YEAR_WORD}${TITLE_END}`), 2, 1],
];

function monthNumber(word) {
  word = (word || '').toLowerCase();
  return MONTHS[word] ?? FULL_MONTHS[word] ?? null;
}

function monthNameDate(titleLine) {
  const line = titleLine || '';
  for (const [pattern, dayAt, monthAt] of MONTH_NAME_DATES) {
    const m = pattern.match(line);
    if (!m) continue;
    const month = monthNumber(m.group(monthAt));
    if (!month) continue;
    const year = m.group(3);
    return [toInt(m.group(dayAt)), month, year ? toInt(year) + (year.length === 2 ? 2000 : 0) : null, line.slice(m.end)];
  }
  return null;
}

const WEEKDAY_BEFORE_DATE = re(
  '^(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)'
  + '\\.?,?\\s+(?=\\d{1,2}[/.\\-]\\d|\\d{4}-\\d|\\d{1,2}(?:st|nd|rd|th)?\\s+[A-Za-z]{3}|[A-Za-z]{3,9}\\.?\\s+\\d)',
  'i',
);

const SET_ROW = re(
  '^(?P<weight>bw(?:/\\d+(?:\\.\\d+)?)?(?:\\s*[+-]\\s*\\d+(?:\\.\\d+)?)?|-?\\d+(?:\\.\\d+)?)'
  + '\\s*(?:kgs|kg|lbs|lb)?\\s*(?:,|x|×|\\*|\\.(?=\\s))\\s*(?P<reps>\\d+)$',
  'i',
);

/** One set on its own line ("45, 3", "25. 4", "bw+10, 7", "45 x 3"): [weight, reps] tokens or null. */
export function parseSetRow(line) {
  line = re('\\bbody\\s*weight\\b', 'i').sub('bw', strip(line || ''));
  const m = SET_ROW.match(line);
  if (!m) return null;
  return [re('\\s+').sub('', m.group('weight')), m.group('reps')];
}

/** Set rows as the classic one-line form ("45 40 35, 3 4 6"). */
export function joinSetRows(rows) {
  const pairs = rows.map(parseSetRow);
  return `${pairs.map((p) => p[0]).join(' ')}, ${pairs.map((p) => p[1]).join(' ')}`;
}

/** Capitalise the first letter of each word, leaving the rest as typed. */
export function titleCase(name) {
  return re('(^|[\\s\\-/(\\[])([a-z])').sub((m) => m.group(1) + m.group(2).toUpperCase(), name);
}

const UNSPACED_TARGET = re('^(.*?[A-Za-z)])\\s*[-–—]?\\s*(\\[[\\d\\s,.\\-–—sS]*\\].*)$');
const EMOJI = re('[\\U0001F000-\\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0E\uFE0F\u200D]');

/** Drop stray separators, bullets, emoji and tabs around a typed name. */
export function cleanExerciseName(name) {
  name = EMOJI.sub(' ', name || '');
  name = strip(re('\\s+').sub(' ', name));
  return strip(strip(name, '-–—:,.; •◦▪‣*·'));
}

/**
 * Raw workout text -> {date, date_found, invalid_date_text, workout_name, bodyweight,
 * bodyweight_unit, exercises: [...]}, or null when there is nothing to parse.
 * `now` is when the workout is saved, as "YYYY-MM-DDTHH:MM:SS" (the person's own clock);
 * dates come back in that form too.
 */
export function workoutParser(text, { bodyweight = null, preserveBodyweightOffsets = false, now } = {}) {
  if (!text || !strip(text)) return null;

  const rawLines = [];
  let lineNumbers = [];
  let parsedBodyweight = null;
  let parsedBodyweightUnit = null;
  text.split('\n').forEach((line, index) => {
    const stripped = strip(line || '');
    if (!stripped) return;
    if (stripped.startsWith('#')) return;
    const [bwValue, bwUnit] = parseBodyweightLine(stripped);
    if (bwValue !== null) {
      parsedBodyweight = bwValue;
      parsedBodyweightUnit = bwUnit;
      return;
    }
    rawLines.push(stripped);
    lineNumbers.push(index + 1);
  });
  if (!rawLines.length) return null;

  let titleLine = rawLines[0];
  const weekday = WEEKDAY_BEFORE_DATE.match(titleLine);
  if (weekday) titleLine = titleLine.slice(weekday.end);
  const nowParts = parseDate(now);
  const currentYear = nowParts.year;
  const iso = re('^(\\d{4})[-/.](\\d{1,2})[-/.](\\d{1,2})(?=\\s|$|[-–—:,])').match(titleLine);
  const firstToken = split(titleLine)[0] ?? '';
  const dateNums = !iso ? re('\\d+').findall(firstToken) : [];

  let invalidDateText = null;
  const mnd = dateNums.length >= 2 || iso ? null : monthNameDate(titleLine);
  let dateObj;
  let dateFound;
  const nowText = formatDateTime(nowParts);
  if (iso) {
    const y = toInt(iso.group(1));
    const mo = toInt(iso.group(2));
    const d = toInt(iso.group(3));
    if (isValidDate(y, mo, d)) {
      dateObj = makeDate(y, mo, d);
      dateFound = true;
    } else {
      dateObj = nowText;
      dateFound = false;
      invalidDateText = iso.group(0);
    }
  } else if (mnd) {
    const [day, month, writtenYear, rest] = mnd;
    const year = writtenYear || (month > nowParts.month + 1 ? currentYear - 1 : currentYear);
    if (isValidDate(year, month, day)) {
      dateObj = makeDate(year, month, day);
      dateFound = true;
    } else {
      dateObj = nowText;
      dateFound = false;
      invalidDateText = strip(titleLine.slice(0, titleLine.length - rest.length));
    }
  } else if (dateNums.length >= 2) {
    const parsedMonth = toInt(dateNums[1]);
    let year = parsedMonth > nowParts.month + 1 ? currentYear - 1 : currentYear;
    if (dateNums.length >= 3 && (dateNums[2].length === 2 || dateNums[2].length === 4)) {
      year = toInt(dateNums[2]) + (dateNums[2].length === 2 ? 2000 : 0);
    }
    // datetime.strptime(f"{d}-{m}-{year}", "%d-%m-%Y")
    const dayOk = Boolean(re('(?:3[01]|[12]\\d|0[1-9]|[1-9])').fullmatch(dateNums[0]));
    const monthOk = Boolean(re('(?:1[0-2]|0[1-9]|[1-9])').fullmatch(dateNums[1]));
    const yearOk = /^\d{4}$/.test(String(year));
    if (dayOk && monthOk && yearOk && isValidDate(year, toInt(dateNums[1]), toInt(dateNums[0]))) {
      dateObj = makeDate(year, toInt(dateNums[1]), toInt(dateNums[0]));
      dateFound = true;
    } else {
      dateObj = nowText;
      dateFound = false;
      if (re('\\d{1,2}[/.\\-]\\d{1,2}(?:[/.\\-]\\d{2,4})?').fullmatch(firstToken)) invalidDateText = firstToken;
    }
  } else {
    dateObj = nowText;
    dateFound = false;
  }

  let workoutName = titleLine;
  if (iso) workoutName = titleLine.slice(iso.end);
  else if (mnd && dateFound) workoutName = strip(mnd[3]);
  else if (dateNums.length >= 2) {
    const i = titleLine.indexOf(' ');
    if (i >= 0) workoutName = strip(titleLine.slice(i + 1));
    else if (dateFound) workoutName = '';
  }
  workoutName = unescapeHtml(workoutName);
  workoutName = strip(lstrip(workoutName, '-–—:,'));

  const effectiveBodyweight = preserveBodyweightOffsets ? null : (parsedBodyweight !== null ? parsedBodyweight : bodyweight);
  const workoutDay = {
    date: dateObj,
    date_found: dateFound,
    invalid_date_text: invalidDateText,
    workout_name: workoutName,
    bodyweight: parsedBodyweight,
    bodyweight_unit: parsedBodyweightUnit,
    exercises: [],
  };

  const lines = [];
  const keptNumbers = [];
  rawLines.forEach((line, k) => {
    const stripped = strip(line);
    if (lines.length > 1 && re('\\d+\\s*sets?', 'i').fullmatch(stripped)
        && !isDataLine(lines[lines.length - 1])
        && extractDeclaredSets(lines[lines.length - 1])[0] === null) {
      lines[lines.length - 1] = `${lines[lines.length - 1]} ${stripped}`;
      return;
    }
    lines.push(isDataLine(stripped) ? stripped : stripListNumber(stripped));
    keptNumbers.push(lineNumbers[k]);
  });
  lineNumbers = keptNumbers;

  let i = 1;
  while (i < lines.length) {
    const cleanLine = lines[i];
    let name = '';
    let weights = [];
    let reps = [];
    let dataPart = '';
    const timeRangeHint = hasTimeRangeHint(cleanLine);
    let [declaredSets, cleanedLine] = extractDeclaredSets(cleanLine);
    const unspaced = UNSPACED_TARGET.match(cleanedLine);
    if (unspaced && !cleanedLine.includes(' - [')) cleanedLine = `${unspaced.group(1)} - ${unspaced.group(2)}`;
    const bracketSets = extractSetsFromBracket(cleanedLine);
    if (bracketSets !== null) declaredSets = bracketSets;

    let exerciseLines = [cleanedLine];
    let consumed = 1;

    const takeFollowingData = () => {
      const dataLine = strip(lines[i + 1]);
      exerciseLines.push(dataLine);
      dataPart = dataLine;
      consumed += 1;
      if (!dataPart.includes(',') && !parseSetRow(dataPart) && i + 2 < lines.length && isDataLine(lines[i + 2])) {
        const repsLine = strip(lines[i + 2]);
        exerciseLines.push(repsLine);
        dataPart = `${dataPart}, ${repsLine}`;
        consumed += 1;
      }
    };

    if (cleanedLine.includes(' - [')) {
      name = strip(split1(cleanedLine, ' - [')[0]);
      if (cleanedLine.includes(']')) {
        let tail = strip(split1(cleanedLine, ']')[1]);
        tail = strip(lstrip(tail, '-:'));
        dataPart = tail;
      }
      if (!dataPart && i + 1 < lines.length && isDataLine(lines[i + 1])) takeFollowingData();
    } else {
      const tokens = split(cleanedLine);
      let firstNumIdx = -1;
      const firstWord = tokens.findIndex((token) => re('^[A-Za-z]').match(token) && !SET_WORD.match(token)
        && !re('^body', 'i').match(token));
      for (let idx = 0; idx < tokens.length; idx++) {
        if (firstWord >= 0 && idx <= firstWord) continue;
        const token = tokens[idx];
        const tokenLower = token.toLowerCase();
        if (re('^-?\\d').match(token) || token.startsWith(',') || tokenLower.startsWith('bw')
            || tokenLower.startsWith('bodyweight')
            || (tokenLower === 'body' && idx + 1 < tokens.length && tokens[idx + 1].toLowerCase().startsWith('weight'))) {
          firstNumIdx = idx;
          break;
        }
      }
      if (firstNumIdx !== -1) {
        name = strip(tokens.slice(0, firstNumIdx).join(' '));
        dataPart = strip(tokens.slice(firstNumIdx).join(' '));
      } else {
        name = cleanedLine;
        dataPart = '';
      }
    }

    if (!dataPart && i + 1 < lines.length && isDataLine(lines[i + 1])) takeFollowingData();

    if (dataPart && isSetsLine(dataPart)) {
      while (i + consumed < lines.length && isSetsLine(lines[i + consumed])) {
        const extra = strip(lines[i + consumed]);
        exerciseLines.push(extra);
        dataPart = `${dataPart}, ${extra}`;
        consumed += 1;
      }
    } else if (dataPart && parseSetRow(dataPart)) {
      const rows = [dataPart];
      if (consumed > 1) {
        while (i + consumed < lines.length && parseSetRow(lines[i + consumed])) {
          rows.push(strip(lines[i + consumed]));
          consumed += 1;
        }
      }
      if (rows.length > 1 || !dataPart.includes(',')) {
        dataPart = joinSetRows(rows);
        if (consumed > 1) exerciseLines = [exerciseLines[0], dataPart];
      }
    }

    if (dataPart && !isProbableDataSegment(dataPart)) dataPart = '';

    const maxRepValue = timeRangeHint ? 600 : 30;
    const timeSets = dataPart ? parseTimeSets(dataPart) : null;
    const setsAtWeight = timeSets ? null : (dataPart ? parseSetsAtWeight(dataPart, effectiveBodyweight) : null);
    let repsAtWeight;
    if (timeSets) {
      const [countedSets, secs] = timeSets;
      reps = secs;
      weights = repeat(0.0, reps.length);
      if (countedSets) declaredSets = countedSets;
    } else if (setsAtWeight) {
      [declaredSets, weights, reps] = setsAtWeight;
    } else if (dataPart && (repsAtWeight = parseRepsAtWeight(dataPart, effectiveBodyweight, maxRepValue))) {
      [weights, reps] = repsAtWeight;
    } else if (dataPart) {
      const [wList, rList] = parseWeightXReps(dataPart, effectiveBodyweight);
      if (wList && wList.length) {
        weights = wList;
        reps = rList;
      } else if (dataPart.includes(',')) {
        const subparts = split1(dataPart, ',');
        weights = extractWeights(subparts[0], effectiveBodyweight);
        reps = extractNumbers(subparts[1]);
        if (!weights.length && reps.length) weights = repeat(1.0, reps.length);
        else if (weights.length && !reps.length) reps = repeat(1, weights.length);
      } else {
        const [wPairs, rPairs] = parseWeightRepsPairs(dataPart, effectiveBodyweight, maxRepValue);
        if (wPairs && wPairs.length && rPairs && rPairs.length) {
          weights = wPairs;
          reps = rPairs;
        } else {
          const [wHalves, rHalves] = parseWeightRepsHalves(dataPart, effectiveBodyweight, maxRepValue);
          if (wHalves && wHalves.length && rHalves && rHalves.length) {
            weights = wHalves;
            reps = rHalves;
          } else {
            weights = extractWeights(dataPart, effectiveBodyweight);
            reps = repeat(1, weights.length);
          }
        }
      }
    }

    const sourceName = name;
    name = cleanExerciseName(name);
    const missingName = !name;
    if (missingName) name = 'Unknown Exercise';

    const inferredSets = weights.length || reps.length ? Math.max(weights.length, reps.length) : 0;
    let targetSets;
    if (declaredSets !== null) targetSets = Math.max(toInt(declaredSets), inferredSets);
    else targetSets = inferredSets > 3 ? inferredSets : 3;

    [weights, reps] = alignSets(weights, reps, targetSets);
    const isValid = reps.length > 0 || weights.some((w) => w !== 0);

    workoutDay.exercises.push({
      name: titleCase(name),
      exercise_string: strip(exerciseLines.join('\n')),
      weights,
      reps,
      valid: isValid,
      line: lineNumbers[i],
      source_name: sourceName,
      missing_name: missingName,
    });

    i += consumed;
  }

  return workoutDay;
}

export { isSpace };
