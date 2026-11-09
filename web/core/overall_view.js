// What the Stats page shows for "Overall strength", as the original page worked it out
// (templates/stats.html: renderChart, updateHero, updateTiles, strengthHighlights).
//
// The Strength Index is 100 at your start (each exercise's first sessions). The headline is the
// 14-day average of it, so one light day doesn't move it; ranges only change the line under it
// ("4% stronger than 3 months ago") and the tiles, never the headline.

export const OVERALL_TREND_DAYS = 14;
export const BREAK_GAP_DAYS = 45;
export const RANGE_AGO = { 30: 'a month ago', 90: '3 months ago', 180: '6 months ago', 365: 'a year ago' };
export const RANGE_SHORT = { 30: 'last month', 90: 'last 3 months', 180: 'last 6 months', 365: 'last year', all: 'all time' };

const finite = (v) => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));

export function dayNumber(label) {
  const parts = String(label || '').split('-').map(Number);
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return null;
  return Math.round(Date.UTC(parts[0], parts[1] - 1, parts[2]) / 86400000);
}

export function lastFiniteIndex(values, from = values.length - 1) {
  for (let i = from; i >= 0; i--) if (finite(values[i])) return i;
  return null;
}

export function firstFiniteIndex(values, from = 0) {
  for (let i = from; i < values.length; i++) if (finite(values[i])) return i;
  return null;
}

/** First index inside the range, counted back from the last day shown (not from today). */
export function rangeStartIndex(labels, range) {
  if (!labels.length || range === 'all') return 0;
  const days = Number(range);
  const lastDay = dayNumber(labels[labels.length - 1]);
  if (!Number.isFinite(days) || lastDay === null) return 0;
  const cutoff = lastDay - days + 1;
  const idx = labels.findIndex((l) => {
    const d = dayNumber(l);
    return d !== null && d >= cutoff;
  });
  return idx < 0 ? 0 : idx;
}

export function trailingAverageByDate(labels, values, windowDays) {
  const days = labels.map(dayNumber);
  const out = new Array(values.length).fill(null);
  let lo = 0;
  let sum = 0;
  let count = 0;
  for (let i = 0; i < values.length; i++) {
    if (finite(values[i])) { sum += Number(values[i]); count += 1; }
    while (lo < i && days[lo] !== null && days[i] !== null && days[lo] <= days[i] - windowDays) {
      if (finite(values[lo])) { sum -= Number(values[lo]); count -= 1; }
      lo += 1;
    }
    if (finite(values[i]) && count > 0) out[i] = sum / count;
  }
  return out;
}

/** '16%', '4.2%': whole numbers from 10 up. */
export function formatPercentChange(pct) {
  const abs = Math.abs(pct);
  return `${abs >= 10 ? Math.round(abs) : Number(abs.toFixed(1))}%`;
}

/** An index value against the start (100): '+16.3%', '−2%', '0%'. */
export function formatVsStart(raw, decimals = 1) {
  const num = Number(raw);
  if (!Number.isFinite(num)) return '-';
  const diff = Number((num - 100).toFixed(decimals));
  if (diff === 0) return '0%';
  const text = Math.abs(diff).toFixed(decimals).replace(/\.0+$/, '');
  return `${diff > 0 ? '+' : '−'}${text}%`;
}

/**
 * New bests in the range, and the main lift that improved most: its best in the range against
 * its best before it (all time: against where it started). Main lifts are the heavier half with
 * at least 4 sessions, so a light ab exercise can't claim +1000%.
 */
