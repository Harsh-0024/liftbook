import test from 'node:test';
import assert from 'node:assert/strict';
import { dateHeader, splitDays, inferDates } from '../bulk.js';

test('date lines start a day; weights and exercise names do not', () => {
  assert.deepEqual(dateHeader('03/02 Back & Bicep'), { day: 3, month: 2, year: null });
  assert.deepEqual(dateHeader('3/2/25 Push'), { day: 3, month: 2, year: 2025 });
  assert.deepEqual(dateHeader('2025-02-03 Legs'), { day: 3, month: 2, year: 2025 });
  assert.deepEqual(dateHeader('03.02.25 Pull'), { day: 3, month: 2, year: 2025 });
  assert.deepEqual(dateHeader('20 nov - Chest'), { day: 20, month: 11, year: null });
  assert.deepEqual(dateHeader('Monday 28/9 Push'), { day: 28, month: 9, year: null });
  assert.deepEqual(dateHeader('Tue, 29 Sep 25 Pull'), { day: 29, month: 9, year: 2025 });
  assert.equal(dateHeader('12.5 10, 8 8'), null);
  assert.equal(dateHeader('3 Decline Press'), null);
  assert.equal(dateHeader('#Gym 03/02'), null);
  assert.equal(dateHeader('Bench Press - [6-10]'), null);
});

test('pasted text splits into days, with their line numbers', () => {
  const days = splitDays('notes first\n03/02 Back\nPull-Ups\nbw, 10 8 6\n\n04/02 Chest\nBench Press\n80 75, 8 10\n');
  assert.deepEqual(days.map((d) => [d.start, d.end, d.text.split('\n')[0]]), [[2, 5, '03/02 Back'], [6, 8, '04/02 Chest']]);
  assert.equal(days[0].text, '03/02 Back\nPull-Ups\nbw, 10 8 6');
});

test('a missing year follows the day before and rolls into the next year', () => {
  const today = new Date(2026, 10, 4);
  const h = (day, month, year = null) => ({ day, month, year });
  assert.deepEqual(inferDates([h(28, 12), h(2, 1)], today), ['2026-12-28', '2027-01-02']);
  assert.deepEqual(inferDates([h(20, 11), h(5, 1, 2025)], today), ['2024-11-20', '2025-01-05']);
  assert.deepEqual(inferDates([h(31, 2), h(1, 3)], today), [null, '2026-03-01']);
  assert.deepEqual(inferDates([h(10, 10, 2026), h(9, 10), h(1, 1)], today), ['2026-10-10', '2027-10-09', '2028-01-01']);
});
