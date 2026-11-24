import test from 'node:test';
import assert from 'node:assert/strict';
import { personalBests, sortBests, topSetText, exerciseHeadline } from '../bests.js';

const chart = (labels, data, weight, reps, extra = {}) => ({ labels, data, weight, reps, ...extra });

test('topSetText covers weights, bodyweight and timed sets', () => {
  assert.equal(topSetText({ weight: 80, reps: 5 }), '80 × 5');
  assert.equal(topSetText({ weight: 82.5, reps: 3 }), '82.5 × 3');
  assert.equal(topSetText({ weight: 80, reps: 8, offset: 10 }), 'BW+10 × 8');
  assert.equal(topSetText({ weight: 70, reps: 12, offset: 0 }), 'BW × 12');
  assert.equal(topSetText({ weight: 50, reps: 6, offset: -20 }), 'BW−20 × 6');
  assert.equal(topSetText({ weight: 20, reps: 45, isTimed: true }), '20 × 45s');
  assert.equal(topSetText({ weight: 0, reps: 60, isTimed: true }), '60s');
  assert.equal(topSetText({ weight: 79.5, reps: 60, offset: 0, isTimed: true }), 'BW × 60s');
  assert.equal(topSetText({ weight: 89.5, reps: 30, offset: 10, isTimed: true }), 'BW+10 × 30s');
  assert.equal(topSetText({ weight: 0, reps: 0 }), '');
});

test('the best is the first day the highest score was reached', () => {
  const [row] = personalBests([{ value: 'bench', label: 'Bench Press',
    chart: chart(['2026-09-01', '2026-10-01', '2026-11-10', '2026-11-12'], [90, 100, 100, 95], [70, 80, 77.5, 80], [8, 5, 8, 6]) }], '2026-11-17');
  assert.equal(row.best, 100);
  assert.equal(row.bestDay, '2026-10-01');
  assert.equal(row.top, '80 × 6'); // same weight, more reps
  assert.equal(row.topDay, '2026-11-12');
  assert.equal(row.sessions, 4);
  assert.equal(row.fresh, false); // reached more than 30 days ago
  assert.equal(Math.round(row.belowPct), 5);
});

test('fresh: a best from the last 30 days, but not a first session', () => {
  const rows = personalBests([
    { value: 'a', label: 'A', chart: chart(['2026-10-01', '2026-11-10'], [90, 100], [70, 80], [8, 5]) },
    { value: 'b', label: 'B', chart: chart(['2026-11-15'], [50], [40], [8]) },
    { value: 'c', label: 'C', chart: chart(['2026-11-15'], [0], [0], [0]) },
    { value: 'd', label: 'D', chart: chart([], [], [], []) },
  ], '2026-11-17');
  assert.deepEqual(rows.map((r) => [r.value, r.fresh]), [['a', true], ['b', false]]);
  assert.equal(rows[0].belowPct, 0);
});

test('sorting: latest best, highest (timed last) and A to Z', () => {
  const rows = personalBests([
    { value: 'a', label: 'Squat', chart: chart(['2026-10-01'], [140], [120], [5]) },
    { value: 'b', label: 'Curl', chart: chart(['2026-11-01'], [30], [25], [8]) },
    { value: 'c', label: 'Plank', chart: chart(['2026-11-05'], [300], [0], [90], { is_timed: true }) },
  ], '2026-11-17');
  assert.deepEqual(sortBests(rows, 'recent').map((r) => r.label), ['Plank', 'Curl', 'Squat']);
  assert.deepEqual(sortBests(rows, 'best').map((r) => r.label), ['Squat', 'Curl', 'Plank']);
  assert.deepEqual(sortBests(rows, 'alpha').map((r) => r.label), ['Curl', 'Plank', 'Squat']);
  assert.equal(rows[2].top, '90s');
});

test('exerciseHeadline: latest value, what it is, and the change since the first shown', () => {
  const h = exerciseHeadline(['2026-08-23', '2026-09-10', '2026-11-16'], [72, 105, 70]);
  assert.deepEqual(h, { value: 70, unit: 'kg', what: 'estimated max, latest session', change: { direction: 'down', amount: 2, year: 2026, month: 8 } });
  const up = exerciseHeadline(['2026-09-12', '2026-11-17'], [72, 105], { metric: 'weight' });
  assert.equal(up.what, 'heaviest set, latest session');
  assert.deepEqual(up.change, { direction: 'up', amount: 33, year: 2026, month: 9 });
  assert.equal(exerciseHeadline(['2026-10-01'], [900], { metric: 'volume' }).what, 'lifted, latest session');
});

test('exerciseHeadline: gaps, one session, small changes and timed holds', () => {
  assert.equal(exerciseHeadline([], []), null);
  assert.equal(exerciseHeadline(['2026-10-01', '2026-10-08'], [null, undefined]), null);
  // Gaps are skipped: the first and last real numbers are compared.
  const g = exerciseHeadline(['2026-07-01', '2026-08-01', '2026-09-01', '2026-10-01'], [null, 60, null, 65]);
  assert.deepEqual(g.change, { direction: 'up', amount: 5, year: 2026, month: 8 });
  assert.equal(exerciseHeadline(['2026-10-01'], [60]).change, null);
  assert.equal(exerciseHeadline(['2026-10-01', '2026-10-08'], [60, 60.3]).change.direction, 'level');
  const timed = exerciseHeadline(['2026-10-01', '2026-11-16'], [600, 616], { isTimed: true });
  assert.equal(timed.unit, '');
  assert.equal(timed.what, 'score, latest session');
  assert.equal(exerciseHeadline(['2026-10-01'], [20], { metric: 'weight', isTimed: true }).unit, 'kg');
});
