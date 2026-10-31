// Numbers from a workout's sets: estimated 1RM (Epley), volume, timed scores, which of two
// workouts is better, and the quality score the Stats charts use. Ports services/helpers.py,
// services/best_scoring.py and services/workout_quality.py.
import { toFloat, toInt, isDict, fsum, sortBy, compareKeys } from './py.js';

function tryFloat(x) {
  try {
    return toFloat(x);
  } catch {
    return null;
  }
}
function tryInt(x) {
  try {
    return toInt(x);
  } catch {
    return null;
  }
}

function padToSameLength(weights, reps) {
  weights = [...(weights || [])];
  reps = [...(reps || [])];
  if (weights.length !== reps.length) {
    if (weights.length < reps.length && weights.length) {
      weights = weights.concat(Array(reps.length - weights.length).fill(weights[weights.length - 1]));
    } else if (reps.length < weights.length && reps.length) {
      reps = reps.concat(Array(weights.length - reps.length).fill(reps[reps.length - 1]));
    }
  }
  return [weights, reps];
}

function zip(a, b) {
  const n = Math.min(a.length, b.length);
  const out = [];
  for (let i = 0; i < n; i++) out.push([a[i], b[i]]);
  return out;
}

/** Epley: weight × (1 + reps / 30). */
export function estimate1rm(weight, reps) {
  if (weight <= 0 || reps <= 0) return 0.0;
  return weight * (1.0 + reps / 30.0);
}

/** [peak e1RM, sum of e1RMs, volume] (services.helpers.get_set_stats). */
export function getSetStats(sets) {
  let peak = 0;
  let strengthSum = 0;
  let volume = 0;
  if (!isDict(sets) || !('weights' in sets)) return [0, 0, 0];
  let weights = [...(sets.weights || [])];
  let reps = [...(sets.reps || [])];
  if (!weights.length || !reps.length) return [0, 0, 0];
  [weights, reps] = padToSameLength(weights, reps);
  for (const [w, r] of zip(weights, reps)) {
    const weight = tryFloat(w);
    const repsValue = tryInt(r);
    if (weight === null || repsValue === null) continue;
    const est = weight * (1 + repsValue / 30);
    if (est > peak) peak = est;
    strengthSum += est;
    volume += weight * repsValue;
  }
  return [peak, strengthSum, volume];
}

/** Load-duration score for timed exercises: weight × √seconds. */
export function timedSetScore(weight, seconds) {
  const w = tryFloat(weight);
  const s = tryFloat(seconds);
  if (w === null || s === null) return 0.0;
  if (w <= 0 || s <= 0) return 0.0;
  return w * Math.sqrt(s);
}

/** [peak score, score sum, total work] for timed sets. */
export function getTimedSetStats(sets) {
  if (!isDict(sets) || !('weights' in sets)) return [0.0, 0.0, 0.0];
  let weights = [...(sets.weights || [])];
  let reps = [...(sets.reps || [])];
  if (!weights.length || !reps.length) return [0.0, 0.0, 0.0];
  [weights, reps] = padToSameLength(weights, reps);
  let peak = 0.0;
  let scoreSum = 0.0;
  let totalWork = 0.0;
  for (const [w, s] of zip(weights, reps)) {
    const wf = tryFloat(w);
    const si = tryInt(s);
    if (wf === null || si === null) continue;
    if (wf <= 0 || si <= 0) continue;
    const score = timedSetScore(wf, si);
    if (score > peak) peak = score;
    scoreSum += score;
    totalWork += wf * si;
  }
  return [peak, scoreSum, totalWork];
}

/** Same-length weights and reps, sets without a positive weight and reps dropped. */
export function coerceEqualLenSets(weights, reps) {
  weights = [...(weights || [])];
  reps = [...(reps || [])];
  if (!weights.length && !reps.length) return [[], []];
  [weights, reps] = padToSameLength(weights, reps);
  const outW = [];
  const outR = [];
  for (const [w, r] of zip(weights, reps)) {
    const wf = tryFloat(w);
    const ri = tryInt(r);
    if (wf === null || ri === null) continue;
    if (wf <= 0 || ri <= 0) continue;
    outW.push(wf);
    outR.push(ri);
  }
  return [outW, outR];
}

