// Bodyweight over time, from the bodyweight saved with each workout's logs (the profile's
// weight on that day, or the one typed in the workout). One point per day.

/** history: workout_logs rows ({date, bodyweight}). Returns null with fewer than two days. */
export function bodyweightTrend(history = []) {
  const byDay = new Map();
  for (const log of history) {
    const w = Number(log?.bodyweight);
    const day = String(log?.date || '').slice(0, 10);
    if (!day || !Number.isFinite(w) || w <= 0) continue;
    byDay.set(day, w); // a day's logs carry the same weight; the last one wins
  }
  const labels = [...byDay.keys()].sort();
  if (labels.length < 2) return null;
  const values = labels.map((d) => byDay.get(d));
  const first = values[0];
  const current = values[values.length - 1];
  // Days the weight changed, newest last: what was actually weighed, not every workout.
  const changes = labels.filter((_, i) => i === 0 || Math.abs(values[i] - values[i - 1]) >= 0.05);
  if (changes.length < 2) return null;
  return {
    labels,
    values,
    first,
    firstDay: labels[0],
    current,
    change: Math.round((current - first) * 10) / 10,
    min: Math.min(...values),
    max: Math.max(...values),
    lastChanged: changes[changes.length - 1],
  };
}
