import test from 'node:test';
import assert from 'node:assert/strict';
import { Store, memoryBackend } from '../store.js';
import { createSync } from '../sync.js';
import { freshStamp, timeKey, toServer } from '../tables.js';
import { fakeServer } from './fake_server.js';

const ME = '11111111-1111-4111-8111-111111111111';
const OTHER = '22222222-2222-4222-8222-222222222222';

/** A device: its own store and clock, syncing with the fake server as `userId`. */
async function device(server, { userId = ME, start = '2026-10-31T10:00:00Z', data = {}, page } = {}) {
  let clock = Date.parse(start);
  const store = await Store.open(memoryBackend(data), { now: () => clock });
  const sync = createSync({ store, db: server.clientFor(userId), userId, debounceMs: 5, page });
  return {
    store, sync, data,
    tick(ms = 1000) {
      clock += ms;
    },
  };
}

const log = (id, extra = {}) => ({
  id, date: '2026-10-31T09:00:00', workout_name: 'Session 1', exercise: 'Squat', exercise_string: 'Squat\n100 x 5',
  sets: { weights: [100], reps: [5] }, bodyweight: null, uses_bodyweight: false, top_weight: 100, top_reps: 5, estimated_1rm: 116.7,
  ...extra,
});

test('a change is written here first, stamped, and pending', async () => {
  const d = await device(fakeServer());
  const row = await d.store.change('workout_logs', log('a'));
  assert.equal(row.updated_at, '2026-10-31T10:00:00.000Z');
  assert.equal(row.created_at, row.updated_at);
  assert.equal(row.deleted_at, null);
  assert.equal(d.store.pendingCount(), 1);
  // Kept across a reload.
  const again = await Store.open(memoryBackend(d.data));
  assert.equal(again.get('workout_logs', 'a').exercise, 'Squat');
  assert.equal(again.pendingCount(), 1);
});

test('a change time is always later than the last one, even with a clock that went back', () => {
  assert.equal(freshStamp('2026-10-31T10:00:00.500000+00:00', Date.parse('2026-10-31T09:00:00Z')), '2026-10-31T10:00:00.501Z');
  assert.equal(freshStamp('2026-10-31T10:00:00.123456+00:00', Date.parse('2026-10-31T10:00:00.123Z')), '2026-10-31T10:00:00.124Z');
  assert.equal(freshStamp(null, Date.parse('2026-10-31T09:00:00Z')), '2026-10-31T09:00:00.000Z');
  assert.ok(timeKey('2026-10-31T10:00:00.123456+00:00') > timeKey('2026-10-31T10:00:00.123Z'));
  assert.equal(timeKey('2026-10-31T15:30:00+05:30'), timeKey('2026-10-31T10:00:00.000Z'));
});

test('offline edits stay on the device and go up once online', async () => {
  const server = fakeServer();
  const d = await device(server);
  server.setOnline(false);
  await d.store.change('workout_logs', log('a'));
  await d.store.change('user_texts', { kind: 'plan', text: 'Session 1\nSquat' });
  const r = await d.sync.runOnce();
  assert.equal(r.error, 'offline');
  assert.equal(d.sync.status().error, 'offline');
  assert.equal(d.store.pendingCount(), 2);
  assert.equal(server.row('workout_logs', ME, 'a'), null);

  server.setOnline(true);
  const r2 = await d.sync.runOnce();
  assert.equal(r2.error, undefined);
  assert.equal(r2.up, 2);
  assert.equal(d.store.pendingCount(), 0);
  assert.equal(server.row('workout_logs', ME, 'a').exercise, 'Squat');
  assert.equal(server.row('user_texts', ME, 'plan').text, 'Session 1\nSquat');
  assert.equal(d.sync.status().error, null);
});

test('a workout logged on one device reaches the other', async () => {
  const server = fakeServer();
  const phone = await device(server);
  const laptop = await device(server);
  await phone.store.change('workout_logs', [log('a'), log('b', { exercise: 'Bench Press' })]);
  await phone.sync.runOnce();
  const r = await laptop.sync.runOnce();
  assert.equal(r.down, 2);
  assert.deepEqual(laptop.store.all('workout_logs').map((x) => x.exercise).sort(), ['Bench Press', 'Squat']);
  assert.equal(laptop.store.pendingCount(), 0);
  // The phone's own rows coming back down change nothing there.
  const r2 = await phone.sync.runOnce();
  assert.equal(r2.down, 0);
});

