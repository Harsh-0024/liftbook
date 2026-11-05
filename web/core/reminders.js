// Reminders: when to send a gentle notification, worked out from the workouts and the settings.
// Plain data in, plain data out (no clock, no device): the app passes "now" and schedules what
// this returns with the phone's own notifications (app/native.js). Times are the device's local
// wall-clock times ("YYYY-MM-DDTHH:MM"), like workout dates.
//
// Two kinds:
//  - "gap":     no workout for longer than usual (the usual number of days between workouts,
//               worked out from recent training, or set by hand). One reminder, the next one due.
//  - "planned": a workout planned for a day and time (once, or every week on a weekday),
//               PLANNED_LEAD_MIN minutes before it starts.
// Nothing is sent in quiet hours: a reminder that falls in them moves to when they end, or is
// dropped if that's too late to still be useful.

import { addDays, daysBetween } from './dates.js';

export const DEFAULT_REMINDERS = Object.freeze({
  on: false,
  quietFrom: '22:00',
  quietTo: '07:00',
  gapDays: 'auto', // or a whole number of days
});
export const GAP_REMINDER_TIME = '09:00'; // a gap reminder comes in the morning
export const PLANNED_LEAD_MIN = 30; // a planned workout's reminder comes this long before it
export const DEFAULT_GAP_DAYS = 3; // until there's enough history to tell
export const HORIZON_DAYS = 14; // how far ahead reminders are scheduled
const LOOKBACK_DAYS = 56;

const pad = (n) => String(n).padStart(2, '0');
const minutesOf = (hhmm) => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || ''));
  return m ? Math.min(23, Number(m[1])) * 60 + Math.min(59, Number(m[2])) : null;
};
const hhmm = (mins) => `${pad(Math.floor(mins / 60))}:${pad(mins % 60)}`;
const dayOfWeek = (day) => {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = Sunday
};
const at = (day, mins) => `${day}T${hhmm(mins)}`;
const splitAt = (stamp) => [stamp.slice(0, 10), minutesOf(stamp.slice(11, 16))];

/** The settings as saved, with defaults filled in and odd values cleaned up. */
export function reminderSettings(saved = {}) {
  const s = { ...DEFAULT_REMINDERS, ...(saved && typeof saved === 'object' ? saved : {}) };
  s.on = s.on === true;
  if (minutesOf(s.quietFrom) === null) s.quietFrom = DEFAULT_REMINDERS.quietFrom;
  if (minutesOf(s.quietTo) === null) s.quietTo = DEFAULT_REMINDERS.quietTo;
  const n = Number(s.gapDays);
  s.gapDays = s.gapDays === 'auto' || !Number.isInteger(n) || n < 1 ? 'auto' : Math.min(n, 30);
  return s;
}

/**
 * The usual number of days from one workout to the next: the median over the last eight weeks
 * (at least three gaps), between 1 and 14. null when there isn't enough training to tell.
 * days: workout days ("YYYY-MM-DD"), any order.
 */
export function usualGapDays(days, today) {
  const recent = [...new Set(days)].filter((d) => d <= today && daysBetween(d, today) <= LOOKBACK_DAYS).sort();
  const gaps = [];
  for (let i = 1; i < recent.length; i++) gaps.push(daysBetween(recent[i - 1], recent[i]));
  if (gaps.length < 3) return null;
  gaps.sort((a, b) => a - b);
  const mid = gaps.length / 2;
  const median = gaps.length % 2 ? gaps[Math.floor(mid)] : (gaps[mid - 1] + gaps[mid]) / 2;
  return Math.max(1, Math.min(14, Math.round(median)));
}

/** Whether a minute of the day (0-1439) is inside quiet hours (which may run past midnight). */
export function inQuietHours(mins, settings) {
  const from = minutesOf(settings.quietFrom);
  const to = minutesOf(settings.quietTo);
  if (from === to) return false; // no quiet window
  return from < to ? mins >= from && mins < to : mins >= from || mins < to;
}

/** The time itself, or when quiet hours end if it falls in them ("YYYY-MM-DDTHH:MM"). */
export function afterQuietHours(stamp, settings) {
  const [day, mins] = splitAt(stamp);
  if (!inQuietHours(mins, settings)) return stamp;
  const to = minutesOf(settings.quietTo);
  // Quiet hours that started the evening before end today; ones that start tonight end tomorrow.
  return mins < to ? at(day, to) : at(addDays(day, 1), to);
}

