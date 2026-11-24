// Personal bests: for every exercise, the best estimated max (or timed score) it ever reached
// and the heaviest set, with the day each happened. Built from the same per-exercise chart the
// Stats page draws (core/stats.js getChartData), so the numbers always agree with it.

import { addDays } from './dates.js';

export const FRESH_DAYS = 30;

const trim = (n) => {
  const r = Math.round(Number(n) * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
};

/** "80 × 5", "BW+10 × 8", "BW × 12", "20 × 45s", "BW × 60s", "60s". */
export function topSetText({ weight, reps, offset = null, isTimed = false }) {
  if (!weight && !reps) return '';
  let load = trim(weight);
  if (offset !== null && offset !== undefined) {
    load = Math.abs(offset) < 0.05 ? 'BW' : `BW${offset > 0 ? '+' : '−'}${trim(Math.abs(offset))}`;
  }
  // A timed hold with bodyweight reads "BW × 60s" as it was logged, not the bodyweight's number.
  if (isTimed) return weight ? `${load} × ${reps}s` : `${reps}s`;
  return reps ? `${load} × ${reps}` : load;
}

/**
 * charts: [{ value, label, chart }] where chart is getChartData's answer.
 * Returns one row per exercise that has a score, unsorted:
 * { value, label, isTimed, best, bestDay, current, belowPct, top, topDay, sessions, lastDay, fresh }
 * bestDay is the first day the best was reached. fresh: reached in the last 30 days, and not on
 * the exercise's very first session (a first session is a start, not a record).
 */
export function personalBests(charts, today) {
  const freshFrom = today ? addDays(today, -FRESH_DAYS) : '';
  const rows = [];
  for (const { value, label, chart } of charts) {
    const data = chart?.data || [];
    if (!data.length) continue;
    let bi = 0;
    for (let i = 1; i < data.length; i += 1) if (data[i] > data[bi]) bi = i;
    if (!(data[bi] > 0)) continue;
    const weights = chart.weight || [];
    const reps = chart.reps || [];
    let ti = -1;
    for (let i = 0; i < weights.length; i += 1) {
      if (!(weights[i] > 0) && !(reps[i] > 0)) continue;
      if (ti < 0 || weights[i] > weights[ti] || (weights[i] === weights[ti] && (reps[i] || 0) > (reps[ti] || 0))) ti = i;
    }
    const current = data[data.length - 1];
    const bestDay = chart.labels[bi] || '';
    rows.push({
      value,
      label,
      isTimed: Boolean(chart.is_timed),
      best: data[bi],
      bestDay,
      current,
      belowPct: current < data[bi] ? ((data[bi] - current) / data[bi]) * 100 : 0,
      top: ti < 0 ? '' : topSetText({ weight: weights[ti], reps: reps[ti] || 0, offset: chart.bodyweight_offset?.[ti] ?? null, isTimed: chart.is_timed }),
      topDay: ti < 0 ? '' : chart.labels[ti] || '',
      sessions: data.length,
      lastDay: chart.labels[chart.labels.length - 1] || '',
      fresh: Boolean(freshFrom && bi > 0 && bestDay >= freshFrom),
    });
  }
  return rows;
}

/** 'recent' (latest best first), 'best' (highest first), 'alpha'. */
export function sortBests(rows, by = 'recent') {
  const list = [...rows];
  if (by === 'alpha') return list.sort((a, b) => a.label.localeCompare(b.label));
  if (by === 'best') return list.sort((a, b) => Number(a.isTimed) - Number(b.isTimed) || b.best - a.best || a.label.localeCompare(b.label));
  return list.sort((a, b) => (b.bestDay > a.bestDay ? 1 : b.bestDay < a.bestDay ? -1 : a.label.localeCompare(b.label)));
}
