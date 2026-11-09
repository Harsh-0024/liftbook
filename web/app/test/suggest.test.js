import test from 'node:test';
import assert from 'node:assert/strict';
import { nameAt, matchNames, applyName } from '../suggest.js';

const TEXT = '31/10/26 Push\n\nBench press\n60 x 8\n\nincl';

test('names are suggested only while typing a name, not the title or sets', () => {
  assert.equal(nameAt(TEXT, 8), null, 'the first line is the date and title');
  assert.equal(nameAt(TEXT, TEXT.indexOf('60') + 2), null, 'a sets line');
  assert.equal(nameAt('31/10\n\nbw x 8', 12), null, 'bodyweight sets');
  assert.equal(nameAt('31/10\n\nB', 8), null, 'one letter is too few');
  const at = nameAt(TEXT, TEXT.length);
  assert.equal(at.prefix, 'incl');
  assert.equal(nameAt('31/10\n\nCurl - [8-12]', 12), null, 'after the name, in the rep range');
});

test('matches start with what was typed first, then contain it; at most six', () => {
  const names = ['Incline Press', 'Barbell Curl', 'Incline Curl', 'Curl', 'Hammer Curl', 'Cable Curl', 'Preacher Curl', 'Spider Curl', 'Squat'];
  assert.deepEqual(matchNames(names, 'cur'), ['Curl', 'Barbell Curl', 'Incline Curl', 'Hammer Curl', 'Cable Curl', 'Preacher Curl']);
  assert.deepEqual(matchNames(names, 'squat'), [], 'the name already typed in full');
});

test('picking a name replaces the word and keeps the rep range', () => {
  const v = '31/10\n\nincl - [6-8]\n60 x 8';
  const at = nameAt(v, 11);
  const r = applyName(v, at, 'Incline Press');
  assert.equal(r.text, '31/10\n\nIncline Press - [6-8]\n60 x 8');
  assert.equal(r.text.slice(0, r.cursor), '31/10\n\nIncline Press');
  const mid = nameAt('31/10\n\nIncl Press', 9);
  assert.equal(applyName('31/10\n\nIncl Press', mid, 'Incline Press').text, '31/10\n\nIncline Press', 'mid-word replaces the whole name');
});