test('conflicts: the newer change wins, whichever device syncs first', async () => {
  for (const newerSyncsFirst of [true, false]) {
    const server = fakeServer();
    const phone = await device(server);
    const laptop = await device(server);
    await phone.store.change('user_texts', { kind: 'plan', text: 'v1' });
    await phone.sync.runOnce();
    await laptop.sync.runOnce();

    // Both edit while offline; the laptop's edit is later.
    phone.tick(10_000);
    await phone.store.change('user_texts', { kind: 'plan', text: 'phone (older)' });
    laptop.tick(20_000);
    await laptop.store.change('user_texts', { kind: 'plan', text: 'laptop (newer)' });

    const order = newerSyncsFirst ? [laptop, phone] : [phone, laptop];
    for (const d of order) await d.sync.runOnce();
    for (const d of order) await d.sync.runOnce();

    assert.equal(server.row('user_texts', ME, 'plan').text, 'laptop (newer)');
    assert.equal(phone.store.get('user_texts', 'plan').text, 'laptop (newer)');
    assert.equal(laptop.store.get('user_texts', 'plan').text, 'laptop (newer)');
    assert.equal(phone.store.pendingCount(), 0);
    assert.equal(laptop.store.pendingCount(), 0);
  }
});

test('deletes are soft and reach the other device', async () => {
  const server = fakeServer();
  const phone = await device(server);
  const laptop = await device(server);
  await phone.store.change('workout_logs', [log('a'), log('b')]);
  await phone.sync.runOnce();
  await laptop.sync.runOnce();

  laptop.tick();
  await laptop.store.remove('workout_logs', ['a']);
  assert.deepEqual(laptop.store.all('workout_logs').map((x) => x.id), ['b']);
  assert.ok(laptop.store.get('workout_logs', 'a', { deleted: true }).deleted_at);
  await laptop.sync.runOnce();

  const kept = server.row('workout_logs', ME, 'a');
  assert.ok(kept, 'the row stays on the server');
  assert.ok(kept.deleted_at);

  await phone.sync.runOnce();
  assert.deepEqual(phone.store.all('workout_logs').map((x) => x.id), ['b']);
});

test('an older delete loses to a newer edit', async () => {
  const server = fakeServer();
  const phone = await device(server);
  const laptop = await device(server);
  await phone.store.change('workout_logs', log('a'));
  await phone.sync.runOnce();
  await laptop.sync.runOnce();

  phone.tick(1000);
  await phone.store.remove('workout_logs', 'a');
  laptop.tick(5000);
  await laptop.store.change('workout_logs', { id: 'a', workout_name: 'Edited later' });
  await phone.sync.runOnce();
  await laptop.sync.runOnce();
  await phone.sync.runOnce();

  assert.equal(server.row('workout_logs', ME, 'a').deleted_at, null);
  assert.equal(phone.store.get('workout_logs', 'a').workout_name, 'Edited later');
});

test('the pull cursor: only rows stamped since the last download (with overlap) come down', async () => {
  const server = fakeServer();
  for (let i = 0; i < 5; i++) server.seed('workout_logs', { ...log(`old${i}`), user_id: ME, updated_at: '2026-10-01T00:00:00Z', created_at: '2026-10-01T00:00:00Z', deleted_at: null });
  const d = await device(server, { page: 2 });
  await d.sync.runOnce();
  assert.equal(d.store.all('workout_logs').length, 5);
  const pulls = server.log.filter((e) => e.op === 'pull' && e.table === 'workout_logs');
  assert.deepEqual(pulls.map((p) => [p.since, p.offset]), [[null, 0], [null, 2], [null, 4]], 'pages through everything the first time');
  const cursor = d.store.getMeta('cursor:workout_logs');
  assert.equal(cursor, server.row('workout_logs', ME, 'old4').server_updated_at);

  // Ten minutes on, one new row: the old ones are outside the overlap and don't come again.
  server.advance(10 * 60 * 1000);
  server.seed('workout_logs', { ...log('mid'), user_id: ME, updated_at: '2026-10-31T09:00:00Z', created_at: '2026-10-31T09:00:00Z', deleted_at: null });
  await d.sync.runOnce();
  server.log.length = 0;
  server.advance(10 * 60 * 1000);
  server.seed('workout_logs', { ...log('new'), user_id: ME, updated_at: '2026-10-31T09:00:00Z', created_at: '2026-10-31T09:00:00Z', deleted_at: null });
  const midCursor = d.store.getMeta('cursor:workout_logs');
  const r = await d.sync.runOnce();
  assert.equal(r.down, 1);
  const second = server.log.filter((e) => e.op === 'pull' && e.table === 'workout_logs');
  assert.equal(timeKey(second[0].since), timeKey(midCursor) - 5 * 60 * 1000 * 1000, 'five minutes of overlap');
  assert.deepEqual(second.flatMap((p) => p.ids), ['mid', 'new'], 'only the rows stamped near or after the cursor');

  // The cursor survives a reload: a reopened app doesn't download everything again.
  const reopened = await device(server, { data: d.data });
  assert.equal(reopened.store.getMeta('cursor:workout_logs'), server.row('workout_logs', ME, 'new').server_updated_at);
});

test('rows that arrive late are still downloaded thanks to the overlap', async () => {
  const server = fakeServer();
  const d = await device(server);
  server.seed('workout_logs', { ...log('x'), user_id: ME, updated_at: '2026-10-31T09:00:00Z', created_at: '2026-10-31T09:00:00Z', deleted_at: null });
  await d.sync.runOnce();
  // A write that committed late, stamped a moment before the newest row seen.
  const seen = server.row('workout_logs', ME, 'x').server_updated_at;
  const earlier = new Date(Date.parse(seen) - 1000).toISOString();
  server.tables.workout_logs.set(`${ME}|late`, { ...log('late'), user_id: ME, updated_at: '2026-10-31T09:00:00Z', created_at: '2026-10-31T09:00:00Z', deleted_at: null, server_updated_at: earlier });
  await d.sync.runOnce();
  assert.ok(d.store.get('workout_logs', 'late'));
});

