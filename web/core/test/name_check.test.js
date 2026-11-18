import test from 'node:test';
import assert from 'node:assert/strict';
import { nameNotes } from '../name_check.js';

const known = { isKnown: (n) => n === 'Rows', suggestion: () => null };

test('a one-letter exercise name is flagged as a likely set line', () => {
  const notes = nameNotes([{ name: 'Rows', line: 2 }, { name: 'X', line: 4 }, { name: 'Shrugs', line: 5 }], known);
  assert.equal(notes[0].state, 'ok');
  assert.equal(notes[1].state, 'short');
  assert.equal(notes[1].note, 'Too short for a name: is this a set line?');
  assert.equal(notes[2].note, 'New exercise');
});
