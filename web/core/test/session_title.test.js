// "Session 2 - Legs" in All workouts: the session goes in front of the exercises, the rest is
// the title (the old list's routes/workouts.py _home_history).
import test from 'node:test';
import assert from 'node:assert/strict';
import { splitSessionTitle, nextSessionId } from '../sessions.js';

test('a session title splits into its session and its name', () => {
  assert.deepEqual(splitSessionTitle('Session 2 - Legs'), { session: 'Session 2', title: 'Legs' });
  assert.deepEqual(splitSessionTitle('session  12: Chest & Biceps'), { session: 'Session 12', title: 'Chest & Biceps' });
  assert.deepEqual(splitSessionTitle('SESSION 3 – Back – heavy'), { session: 'Session 3', title: 'Back – heavy' });
});

test('any other title comes back whole', () => {
  for (const t of ['Legs', 'Session 2', 'Session two - Legs', 'My Session 2 - Legs', '']) {
    assert.deepEqual(splitSessionTitle(t), { session: '', title: t });
  }
  assert.deepEqual(splitSessionTitle(null), { session: '', title: '' });
});

test('nextSessionId: the session after the last one logged, wrapping round', () => {
  const ids = [1, 2, 3, 4];
  assert.equal(nextSessionId(['Session 2 - Shoulders', 'Session 1 - Chest'], ids), 3);
  assert.equal(nextSessionId(['Session 4 - Legs'], ids), 1);
  assert.equal(nextSessionId(['Push', 'session 3: Back'], ids), 4);
  assert.equal(nextSessionId(['Push', 'Pull'], ids), null);
  assert.equal(nextSessionId(['Session 9 - Extra'], ids), null);
  assert.equal(nextSessionId([], ids), null);
});
