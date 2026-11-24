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
 * how many of them were trained, and the run of calendar weeks (Monday to Sunday) in a row that
 * each had a workout. This week counts once it has one; until then it doesn't end the run, since
 * there is still time, so the run is counted from last week.
 */
export function weekStrip(workoutDays, today) {
  const trained = new Set(workoutDays);
  const days = [];
  for (let i = 6; i >= 0; i -= 1) {
    const day = addDays(today, -i);
    const wd = weekdayOf(day);
    days.push({ day, letter: LETTERS[wd], name: NAMES[wd], trained: trained.has(day), today: i === 0 });
  }
  const monday = addDays(today, -((weekdayOf(today) + 6) % 7));
  const has = (k) => {
    for (let i = 0; i < 7; i += 1) if (trained.has(addDays(monday, i - 7 * k))) return true;
    return false;
  };
  let weeks = 0;
  const from = has(0) ? 0 : 1;
  while (weeks < 520 && has(from + weeks)) weeks += 1;
  return { days, count: days.filter((d) => d.trained).length, weeks };
}
