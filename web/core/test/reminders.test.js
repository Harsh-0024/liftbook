import test from 'node:test';
import assert from 'node:assert/strict';
import {
  reminderSettings, usualGapDays, inQuietHours, afterQuietHours, upcomingReminders, notificationId, DEFAULT_REMINDERS,
} from '../reminders.js';

const ON = { on: true };
const everyOtherDay = ['2026-10-20', '2026-10-22', '2026-10-24', '2026-10-26', '2026-10-28', '2026-10-30'];

test('reminders are off unless switched on, and odd settings fall back to the defaults', () => {
  assert.equal(DEFAULT_REMINDERS.on, false);
  assert.deepEqual(upcomingReminders({ now: '2026-11-05T08:00', workoutDays: everyOtherDay }), []);
  assert.deepEqual(reminderSettings({ on: 'yes', quietFrom: '25:99x', gapDays: -2 }),
    { on: false, quietFrom: '22:00', quietTo: '07:00', gapDays: 'auto' });
  assert.equal(reminderSettings({ gapDays: 4 }).gapDays, 4);
});

test('the usual gap is the median of the last eight weeks, once there are three gaps', () => {
  assert.equal(usualGapDays(everyOtherDay, '2026-10-31'), 2);
  assert.equal(usualGapDays(['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29'], '2026-10-30'), 1);
  assert.equal(usualGapDays(['2026-10-01', '2026-10-04', '2026-10-05', '2026-10-12', '2026-10-15'], '2026-10-16'), 3);
  assert.equal(usualGapDays(['2026-10-26', '2026-10-28'], '2026-10-30'), null); // one gap: can't tell
  assert.equal(usualGapDays(['2026-01-01', '2026-01-03', '2026-01-05', '2026-01-07', '2026-10-30'], '2026-10-31'), null); // old ones don't count
});

test('quiet hours can run past midnight', () => {
  const s = reminderSettings({});
  assert.equal(inQuietHours(23 * 60, s), true);
  assert.equal(inQuietHours(6 * 60 + 59, s), true);
  assert.equal(inQuietHours(7 * 60, s), false);
  assert.equal(inQuietHours(12 * 60, s), false);
  assert.equal(afterQuietHours('2026-11-05T23:30', s), '2026-11-06T07:00');
  assert.equal(afterQuietHours('2026-11-06T05:00', s), '2026-11-06T07:00');
  assert.equal(afterQuietHours('2026-11-06T09:00', s), '2026-11-06T09:00');
  const daytime = reminderSettings({ quietFrom: '13:00', quietTo: '15:00' });
  assert.equal(afterQuietHours('2026-11-06T14:10', daytime), '2026-11-06T15:00');
  assert.equal(inQuietHours(12 * 60, reminderSettings({ quietFrom: '08:00', quietTo: '08:00' })), false);
});

test('a gap reminder comes the morning after the usual gap has passed, and only once more after that', () => {
  // Every other day, last on 30 Oct: the 1st would be normal, so the 2nd brings a reminder.
  const [r] = upcomingReminders({ now: '2026-10-31T10:00', workoutDays: everyOtherDay, settings: ON });
  assert.equal(r.kind, 'gap');
  assert.equal(r.at, '2026-11-02T09:00');
  assert.equal(r.body, '3 days since your last one. You usually train every 2 days.');
  // Still nothing logged on the 2nd at noon: once more, the next morning.
  assert.equal(upcomingReminders({ now: '2026-11-02T12:00', workoutDays: everyOtherDay, settings: ON })[0].at, '2026-11-03T09:00');
  // A week away: it has said so twice; no more nagging.
  assert.deepEqual(upcomingReminders({ now: '2026-11-06T12:00', workoutDays: everyOtherDay, settings: ON }), []);
  // A workout logged moves it on.
  const after = upcomingReminders({ now: '2026-11-01T20:00', workoutDays: [...everyOtherDay, '2026-11-01'], settings: ON });
  assert.equal(after[0].at, '2026-11-04T09:00');
});

test('a gap set by hand wins over the worked-out one, and the morning time keeps out of quiet hours', () => {
  const [r] = upcomingReminders({ now: '2026-10-31T10:00', workoutDays: everyOtherDay, settings: { on: true, gapDays: 4 } });
  assert.equal(r.at, '2026-11-04T09:00');
  const late = upcomingReminders({ now: '2026-10-31T10:00', workoutDays: everyOtherDay, settings: { on: true, quietFrom: '21:00', quietTo: '10:30' } });
  assert.equal(late[0].at, '2026-11-02T10:30');
  // No workouts yet: nothing to remind about.
  assert.deepEqual(upcomingReminders({ now: '2026-10-31T10:00', workoutDays: [], settings: ON }), []);
});

test('a planned workout is reminded half an hour before, once or every week', () => {
  const planned = [
    { id: 'a', date: '2026-11-06', time: '18:00', title: 'Session 2 - Pull', category: 'Session', dayId: 2 },
    { id: 'b', weekday: 1, time: '19:30', title: '' }, // Mondays
  ];
  const all = upcomingReminders({ now: '2026-11-05T12:00', workoutDays: ['2026-11-05'], settings: ON, planned });
  const plannedOnes = all.filter((r) => r.kind === 'planned');
  assert.deepEqual(plannedOnes.map((r) => [r.at, r.title]), [
    ['2026-11-06T17:30', 'Session 2 - Pull'],
    ['2026-11-09T19:00', 'Workout'],
    ['2026-11-16T19:00', 'Workout'],
  ]);
  assert.equal(plannedOnes[0].body, 'Planned for 18:00 today. Tap to see what to aim for.');
  assert.deepEqual(plannedOnes.map((r) => r.route), ['retrieve/day/Session/2', 'retrieve', 'retrieve']);
  // A day already trained gets no reminder; a past one neither.
  const trained = upcomingReminders({ now: '2026-11-05T12:00', workoutDays: ['2026-11-06'], settings: ON, planned: [planned[0]] });
  assert.equal(trained.filter((r) => r.kind === 'planned').length, 0);
  assert.equal(upcomingReminders({ now: '2026-11-07T12:00', settings: ON, planned: [planned[0]] }).length, 0);
});

test('a planned workout in or near quiet hours: moved to when they end, or dropped if that is too late', () => {
  // 7:15 am workout: 6:45 is quiet, 7:00 is still before it starts.
  const [early] = upcomingReminders({ now: '2026-11-05T12:00', settings: ON, planned: [{ id: 'x', date: '2026-11-06', time: '07:15' }] });
  assert.equal(early.at, '2026-11-06T07:00');
  // 6:00 am workout: quiet until after it starts, so no reminder.
  assert.equal(upcomingReminders({ now: '2026-11-05T12:00', settings: ON, planned: [{ id: 'y', date: '2026-11-06', time: '06:00' }] }).length, 0);
  // 00:10 with no quiet hours: the reminder is the evening before, worded "tomorrow".
  const [night] = upcomingReminders({ now: '2026-11-05T12:00', settings: { on: true, quietFrom: '00:00', quietTo: '00:00' }, planned: [{ id: 'z', date: '2026-11-06', time: '00:10' }] });
  assert.equal(night.at, '2026-11-05T23:40');
  assert.match(night.body, /tomorrow/);
});

test('notification ids are whole numbers that stay the same for a reminder', () => {
  const a = notificationId('planned:a:2026-11-06');
  assert.equal(a, notificationId('planned:a:2026-11-06'));
  assert.notEqual(a, notificationId('planned:a:2026-11-13'));
  assert.ok(Number.isInteger(a) && a > 0 && a < 2 ** 31);
});