test('imported rows: legacy_id and server_updated_at are never sent back', async () => {
  const server = fakeServer();
  server.seed('workout_logs', { ...log('imp'), legacy_id: 42, user_id: ME, updated_at: '2026-10-01T00:00:00Z', created_at: '2026-10-01T00:00:00Z', deleted_at: null });
  server.seed('profiles', { user_id: ME, legacy_id: 7, username: 'harsh', full_name: 'Harsh', bodyweight: 70, avatar_path: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', deleted_at: null });
  const d = await device(server);
  await d.sync.runOnce();
  assert.equal(d.store.get('workout_logs', 'imp').legacy_id, 42, 'kept here (it orders old logs)');
  d.tick();
  await d.store.change('workout_logs', { id: 'imp', workout_name: 'Renamed' });
  await d.store.change('profiles', { bodyweight: 71 });
  const r = await d.sync.runOnce();
  assert.equal(r.error, undefined);
  assert.equal(server.row('workout_logs', ME, 'imp').workout_name, 'Renamed');
  assert.equal(server.row('workout_logs', ME, 'imp').legacy_id, 42);
  assert.equal(server.row('profiles', ME).bodyweight, 71);
  for (const e of server.log.filter((x) => x.op === 'upsert')) {
    for (const row of e.rows) {
      assert.ok(!('legacy_id' in row));
      assert.ok(!('server_updated_at' in row));
      assert.ok(!('_k' in row) && !('synced' in row), 'nothing of this device’s bookkeeping');
    }
  }
});

test('each person only syncs their own rows', async () => {
  const server = fakeServer();
  server.seed('workout_logs', { ...log('theirs'), user_id: OTHER, updated_at: '2026-10-01T00:00:00Z', created_at: '2026-10-01T00:00:00Z', deleted_at: null });
  const d = await device(server);
  await d.store.change('workout_logs', log('mine'));
  await d.sync.runOnce();
  assert.deepEqual(d.store.all('workout_logs').map((x) => x.id), ['mine']);
  assert.equal(server.row('workout_logs', ME, 'mine').user_id, ME);
});

test('a change made while uploading stays pending for the next sync', async () => {
  const server = fakeServer();
  const store = await Store.open(memoryBackend());
  const db = server.clientFor(ME);
  const slow = {
    ...db,
    async upsert(...args) {
      await store.change('user_texts', { kind: 'plan', text: 'typed during upload' });
      return db.upsert(...args);
    },
  };
  await store.change('user_texts', { kind: 'plan', text: 'first' });
  const sync = createSync({ store, db: slow, userId: ME });
  await sync.runOnce();
  assert.equal(store.get('user_texts', 'plan').text, 'typed during upload');
  assert.equal(store.pendingCount(), 1, 'the newer text is still to go up');
  await createSync({ store, db, userId: ME }).runOnce();
  assert.equal(server.row('user_texts', ME, 'plan').text, 'typed during upload');
  assert.equal(store.pendingCount(), 0);
});

test('quick changes make one sync, a little later', async () => {
  const server = fakeServer();
  const d = await device(server);
  for (let i = 0; i < 5; i++) {
    await d.store.change('workout_logs', log(`q${i}`));
    d.sync.nudge();
  }
  await new Promise((r) => setTimeout(r, 40));
  const upserts = server.log.filter((e) => e.op === 'upsert');
  assert.equal(upserts.length, 1);
  assert.equal(upserts[0].rows.length, 5);
  assert.equal(d.store.pendingCount(), 0);
});

test('a sync asked for while one runs runs once more afterwards', async () => {
  const server = fakeServer();
  const d = await device(server);
  await d.store.change('workout_logs', log('a'));
  const first = d.sync.runOnce();
  await d.store.change('workout_logs', log('b'));
  const joined = d.sync.runOnce();
  assert.equal(first, joined);
  await first;
  assert.equal(d.store.pendingCount(), 0);
  assert.ok(server.row('workout_logs', ME, 'b'));
});

test('upload rows have every column, with the server’s required defaults filled', () => {
  const row = toServer('exercise_settings', { exercise_key: 'squat', is_timed: true, updated_at: 'x', _k: 'squat', synced: null }, ME);
  assert.deepEqual(Object.keys(row).sort(), ['bodyweight_source', 'deleted_at', 'exercise_key', 'exercise_name', 'group_name', 'is_bodyweight', 'is_timed', 'last_viewed_at', 'updated_at', 'user_id', 'view_count']);
  assert.equal(row.view_count, 0);
  assert.equal(toServer('app_settings', { updated_at: 'x' }, ME).json.constructor, Object);
});