function topN(n) {
  return Math.max(1, Number.isInteger(n) && n > 0 ? n : 3);
}

/** Strength-first score for picking a "best" workout: peak 1RM + 25% of the rest of the top N. */
export function bestWorkoutStrengthScore(setsJson, { top_n = 3 } = {}) {
  if (!isDict(setsJson)) return { score: 0.0, peak_1rm: 0.0, top_sum_1rm: 0.0, set_count: 0.0 };
  const [w, r] = coerceEqualLenSets(setsJson.weights || [], setsJson.reps || []);
  if (!w.length || !r.length) return { score: 0.0, peak_1rm: 0.0, top_sum_1rm: 0.0, set_count: 0.0 };
  let oneRms = zip(w, r).map(([wi, ri]) => estimate1rm(wi, ri)).filter((x) => x && x > 0);
  if (!oneRms.length) return { score: 0.0, peak_1rm: 0.0, top_sum_1rm: 0.0, set_count: r.length || 0 };
  oneRms = sortBy(oneRms, (x) => x, true);
  const top = oneRms.slice(0, Math.min(topN(top_n), oneRms.length));
  const peak = top[0];
  const topSum = fsum(top);
  const bonus = 0.25 * Math.max(0.0, topSum - peak);
  return { score: peak + bonus, peak_1rm: peak, top_sum_1rm: topSum, set_count: r.length };
}

/** Timed equivalent of bestWorkoutStrengthScore. */
export function bestWorkoutTimedScore(setsJson, { top_n = 3 } = {}) {
  if (!isDict(setsJson)) return { score: 0.0, peak_timed: 0.0, top_sum: 0.0, set_count: 0.0 };
  const [w, r] = coerceEqualLenSets(setsJson.weights || [], setsJson.reps || []);
  if (!w.length || !r.length) return { score: 0.0, peak_timed: 0.0, top_sum: 0.0, set_count: 0.0 };
  let scores = zip(w, r).map(([wi, ri]) => timedSetScore(wi, ri)).filter((x) => x > 0);
  if (!scores.length) return { score: 0.0, peak_timed: 0.0, top_sum: 0.0, set_count: r.length || 0 };
  scores = sortBy(scores, (x) => x, true);
  const top = scores.slice(0, Math.min(topN(top_n), scores.length));
  const peak = top[0];
  const topSum = fsum(top);
  return { score: peak + 0.25 * Math.max(0.0, topSum - peak), peak_timed: peak, top_sum: topSum, set_count: r.length };
}

function lexicographicCompareDesc(left, right, eps = 1e-9) {
  const limit = Math.max(left.length, right.length);
  for (let idx = 0; idx < limit; idx++) {
    const lv = idx < left.length ? left[idx] : null;
    const rv = idx < right.length ? right[idx] : null;
    if (lv === null && rv === null) return [0, null];
    if (lv === null) return [-1, idx];
    if (rv === null) return [1, idx];
    if (Math.abs(lv - rv) <= eps) continue;
    return lv > rv ? [1, idx] : [-1, idx];
  }
  return [0, null];
}

function rankVectors(setsJson, top_n, scoreOf) {
  const [w, r] = coerceEqualLenSets(setsJson.weights || [], setsJson.reps || []);
  if (!w.length || !r.length) return { scores: [], weights: [] };
  const scores = zip(w, r).map(([wi, ri]) => scoreOf(wi, ri) || 0.0);
  let pairs = zip(scores, w).filter(([score, weight]) => score > 0 && weight > 0);
  if (!pairs.length) return { scores: [], weights: [] };
  pairs = sortBy(pairs, (p) => [p[0], p[1]], true);
  const top = pairs.slice(0, Math.min(topN(top_n), pairs.length));
  return {
    scores: top.map((p) => p[0]),
    weights: sortBy(top.map((p) => p[1]), (x) => x, true),
  };
}

