// Every file the browser loads must at least parse: screens that need a page (DOM) aren't
// imported by the other tests, so a slip such as a name declared twice would only show up as a
// blank app. `node --check` reads each file the way the browser will, as a module.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('../..', import.meta.url));

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (name === 'test' || name === 'tools' || name.startsWith('.')) return [];
    if (statSync(full).isDirectory()) return files(full);
    return name.endsWith('.js') ? [full] : [];
  });
}

test('every script in web/ parses as a module', () => {
  const all = files(WEB);
  assert.ok(all.length > 20);
  for (const f of all) {
    const type = f.endsWith('sw.js') ? 'commonjs' : 'module'; // sw.js is a classic worker script
    try {
      execFileSync(process.execPath, [`--input-type=${type}`, '--check'], { input: readFileSync(f), stdio: ['pipe', 'pipe', 'pipe'] });
    } catch (err) {
      assert.fail(`${f.slice(WEB.length)} doesn't parse:\n${String(err.stderr || err.message)}`);
    }
  }
});
