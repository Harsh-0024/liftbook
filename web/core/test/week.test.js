// Home's week strip.
import test from 'node:test';
import assert from 'node:assert/strict';
import { weekStrip } from '../week.js';

test('the last 7 days, today last, with the trained ones marked', () => {
  const w = weekStrip(['2026-11-17', '2026-11-15', '2026-11-11', '2026-11-10'], '2026-11-17');
  assert.deepEqual(w.days.map((d) => d.day), ['2026-11-11', '2026-11-12', '2026-11-13', '2026-11-14', '2026-11-15', '2026-11-16', '2026-11-17']);
  assert.deepEqual(w.days.map((d) => d.letter).join(''), 'WTFSSMT');
  assert.deepEqual(w.days.map((d) => d.trained), [true, false, false, false, true, false, true]);
  assert.deepEqual(w.days.map((d) => d.today), [false, false, false, false, false, false, true]);
  assert.equal(w.days[6].name, 'Tuesday');
  assert.equal(w.count, 3); // the 10th is 8 days back
});

test('weeks in a row: calendar weeks, Monday to Sunday, that each had a workout', () => {
  // 17 Nov 2026 is a Tuesday. This week (16-22), the week before (9-15), 2-8 Nov, then a gap.
  assert.equal(weekStrip(['2026-11-17', '2026-11-09', '2026-11-08', '2026-10-10'], '2026-11-17').weeks, 3);
  assert.equal(weekStrip(['2026-11-17'], '2026-11-17').weeks, 1);
  assert.equal(weekStrip([], '2026-11-17').weeks, 0);
  // Sunday and the next Monday are two weeks.
  assert.equal(weekStrip(['2026-11-15', '2026-11-16'], '2026-11-16').weeks, 2);
});

test('this week with nothing yet does not end the run until Sunday is over', () => {
  // Tuesday 17 Nov, nothing since Monday, but the two weeks before both had one.
  const w = weekStrip(['2026-11-09', '2026-11-03'], '2026-11-17');
  assert.equal(w.count, 0);
  assert.equal(w.weeks, 2);
  // A whole week missed (9-15 Nov): the run is over, even though 8 Nov is only 9 days back.
  assert.equal(weekStrip(['2026-11-08', '2026-11-01'], '2026-11-17').weeks, 0);
});

test('month and year ends', () => {
  const w = weekStrip(['2026-12-31', '2027-01-02'], '2027-01-02');
  assert.deepEqual(w.days.map((d) => d.day)[0], '2026-12-27');
  assert.equal(w.count, 2);
});
