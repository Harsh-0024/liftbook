import test from 'node:test';
import { load, check } from './helpers.js';
import { parsePlanExerciseLine } from '../parser.js';
import { canonicalRepText, getWorkoutDays, parseRepEntries } from '../plans.js';

test('plan exercise lines match Python', (t) => check(t, load('plan_line'), ({ line }) => parsePlanExerciseLine(line)));
test('plan days match Python', (t) => check(t, load('workout_days'), ({ text }) => getWorkoutDays(text)));
test('rep-range entries match Python', (t) => check(t, load('rep_entries'), ({ text }) => parseRepEntries(text)));
test('canonical rep-range text matches Python', (t) => check(t, load('rep_canonical'), ({ text }) => canonicalRepText(text)));
