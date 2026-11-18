// "Session 2 - Legs" in All workouts: the session goes in front of the exercises, the rest is
// the title (the old list's routes/workouts.py _home_history).
import test from 'node:test';
import assert from 'node:assert/strict';
import { splitSessionTitle, nextSessionId, lastDoneBySession } from '../sessions.js';

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

test('Retrieve: each session knows the last day it was done', () => {
  const last = lastDoneBySession([
    { day: '2026-11-09', title: 'Session 2 - Shoulders & Forearms' },
    { day: '2026-11-16', title: 'Session 2 – Shoulders & Forearms' },
    { day: '2026-11-12', title: 'session 3' },
    { day: '2026-11-14', title: 'Push' },
    { day: '', title: 'Session 4 - Legs' },
  ]);
  assert.equal(last.get(2), '2026-11-16');
  assert.equal(last.get(3), '2026-11-12');
  assert.equal(last.has(4), false);
  assert.equal(last.size, 2);
  assert.equal(lastDoneBySession(null).size, 0);
});
