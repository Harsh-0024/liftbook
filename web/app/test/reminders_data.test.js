// Reminder settings and planned workouts are kept in the synced settings row (app_settings),
// and the app works out the reminders from them and the workouts.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Store, memoryBackend } from '../store.js';
import { Liftbook } from '../data.js';

async function app() {
  const store = await Store.open(memoryBackend());
  await store.change('profiles', { username: 'tester', full_name: 'Test', bodyweight: 70 });
  return new Liftbook(store, { db: {}, storage: {} }, 'u1');
}

test('off by default; switching on and planning a workout give reminders, synced like other settings', async () => {
  const lb = await app();
  for (const d of ['20/10/26', '22/10/26', '24/10/26', '26/10/26']) await lb.log(`${d} Session 1\n\nSquat\n100 x 5`);
  const now = new Date(2026, 9, 27, 12, 0); // 27 Oct, noon
  assert.equal(lb.reminders().on, false);
  assert.deepEqual(lb.upcomingReminders(now), []);

  await lb.setReminders({ on: true });
  await lb.savePlannedWorkouts([{ id: 'p1', date: '2026-10-28', time: '18:00', title: 'Session 2 - Pull' }, { id: 'bad' }]);
  assert.deepEqual(lb.plannedWorkouts().map((p) => p.id), ['p1']); // the broken one isn't kept
  assert.deepEqual(lb.upcomingReminders(now).map((r) => [r.kind, r.at]), [
    ['planned', '2026-10-28T17:30'],
    ['gap', '2026-10-29T09:00'],
  ]);
  // Saved in the one settings row, waiting to sync.
  const row = lb.store.get('app_settings');
  assert.equal(row.json.reminders.on, true);
  assert.equal(row.json.planned_workouts.length, 1);
  assert.equal(lb.store.pending('app_settings').length, 1);

  await lb.setReminders({ quietFrom: '23:00' });
  assert.equal(lb.reminders().on, true); // changing one setting keeps the others
});
