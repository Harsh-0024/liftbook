// Training balance: how many sets each muscle group got, per week, over a stretch of days.
// A quick read on what is getting the work and what is being skipped.

import { daysBetween } from './dates.js';
import { loggedSetCount } from './stats.js';
import { muscleGroup } from './coach_tools.js';

export const BALANCE_GROUPS = ['Chest', 'Back', 'Shoulders', 'Biceps', 'Triceps', 'Forearms', 'Legs', 'Abs', 'Other'];

/**
 * history: workout_logs rows ({date, exercise, sets}). from: first day counted ('' for all);
 * today: 'YYYY-MM-DD'. Returns null when nothing was logged in the stretch, else
 * { weeks, total, rows: [{ group, sets, perWeek, share }] } in the usual group order, with
 * groups that got nothing left out ("Other" too, unless it has sets).
 */
export function muscleBalance(history = [], { from = '', today }) {
  const sets = new Map();
  let first = '';
  for (const log of history) {
    const day = String(log?.date || '').slice(0, 10);
    if (!day || (from && day < from) || (today && day > today)) continue;
    if (!first || day < first) first = day;
    const g = muscleGroup(log.exercise);
    sets.set(g, (sets.get(g) || 0) + loggedSetCount(log));
  }
  if (!sets.size) return null;
  // A chosen range counts its whole length; "all" counts from the first workout.
  const span = daysBetween(from || first, today) + 1;
  const weeks = Math.max(1, span / 7);
  const total = [...sets.values()].reduce((a, b) => a + b, 0);
  const top = Math.max(...sets.values());
  const rows = BALANCE_GROUPS.filter((g) => sets.has(g)).map((group) => ({
    group,
    sets: sets.get(group),
    perWeek: Math.round((sets.get(group) / weeks) * 10) / 10,
    share: sets.get(group) / top,
  }));
  return { weeks, total, rows };
}
