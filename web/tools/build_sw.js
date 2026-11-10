#!/usr/bin/env node
// Fills in sw.js's list of files to keep offline and its version (a hash of them all), so a
// change to any file installs as a new version. Run after changing anything in web/:
//
//   node web/tools/build_sw.js           (writes sw.js)
//   node web/tools/build_sw.js --check   (fails if sw.js is out of date; the tests run this)

import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SKIP = new Set(['test', 'tools', 'sw.js', 'README.md', '.DS_Store', '_headers', '_routes.json', '_worker.js']); // Cloudflare Pages' own files

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir).sort()) {
    if (SKIP.has(name) || name.startsWith('.')) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

export function build() {
  const files = walk(ROOT);
  const hash = createHash('sha256');
  for (const f of files) hash.update(relative(ROOT, f)).update(readFileSync(f));
  const list = ['./', ...files.map((f) => relative(ROOT, f).split('\\').join('/'))];
  const swPath = join(ROOT, 'sw.js');
  const sw = readFileSync(swPath, 'utf8');
  const next = sw
    .replace(/const VERSION = '[^']*';/, `const VERSION = '${hash.digest('hex').slice(0, 12)}';`)
    .replace(/const FILES = \[[\s\S]*?\];/, `const FILES = ${JSON.stringify(list, null, 2).replace(/"/g, "'")};`);
  return { sw, next, swPath };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const { sw, next, swPath } = build();
  if (process.argv.includes('--check')) {
    if (sw !== next) {
      console.error('web/sw.js is out of date: run node web/tools/build_sw.js');
      process.exit(1);
    }
  } else if (sw !== next) {
    writeFileSync(swPath, next);
    console.log('web/sw.js updated');
  } else {
    console.log('web/sw.js already up to date');
  }
}