export function strengthRankVectors(setsJson, top_n = 3) {
  return rankVectors(setsJson || {}, top_n, estimate1rm);
}
export function timedRankVectors(setsJson, top_n = 3) {
  return rankVectors(setsJson || {}, top_n, timedSetScore);
}

function compareRankVectors(previous, current) {
  const [perfCmp, perfIdx] = lexicographicCompareDesc(current.scores || [], previous.scores || []);
  if (perfCmp !== 0) {
    return {
      cmp: perfCmp,
      reason: perfIdx === 0 ? 'peak' : 'consistency',
      diff_index: perfIdx,
      diff: perfIdx !== null && perfIdx < current.scores.length && perfIdx < previous.scores.length
        ? current.scores[perfIdx] - previous.scores[perfIdx] : null,
    };
  }
  const [weightCmp, weightIdx] = lexicographicCompareDesc(current.weights || [], previous.weights || []);
  if (weightCmp !== 0) {
    return {
      cmp: weightCmp,
      reason: 'consistency',
      diff_index: weightIdx,
      diff: weightIdx !== null && weightIdx < current.weights.length && weightIdx < previous.weights.length
        ? current.weights[weightIdx] - previous.weights[weightIdx] : null,
    };
  }
  return { cmp: 0, reason: 'same', diff_index: null, diff: 0.0 };
}

/** Compare two strength workouts set by set (best, 2nd best, ...), then by weights. */
export function compareStrengthWorkouts(previousSets, currentSets, { top_n = 3 } = {}) {
  const previous = strengthRankVectors(previousSets || {}, top_n);
  const current = strengthRankVectors(currentSets || {}, top_n);
  return { ...compareRankVectors(previous, current), previous, current };
}

export function compareTimedWorkouts(previousSets, currentSets, { top_n = 3 } = {}) {
  const previous = timedRankVectors(previousSets || {}, top_n);
  const current = timedRankVectors(currentSets || {}, top_n);
  return { ...compareRankVectors(previous, current), previous, current };
}

// --- WorkoutQualityScorer ---

function mean(values) {
  return fsum(values) / values.length;
}

function stdev(values) {
  const m = mean(values);
  return Math.sqrt(fsum(values.map((v) => (v - m) ** 2)) / (values.length - 1));
}

function emptyScore() {
  return {
    peak_1rm: 0, avg_1rm: 0, total_volume: 0, effective_volume: 0, set_count: 0, working_set_count: 0,
    sustained_intensity: 0, volume_consistency: 0, rep_range_adherence: 0, quality_index: 0,
    quality_score: 0, set_details: [],
  };
}

function emptyTimedScore() {
  return {
    peak_timed_score: 0, total_work: 0, effective_work: 0, set_count: 0, duration_adherence: 0,
    work_consistency: 0, quality_index: 0, quality_score: 0, set_details: [], peak_1rm: 0,
    total_volume: 0, effective_volume: 0,
  };
}

function workingSetWeight(intensityRatio) {
  if (intensityRatio <= 0) return 0.0;
  return Math.max(0.0, Math.min(1.0, (intensityRatio - 0.5) / 0.5));
}

function repAdherenceScore(reps, targetRange, intensityRatio = 0.0) {
  if (!targetRange) return 1.0;
  if (reps <= 0) return 0.0;
  const [minReps, maxReps] = targetRange;
  if (minReps <= reps && reps <= maxReps) return 1.0;
  if (intensityRatio >= 0.9) return 1.0;
  if (reps > maxReps && maxReps > 0) return Math.max(0.0, 1.0 - (reps - maxReps) / maxReps);
  if (reps < minReps && minReps > 0) return Math.max(0.0, 1.0 - (minReps - reps) / minReps);
  return 0.0;
}

