// The workout page's insights against what services/workout_insights.py gives for the same input
// (expected values printed by the Python module).
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatPct, rankedSets, compareColumns, sessionScore, trend, bestSummary, sparkline, displaySets, shortDate, longDate,
} from '../insights.js';

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} vs ${b}`);

test('percentages read as in Python (half-even rounding included)', () => {
  const cases = [[4.83, '+4.8%', '4.8%'], [-12.4, '−12%', '12%'], [0.4, '+0.4%', '0.4%'], [0, '0%', '0%'], [10, '+10%', '10%'],
    [9.96, '+10%', '10%'], [-0.05, '−0.1%', '0.1%'], [2.5, '+2.5%', '2.5%'], [1.25, '+1.2%', '1.2%']];
  for (const [v, signed, plain] of cases) {
    assert.equal(formatPct(v), signed);
    assert.equal(formatPct(v, { signed: false }), plain);
  }
  assert.equal(formatPct(null), '');
});

test('sets rank strongest first, labelled as logged', () => {
  const plain = { usesBodyweight: false, isTimed: false };
  const today = rankedSets({ weights: [100, 105, 0], reps: [5, 3, 8] }, { weights: [100, 105, 0], reps: [5, 3, 8] }, plain);
  assert.deepEqual(today.map((r) => r.label), ['100×5', '105×3']);
  close(today[0].score, 116.66666666666667);
  const bw = rankedSets({ weights: [0, 5, -10], reps: [10, 8, 12] }, { weights: [70, 75, 60], reps: [10, 8, 12] }, { usesBodyweight: true, isTimed: false });
  assert.deepEqual(bw.map((r) => r.label), ['BW+5×8', 'BW×10', 'BW−10×12']);
  assert.deepEqual(rankedSets({ weights: [0, 0], reps: [60, 45] }, { weights: [0, 0], reps: [60, 45] }, { usesBodyweight: false, isTimed: true }), []);

  const last = rankedSets({ weights: [100, 100], reps: [5, 4] }, { weights: [100, 100], reps: [5, 4] }, plain);
  const cols = compareColumns(today, last, null);
  assert.equal(cols.length, 2);
  assert.deepEqual([cols[0].rank, cols[0].today, cols[0].last.label, cols[0].last.pct_text, cols[0].last.direction, cols[0].best],
    ['1st', '100×5', '100×5', 'same', 'steady', null]);
  assert.deepEqual([cols[1].rank, cols[1].last.label, cols[1].last.pct_text, cols[1].last.direction], ['2nd', '100×4', '+1.9%', 'up']);
});

test('session score, trend and best chips match Python', () => {
  close(sessionScore({ weights: [100, 105, 90], reps: [5, 3, 8] }, { topN: 3, isTimed: false }), 174.04166666666669);
  const tr = trend(110, [{ day: '2026-10-27', score: 100 }, { day: '2026-10-21', score: 104 }, { day: '2026-10-15', score: 0 },
    { day: '2026-10-09', score: 98 }, { day: '2026-10-01', score: 90 }]);
  assert.deepEqual([tr.direction, tr.text, tr.count, tr.days], ['up', '↑ 9.3%', 3, ['2026-10-09', '2026-10-21', '2026-10-27']]);
  close(tr.average, 100.66666666666667);
  assert.equal(trend(0, [{ score: 1 }]), null);

  const expect = [
    [['gold_strength', 2.4, 0, true], 'medal', '🥇', '+2.4%', 'New best: your strongest set beat your best by 2.4%.'],
    [['silver_load', 3.1, 1, true], 'medal', '🥈', '+3.1%', 'New best: same strength as your best, with 3.1% more weight on your 2nd set.'],
    [['bronze_strength', 1.25, 2, true], 'medal', '🥉', '+1.2%', 'New best: your top two sets matched your best, and your 3rd set beat it by 1.2%.'],
    [['significantly_off', -5.2, 0, true], 'below', '', '−5.2%', 'Your strongest set was 5.2% below your best.'],
    [['moderately_off', -0.4, 1, true], 'below', '', '<1%', 'Your strongest set matched your best, but your 2nd set was less than 1% below it.'],
    [['consistent', null, null, true], 'match', '', '= Best', 'You matched your best exactly.'],
    [['first_log', null, null, true], 'first', '', '✦ New', 'No earlier session with the same number of sets to compare against yet.'],
    [['first_log', null, null, false], 'first', '', '✦ First', 'First time logged, so this sets your baseline.'],
  ];
  for (const [[key, pct, idx, hasHistory], kind, emoji, chip, explain] of expect) {
    const b = bestSummary({ key, diff_pct: pct, diff_index: idx }, { hasHistory });
    assert.deepEqual([b.kind, b.emoji, b.chip, b.explain], [kind, emoji, chip, explain], key);
  }
});

test('sparkline points as in Python', () => {
  const sp = sparkline([100, 102, 101, 105].map((score) => ({ score })), { average: 101 });
  assert.deepEqual(sp.dots.map((d) => d.y), [92.5, 62.5, 77.5, 17.5]);
  assert.deepEqual(sp.dots.map((d) => d.x), [10, 203.3, 396.7, 590]);
  assert.equal(sp.average_y, 77.5);
  assert.equal(sparkline([{ score: 5 }]), null);
});

test('bodyweight sets show the load added to bodyweight; dates', () => {
  assert.deepEqual(displaySets({ sets: { weights: [70, 75], reps: [10, 8] }, bodyweight: 70 }, { weights: [70, 75], reps: [10, 8] }, true),
    { weights: [0, 5], reps: [10, 8] });
  assert.deepEqual(displaySets({ sets: { weights: [1, 10], reps: [10, 8] }, bodyweight: null }, { weights: [71, 80], reps: [10, 8] }, true),
    { weights: [0, 10], reps: [10, 8] });
  assert.equal(shortDate('2026-08-10', 2026), '10 Aug');
  assert.equal(shortDate('2025-08-10', 2026), '10 Aug 2025');
  assert.equal(longDate('2026-07-12'), 'Sun, 12 Jul 2026');
});
