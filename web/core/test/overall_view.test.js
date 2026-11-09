// The overall-strength card against what the original Stats page (templates/stats.html) showed
// for the same data: the demo user's 36 workouts (Push/Pull/Legs, bodyweight 78 kg).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { overallView, formatVsStart, formatPercentChange, trailingAverageByDate, rangeStartIndex } from '../overall_view.js';

const data = JSON.parse(readFileSync(new URL('./fixtures/overall_demo.json', import.meta.url)));

test('headline, line under it and tiles match the original page on every range', () => {
  const expect = {
    all: ['+14%', null, '+16.3%', 52, 'all time', ['Barbell Row', '+35%']],
    30: ['+14%', '8.4% stronger than a month ago', '+16.3%', 24, 'last month', ['Flat Barbell Press', '+17%']],
    90: ['+14%', '19% stronger than 3 months ago', '+16.3%', 52, 'last 3 months', null],
  };
  for (const [range, [headline, change, best, newBests, rangeText, top]] of Object.entries(expect)) {
    const v = overallView(data, range);
    assert.equal(v.headline, headline, range);
    assert.equal(v.change ? `${v.change.amount || ''}${v.change.text}` : null, change, range);
    assert.equal(v.best.text, best, range);
    assert.equal(v.newBests, newBests, range);
    assert.equal(v.rangeText, rangeText, range);
    assert.deepEqual(v.top ? [v.top.name, v.top.text] : null, top, range);
    assert.equal(v.direction, 'up');
    assert.equal(v.firstLabel, data.labels[0]);
  }
});

test('the chart line ends on the headline', () => {
  const v = overallView(data, 'all');
  assert.equal(Math.round(v.line.at(-1)), 14);
});

test('formats and helpers', () => {
  assert.equal(formatVsStart(116.344), '+16.3%');
  assert.equal(formatVsStart(98), '−2%');
  assert.equal(formatVsStart(100.01), '0%');
  assert.equal(formatPercentChange(-8.43), '8.4%');
  assert.equal(formatPercentChange(19.4), '19%');
  assert.deepEqual(trailingAverageByDate(['2026-01-01', '2026-01-10', '2026-01-20'], [100, 110, 120], 14), [100, 105, 115]);
  assert.equal(rangeStartIndex(['2026-01-01', '2026-01-10', '2026-01-20'], '15'), 1);
  assert.equal(overallView({ labels: [], data: [] }, 'all'), null);
});
