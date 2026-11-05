// What the home-screen widget shows (Liftbook.widgetSummary).
import test from 'node:test';
import assert from 'node:assert/strict';
import { Store, memoryBackend } from '../store.js';
import { Liftbook } from '../data.js';

async function app() {
  const store = await Store.open(memoryBackend());
  await store.change('profiles', { username: 'tester', full_name: 'Test', bodyweight: 70 });
  const lb = new Liftbook(store, { db: {}, storage: {} }, 'u1');
  await lb.setText('plan', 'Session 1 - Push\nBench Press\nDips\n\nSession 2 - Pull\nBarbell Row\nBarbell Curl - [2]\n');
  return lb;
}

const THU = new Date(2026, 10, 5, 8, 0); // Thursday 5 Nov, 8 am

test('with nothing planned it shows the next session, with the last sets to beat', async () => {
  const lb = await app();
  await lb.log('3/11/26 Session 1 - Push\n\nBench press\n60 x 8, 8\n\nDips\nbw x 10');
  await lb.log('1/11/26 Session 2 - Pull\n\nBarbell row\n70 x 8, 7');
  const w = lb.widgetSummary(THU);
  assert.equal(w.heading, 'Next');
  assert.equal(w.title, 'Session 2 - Pull');
  assert.deepEqual(w.lines.map((l) => l.name), ['Barbell Row', 'Barbell Curl']);
  assert.match(w.lines[0].aim, /70/);
  assert.equal(w.lines[1].aim, '2 × 6–10'); // never done: its target sets and reps
  assert.equal(w.route, 'retrieve/day/Session/2');
});

test('a workout planned for today comes first, and says when it is logged', async () => {
  const lb = await app();
  await lb.savePlannedWorkouts([
    { id: 'w', weekday: 4, time: '18:30', title: 'Session 1 - Push', category: 'Session', dayId: 1 }, // Thursdays
    { id: 'x', date: '2026-11-06', time: '07:00', title: 'Session 2 - Pull', category: 'Session', dayId: 2 },
  ]);
  let w = lb.widgetSummary(THU);
  assert.equal(w.heading, 'Today · 18:30');
  assert.equal(w.title, 'Session 1 - Push');
  assert.deepEqual(w.lines.map((l) => l.name), ['Bench Press', 'Dips']);
  await lb.log('Session 1 - Push\n\nBench press\n60 x 8', { now: new Date(2026, 10, 5, 19, 0) });
  w = lb.widgetSummary(new Date(2026, 10, 5, 20, 0));
  assert.equal(w.heading, 'Today · logged');
});

test('with no plan at all it offers to log a workout', async () => {
  const store = await Store.open(memoryBackend());
  await store.change('profiles', { username: 'tester', full_name: 'Test' });
  const lb = new Liftbook(store, { db: {}, storage: {} }, 'u1');
  await lb.setText('plan', 'just some notes');
  const w = lb.widgetSummary(THU);
  assert.equal(w.title, 'Log a workout');
  assert.deepEqual(w.lines, []);
  assert.equal(w.route, 'log');
});
