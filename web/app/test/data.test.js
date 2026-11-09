import test from 'node:test';
import assert from 'node:assert/strict';
import { Store, memoryBackend } from '../store.js';
import { Liftbook } from '../data.js';

async function app() {
  const store = await Store.open(memoryBackend());
  await store.change('profiles', { username: 'tester', full_name: 'Test', bodyweight: 70 });
  return new Liftbook(store, { db: {}, storage: {} }, 'u1');
}

const DAY1 = '31/10/26 Session 1\n\nSquat\n100 x 5, 5, 5\n\nBench press\n60 x 8, 8, 8';

test('logging a workout writes one row per exercise, pending sync', async () => {
  const lb = await app();
  const r = await lb.log(DAY1);
  assert.equal(r.error, undefined);
  assert.equal(r.day, '2026-10-31');
  assert.deepEqual(r.summary.map((s) => [s.name, s.status]), [['Squat', 'NEW'], ['Bench Press', 'NEW']]);
  const logs = lb.history();
  assert.equal(logs.length, 2);
  assert.deepEqual(logs[0].sets, { weights: [100, 100, 100], reps: [5, 5, 5] });
  assert.equal(logs[0].bodyweight, 70);
  assert.equal(lb.store.pending('workout_logs').length, 2);
  assert.equal(lb.workouts()[0].title, 'Session 1');
});

test('a second workout the same day asks first, or joins it', async () => {
  const lb = await app();
  await lb.log(DAY1);
  const again = await lb.log('31/10/26 Extra\n\nCurl\n20 x 10');
  assert.deepEqual(again.existing, { day: '2026-10-31', title: 'Session 1' });
  const joined = await lb.log('31/10/26 Extra\n\nCurl\n20 x 10', { append: true });
  assert.equal(joined.appended, true);
  const w = lb.workout('2026-10-31');
  assert.equal(w.logs.length, 3);
  assert.equal(w.title, 'Session 1');
});

test('a better day is marked as an improvement', async () => {
  const lb = await app();
  await lb.log(DAY1);
  const r = await lb.log('1/11/26 Session 1\n\nSquat\n105 x 5, 5, 5');
  assert.equal(r.summary[0].class, 'improved');
  assert.match(r.summary[0].old, /100/);
});

test('editing replaces the day; deleting is soft', async () => {
  const lb = await app();
  await lb.log(DAY1);
  const text = lb.workoutText(lb.workout('2026-10-31'));
  assert.match(text, /^31\/10\/26 Session 1\n\nSquat\n100 x 5, 5, 5/);
  const r = await lb.log(text.replace('100 x', '110 x'), { replaceDay: '2026-10-31' });
  assert.equal(r.error, undefined);
  assert.equal(lb.workout('2026-10-31').logs[0].top_weight, 110);
  assert.equal(lb.store.all('workout_logs', { deleted: true }).length, 4);
  await lb.deleteWorkout('2026-10-31');
  assert.equal(lb.workouts().length, 0);
  assert.ok(lb.store.all('workout_logs', { deleted: true }).every((l) => l.deleted_at));
});

test('text that can’t be read is refused with a reason', async () => {
  const lb = await app();
  assert.match((await lb.log('')).error, /Type your workout/);
  const r = await lb.log('31/10/26 Session\n\n100 x 5');
  assert.ok(r.error);
  assert.equal(lb.history().length, 0);
});

test('a bodyweight line updates the profile', async () => {
  const lb = await app();
  await lb.log('31/10/26 Session 1\nBodyweight - 72\n\nPull ups\nbw x 8, 8, 8');
  assert.equal(lb.profile().bodyweight, 72);
  assert.equal(lb.exerciseSetting('Pull Ups').is_bodyweight, true);
});

test('retrieve uses the plan and the last sets', async () => {
  const lb = await app();
  await lb.setText('plan', 'Session 1 - Legs\nSquat - [3, 5-8]\nLeg press');
  await lb.log(DAY1);
  const r = lb.retrieveDay('Session', 1);
  assert.match(r.text, /Session 1 - Legs/);
  assert.match(r.text, /Squat - \[3, 5-8\]\n100, 5\n100, 5\n100, 5/);
  assert.equal(r.exercises, 2);
  const custom = lb.retrieveCustom(['Bench Press'], 'Push');
  assert.match(custom.text, /- Push\n/);
  assert.match(custom.text, /Bench Press[^\n]*\n60, 8/);
});