function calculateSetQuality(importance, adherence) {
  if (importance <= 0) return 0.0;
  return Math.max(0.0, Math.min(1.0, 0.2 + 0.55 * importance + 0.25 * adherence));
}

function volumeConsistency(setScores) {
  if (setScores.length < 2) return 1.0;
  let working = setScores.filter((s) => (s.importance ?? 1.0) > 0.15);
  if (working.length < 2) working = setScores;
  const volumes = working.map((s) => s.volume || 0.0);
  if (!volumes.length || Math.max(...volumes) <= 0) return 0.0;
  const y = volumes.map((v) => Math.log(v + 1.0));
  const n = y.length;
  if (n < 2) return 1.0;
  const x = [...Array(n).keys()];
  const xMean = mean(x);
  const yMean = mean(y);
  const denom = fsum(x.map((xi) => (xi - xMean) ** 2));
  if (denom <= 0) return Math.exp(-(stdev(y) / 0.35));
  const slope = fsum(x.map((xi, i) => (xi - xMean) * (y[i] - yMean))) / denom;
  const intercept = yMean - slope * xMean;
  const residuals = y.map((yi, i) => yi - (slope * x[i] + intercept));
  return Math.exp(-(stdev(residuals) / 0.35));
}

function repRangeAdherence(setScores, targetRange) {
  if (!targetRange || !setScores.length) return 1.0;
  const scores = setScores.map((s) => repAdherenceScore(Math.trunc(s.reps || 0), targetRange, s.intensity_ratio || 0.0));
  return scores.length ? fsum(scores) / scores.length : 0.0;
}

function overallQuality(peak, avg, consistencyRaw, adherenceRaw, workingSetCount, totalSetCount) {
  if (peak <= 0) return 0.0;
  const sustained = Math.max(0.0, Math.min(1.0, peak > 0 ? avg / peak : 0.0));
  const workDensity = Math.max(0.0, Math.min(1.0, totalSetCount > 0 ? workingSetCount / totalSetCount : 0.0));
  const consistency = Math.max(0.0, Math.min(1.0, consistencyRaw));
  const adherence = Math.max(0.0, Math.min(1.0, adherenceRaw));
  const q = 0.4 * consistency + 0.35 * adherence + 0.15 * sustained + 0.1 * workDensity;
  return Math.max(0.0, Math.min(1.0, q));
}

/** Quality of a strength workout (WorkoutQualityScorer.calculate_workout_score). */
export function calculateWorkoutScore(setsJson, targetRepRange = null) {
  if (!isDict(setsJson)) return emptyScore();
  let weights = setsJson.weights || [];
  let reps = setsJson.reps || [];
  if (!weights.length || !reps.length) return emptyScore();
  [weights, reps] = padToSameLength(weights, reps);
  const setScores = [];
  let totalVolume = 0.0;
  let peak = 0.0;
  for (const [w, r] of zip(weights, reps)) {
    const weight = tryFloat(w);
    const repCount = tryInt(r);
    if (weight === null || repCount === null) continue;
    if (weight <= 0 || repCount <= 0) continue;
    const set1rm = estimate1rm(weight, repCount);
    const setVolume = weight * repCount;
    setScores.push({ weight, reps: repCount, '1rm': set1rm, volume: setVolume });
    totalVolume += setVolume;
    peak = Math.max(peak, set1rm);
  }
  if (!setScores.length) return emptyScore();

  let weightsSum = 0.0;
  let weighted1rmSum = 0.0;
  let weightedAdherenceSum = 0.0;
  let effectiveVolume = 0.0;
  let workingSetCount = 0;
  for (const s of setScores) {
    const intensityRatio = peak > 0 ? s['1rm'] / peak : 0.0;
    const importance = workingSetWeight(intensityRatio);
    const adherence = repAdherenceScore(s.reps, targetRepRange, intensityRatio);
    s.intensity_ratio = intensityRatio;
    s.importance = importance;
    s.adherence = adherence;
    s.quality = calculateSetQuality(importance, adherence);
    if (importance > 0.15) workingSetCount += 1;
    weightsSum += importance;
    weighted1rmSum += s['1rm'] * importance;
    weightedAdherenceSum += adherence * importance;
    effectiveVolume += s.volume * importance;
  }
  let avg1rm;
  let adherence;
  if (weightsSum > 0) {
    avg1rm = weighted1rmSum / weightsSum;
    adherence = weightedAdherenceSum / weightsSum;
  } else {
    avg1rm = mean(setScores.map((s) => s['1rm']));
    adherence = repRangeAdherence(setScores, targetRepRange);
  }
  const consistency = volumeConsistency(setScores);
  const qualityIndex = overallQuality(peak, avg1rm, consistency, adherence, workingSetCount, setScores.length);
  return {
    peak_1rm: peak,
    avg_1rm: avg1rm,
    total_volume: totalVolume,
    effective_volume: effectiveVolume,
    set_count: setScores.length,
    working_set_count: workingSetCount,
    sustained_intensity: peak > 0 ? avg1rm / peak : 0,
    volume_consistency: consistency,
    rep_range_adherence: adherence,
    quality_index: qualityIndex,
    quality_score: qualityIndex * 100.0,
    set_details: setScores,
  };
}

