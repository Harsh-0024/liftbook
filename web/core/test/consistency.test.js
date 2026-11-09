// Stats "Consistency" against what the original Stats page showed for the demo user's 36
// workouts on 4 Nov 2026.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { consistencyYears, yearWindow, consistencyHero, consistencyTiles, levelFor, yearGrid } from '../consistency.js';

const days = JSON.parse(readFileSync(new URL('./fixtures/overall_demo.json', import.meta.url))).workout_days.slice().sort();
const today = new Date(2026, 10, 4);

test('headline and tiles match the original page', () => {
  assert.deepEqual(consistencyYears(days, today), [2026]);
  const win = yearWindow(2026, today);
  const hero = consistencyHero(days, win);
  assert.deepEqual([hero.value, hero.caption, hero.change], ['3.4', 'workouts a week since Aug 23', null]);
  const t = consistencyTiles(days, win);
  assert.deepEqual([t.workouts.value, t.workouts.sub, t.month.value, t.month.sub, t.day.value, t.day.sub],
    ['36', 'in 2026', 'October', '16 workouts', 'Wednesday', '6 workouts']);
  assert.deepEqual([consistencyTiles(days, win, { short: true }).month.value, consistencyTiles(days, win, { short: true }).day.value], ['Oct', 'Wed']);
});

test('a year with training the year before compares with the same stretch of it', () => {
  const list = ['2025-01-01', '2025-01-08', '2025-01-15', '2026-01-02', '2026-01-09'];
  const win = yearWindow(2026, new Date(2026, 0, 20));
  const hero = consistencyHero(list, win);
  assert.equal(hero.caption, 'workouts a week in 2026');
  assert.equal(hero.change.direction, 'down');
  assert.match(hero.change.text, /fewer a week than this time last year/);
});

test('levels split at your own quartiles; the grid has every day of the year', () => {
  const level = levelFor({ a: 4, b: 8, c: 12, d: 16, e: 20 });
  assert.deepEqual([4, 8, 12, 16, 20, 0].map(level), [1, 1, 2, 3, 4, 3]); // quartiles 8, 12, 16
  assert.equal(levelFor({ a: 5 })(5), 3);
  const g = yearGrid(yearWindow(2026, today), days, { daySets: { [days[0]]: 12 }, titles: { [days[0]]: 'Push' } });
  const cells = g.weeks.flat();
  assert.equal(cells.filter((c) => !c.out).length, 365);
  assert.equal(cells.filter((c) => c.on).length, 36);
  assert.equal(cells.find((c) => c.iso === days[0]).title, 'Push');
  assert.ok(cells.find((c) => c.iso === '2026-11-04').today);
  assert.ok(cells.find((c) => c.iso === '2026-11-05').future);
  assert.equal(g.months[0].col, 1); // 1 Jan 2026 is a Thursday: the first full week column
});
