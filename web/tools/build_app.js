#!/usr/bin/env node
// Copies the web app into build/www, the files the Android app (Capacitor) carries inside it, so
// it opens and works with no connection. Leaves out what only the website or development needs:
// tests, tools, the offline copy (sw.js: the app already has every file) and Cloudflare's _headers.
//
//   node web/tools/build_app.js    (then: npx cap sync android; see android/README.md)

import { cpSync, mkdirSync, rmSync } from 'node:fs';
import { basename, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const OUT = fileURLToPath(new URL('../../build/www', import.meta.url));
const SKIP = new Set(['test', 'tools', 'sw.js', 'README.md', '.DS_Store', '_headers']);

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
cpSync(ROOT, OUT, {
  recursive: true,
  filter: (src) => src === ROOT || (!SKIP.has(basename(src)) && !basename(src).startsWith('.')),
});
console.log(`web app copied to ${join('build', 'www')}`);