function durationAdherence(secondsList, targetRange) {
  if (!targetRange || !secondsList.length) return 1.0;
  const [minS, maxS] = targetRange;
  const scores = secondsList.map((s) => {
    if (minS <= s && s <= maxS) return 1.0;
    if (s > maxS && maxS > 0) return Math.max(0.0, 1.0 - (s - maxS) / maxS);
    if (s < minS && minS > 0) return Math.max(0.0, 1.0 - (minS - s) / minS);
    return 0.0;
  });
  return fsum(scores) / scores.length;
}

function workConsistency(works) {
  if (works.length < 2) return 1.0;
  return Math.exp(-(stdev(works.map((w) => Math.log(w + 1.0))) / 0.35));
}

/** Quality of a timed workout (weight × √seconds, duration in range). */
export function calculateTimedWorkoutScore(setsJson, targetSecondsRange = null) {
  if (!isDict(setsJson)) return emptyTimedScore();
  let weights = [...(setsJson.weights || [])];
  let secondsList = [...(setsJson.reps || [])];
  if (!weights.length || !secondsList.length) return emptyTimedScore();
  [weights, secondsList] = padToSameLength(weights, secondsList);
  const setScores = [];
  let totalWork = 0.0;
  let peak = 0.0;
  for (const [w, s] of zip(weights, secondsList)) {
    const weight = tryFloat(w);
    const secs = tryInt(s);
    if (weight === null || secs === null) continue;
    if (weight <= 0 || secs <= 0) continue;
    const score = weight * Math.sqrt(secs);
    const work = weight * secs;
    setScores.push({ weight, seconds: secs, score, work });
    totalWork += work;
    peak = Math.max(peak, score);
  }
  if (!setScores.length) return emptyTimedScore();
  const adherence = durationAdherence(setScores.map((s) => s.seconds), targetSecondsRange);
  const consistency = workConsistency(setScores.map((s) => s.work));
  const avgRatio = peak > 0 ? mean(setScores.map((s) => s.score)) / peak : 0.0;
  const qualityIndex = Math.max(0.0, Math.min(1.0, 0.45 * consistency + 0.35 * adherence + 0.2 * avgRatio));
  const effective = peak > 0 ? fsum(setScores.map((s) => s.work * (s.score / peak))) : 0.0;
  return {
    peak_timed_score: peak,
    total_work: totalWork,
    effective_work: effective,
    set_count: setScores.length,
    duration_adherence: adherence,
    work_consistency: consistency,
    quality_index: qualityIndex,
    quality_score: qualityIndex * 100.0,
    set_details: setScores,
    peak_1rm: peak,
    total_volume: totalWork,
    effective_volume: effective,
  };
}

export { compareKeys };
