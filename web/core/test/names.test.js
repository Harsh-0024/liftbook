import test from 'node:test';
import { load, check } from './helpers.js';
import { normalizeExerciseName, sameExercise } from '../names.js';

test('exercise names normalise as in Python', (t) => check(t, load('normalize'), ({ name }) => normalizeExerciseName(name)));
test('same-exercise matching agrees with Python', (t) => check(t, load('same_exercise'), ({ a, b }) => sameExercise(a, b)));
