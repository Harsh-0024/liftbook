// Bulk import: many workout days pasted at once, each starting with a date line.
// A port of the old bulk_import route (liftbook/routes/auth.py): how it finds the days and how it
// guesses a year that wasn't written.

import { isValidDate, makeDate } from './dates.js';

const MONTHS = {
  jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4, may: 5,
  jun: 6, june: 6, jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9, september: 9,
  oct: 10, october: 10, nov: 11, november: 11, dec: 12, december: 12,
};

const WEEKDAY_BEFORE_DATE = new RegExp(
  '^(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)'
  + '\\.?,?\\s+(?=\\d{1,2}[/.\\-]\\d|\\d{4}-\\d|\\d{1,2}(?:st|nd|rd|th)?\\s+[A-Za-z]{3}|[A-Za-z]{3,9}\\.?\\s+\\d)',
  'i',
);

const year = (s) => {
  if (!s) return null;
  const y = Number(s);
  return y < 100 ? 2000 + y : y;
};

/** {day, month, year|null} when the line starts a new day, else null. */
export function dateHeader(line) {
  let s = String(line || '').trim();
  if (!s || s.startsWith('#')) return null;
  const weekday = WEEKDAY_BEFORE_DATE.exec(s);
  if (weekday) s = s.slice(weekday[0].length);
  // yyyy-mm-dd, as exports from other apps write it
  let m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?=\s|$|[-–—:,])/.exec(s);
  if (m) return { day: Number(m[3]), month: Number(m[2]), year: Number(m[1]) };
  // dd.mm.yy / dd-mm-yyyy: only with a year, so a weight like "12.5" isn't 12 May
  m = /^(\d{1,2})[.-](\d{1,2})[.-](\d{2}|\d{4})(?=\s|$|[-–—:,])/.exec(s);
  if (m) return { day: Number(m[1]), month: Number(m[2]), year: year(m[3]) };
  // dd/mm[/yy]
  m = /^\s*(\d{1,2})\s*\/\s*(\d{1,2})(?:\s*\/\s*(\d{2,4}))?/.exec(s);
  if (m) return { day: Number(m[1]), month: Number(m[2]), year: year(m[3]) };
  // dd Mon [yy]: a month's name or its short form only, so "3 Decline Press" isn't 3 December
  m = /^\s*(\d{1,2})\s*([A-Za-z]{3,9})\b\.?\s*(\d{2,4})?/.exec(s);
  if (m) {
    const month = MONTHS[m[2].toLowerCase()];
    return month ? { day: Number(m[1]), month, year: year(m[3]) } : null;
  }
  return null;
}

/** The pasted text as days: [{text, start, end, header}], lines counted from 1. */
export function splitDays(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').trim().split('\n').map((l) => l.trimEnd());
  const blocks = [];
  let current = null;
  lines.forEach((line, i) => {
    const header = dateHeader(line);
    if (header) {
      if (current) blocks.push({ ...current, end: i });
      current = { lines: [line], start: i + 1, header };
    } else if (current) {
      current.lines.push(line);
    }
  });
  if (current) blocks.push({ ...current, end: lines.length });
  return blocks
    .map(({ lines: ls, ...b }) => ({ ...b, text: ls.join('\n').trim() }))
    .filter((b) => b.text);
}

const dateOf = (y, m, d) => (isValidDate(y, m, d) ? makeDate(y, m, d).slice(0, 10) : null);

/**
 * A date (yyyy-mm-dd, or null when it can't be one) for each header. A missing year follows the
 * day before it, moving on a year when the date would go backwards; before any dated day it takes
 * the next written year, or this year.
 */
export function inferDates(headers, today = new Date()) {
  const out = [];
  headers.forEach((h, i) => {
    if (!h) return out.push(null);
    if (h.year !== null && h.year !== undefined) return out.push(dateOf(h.year, h.month, h.day));
    const prev = [...out].reverse().find(Boolean);
    if (prev) {
      let y = Number(prev.slice(0, 4));
      let candidate = dateOf(y, h.month, h.day);
      while (candidate && candidate < prev) candidate = dateOf(++y, h.month, h.day);
      return out.push(candidate);
    }
    const next = headers.slice(i + 1).find((f) => f && f.year !== null && f.year !== undefined);
    let y = today.getFullYear();
    if (next) {
      y = next.year;
      const nextDate = dateOf(next.year, next.month, next.day);
      const candidate = dateOf(y, h.month, h.day);
      if (nextDate && candidate && candidate > nextDate) y -= 1;
    }
    return out.push(dateOf(y, h.month, h.day));
  });
  return out;
}