/** The next dates a planned workout happens on, from `today` on, within the horizon. */
function occurrences(plan, today, horizon) {
  if (plan.date) return plan.date >= today && daysBetween(today, plan.date) <= horizon ? [plan.date] : [];
  if (Number.isInteger(plan.weekday) && plan.weekday >= 0 && plan.weekday <= 6) {
    const out = [];
    for (let i = 0; i <= horizon; i++) {
      const d = addDays(today, i);
      if (dayOfWeek(d) === plan.weekday) out.push(d);
    }
    return out;
  }
  return [];
}

/** Planned workouts as saved, cleaned up: each has an id, a time, and a date or a weekday. */
export function plannedWorkouts(saved) {
  return (Array.isArray(saved) ? saved : []).filter((p) => p && p.id && minutesOf(p.time) !== null
    && (/^\d{4}-\d{2}-\d{2}$/.test(p.date || '') || Number.isInteger(p.weekday)));
}

/** "Session 2 - Pull", or "Workout" when the plan has no name. */
export const plannedTitle = (p) => String(p.title || '').trim() || 'Workout';

/**
 * Every reminder to schedule: [{ key, kind, at: "YYYY-MM-DDTHH:MM", title, body }], soonest first.
 * now: "YYYY-MM-DDTHH:MM" on the device's clock. workoutDays: days with a workout.
 * Nothing when reminders are off.
 */
export function upcomingReminders({ now, workoutDays = [], settings: saved = {}, planned = [], horizonDays = HORIZON_DAYS }) {
  const settings = reminderSettings(saved);
  if (!settings.on) return [];
  const [today] = splitAt(now);
  const out = [];
  const keep = (r) => { if (r.at > now) out.push(r); };

  // Not trained for longer than usual: the morning after the usual gap has passed.
  const days = [...new Set(workoutDays)].filter((d) => d <= today).sort();
  const last = days[days.length - 1];
  if (last) {
    const usual = settings.gapDays === 'auto' ? usualGapDays(days, today) ?? DEFAULT_GAP_DAYS : settings.gapDays;
    let due = afterQuietHours(at(addDays(last, usual + 1), minutesOf(GAP_REMINDER_TIME)), settings);
    // Already past (no workout since): once more tomorrow morning, then it stays quiet.
    if (due <= now) due = afterQuietHours(at(addDays(today, 1), minutesOf(GAP_REMINDER_TIME)), settings);
    const away = daysBetween(last, due.slice(0, 10));
    if (away <= usual + 3) {
      keep({
        key: `gap:${last}`, kind: 'gap', at: due, title: 'Time for a workout?', route: 'log',
        body: `${away} days since your last one. You usually train every ${usual === 1 ? 'day' : `${usual} days`}.`,
      });
    }
  }

  // Planned workouts: a little before each one, never in quiet hours.
  const trainedOn = new Set(workoutDays);
  for (const plan of plannedWorkouts(planned)) {
    const start = minutesOf(plan.time);
    for (const day of occurrences(plan, today, horizonDays)) {
      if (trainedOn.has(day)) continue; // already trained that day
      const begins = at(day, start);
      const early = start - PLANNED_LEAD_MIN;
      const wanted = early >= 0 ? at(day, early) : at(addDays(day, -1), 1440 + early);
      const when = afterQuietHours(wanted, settings);
      if (when > begins) continue; // quiet until after it starts: no reminder
      keep({
        key: `planned:${plan.id}:${day}`, kind: 'planned', at: when, title: plannedTitle(plan),
        body: `Planned for ${plan.time} ${when.slice(0, 10) === day ? 'today' : 'tomorrow'}. Tap to see what to aim for.`,
        plan: plan.id, day,
        // Tapping it opens that session's targets (or Retrieve when it isn't one of the plan's).
        route: plan.category && plan.dayId ? `retrieve/day/${encodeURIComponent(plan.category)}/${plan.dayId}` : 'retrieve',
      });
    }
  }
  return out.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
}

/** A whole number (the phone needs one per notification) that stays the same for a key. */
export function notificationId(key) {
  let h = 2166136261;
  for (const ch of String(key)) h = Math.imul(h ^ ch.codePointAt(0), 16777619);
  return (h >>> 1) || 1; // positive 31-bit
}
