// Stats "Consistency": one calendar year at a time, as the original Stats page showed it
// (templates/stats.html: consistencyYears, yearWindow, updateConsistencyHero/Tiles, levelFor).
// Days are 'YYYY-MM-DD' in the person's own calendar.

export const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
export const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const MONTHS = MONTH_NAMES.map((m) => m.slice(0, 3));

export const dateOf = (iso) => { const [y, m, d] = String(iso).split('-').map(Number); return new Date(y, m - 1, d); };
export const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
export const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
export const mondayOf = (d) => addDays(d, -((d.getDay() + 6) % 7));
export const daysBetween = (a, b) => Math.round((b - a) / 86400000);
const dayOnly = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

/** Every year from the first workout to this one. */
export function consistencyYears(dayList, today = new Date()) {
  const now = today.getFullYear();
  const first = dayList.length ? Math.min(Number(dayList[0].slice(0, 4)), now) : now;
  const years = [];
  for (let y = first; y <= now; y += 1) years.push(y);
  return years;
}

export function yearWindow(year, today = new Date()) {
  const t = dayOnly(today);
  const isCurrent = year === t.getFullYear();
  return { year, isCurrent, today: t, start: new Date(year, 0, 1), yearEnd: new Date(year, 11, 31), end: isCurrent ? t : new Date(year, 11, 31) };
}

const countBetween = (dayList, start, end) => {
  const a = isoOf(start);
  const b = isoOf(end);
  return dayList.filter((d) => d >= a && d <= b).length;
};

/**
 * The headline (workouts a week that year; in the year you started, counted from your first
 * workout) and, when you trained the year before too, the change against the same stretch of it.
 */
export function consistencyHero(dayList, win) {
  const weeksOf = (a, b) => Math.max(1, (daysBetween(a, b) + 1) / 7);
  const firstDay = dayList.length ? dateOf(dayList[0]) : null;
  const startedThisYear = Boolean(firstDay && firstDay > win.start && firstDay <= win.end);
  const from = startedThisYear ? firstDay : win.start;
  const perWeek = Number((countBetween(dayList, win.start, win.end) / weeksOf(from, win.end)).toFixed(1));
  const caption = startedThisYear
    ? `workouts a week since ${MONTHS[firstDay.getMonth()]} ${firstDay.getDate()}`
    : `workouts a week in ${win.year}`;
  let change = null;
  const prevStart = new Date(win.year - 1, 0, 1);
  const prevEnd = new Date(win.year - 1, win.end.getMonth(), win.end.getDate());
  if (dayList.length && dateOf(dayList[0]) <= prevStart) {
    const before = Number((countBetween(dayList, prevStart, prevEnd) / weeksOf(prevStart, prevEnd)).toFixed(1));
    const diff = Number((perWeek - before).toFixed(1));
    const than = win.isCurrent ? 'this time last year' : String(win.year - 1);
    change = Math.abs(diff) < 0.1
      ? { text: `About the same as ${than}`, direction: 'flat' }
      : { amount: Math.abs(diff).toFixed(1), text: ` ${diff > 0 ? 'more' : 'fewer'} a week than ${than}`, direction: diff > 0 ? 'up' : 'down' };
  }
  return { value: perWeek.toFixed(1), caption, change };
}

/** Workouts that year, busiest month, favourite day (ties: the earlier day, Monday first). */
export function consistencyTiles(dayList, win, { short = false } = {}) {
  const a = isoOf(win.start);
  const b = isoOf(win.end);
  const inYear = dayList.filter((d) => d >= a && d <= b);
  const workouts = (n) => `${n} workout${n === 1 ? '' : 's'}`;
  const byMonth = new Array(12).fill(0);
  inYear.forEach((d) => { byMonth[Number(d.slice(5, 7)) - 1] += 1; });
  const topMonth = Math.max(...byMonth);
  const byDay = [0, 0, 0, 0, 0, 0, 0];
  inYear.forEach((d) => { byDay[dateOf(d).getDay()] += 1; });
  const most = Math.max(...byDay);
  const fav = [1, 2, 3, 4, 5, 6, 0].find((i) => byDay[i] === most);
  return {
    workouts: { value: String(inYear.length), sub: `in ${win.year}` },
    month: topMonth > 0
      ? { value: short ? MONTHS[byMonth.indexOf(topMonth)] : MONTH_NAMES[byMonth.indexOf(topMonth)], sub: workouts(topMonth) }
      : { value: '–', sub: `in ${win.year}` },
    day: most > 0
      ? { value: short ? WEEKDAYS[fav].slice(0, 3) : WEEKDAYS[fav], sub: workouts(most) }
      : { value: '–', sub: `in ${win.year}` },
  };
}

/** Busier days (more sets) get deeper gold: four steps, split at your own quartiles. */
export function levelFor(daySets) {
  const vals = Object.values(daySets || {}).map(Number).filter((v) => v > 0).sort((x, y) => x - y);
  if (vals.length < 4) return () => 3;
  const q = (p) => vals[Math.floor(p * (vals.length - 1))];
  const t1 = q(0.25);
  const t2 = q(0.5);
  const t3 = q(0.75);
  return (n) => (!(n > 0) ? 3 : n <= t1 ? 1 : n <= t2 ? 2 : n <= t3 ? 3 : 4);
}

/**
 * The year as weeks (Monday first) of days: {iso, out, future, today, on, level, sets, title}.
 * Plus where each month's label starts (week column).
 */
export function yearGrid(win, trainedDays, { titles = {}, daySets = {} } = {}) {
  const trained = new Set(trainedDays);
  const level = levelFor(daySets);
  const first = mondayOf(win.start);
  const last = addDays(mondayOf(win.yearEnd), 6);
  const weekCount = (daysBetween(first, last) + 1) / 7;
  const todayIso = isoOf(win.today);
  const weeks = [];
  for (let c = 0; c < weekCount; c += 1) {
    const week = [];
    for (let i = 0; i < 7; i += 1) {
      const d = addDays(first, 7 * c + i);
      const iso = isoOf(d);
      if (d.getFullYear() !== win.year) week.push({ iso, out: true });
      else if (iso > todayIso) week.push({ iso, future: true });
      else {
        const sets = Number(daySets[iso]) || 0;
        const on = trained.has(iso);
        week.push({ iso, on, today: iso === todayIso, level: on ? level(sets) : 0, sets, title: on ? (titles[iso] || 'Workout') : '' });
      }
    }
    weeks.push(week);
  }
  const months = MONTHS.map((name, m) => ({ name, col: Math.ceil(daysBetween(first, new Date(win.year, m, 1)) / 7) }));
  return { weeks, months };
}