test('renaming moves the logs, plan and future logs; undo puts them back', async () => {
  const lb = await app();
  await lb.setText('plan', 'Session 1\nBench press - [3, 6-8]');
  await lb.log(DAY1);
  const preview = lb.renamePreview('Bench Press', 'Flat Bench');
  assert.equal(preview.logs, 1);
  await lb.rename('Bench Press', 'Flat Bench');
  assert.ok(lb.history().some((l) => l.exercise === 'Flat Bench'));
  assert.match(lb.text('plan'), /Flat Bench - \[3, 6-8\]/);
  await lb.log('1/11/26 Session 1\n\nBench press\n62 x 8');
  assert.equal(lb.workout('2026-11-01').logs[0].exercise, 'Flat Bench', 'the old name is redirected');
  const [rename] = lb.renames();
  await lb.undoRename(rename.id);
  assert.equal(lb.workout('2026-10-31').logs[1].exercise, 'Bench Press');
  assert.equal(lb.renames().length, 0);
});

test('stats come from the local history', async () => {
  const lb = await app();
  await lb.log(DAY1);
  await lb.log('2/11/26 Session 1\n\nSquat\n105 x 5, 5, 5');
  const options = lb.statsOptions();
  assert.ok(options.some((o) => o.value === 'Squat' && o.sessions === 2));
  const chart = lb.chart('Squat');
  assert.equal(chart.labels.length, 2);
  await lb.countView('Squat');
  assert.equal(lb.exerciseSetting('Squat').view_count, 1);
  assert.equal(lb.overview().total, 2);
});

test('settings are one JSON row; plan texts are rows by kind', async () => {
  const lb = await app();
  await lb.setSetting('follow_shared_plan', true);
  await lb.setSetting('stats_range', '90');
  assert.deepEqual(lb.settings(), { follow_shared_plan: true, stats_range: '90' });
  await lb.store.setMeta('shared_plan', { plan: 'Session 1\nDeadlift', rep_ranges: null });
  assert.match(lb.planText(), /Deadlift/);
  await lb.setSetting('follow_shared_plan', false);
  assert.doesNotMatch(lb.planText(), /^Session 1\nDeadlift$/);
});

test('the spreadsheet has the old app’s columns, newest first, and dates can limit it', async () => {
  const lb = await app();
  await lb.log(DAY1);
  await lb.log('1/11/26 Core\n\nPlank\n60, 45');
  const all = lb.csv();
  const lines = all.text.trimEnd().split('\r\n');
  assert.equal(all.count, 3);
  assert.equal(lines[0], 'Date,Workout Name,Exercise,Exercise String,Weights,Reps,Sets JSON,Top Weight (kg),Top Reps,Estimated 1RM (kg),Uses Bodyweight,Bodyweight (kg),Timed');
  assert.match(lines[1], /^2026-11-01T[\d:]+,Core,Plank,/);
  assert.match(lines[1], /,yes$/, 'plank is timed');
  assert.match(lines[2], /^2026-10-31T[\d:]+,Session 1,Squat,"Squat\n100 x 5, 5, 5","100,100,100","5,5,5","{""weights"":\[100,100,100\],""reps"":\[5,5,5\]}",100,5,/);
  assert.match(lines[2], /,no$/);
  assert.equal(lb.csv({ from: '2026-11-01' }).count, 1);
  assert.equal(lb.csv({ to: '2026-10-31' }).count, 2);
  assert.equal(lb.csv({ from: '2027-01-01' }).count, 0);
});

test('history is kept between calls but follows every change, here or synced', async () => {
  const lb = await app();
  await lb.log(DAY1);
  const order = lb.history().map((l) => l.id);
  lb.history().reverse();
  assert.deepEqual(lb.history().map((l) => l.id), order, 'a caller’s copy can’t change the kept list');
  await lb.log('1/11/26 Session 1\n\nSquat\n105 x 5');
  assert.equal(lb.history().length, 3);
  assert.equal(lb.workouts().length, 2);
  const nov1 = lb.history().find((l) => l.date.startsWith('2026-11-01'));
  await lb.store.applyRemote('workout_logs', [{ ...nov1, workout_name: 'From phone', updated_at: '2099-01-01T00:00:00Z' }]);
  assert.equal(lb.workout('2026-11-01').title, 'From phone');
  await lb.deleteWorkout('2026-11-01');
  assert.equal(lb.workouts().length, 1);
});
