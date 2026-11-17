import test from 'node:test';
import assert from 'node:assert/strict';
import { bodyweightTrend } from '../weight_trend.js';

test('no trend without two different weights', () => {
  assert.equal(bodyweightTrend([]), null);
  assert.equal(bodyweightTrend([{ date: '2026-10-01', bodyweight: 80 }]), null);
  assert.equal(bodyweightTrend([{ date: '2026-10-01', bodyweight: 80 }, { date: '2026-10-05', bodyweight: 80 }]), null);
});

test('one point per day, in order, with the change since the first', () => {
  const t = bodyweightTrend([
    { date: '2026-10-05T10:00:00', bodyweight: 79.5 },
    { date: '2026-10-01', bodyweight: 81 },
    { date: '2026-10-01', bodyweight: 81 },
    { date: '2026-10-09', bodyweight: '79.5' },
    { date: '2026-10-03', bodyweight: null },
    { date: '', bodyweight: 70 },
  ]);
  assert.deepEqual(t.labels, ['2026-10-01', '2026-10-05', '2026-10-09']);
  assert.deepEqual(t.values, [81, 79.5, 79.5]);
  assert.equal(t.change, -1.5);
  assert.equal(t.current, 79.5);
  assert.equal(t.min, 79.5);
  assert.equal(t.max, 81);
  assert.equal(t.lastChanged, '2026-10-05');
});
