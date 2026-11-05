// Dates and times without a time zone ("naive", as Python's datetime and the workout_logs.date
// column keep them): "YYYY-MM-DDTHH:MM:SS" strings, so no device time zone ever shifts them.

function pad(n, width = 2) {
  return String(n).padStart(width, '0');
}

/** A date-time string (or a JS Date, read in local time, or nothing for now) -> its parts. */
export function parseDate(value) {
  if (value === undefined || value === null) value = new Date();
  if (value instanceof Date) {
    return {
      year: value.getFullYear(), month: value.getMonth() + 1, day: value.getDate(),
      hour: value.getHours(), minute: value.getMinutes(), second: value.getSeconds(),
      micro: value.getMilliseconds() * 1000,
    };
  }
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?/.exec(String(value));
  if (!m) throw new Error(`not a date: ${value}`);
  return {
    year: Number(m[1]), month: Number(m[2]), day: Number(m[3]),
    hour: Number(m[4] || 0), minute: Number(m[5] || 0), second: Number(m[6] || 0),
    micro: m[7] ? Number(m[7].padEnd(6, '0')) : 0,
  };
}

/** Parts -> "YYYY-MM-DDTHH:MM:SS" (with ".ffffff" when there are microseconds), as isoformat(). */
export function formatDateTime(p) {
  const base = `${pad(p.year, 4)}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
  return p.micro ? `${base}.${pad(p.micro, 6)}` : base;
}

export function makeDate(year, month, day) {
  return formatDateTime({ year, month, day, hour: 0, minute: 0, second: 0, micro: 0 });
}

function isLeap(y) {
  return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
}

export function daysInMonth(y, m) {
  return [31, isLeap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
}

/** Whether datetime(year, month, day) exists. */
export function isValidDate(y, m, d) {
  return Number.isInteger(y) && y >= 1 && y <= 9999 && m >= 1 && m <= 12 && d >= 1 && d <= daysInMonth(y, m);
}

// Days since 0001-01-01 (as date.toordinal() - 1), and back.
function ordinal(y, m, d) {
  const yy = y - 1;
  let days = yy * 365 + Math.floor(yy / 4) - Math.floor(yy / 100) + Math.floor(yy / 400);
  for (let k = 1; k < m; k++) days += daysInMonth(y, k);
  return days + d - 1;
}

function fromOrdinal(n) {
  // 400-year cycles have 146097 days
  let y = 1 + 400 * Math.floor(n / 146097);
  n %= 146097;
  while (true) {
    const len = isLeap(y) ? 366 : 365;
    if (n < len) break;
    n -= len;
    y++;
  }
  let m = 1;
  while (n >= daysInMonth(y, m)) {
    n -= daysInMonth(y, m);
    m++;
  }
  return { year: y, month: m, day: n + 1 };
}

/** The calendar day ("YYYY-MM-DD") of a date-time, moved by `offsetMinutes` (local_date()). */
export function localDay(value, offsetMinutes = 0) {
  if (!value) return null;
  const p = parseDate(value);
  const totalMinutes = p.hour * 60 + p.minute + offsetMinutes;
  const dayShift = Math.floor(totalMinutes / 1440);
  const d = fromOrdinal(ordinal(p.year, p.month, p.day) + dayShift);
  return `${pad(d.year, 4)}-${pad(d.month)}-${pad(d.day)}`;
}

/** The calendar day ("YYYY-MM-DD") on this device's clock, or of a Date or ISO time read on it.
 *  (new Date().toISOString() gives the UTC day, which is yesterday in India before 5:30 am.) */
export function deviceDay(value = new Date()) {
  const d = value instanceof Date ? value : new Date(Date.parse(value));
  return `${pad(d.getFullYear(), 4)}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Whole days from day a to day b ("YYYY-MM-DD"). */
export function daysBetween(a, b) {
  const pa = parseDate(a);
  const pb = parseDate(b);
  return ordinal(pb.year, pb.month, pb.day) - ordinal(pa.year, pa.month, pa.day);
}

/** day + n days. */
export function addDays(day, n) {
  const p = parseDate(day);
  const d = fromOrdinal(ordinal(p.year, p.month, p.day) + n);
  return `${pad(d.year, 4)}-${pad(d.month)}-${pad(d.day)}`;
}

/** Compare two date-time strings: -1, 0 or 1. */
export function compareDates(a, b) {
  const pa = parseDate(a);
  const pb = parseDate(b);
  for (const k of ['year', 'month', 'day', 'hour', 'minute', 'second', 'micro']) {
    if (pa[k] !== pb[k]) return pa[k] < pb[k] ? -1 : 1;
  }
  return 0;
}

/** The date as Retrieve's header writes it: "31/10/26", for an India (UTC+5:30) day by default. */
export function retrieveDateString(nowUtc = new Date(), offsetMinutes = 330) {
  const t = new Date(nowUtc.getTime() + offsetMinutes * 60000);
  return `${t.getUTCDate()}/${t.getUTCMonth() + 1}/${pad(t.getUTCFullYear() % 100)}`;
}
