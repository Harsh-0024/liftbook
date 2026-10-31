import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from '../../tools/build_sw.js';

test('sw.js lists every app file and the current version (run node web/tools/build_sw.js)', () => {
  const { sw, next } = build();
  assert.ok(next.includes("'app/main.js'") && next.includes("'core/parser.js'") && !next.includes('fixtures'));
  assert.equal(sw, next);
});
