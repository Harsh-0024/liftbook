// One rule for days: a workout's saved time is the phone's own clock time, and every screen
// (History, Home, Stats) puts it on that day. Before, Stats added 5h30 on top, so a workout
// saved without a date after 6:30 pm showed in Stats on the next day.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Store, memoryBackend } from '../store.js';
import { Liftbook } from '../data.js';
import { deviceDay, addDays } from '../../core/dates.js';

async function app() {
  const store = await Store.open(memoryBackend());
  await store.change('profiles', { username: 'tester', full_name: 'Test', bodyweight: 70 });
  return new Liftbook(store, { db: {}, storage: {} }, 'u1');
}

// Phone clock times (new Date(y, m, d, h, min) is read in the device's own time zone).
const EVENING = new Date(2026, 10, 4, 19, 15); // 4 Nov, 7:15 pm
const AFTER_MIDNIGHT = new Date(2026, 10, 5, 1, 30); // 5 Nov, 1:30 am

test('an undated workout saved at 7:15 pm is on that day everywhere, Stats too', async () => {
  const lb = await app();
  const r = await lb.log('Pull\n\nBarbell row\n60 x 8, 8', { now: EVENING });
  assert.equal(r.day, '2026-11-04');
  assert.equal(lb.workouts()[0].day, '2026-11-04');
  assert.deepEqual(lb.chart('Barbell Row').labels, ['2026-11-04']);
});

test('an undated workout saved at 1:30 am is on the new day, not the night before', async () => {
  const lb = await app();
  await lb.log('4/11/26 Push\n\nBench press\n60 x 8', { now: EVENING });
  const r = await lb.log('Pull\n\nBarbell row\n60 x 8', { now: AFTER_MIDNIGHT });
  assert.equal(r.existing, undefined); // not taken for the 4th's workout
  assert.equal(r.day, '2026-11-05');
  assert.deepEqual(lb.workouts().map((w) => w.day), ['2026-11-05', '2026-11-04']);
  assert.deepEqual(lb.chart('Barbell Row').labels, ['2026-11-05']);
  assert.deepEqual(lb.chart('Bench Press').labels, ['2026-11-04']);
});

test('Stats days match History days for every saved time of day', async () => {
  const lb = await app();
  for (let hour = 0; hour < 24; hour += 1) {
    await lb.log(`Day\n\nSquat\n${100 + hour} x 5`, { now: new Date(2026, 9, 1 + hour, hour, 40) });
  }
  const historyDays = lb.workouts().map((w) => w.day).sort();
  assert.equal(historyDays.length, 24);
  assert.deepEqual(lb.chart('Squat').labels, historyDays);
  assert.deepEqual(lb.overall('index').workout_days.slice().sort(), historyDays);
});

test('"today" is the phone\'s day, not the UTC day', () => {
  // 20:00 UTC on 4 Nov is already 5 Nov for a phone in India (and still 4 Nov in London).
  const moment = '2026-11-04T20:00:00Z';
  const d = new Date(moment);
  const expected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  assert.equal(deviceDay(moment), expected);
  assert.equal(deviceDay(new Date(2026, 10, 5, 0, 10)), '2026-11-05');
  assert.equal(addDays(deviceDay(new Date(2026, 10, 5, 0, 10)), -7), '2026-10-29');
});
