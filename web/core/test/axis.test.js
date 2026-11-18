// A chart's side scale: round gridlines.
import test from 'node:test';
import assert from 'node:assert/strict';
import { chartScale } from '../axis.js';

test('an exercise chart reads on round numbers, not on quarters of its range', () => {
  // These values used to label the side 67, 77, 88, 98, 109.
  assert.deepEqual(chartScale([70, 82.5, 105, 92, 70]).ticks, [60, 80, 100, 120]);
});

test('bodyweight in whole kilos, with no more than five lines', () => {
  assert.deepEqual(chartScale([78, 78, 79.5]).ticks, [77, 78, 79, 80]);
});

test('a percent chart around a start of 0 puts 0 on a line of its own', () => {
  const s = chartScale([0, 4, 9, 16.3, 13, -2.5]);
  assert.ok(s.ticks.includes(0));
  assert.deepEqual(s.ticks, [-10, 0, 10, 20]);
});

test('small steps get the decimals they need, and no float or "-0" leftovers', () => {
  const s = chartScale([0.1, 0.2, 0.3]);
  assert.deepEqual(s.ticks, [0, 0.1, 0.2, 0.3, 0.4]);
  assert.equal(s.places, 1);
  assert.equal(chartScale([0.1, 0.15]).places, 2); // steps of 0.025: 0.1, 0.125…
  assert.ok(s.ticks.every((t) => String(t).length <= 5 && !Object.is(t, -0)), String(s.ticks));
  assert.equal(chartScale([1, 7]).places, 0);
  assert.deepEqual(chartScale([60, 61]).ticks, [59.5, 60, 60.5, 61, 61.5]);
  assert.equal(chartScale([60, 61]).places, 1);
});

test('one value alone still gets a scale around it', () => {
  const s = chartScale([80]);
  assert.ok(s.lo < 80 && s.hi > 80);
});

test('any range: four or five lines, round steps, every value inside', () => {
  let seed = 7;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 5000; i++) {
    const a = (rand() - 0.3) * 10 ** (rand() * 4 - 1);
    const b = a + rand() * 10 ** (rand() * 4 - 1);
    const s = chartScale([a, b]);
    assert.ok(s.ticks.length >= 4 && s.ticks.length <= 5, `${a}..${b}: ${s.ticks}`);
    assert.ok(s.lo <= a && s.hi >= b, `${a}..${b} inside ${s.lo}..${s.hi}`);
    const lead = s.step / 10 ** Math.floor(Math.log10(s.step));
    assert.ok([1, 2, 2.5, 5].some((m) => Math.abs(lead - m) < 1e-9), `step ${s.step}`);
  }
});