export function strengthHighlights(exercises, range, rangeStartLabel) {
  const from = range === 'all' ? '' : String(rangeStartLabel || '');
  let newBests = 0;
  let top = null;
  const bases = (exercises || []).map((ex) => Number(ex.baseline) || 0).sort((a, b) => a - b);
  const mainLift = bases.length ? bases[Math.floor((bases.length - 1) / 2)] : 0;
  for (const ex of exercises || []) {
    const days = Array.isArray(ex.days) ? ex.days : [];
    const vals = Array.isArray(ex.values) ? ex.values : [];
    let bestSoFar = null;
    let bestBefore = null;
    let bestIn = null;
    days.forEach((day, i) => {
      const v = Number(vals[i]);
      if (!(v > 0)) return;
      const inRange = day >= from;
      if (inRange && bestSoFar !== null && v > bestSoFar * 1.001) newBests += 1;
      if (bestSoFar === null || v > bestSoFar) bestSoFar = v;
      if (inRange) bestIn = Math.max(bestIn || 0, v);
      else bestBefore = Math.max(bestBefore || 0, v);
    });
    const ref = range === 'all' ? Number(ex.baseline) : bestBefore;
    const isMain = (Number(ex.baseline) || 0) >= mainLift && days.length >= 4;
    if (isMain && bestIn && ref > 0) {
      const pct = ((bestIn / ref) - 1) * 100;
      if (pct >= 0.5 && (!top || pct > top.pct)) top = { name: ex.name, pct };
    }
  }
  return { newBests, top };
}

/**
 * Everything the overall card shows, from getOverallProgressData() (mode "index") and a range
 * ('30' | '90' | '180' | '365' | 'all'). Null when there is nothing to show yet.
 */
export function overallView(data, range) {
  const labels = Array.isArray(data?.labels) ? data.labels : [];
  const values = (data?.data || []).map((v) => (finite(v) && Number(v) > 0 ? Number(v) : null));
  const workoutDays = new Set(Array.isArray(data?.workout_days) ? data.workout_days : labels);
  const logged = [];
  labels.forEach((l, i) => { if (workoutDays.has(l)) logged.push(i); });
  const loggedSet = new Set(logged);
  // A long break only drifts as exercises fade out, which isn't strength: show it as a gap.
  let lastWorkoutDay = null;
  labels.forEach((l, i) => {
    const d = dayNumber(l);
    if (loggedSet.has(i)) lastWorkoutDay = d;
    else if (lastWorkoutDay !== null && d - lastWorkoutDay > BREAK_GAP_DAYS) values[i] = null;
  });
  if (!labels.length || firstFiniteIndex(values) === null) return null;

  const startIdx = rangeStartIndex(labels, range);
  const trend = trailingAverageByDate(labels, values, OVERALL_TREND_DAYS);
  const endIdx = lastFiniteIndex(trend);
  if (endIdx === null) return null;

  const firstLabel = labels[firstFiniteIndex(values)];
  const diff = trend[endIdx] - 100;
  const pctText = formatPercentChange(diff);
  let headline;
  let direction;
  if (diff >= 0.5) { headline = `+${pctText}`; direction = 'up'; }
  else if (diff <= -0.5) { headline = `−${pctText}`; direction = 'down'; }
  else { headline = '0%'; direction = 'flat'; }

  // The line under the headline: how it moved over the range (none for All: the headline is that).
  let change = null;
  if (range !== 'all') {
    const fromIdx = lastFiniteIndex(trend, startIdx) ?? firstFiniteIndex(trend, startIdx);
    if (fromIdx !== null && fromIdx < endIdx) {
      const from = Number(trend[fromIdx]);
      const to = Number(trend[endIdx]);
      const pct = from > 0 ? ((to / from) - 1) * 100 : 0;
      const when = RANGE_AGO[range] || '';
      change = Math.abs(pct) < 0.5
        ? { text: `About the same as ${when}`, direction: 'flat' }
        : { amount: formatPercentChange(pct), text: ` ${pct > 0 ? 'stronger' : 'weaker'} than ${when}`, direction: pct > 0 ? 'up' : 'down' };
    }
  }

  const inRange = logged.filter((i) => i >= startIdx && finite(values[i]));
  const bestIdx = inRange.length ? inRange.reduce((b, i) => (values[i] > values[b] ? i : b), inRange[0]) : null;
  const hl = strengthHighlights(data.exercises, range, labels[startIdx]);
  return {
    headline, direction, firstLabel, change,
    // The chart: the trend from the range start, as % against the start (ends on the headline).
    labels: labels.slice(startIdx),
    line: trend.slice(startIdx).map((v) => (finite(v) ? v - 100 : null)),
    best: bestIdx === null ? null : { text: formatVsStart(values[bestIdx]), day: labels[bestIdx] },
    newBests: hl.newBests,
    rangeText: RANGE_SHORT[range] || '',
    top: hl.top ? { name: hl.top.name, text: `+${formatPercentChange(hl.top.pct)}` } : null,
  };
}
