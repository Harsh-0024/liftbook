// "Less often" in the custom picker against services/retrieve.py often_trained_keys
// (expected values printed by the Python function for the same workouts).
import test from 'node:test';
import assert from 'node:assert/strict';
import { oftenTrainedKeys } from '../retrieve.js';

const cases = [
  [[['2026-10-01', ['a', 'b']], ['2026-10-04', ['a', 'c']], ['2026-10-08', ['a', 'b']], ['2026-10-11', ['a']], ['2026-10-15', ['b', 'd']], ['2026-10-20', ['a', 'e']]], ['a', 'b', 'x'], ['a', 'b', 'd', 'e', 'x']],
  [[['2026-10-01', ['a']], ['2026-10-04', ['a']]], [], null],
  [[['2026-01-01', ['a', 'b']], ['2026-01-05', ['a', 'b']], ['2026-01-09', ['a', 'b']], ['2026-06-01', ['a', 'c']], ['2026-06-04', ['a', 'c']], ['2026-06-07', ['c']], ['2026-06-10', ['c', 'z']]], ['a', 'q', 'r'], ['a', 'b', 'c', 'z']],
  [[['2026-03-01', ['p', 'q']], ['2026-03-03', ['p']], ['2026-03-05', ['p', 'q']], ['2026-03-09', ['p']], ['2026-03-11', ['q', 's']], ['2026-03-12', ['p', 't']], ['2026-03-20', ['p']]], ['p', 'q', 's', 'u'], ['p', 'q', 's', 'u']],
];

test('often-trained exercises match Python', () => {
  for (const [w, plan, expect] of cases) {
    const r = oftenTrainedKeys(w.map(([d, k]) => [d, new Set(k)]), plan);
    assert.deepEqual(r === null ? null : [...r].sort(), expect);
  }
});
