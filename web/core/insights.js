// Per-exercise insights for the workout page (services/workout_insights.py).
//
// Everything is scored with the same estimators as the medals (Epley e1RM for strength,
// weight × √seconds for timed) so the numbers on the page never contradict the badges.

import { estimate1rm, timedSetScore, bestWorkoutStrengthScore, bestWorkoutTimedScore } from './scoring.js';
import { formatG, formatFixed } from './py.js';

/** Trend: today vs the average of this many previous sessions. */
export const TREND_WINDOW = 3;
/** Changes inside ± this band read as "Steady". One extra rep is ~2%, so real gains still show. */
export const STEADY_BAND_PCT = 1.0;
export const SPARKLINE_SESSIONS = 8;

export const MEDAL_KEYS = new Set(['gold_strength', 'silver_strength', 'bronze_strength', 'gold_load', 'silver_load', 'bronze_load']);
export const BELOW_BEST_KEYS = new Set(['slightly_off', 'moderately_off', 'significantly_off']);
const MEDAL_EMOJI = { gold: '🥇', silver: '🥈', bronze: '🥉' };
const RANK_NAMES = ['strongest set', '2nd set', '3rd set'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const num = (v) => formatG(Number(v));

/** '+4.8%', '−12%', '+0.4%'. One decimal below 10%, whole numbers above. */
export function formatPct(value, { signed = true } = {}) {
  if (value === null || value === undefined) return '';
  const magnitude = Math.abs(Number(value));
  const text = magnitude >= 10 ? formatFixed(magnitude, 0) : formatFixed(magnitude, 1).replace(/0+$/, '').replace(/\.$/, '');
  if (!signed) return `${text}%`;
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${text}%`;
}

export function formatSet(weight, reps, { usesBodyweight, isTimed }) {
  const w = Number(weight);
  if (isTimed && !usesBodyweight && !w) return `${Math.trunc(reps)}s`;
  let load;
  if (usesBodyweight) load = w === 0 ? 'BW' : w > 0 ? `BW+${num(w)}` : `BW−${num(-w)}`;
  else load = num(w);
  return isTimed ? `${load}×${Math.trunc(reps)}s` : `${load}×${Math.trunc(reps)}`;
}

function pairs(sets) {
  if (!sets || typeof sets !== 'object') return [];
  const ws = sets.weights || [];
  const rs = sets.reps || [];
  const out = [];
  for (let i = 0; i < Math.min(ws.length, rs.length); i++) {
    const w = Number(ws[i]);
    const r = Number(rs[i]);
    if (ws[i] === null || rs[i] === null || Number.isNaN(w) || Number.isNaN(r)) continue;
    out.push([w, Math.trunc(r)]);
  }
  return out;
}

/** Sets in the order they were logged: '50×14 · 50×13 · 43.6×13'. */
export function formatSetsLine(sets, opts) {
  return pairs(sets).filter(([, r]) => r > 0).map(([w, r]) => formatSet(w, r, opts)).join(' · ');
}

/**
 * The sets as the person thinks of them: for bodyweight exercises, the load added on top of
 * bodyweight (routes/workouts.py _display_sets).
 */
export function displaySets(log, effective, usesBodyweight) {
  const raw = log?.sets ?? log?.sets_json ?? null;
  if (!usesBodyweight || !effective) return raw;
  if (log.bodyweight === null || log.bodyweight === undefined) {
    // No bodyweight saved: loads were stored as offsets, with 1 as the old "just BW" marker.
    const weights = (raw?.weights || []).map((w) => (Number.isNaN(Number(w)) ? w : Number(w) <= 1 ? 0 : Number(w)));
    return { weights, reps: [...(raw?.reps || [])] };
  }
  const bw = Number(log.bodyweight);
  const weights = (effective.weights || []).map((w) => (Number.isNaN(Number(w)) ? w : Math.round((Number(w) - bw) * 100) / 100));
  return { weights, reps: [...(effective.reps || [])] };
}

const setScore = (w, r, isTimed) => (isTimed ? timedSetScore(w, r) || 0 : estimate1rm(w, r) || 0);

/** Sets strongest first: scored on effective loads (bodyweight added), labelled as logged. */
export function rankedSets(loggedSets, effectiveSets, { usesBodyweight, isTimed }) {
  const logged = pairs(loggedSets);
  const rows = [];
  pairs(effectiveSets).forEach(([w, r], i) => {
    const score = setScore(w, r, isTimed);
    if (score <= 0) return;
    const [rw, rr] = i < logged.length ? logged[i] : [w, r];
    rows.push({ score, effective_weight: w, label: formatSet(rw, rr, { usesBodyweight, isTimed }) });
  });
  return rows.sort((a, b) => b.score - a.score || b.effective_weight - a.effective_weight);
}

/** Whole-exercise score: strongest set + 25% credit for the next-best sets. */
export function sessionScore(effectiveSets, { topN, isTimed }) {
  const r = isTimed ? bestWorkoutTimedScore(effectiveSets || {}, { top_n: topN }) : bestWorkoutStrengthScore(effectiveSets || {}, { top_n: topN });
  return Number(r.score) || 0;
}

export function pctChange(current, reference) {
  if (!current || !reference || reference <= 0) return null;
  return ((current - reference) / reference) * 100;
}

function direction(pct, band = STEADY_BAND_PCT) {
  if (pct === null || pct === undefined) return null;
  if (pct >= band) return 'up';
  if (pct <= -band) return 'down';
  return 'steady';
}

export function ordinal(n) {
  const suffix = n % 100 >= 10 && n % 100 <= 20 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${suffix}`;
}

function deltaCell(mine, theirs) {
  if (!theirs) return null;
  const pct = mine ? pctChange(mine.score, theirs.score) : null;
  const text = pct === null ? '' : Math.abs(pct) < 0.05 ? 'same' : formatPct(pct);
  return { label: theirs.label, pct, pct_text: text, direction: direction(pct, 0.05) };
}

/** Today's sets strongest first, with last session and best beside them, matched by strength rank. */
export function compareColumns(today, last = null, best = null) {
  const l = last || [];
  const b = best || [];
  const rows = [];
  for (let i = 0; i < Math.max(today.length, l.length, b.length); i++) {
    const mine = today[i] || null;
    rows.push({
      rank: ordinal(i + 1),
      today: mine ? mine.label : '—',
      last: i < l.length ? deltaCell(mine, l[i]) : (l.length ? { label: '—' } : null),
      best: i < b.length ? deltaCell(mine, b[i]) : (b.length ? { label: '—' } : null),
    });
  }
  return rows;
}

/** Today's session score vs the average of the last TREND_WINDOW sessions. previous: newest first. */
export function trend(todayScore, previous) {
  const window = previous.filter((r) => r.score).slice(0, TREND_WINDOW);
  if (!todayScore || !window.length) return null;
  const average = window.reduce((a, r) => a + r.score, 0) / window.length;
  const pct = pctChange(todayScore, average);
  const dir = direction(pct);
  const text = dir === 'up' ? `↑ ${formatPct(pct, { signed: false })}` : dir === 'down' ? `↓ ${formatPct(pct, { signed: false })}` : '→ Steady';
  return { pct, direction: dir, text, average, days: window.map((r) => r.day).reverse(), count: window.length };
}

const lowerFirst = (t) => (t ? t[0].toLowerCase() + t.slice(1) : t);
const matchedPrefix = (i) => (i === 1 ? 'Your strongest set matched your best' : 'Your top two sets matched your best');

/** The short "vs best" chip for a row, and a sentence explaining it. */
export function bestSummary(perf, { hasHistory }) {
  const key = perf?.key || '';
  const pct = perf?.diff_pct ?? null;
  const idx = perf?.diff_index || 0;
  const rank = idx < RANK_NAMES.length ? RANK_NAMES[idx] : `${ordinal(idx + 1)} set`;
  const tier = key.split('_')[0];
  if (MEDAL_KEYS.has(key)) {
    const by = formatPct(pct, { signed: false });
    let explain;
    if (key.endsWith('_load')) explain = `New best: same strength as your best, with ${by} more weight on your ${rank}.`;
    else if (idx === 0) explain = `New best: your strongest set beat your best by ${by}.`;
    else explain = `New best: ${lowerFirst(matchedPrefix(idx))}, and your ${rank} beat it by ${by}.`;
    return { kind: 'medal', tier, emoji: MEDAL_EMOJI[tier] || '🥇', chip: pct !== null ? formatPct(pct) : '', explain };
  }
  if (BELOW_BEST_KEYS.has(key)) {
    let gap = pct !== null ? formatPct(pct, { signed: false }) : '';
    let chip;
    if (pct !== null && Math.abs(pct) < 0.95) {
      chip = '<1%';
      gap = 'less than 1%';
    } else chip = gap ? `−${gap}` : 'Below';
    const explain = idx === 0 ? `Your strongest set was ${gap} below your best.` : `${matchedPrefix(idx)}, but your ${rank} was ${gap} below it.`;
    return { kind: 'below', emoji: '', chip, explain };
  }
  if (key === 'consistent') return { kind: 'match', emoji: '', chip: '= Best', explain: 'You matched your best exactly.' };
  if (hasHistory) return { kind: 'first', emoji: '', chip: '✦ New', explain: 'No earlier session with the same number of sets to compare against yet.' };
  return { kind: 'first', emoji: '', chip: '✦ First', explain: 'First time logged, so this sets your baseline.' };
}

/** Coordinates for a small SVG line chart. points oldest first: {score, ...anything else kept}. */
export function sparkline(points, { average = null, width = 600, height = 110, pad = 10 } = {}) {
  const usable = points.filter((p) => p.score);
  if (usable.length < 2) return null;
  const values = usable.map((p) => p.score);
  if (average) values.push(average);
  let low = Math.min(...values);
  let high = Math.max(...values);
  const span = (high - low) || Math.max(high * 0.05, 1);
  low -= span * 0.1;
  high += span * 0.1;
  const r1 = (v) => Math.round(v * 10) / 10;
  const yOf = (v) => r1(pad + (height - 2 * pad) * (1 - (v - low) / (high - low)));
  const step = (width - 2 * pad) / (usable.length - 1);
  const dots = usable.map((p, i) => ({ ...p, x: r1(pad + i * step), y: yOf(p.score) }));
  return {
    width, height, dots,
    path: dots.map((d, i) => `${i ? 'L' : 'M'}${d.x},${d.y}`).join(' '),
    average_y: average ? yOf(average) : null,
  };
}

const ymd = (day) => String(day).slice(0, 10).split('-').map(Number);

/** '10 Aug', or '10 Aug 2025' when the year differs from refYear. */
export function shortDate(day, refYear = null) {
  const [y, m, d] = ymd(day);
  return `${d} ${MONTHS[m - 1]}${refYear !== null && y !== refYear ? ` ${y}` : ''}`;
}

/** 'Sat, 12 Jul 2026'. */
export function longDate(day) {
  const [y, m, d] = ymd(day);
  return `${WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]}, ${d} ${MONTHS[m - 1]} ${y}`;
}
