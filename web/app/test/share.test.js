import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shareUrl, sharedText, SHARE_PATH } from '../share.js';

test('a share link points at this website, or the public one from the phone app', () => {
  const token = 'a'.repeat(32);
  assert.equal(shareUrl(token, { native: false, loc: { origin: 'https://beta.liftbook.in', pathname: '/' } }),
    `https://beta.liftbook.in/#/s/${token}`);
  assert.equal(shareUrl(token, { native: true }), `https://beta.liftbook.in/#/s/${token}`);
  assert.equal(SHARE_PATH.exec(`s/${token}`)[1], token);
  assert.equal(SHARE_PATH.exec('s/not-a-token'), null);
});

test('a shared workout copies as the owner’s text, with the link', () => {
  const w = {
    day: '2025-05-10', workout_name: 'Push',
    exercises: [
      { exercise: 'Bench Press', exercise_string: 'Bench Press\n85 x 5', sets: { weights: [85], reps: [5] } },
      { exercise: 'Dip', exercise_string: null, sets: { weights: ['bw'], reps: [8] } },
    ],
  };
  const text = sharedText(w, 'https://x/#/s/abc');
  assert.match(text, /^10\/5\/25 Push\n\nBench Press\n85 x 5\n\nDip\n/);
  assert.match(text, /Shared from Liftbook: https:\/\/x\/#\/s\/abc$/);
});
