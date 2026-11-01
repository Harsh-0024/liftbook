// The two Edge Functions end to end, against a fake Supabase and fake Gemini/Groq.
import test from 'node:test';
import assert from 'node:assert/strict';
import { fakeSupabase, logRow, ENV } from './fake_supabase.js';
import { handle as coach, RATE_LIMIT } from '../coach/handler.js';
import { handle as shortcut, sha256Hex, KEY_INVALID, KEY_MISSING, DAY_TAKEN } from '../shortcut/handler.js';
import { resolveDay, sessionLabels, normalizeKey } from '../shortcut/sessions.js';
import { localNow } from '../_shared/liftbook.js';

const ME = '11111111-1111-4111-8111-111111111111';
const OTHER = '22222222-2222-4222-8222-222222222222';
const NOW = Date.parse('2026-11-01T06:00:00Z'); // 11:30 in India
const PLAN = 'Session 1 – Chest & Biceps\nFlat Barbell Press - [3, 6-8]\nBarbell Curl - [2, 8-10]\n\nSession 2 – Back & Triceps\nBarbell Row - [3, 8-10]\nRod Pushdown - [2, 10-12]\n\nLegs 1\nSquat - [3, 5-8]';

function world() {
  const sb = fakeSupabase();
  sb.seed('profiles', { user_id: ME, username: 'harsh', full_name: 'Harsh Kumar', bodyweight: 78, created_at: '2025-01-01T00:00:00Z' });
  sb.seed('user_texts', { user_id: ME, kind: 'plan', text: PLAN });
  sb.seed('workout_logs', logRow(ME, 'a1', '2026-10-28T18:00:00', 'Flat Barbell Press', [60, 60, 60], [8, 7, 6]));
  sb.seed('workout_logs', logRow(ME, 'a2', '2026-10-28T18:00:00', 'Barbell Curl', [25, 25], [10, 9]));
  sb.seed('workout_logs', logRow(ME, 'a3', '2026-10-21T18:00:00', 'Flat Barbell Press', [57.5, 57.5, 57.5], [8, 8, 7]));
  sb.seed('workout_logs', logRow(ME, 'b1', '2026-10-30T18:00:00', 'Squat', [140], [5], { user_id: OTHER }));
  return sb;
}

const opts = (sb) => ({ fetchFn: sb.fetchFn, now: () => NOW });

/* ---------------- Shortcuts ---------------- */

async function withKey(sb, key = 'lbk_test_key_1234') {
  sb.seed('shortcut_keys', { user_id: ME, key_hash: await sha256Hex(key), key_hint: key.slice(-4), created_at: '2026-10-01T00:00:00Z' });
  return key;
}

