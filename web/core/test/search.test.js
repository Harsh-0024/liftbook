import test from 'node:test';
import assert from 'node:assert/strict';
import { exerciseMatches } from '../search.js';

test('plain text still matches as before', () => {
  assert.equal(exerciseMatches('Barbell Row', 'row'), true);
  assert.equal(exerciseMatches('Barbell Row', 'BARBELL R'), true);
  assert.equal(exerciseMatches('Barbell Row', ''), true);
  assert.equal(exerciseMatches('Barbell Row', 'curl'), false);
});

test('gym short names find the lift', () => {
  assert.equal(exerciseMatches('Romanian Deadlift', 'rdl'), true);
  assert.equal(exerciseMatches('Seated Overhead Press', 'ohp'), true);
  assert.equal(exerciseMatches('Flat Barbell Bench Press', 'bp'), true);
  assert.equal(exerciseMatches('Lat Pull-Down', 'lpd'), true);
  assert.equal(exerciseMatches('Pull-Ups', 'pullups'), true);
  assert.equal(exerciseMatches('Barbell Back Squat', 'rdl'), false);
});

test('each word may be short, and words come in any order', () => {
  assert.equal(exerciseMatches('Incline Dumbbell Press', 'db press'), true);
  assert.equal(exerciseMatches('Incline Dumbbell Press', 'press incl db'), true);
  assert.equal(exerciseMatches('Incline EZ-Bar Skull Crushers', 'ez skull'), true);
  assert.equal(exerciseMatches('Dumbbell Romanian Deadlift', 'db rdl'), true);
  assert.equal(exerciseMatches('Incline Dumbbell Press', 'bb press'), false);
});
