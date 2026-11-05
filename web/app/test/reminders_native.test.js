// The phone side of reminders (app/native.js), with a stand-in for Capacitor's
// LocalNotifications plugin: Liftbook's pending notifications are replaced by the new list,
// nothing else is touched, and nothing is set without permission.
import test from 'node:test';
import assert from 'node:assert/strict';

function fakePlugin({ permission = 'granted' } = {}) {
  const state = { pending: [{ id: 7, title: 'someone else', extra: {} }], permission, asked: 0, listeners: {} };
  return {
    state,
    async checkPermissions() { return { display: state.permission }; },
    async requestPermissions() { state.asked += 1; state.permission = 'granted'; return { display: 'granted' }; },
    async getPending() { return { notifications: state.pending.slice() }; },
    async cancel({ notifications }) { const ids = new Set(notifications.map((n) => n.id)); state.pending = state.pending.filter((n) => !ids.has(n.id)); },
    async schedule({ notifications }) { state.pending.push(...notifications); },
    addListener(name, fn) { state.listeners[name] = fn; },
  };
}

const LN = fakePlugin();
globalThis.Capacitor = { isNativePlatform: () => true, Plugins: { LocalNotifications: LN } };
const native = await import('../native.js');
const { notificationId } = await import('../../core/reminders.js');

const list = [
  { key: 'gap:2026-10-30', kind: 'gap', at: '2026-11-02T09:00', title: 'Time for a workout?', body: '3 days since your last one.' },
  { key: 'planned:a:2026-11-06', kind: 'planned', at: '2026-11-06T17:30', title: 'Session 2 - Pull', body: 'Planned for 18:00 today.', day: '2026-11-06' },
];

test('reminders are set at the local time, and replace the old ones but nothing else', async () => {
  assert.equal(native.remindersSupported, true);
  assert.equal(await native.scheduleReminders(list, notificationId), 2);
  assert.equal(await native.scheduleReminders(list, notificationId), 2); // again: no doubles
  const ours = LN.state.pending.filter((n) => n.extra?.liftbook);
  assert.equal(ours.length, 2);
  assert.equal(LN.state.pending.length, 3); // the other app's one stays
  const pull = ours.find((n) => n.extra.kind === 'planned');
  assert.equal(pull.id, notificationId('planned:a:2026-11-06'));
  assert.deepEqual([pull.schedule.at.getFullYear(), pull.schedule.at.getMonth(), pull.schedule.at.getDate(), pull.schedule.at.getHours(), pull.schedule.at.getMinutes()], [2026, 10, 6, 17, 30]);
  assert.equal(pull.extra.route, 'retrieve');
  // Switched off (empty list): Liftbook's are cleared.
  await native.scheduleReminders([], notificationId);
  assert.deepEqual(LN.state.pending.map((n) => n.id), [7]);
});

test('without permission nothing is set, and permission is only asked for when the person turns them on', async () => {
  LN.state.permission = 'denied';
  assert.equal(await native.scheduleReminders(list, notificationId), 0);
  assert.equal(LN.state.pending.filter((n) => n.extra?.liftbook).length, 0);
  LN.state.permission = 'prompt';
  assert.equal(await native.reminderPermission(), 'prompt');
  assert.equal(LN.state.asked, 0);
  assert.equal(await native.reminderPermission({ ask: true }), 'granted');
  assert.equal(LN.state.asked, 1);
});

test('tapping a reminder opens its page', () => {
  const opened = [];
  native.onReminderTap((route) => opened.push(route));
  LN.state.listeners.localNotificationActionPerformed({ notification: { extra: { liftbook: true, route: 'retrieve' } } });
  LN.state.listeners.localNotificationActionPerformed({ notification: { extra: {} } }); // not ours
  assert.deepEqual(opened, ['retrieve']);
});