const form = (fields) => ({ method: 'POST', body: new URLSearchParams(fields), headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
const call = (sb, path, init) => shortcut(new Request(`https://example.supabase.co/functions/v1/shortcut${path}`, init), ENV, opts(sb));

test('a Shortcut logs a workout through the sync tables', async () => {
  const sb = world();
  const key = await withKey(sb);
  const res = await call(sb, `/log/${key}`, form({ workout_text: '1/11 Session 1\n\nFlat Barbell Press\n62.5 60 60, 6 7 7\n\nBarbell Curl\n25 25, 10 10' }));
  const body = await res.json();
  assert.equal(body.ok, true, JSON.stringify(body));
  assert.equal(body.server, 'Supabase');
  assert.equal(body.date, '2026-11-01');
  assert.equal(body.exercise_count, 2);
  assert.equal(body.set_count, 6); // the parser reads "25 25, 10 10" as three sets, as Python does
  assert.equal(body.result_url, 'https://app.liftbook.in/#/workout/2026-11-01');
  assert.equal(body.input_source, 'form.workout_text');
  const rows = sb.tables.workout_logs.filter((r) => r.user_id === ME && r.date.startsWith('2026-11-01'));
  assert.deepEqual(rows.map((r) => r.exercise), ['Flat Barbell Press', 'Barbell Curl']);
  for (const r of rows) {
    assert.ok(!('legacy_id' in r), 'legacy_id is never written');
    assert.match(r.id, /^[0-9a-f-]{36}$/);
    assert.ok(r.updated_at && r.created_at && r.server_updated_at);
    assert.equal(r.deleted_at, null);
  }
  assert.equal(rows[0].top_weight, 62.5);
  // The key's last use is noted; nobody else's rows were touched.
  assert.ok(sb.tables.shortcut_keys[0].last_used_at);
  assert.equal(sb.tables.workout_logs.filter((r) => r.user_id === OTHER).length, 1);

  // Sent again (the phone gave up waiting the first time): no second copy.
  const again = await (await call(sb, `/log/${key}`, form({ workout_text: '1/11 Session 1\n\nFlat Barbell Press\n62.5 60 60, 6 7 7\n\nBarbell Curl\n25 25, 10 10' }))).json();
  assert.equal(again.ok, true);
  assert.equal(again.already_exists, true);
  assert.equal(again.message, 'Workout already there.');
  // A different workout on that day isn't saved.
  const other = await (await call(sb, `/log/${key}`, form({ workout_text: '1/11\nSquat\n100, 5' }))).json();
  assert.equal(other.ok, false);
  assert.equal(other.error, DAY_TAKEN);
  assert.equal(sb.tables.workout_logs.filter((r) => r.user_id === ME && r.date.startsWith('2026-11-01')).length, 2);
});

test('a Shortcut note can come as JSON, raw text, rich text, or with the key in a header', async () => {
  const sb = world();
  const key = await withKey(sb);
  const json = await (await call(sb, `/log/${key}`, { method: 'POST', body: JSON.stringify({ text: '20/10\nSquat\n100 100, 5 5' }), headers: { 'Content-Type': 'application/json' } })).json();
  assert.equal(json.ok, true, JSON.stringify(json));
  assert.equal(json.input_source, 'json.named');
  assert.equal(json.date, '2026-10-20');
  const raw = await (await call(sb, `/log/${key}`, { method: 'POST', body: '<div>19/10</div><div>Squat</div><div>90 90, 5 5</div>' })).json();
  assert.equal(raw.ok, true, JSON.stringify(raw));
  assert.equal(raw.input_source, 'raw.body');
  const header = await (await call(sb, '/log', { ...form({ note: '18/10 Squat • 80 80, 5 5' }), headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Liftbook-Key': key } })).json();
  assert.equal(header.ok, true, JSON.stringify(header));
  assert.equal(header.input_source, 'form.text_or_note');
  assert.equal(sb.tables.workout_logs.filter((r) => r.exercise === 'Squat' && r.user_id === ME).length, 3);
});

test('a Shortcut with a wrong or missing key saves nothing', async () => {
  const sb = world();
  await withKey(sb);
  const before = sb.tables.workout_logs.length;
  const wrong = await (await call(sb, '/log/lbk_not_it', form({ workout_text: '1/11\nSquat\n100, 5' }))).json();
  assert.deepEqual([wrong.ok, wrong.error, wrong.server], [false, KEY_INVALID, 'Supabase']);
  const missing = await (await call(sb, '/log', form({ workout_text: '1/11\nSquat\n100, 5' }))).json();
  assert.equal(missing.error, KEY_MISSING);
  const pick = await call(sb, '/pick/lbk_not_it?list=1');
  assert.equal(pick.status, 401);
  assert.equal(sb.tables.workout_logs.length, before);
  const empty = await (await call(sb, `/log/lbk_test_key_1234`, form({ workout_text: '  ' }))).json();
  assert.equal(empty.error, 'Please enter workout data.');
});

test('Get Workout lists the plan days and gives a day as text', async () => {
  const sb = world();
  const key = await withKey(sb);
  const list = await (await call(sb, `/pick/${key}?list=1`)).json();
  assert.deepEqual(list, { ok: true, sessions: ['Legs 1', 'Session 1 - Chest & Biceps', 'Session 2 - Back & Triceps'], server: 'Supabase' });
  const day = await (await call(sb, `/pick/${key}?format=json&key=${encodeURIComponent('Session 1 - Chest & Biceps')}`)).json();
  assert.equal(day.ok, true, JSON.stringify(day));
  assert.match(day.text, /Flat Barbell Press/);
  assert.match(day.text, /Barbell Curl/);
  const plain = await call(sb, `/pick/${key}?key=legs`);
  assert.equal(plain.headers.get('content-type'), 'text/plain; charset=utf-8');
  assert.match(await plain.text(), /Squat/);
  const bad = await (await call(sb, `/pick/${key}?format=json&key=zumba`)).json();
  assert.equal(bad.ok, false);
  assert.match(bad.error, /^No workout day matched 'zumba'\. Try one of: Legs 1, Session 1 - Chest & Biceps/);
});

test('session words resolve as the old app resolved them', () => {
  assert.equal(normalizeKey('Session 1 – Chest &amp; Biceps!'), 'session 1 chest biceps');
  const pick = (k, custom) => {
    const r = resolveDay(PLAN, k, custom);
    return r.day ? r.day.label : r.error;
  };
  // A bare number is every category's day with that number.
  assert.equal(pick('1'), "Ambiguous key '1'. Matches: Legs 1, Session 1 - Chest & Biceps");
  assert.equal(pick('2'), 'Session 2 - Back & Triceps');
  assert.equal(pick('s2'), 'Session 2 - Back & Triceps');
  assert.equal(pick('back'), 'Session 2 - Back & Triceps');
  assert.equal(pick('Legs-1'), 'Legs 1');
  assert.equal(pick('0'), "No workout day matched '0'. Try one of: Legs 1, Session 1 - Chest & Biceps, Session 2 - Back & Triceps");
  assert.match(pick('session'), /^Ambiguous key 'session'\. Matches: Session 1 - Chest & Biceps, Session 2 - Back & Triceps$/);
  assert.equal(pick('pull day', JSON.stringify({ 'session:2': 'Pull day' })), 'Session 2 - Back & Triceps');
  assert.equal(resolveDay('', 'x').error, 'No workout plan found.');
  assert.deepEqual(sessionLabels(PLAN), ['Legs 1', 'Session 1 - Chest & Biceps', 'Session 2 - Back & Triceps']);
});

test('a Shortcut workout without a date is dated by the clock in India', () => {
  assert.equal(localNow(330, Date.parse('2026-10-31T20:00:00Z')), '2026-11-01T01:30:00');
  assert.equal(localNow(0, Date.parse('2026-10-31T20:00:00Z')), '2026-10-31T20:00:00');
});

/* ---------------- the coach ---------------- */

const ask = (sb, token, body) => coach(new Request('https://example.supabase.co/functions/v1/coach', {
  method: 'POST', headers: token ? { Authorization: `Bearer ${token}` } : {}, body: JSON.stringify(body),
}), ENV, opts(sb));

const groqCall = (name, args) => () => ({ json: { choices: [{ message: { content: null, tool_calls: [{ id: 't1', function: { name, arguments: JSON.stringify(args) } }] } }], usage: { total_tokens: 100 } } });
const groqAnswer = (text) => () => ({ json: { choices: [{ message: { content: text } }], usage: { total_tokens: 50 } } });
const geminiAnswer = (text) => () => ({ json: { candidates: [{ content: { parts: [{ text }] } }], usageMetadata: { totalTokenCount: 40 } } });

test('the coach needs a sign-in and a key of the person’s own', async () => {
  const sb = world();
  assert.equal((await ask(sb, null, { messages: [{ role: 'user', text: 'hi' }] })).status, 401);
  assert.equal((await ask(sb, 'forged', { messages: [{ role: 'user', text: 'hi' }] })).status, 401);
  const token = sb.signIn(ME);
  sb.seed('ai_keys', { user_id: OTHER, api_key: 'gsk_someone_elses_key_000000', is_active: true, created_at: '2026-10-01T00:00:00Z' });
  sb.seed('ai_keys', { user_id: ME, api_key: 'gsk_switched_off_key_0000000', is_active: false, created_at: '2026-10-01T00:00:00Z' });
  const res = await ask(sb, token, { messages: [{ role: 'user', text: 'How is my bench?' }] });
  const body = await res.json();
  assert.equal(body.no_key, true);
  assert.equal(sb.ai.seen.length, 0, 'no model was asked');
});

test('the coach looks things up, answers, and keeps the answer', async () => {
  const sb = world();
  const token = sb.signIn(ME);
  sb.seed('ai_keys', { user_id: ME, api_key: 'gsk_my_groq_key_000000000000', is_active: true, created_at: '2026-10-01T00:00:00Z' });
  sb.ai.replies.push(groqCall('get_progress_trend', { exercise: 'flat barbell press' }), groqAnswer('Your **Flat Barbell Press** is up: 2026-10-28 beat 2026-10-21. Use get_progress_trend weekly.'));
  const res = await ask(sb, token, { messages: [{ role: 'user', text: 'How is my bench?' }], context: { page: 'coach' } });
  const body = await res.json();
  assert.equal(body.ok, true, JSON.stringify(body));
  assert.equal(body.answer, 'Your **Flat Barbell Press** is up: 2026-10-28 beat 2026-10-21. Use progress trend weekly.');
  assert.deepEqual(body.steps, [{ label: 'Progress trend', args: { exercise: 'flat barbell press' }, ok: true }]);
  assert.deepEqual(body.links.map((l) => l.url), ['#/workout/2026-10-28', '#/workout/2026-10-21']);
  assert.equal(body.model, 'openai/gpt-oss-120b');
  assert.ok(!('usage' in body) && !('key_id' in body));

  // The model got the person's real numbers back from the tool, and the prompt knows the day.
  const second = sb.ai.seen[1].body;
  assert.match(second.messages[0].content, /You are talking with Harsh\. Today is 2026-11-01 \(Sunday\)\. Weights are in kg\./);
  assert.match(second.messages[0].content, /Their bodyweight is 78 kg\./);
  const toolReply = JSON.parse(second.messages.find((m) => m.role === 'tool').content);
  assert.equal(toolReply.exercise, 'Flat Barbell Press');
  assert.equal(toolReply.latest.e1rm_kg, 76);
  assert.equal(sb.ai.seen[0].headers.authorization, 'Bearer gsk_my_groq_key_000000000000');

  const [saved] = sb.tables.coach_answers;
  assert.equal(saved.user_id, ME);
  assert.equal(saved.question, 'How is my bench?');
  assert.equal(saved.answer, body.answer);
  assert.equal(body.answer_id, saved.id);
  assert.deepEqual(saved.steps, [{ tool: 'get_progress_trend', args: { exercise: 'flat barbell press' }, ok: true }]);
  assert.equal(saved.calls, 2);
  assert.equal(saved.tokens, 150);
  assert.ok(sb.tables.ai_keys[0].last_used_at);
  // The training was read with the person's own sign-in, not the service key.
  const logReads = sb.requests.filter((r) => r.url.includes('/rest/v1/workout_logs'));
  assert.ok(logReads.length && logReads.every((r) => r.headers.authorization === `Bearer ${token}`));
});

test('a refused or busy key hands the question to the next model or key', async () => {
  const sb = world();
  const token = sb.signIn(ME);
  sb.seed('ai_keys', { user_id: ME, api_key: 'AIzaMyGeminiKey00000000000000', is_active: true, created_at: '2026-09-01T00:00:00Z' });
  sb.seed('ai_keys', { user_id: ME, api_key: 'gsk_revoked_groq_key_0000000', is_active: true, created_at: '2026-10-01T00:00:00Z' });
  sb.ai.replies.push(() => ({ status: 401, json: { error: 'invalid key' } }), () => ({ status: 429, json: {} }), geminiAnswer('Bench is moving up nicely.'));
  const body = await (await ask(sb, token, { messages: [{ role: 'user', text: 'Bench?' }] })).json();
  assert.equal(body.ok, true, JSON.stringify(body));
  assert.equal(body.model, 'gemini-3.5-flash-lite');
  assert.deepEqual(sb.ai.seen.map((s) => new URL(s.url).hostname), ['api.groq.com', 'generativelanguage.googleapis.com', 'generativelanguage.googleapis.com']);
  assert.equal(sb.tables.coach_answers[0].failed, 'openai/gpt-oss-120b:401,gemini-2.5-flash:429');

  sb.ai.replies.push(() => ({ status: 403, json: {} }), () => ({ status: 401, json: {} }));
  const refused = await (await ask(sb, token, { messages: [{ role: 'user', text: 'Bench?' }] })).json();
  assert.equal(refused.ok, false);
  assert.match(refused.error, /^Your AI keys were refused/);
});

test('the coach streams each lookup, then the answer', async () => {
  const sb = world();
  const token = sb.signIn(ME);
  sb.seed('ai_keys', { user_id: ME, api_key: 'gsk_my_groq_key_000000000000', is_active: true, created_at: '2026-10-01T00:00:00Z' });
  sb.ai.replies.push(groqCall('get_training_summary', { days: 28 }), groqAnswer('Two workouts in four weeks.'));
  const res = await ask(sb, token, { messages: [{ role: 'user', text: 'How did I train?' }], stream: true });
  assert.equal(res.headers.get('content-type'), 'application/x-ndjson');
  const lines = (await res.text()).trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(lines[0], { type: 'step', label: 'Training summary', args: { days: 28 }, ok: true });
  assert.equal(lines[1].type, 'done');
  assert.equal(lines[1].ok, true);
  assert.equal(lines[1].answer, 'Two workouts in four weeks.');
  assert.equal(typeof lines[1].answer_id, 'number');
});

test('the coach stops someone asking too much', async () => {
  const sb = world();
  const token = sb.signIn(ME);
  sb.seed('ai_keys', { user_id: ME, api_key: 'gsk_my_groq_key_000000000000', is_active: true, created_at: '2026-10-01T00:00:00Z' });
  for (let i = 0; i < RATE_LIMIT; i++) sb.seed('coach_answers', { user_id: ME, question: 'q', answer: 'a', created_at: new Date(NOW - 60000).toISOString() });
  const res = await ask(sb, token, { messages: [{ role: 'user', text: 'Again?' }] });
  assert.equal(res.status, 429);
  assert.equal(sb.ai.seen.length, 0);
});
