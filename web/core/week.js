// Home's week strip: the last 7 days (today last), which of them were trained, and how many
// weeks in a row had at least one workout.

import { addDays } from './dates.js';

const LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

const weekdayOf = (day) => {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
};

/**
 * workoutDays: the days with a workout ('YYYY-MM-DD', any order). today: the device's day.
 * Returns {days: [{day, letter, name, trained, today}], count, weeks}: the 7 days ending today,
 * how many of them were trained, and the run of 7-day stretches (counted back from today) that
 * each had a workout. A week with nothing yet doesn't end the run until it is over, so the run
 * is counted from last week when the current stretch is still empty.
 */
export function weekStrip(workoutDays, today) {
  const trained = new Set(workoutDays);
  const days = [];
  for (let i = 6; i >= 0; i -= 1) {
    const day = addDays(today, -i);
    const wd = weekdayOf(day);
    days.push({ day, letter: LETTERS[wd], name: NAMES[wd], trained: trained.has(day), today: i === 0 });
  }
  const has = (k) => {
    for (let i = 0; i < 7; i += 1) if (trained.has(addDays(today, -(7 * k + i)))) return true;
    return false;
  };
  let weeks = 0;
  const from = has(0) ? 0 : 1;
  while (weeks < 520 && has(from + weeks)) weeks += 1;
  return { days, count: days.filter((d) => d.trained).length, weeks };
}
