// The coach and note-text cleaning give what the Python app gives (fixtures made by
// scripts/make_function_fixtures.py).
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { check } from '../../../web/core/test/helpers.js';
import { runTool, coachData } from '../../../web/core/coach_tools.js';
import { toPlainText } from '../../../web/core/rich_text.js';
import {
  systemPrompt, cleanHistory, keyProvider, modelOrder, geminiPayload, openaiPayload, parseGemini, parseOpenai,
  plainWords, linksFor,
} from '../coach/coach.js';

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), 'fixtures');
const load = (name) => JSON.parse(readFileSync(join(FIXTURES, `${name}.json`), 'utf8')).cases;

test('coach tools match Python', (t) => {
  const states = load('coach_states');
  const data = new Map();
  check(t, load('coach_tools'), ({ tool, args, today, state }, c) => {
    const key = `${state}|${today}`;
    if (!data.has(key)) {
      const s = states[state];
      const history = [...s.history].sort((a, b) => a.id - b.id);
      data.set(key, coachData({ history, settings: s.settings, planText: s.plan, repRangesText: s.rep_ranges, today }));
    }
    const out = runTool(data.get(key), tool, args);
    // Python crashed on a missing required argument; here the model is told what's wrong.
    if (c.output.python_raised) return 'error' in out ? c.output : out;
    return out;
  }, (c) => `${c.input.tool}(${JSON.stringify(c.input.args)}) state ${c.input.state} on ${c.input.today}`);
});

test('note text is cleaned as Python cleans it', (t) => {
  check(t, load('rich_text'), (input) => toPlainText(input && input.bytes ? new Uint8Array(input.bytes) : input));
});

test('coach prompt matches Python', (t) => {
  check(t, load('coach_prompt'), ({ profile, context, today }) => systemPrompt(profile, context, today));
});

test('chat history clean-up matches Python', (t) => {
  check(t, load('coach_history'), (input) => cleanHistory(input));
});

test('key provider and model order match Python', (t) => {
  check(t, load('coach_key_provider'), (input) => keyProvider(input));
  check(t, load('coach_model_order'), (input) => modelOrder(input));
});

// Python's json.dumps puts spaces after , and : inside tool arguments and results.
const reparse = (payload) => JSON.parse(JSON.stringify(payload), (k, v) => (
  (k === 'arguments' || k === 'content') && typeof v === 'string' && /^[[{]/.test(v) ? JSON.parse(v) : v));

test('request bodies match Python', (t) => {
  const cases = load('coach_payload').map((c) => ({ ...c, output: reparse(c.output) }));
  check(t, cases, ({ kind, model, final, turns }) => reparse(kind === 'gemini'
    ? geminiPayload('SYSTEM', turns, final)
    : openaiPayload('SYSTEM', turns, model, final)));
});

test('replies are read as Python reads them', (t) => {
  check(t, load('coach_parse'), ({ kind, data, round }) => (kind === 'gemini' ? parseGemini(data, round) : parseOpenai(data, round)));
});

test('answers lose tool names and gain workout links as in Python', (t) => {
  check(t, load('coach_plain_words'), (input) => plainWords(input));
  check(t, load('coach_links'), (input) => linksFor(input));
});
