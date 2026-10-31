// Shared by the tests: loads the golden fixtures (made by scripts/make_core_fixtures.py) and
// compares results with what Python gave.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), 'fixtures');
let states = null;

export function load(name) {
  const cases = JSON.parse(readFileSync(join(FIXTURES, `${name}.json`), 'utf8')).cases;
  states ??= JSON.parse(readFileSync(join(FIXTURES, 'states.json'), 'utf8')).cases;
  for (const c of cases) {
    if (typeof c.input?.state === 'number') c.input.state = structuredClone(states[c.input.state]);
  }
  return cases;
}

// Floats may differ in the last digit or so: Python's statistics.mean/stdev work in exact
// fractions, and Math.log/exp are not guaranteed to round like libm.
const REL_TOL = 1e-9;
export const tally = { compared: 0, inexact: 0 };

function close(a, b) {
  if (a === b) return true;
  return Math.abs(a - b) <= REL_TOL * Math.max(Math.abs(a), Math.abs(b), 1e-300);
}

/** The first difference between actual and expected (a path and both values), or null. */
export function diff(actual, expected, path = '$') {
  if (typeof expected === 'number' && typeof actual === 'number') {
    tally.compared += 1;
    if (actual === expected || (Object.is(actual, -0) && expected === 0)) return null;
    if (close(actual, expected)) {
      tally.inexact += 1;
      return null;
    }
    return { path, actual, expected };
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual)) return { path, actual, expected };
    if (actual.length !== expected.length) return { path: `${path}.length`, actual: actual.length, expected: expected.length, actualValue: actual, expectedValue: expected };
    for (let i = 0; i < expected.length; i += 1) {
      const d = diff(actual[i], expected[i], `${path}[${i}]`);
      if (d) return d;
    }
    return null;
  }
  if (expected && typeof expected === 'object') {
    if (!actual || typeof actual !== 'object' || Array.isArray(actual)) return { path, actual, expected };
    const keys = new Set([...Object.keys(expected), ...Object.keys(actual)]);
    for (const key of keys) {
      if (!(key in actual)) return { path: `${path}.${key}`, missing: 'in JS', expected: expected[key] };
      if (!(key in expected)) return { path: `${path}.${key}`, missing: 'in Python', actual: actual[key] };
      const d = diff(actual[key], expected[key], `${path}.${key}`);
      if (d) return d;
    }
    return null;
  }
  return actual === expected ? null : { path, actual, expected };
}

/** Plain JSON data, as Python's json.dumps would give it (Maps become objects). */
export function plain(value) {
  if (value instanceof Map) return Object.fromEntries([...value].map(([k, v]) => [String(k), plain(v)]));
  if (value instanceof Set) return [...value].map(plain);
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v)]));
  return value;
}

/** Runs every case; fails with the first few mismatches, in readable form. */
export function check(t, cases, run, label = (c) => JSON.stringify(c.input).slice(0, 200)) {
  const failures = [];
  for (const c of cases) {
    let actual;
    try {
      actual = plain(run(c.input, c));
    } catch (err) {
      failures.push(`${label(c)}\n    threw ${err?.stack || err}`);
      continue;
    }
    const d = diff(actual, c.output);
    if (d) failures.push(`${label(c)}\n    ${JSON.stringify(d).slice(0, 1500)}`);
  }
  if (failures.length) {
    throw new Error(`${failures.length} of ${cases.length} cases differ from Python:\n  ${failures.slice(0, 8).join('\n  ')}`);
  }
  t.diagnostic(`${cases.length} cases match`);
}
