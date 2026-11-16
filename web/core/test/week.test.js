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

test('weeks in a row: 7-day stretches back from today that each had a workout', () => {
  // This stretch (11-17), the one before (4-10), the one before that (28 Oct-3 Nov), then a gap.
  assert.equal(weekStrip(['2026-11-17', '2026-11-05', '2026-10-28', '2026-10-10'], '2026-11-17').weeks, 3);
  assert.equal(weekStrip(['2026-11-17'], '2026-11-17').weeks, 1);
  assert.equal(weekStrip([], '2026-11-17').weeks, 0);
});

test('an empty current stretch does not end the run until it is over', () => {
  // Nothing in the last 7 days, but the two stretches before both had one.
  const w = weekStrip(['2026-11-09', '2026-11-01'], '2026-11-17');
  assert.equal(w.count, 0);
  assert.equal(w.weeks, 2);
  // Two empty stretches: the run is over.
  assert.equal(weekStrip(['2026-11-01'], '2026-11-17').weeks, 0);
});

test('month and year ends', () => {
  const w = weekStrip(['2026-12-31', '2027-01-02'], '2027-01-02');
  assert.deepEqual(w.days.map((d) => d.day)[0], '2026-12-27');
  assert.equal(w.count, 2);
});
