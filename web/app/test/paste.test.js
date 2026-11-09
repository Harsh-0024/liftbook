import test from 'node:test';
import assert from 'node:assert/strict';
import { tidyPaste } from '../paste.js';

test('a paste with a blank line between every line is put back together', () => {
  const doubled = '4/11/26 Push\n\nBench Press - [3]\n\n60 x 8, 8\n\nbw x 10\n\nCurl\n\n20, 10\n';
  assert.equal(tidyPaste(doubled), '4/11/26 Push\n\nBench Press - [3]\n60 x 8, 8\nbw x 10\n\nCurl\n20, 10\n');
  assert.equal(tidyPaste(doubled.replace(/\n/g, '\r\n')), '4/11/26 Push\n\nBench Press - [3]\n60 x 8, 8\nbw x 10\n\nCurl\n20, 10\n');
});

test('normal pastes and short ones are left alone', () => {
  const normal = '4/11/26 Push\n\nBench Press\n60 x 8\n\nCurl\n20, 10';
  assert.equal(tidyPaste(normal), normal);
  assert.equal(tidyPaste('Bench Press\n\n60 x 8'), 'Bench Press\n\n60 x 8', 'fewer than four lines');
});
