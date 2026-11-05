// The app's side of the home-screen widget (native.js updateWidget), with a stand-in for the
// app's own LiftbookWidget plugin (android/.../WidgetBridgePlugin.java).
import test from 'node:test';
import assert from 'node:assert/strict';

const calls = [];
globalThis.Capacitor = {
  isNativePlatform: () => true,
  Plugins: { LiftbookWidget: { update: async (a) => calls.push(['update', a]), clear: async () => calls.push(['clear']) } },
};
const { updateWidget } = await import('../native.js');

test('the summaries go to the widget, and signing out clears it', async () => {
  const days = { '2026-11-05': { heading: 'Next', title: 'Session 2 - Pull', lines: [], more: 0, route: 'retrieve/day/Session/2' } };
  assert.equal(await updateWidget(days), true);
  assert.equal(await updateWidget(null), true);
  assert.deepEqual(calls, [['update', { days }], ['clear']]);
});
