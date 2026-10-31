// The helpers that make JavaScript behave like Python, checked against values Python 3.13 gives.
import test from 'node:test';
import assert from 'node:assert/strict';
import { formatFixed, formatG, pyRound, re, split, title, toFloat, toInt } from '../py.js';

test('numbers print as Python prints them', () => {
  const values = [0.1 + 0.2, 1e16, 123456789.0, 2.5, 1e-5, 0.0001, 100.0, -0.0, 1 / 3];
  assert.deepEqual(values.map((v) => formatG(v)), ['0.3', '1e+16', '1.23457e+08', '2.5', '1e-05', '0.0001', '100', '-0', '0.333333']);
  assert.deepEqual([0.25, 0.35, 2.675, -1.45].map((v) => pyRound(v, 1)), [0.2, 0.3, 2.7, -1.4]);
  assert.deepEqual([0.25, 0.35, 2.675, -1.45].map((v) => formatFixed(v, 1)), ['0.2', '0.3', '2.7', '-1.4']);
});

test('text helpers behave like Python', () => {
  assert.equal(re('(\\d+)\\s*sets?\\s*of\\s*(\\d+)').sub('\\1x\\2', '3 sets of 8 at 60'), '3x8 at 60');
  assert.deepEqual(split(' a b c '), ['a', 'b', 'c']);
  assert.equal(title("o'neil pull-ups 3rd"), "O'Neil Pull-Ups 3Rd");
  assert.equal(toInt('١٠'), 10);
  assert.equal(toFloat(' ０.５ '), 0.5);
  assert.throws(() => toInt('1.5'));
});
