import test from 'node:test';
import { load, check } from './helpers.js';
import { workoutParser } from '../parser.js';

test('workout parser matches Python', (t) => {
  check(t, load('parser'), ({ text, bodyweight, preserve, now }) =>
    workoutParser(text, { bodyweight, preserveBodyweightOffsets: preserve, now }), (c) => JSON.stringify(c.input.text).slice(0, 300));
});
