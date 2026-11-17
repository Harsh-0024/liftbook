import test from 'node:test';
import assert from 'node:assert/strict';
import { muscleBalance } from '../balance.js';

const log = (date, exercise, n) => ({ date, exercise, sets: { reps: new Array(n).fill(8), weights: new Array(n).fill(50) } });

test('nothing in the stretch: no balance', () => {
  assert.equal(muscleBalance([], { from: '', today: '2026-11-17' }), null);
  assert.equal(muscleBalance([log('2026-01-01', 'Barbell Curl', 3)], { from: '2026-11-01', today: '2026-11-17' }), null);
});

test('sets per group per week over a chosen range', () => {
  const b = muscleBalance([
    log('2026-11-03', 'Flat Barbell Press', 3),
    log('2026-11-10', 'Incline Dumbbell Press', 3),
    log('2026-11-10', 'Barbell Curl', 2),
    log('2026-11-12', 'Back Squat', 4),
    log('2026-10-01', 'Back Squat', 9), // before the range
  ], { from: '2026-11-04', today: '2026-11-17' });
  assert.equal(b.weeks, 2);
  assert.deepEqual(b.rows.map((r) => [r.group, r.sets, r.perWeek]), [['Chest', 3, 1.5], ['Biceps', 2, 1], ['Legs', 4, 2]]);
  assert.equal(b.total, 9);
  assert.equal(b.rows.find((r) => r.group === 'Legs').share, 1);
});

test('"all" counts from the first workout, and never less than a week', () => {
  const b = muscleBalance([log('2026-11-16', 'Lat Pulldown', 3)], { from: '', today: '2026-11-17' });
  assert.equal(b.weeks, 1);
  assert.deepEqual(b.rows.map((r) => [r.group, r.perWeek]), [['Back', 3]]);
});
