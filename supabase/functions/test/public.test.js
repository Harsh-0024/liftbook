// The two functions anyone may call: share (a shared day plus the owner's photo) and signin
// (sign in with a username). Supabase is a small stub that records what was asked.
import test from 'node:test';
import assert from 'node:assert/strict';
import { handle as share } from '../share/handler.js';
import { handle as signin, MAX_FAILURES, NO_MATCH } from '../signin/handler.js';

const ENV = { SUPABASE_URL: 'https://x.supabase.co', SUPABASE_ANON_KEY: 'anon', SUPABASE_SERVICE_ROLE_KEY: 'service' };
const TOKEN = 'a'.repeat(32);
const WORKOUT = { day: '2026-11-09', username: 'harsh', workout_name: 'Push', exercises: [{ exercise: 'Bench Press', sets: { weights: [60], reps: [8] }, best: true }] };

function stub(routes) {
  const calls = [];
  const fetchFn = async (url, init = {}) => {
    const u = new URL(url);
    const key = `${init.method || 'GET'} ${u.pathname}`;
    calls.push({ key, url: String(url), init });
    const r = routes[key];
    const out = typeof r === 'function' ? r(u, init) : r;
    if (out === undefined) return new Response('{"message":"not stubbed"}', { status: 404 });
    const [status, body] = Array.isArray(out) && typeof out[0] === 'number' ? out : [200, out];
    return new Response(status === 204 ? null : JSON.stringify(body), { status });
  };
  return { fetchFn, calls };
}

const get = (path) => new Request(`https://x.supabase.co/functions/v1/share/${path}`);

test('share: a shared day with a 7-day link to the owner\'s photo', async () => {
  const { fetchFn, calls } = stub({
    'POST /rest/v1/rpc/shared_workout': WORKOUT,
    'GET /rest/v1/share_links': [{ user_id: 'u1' }],
    'GET /rest/v1/profiles': [{ avatar_path: 'u1/avatar-1.jpg' }],
    'POST /storage/v1/object/sign/avatars/u1/avatar-1.jpg': { signedURL: '/object/sign/avatars/u1/avatar-1.jpg?token=t' },
  });
  const res = await share(get(TOKEN), ENV, { fetchFn });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.workout_name, 'Push');
  assert.equal(body.avatar_url, 'https://x.supabase.co/storage/v1/object/sign/avatars/u1/avatar-1.jpg?token=t');
  const sign = calls.find((c) => c.key.startsWith('POST /storage'));
  assert.equal(sign.init.headers.Authorization, 'Bearer service');
  assert.deepEqual(JSON.parse(sign.init.body), { expiresIn: 7 * 86400 });
});

test('share: no photo is fine, and a stopped link is a 404', async () => {
  const { fetchFn } = stub({
    'POST /rest/v1/rpc/shared_workout': WORKOUT,
    'GET /rest/v1/share_links': [{ user_id: 'u1' }],
    'GET /rest/v1/profiles': [{ avatar_path: null }],
  });
  assert.equal((await (await share(get(TOKEN), ENV, { fetchFn })).json()).avatar_url, null);
  const gone = stub({ 'POST /rest/v1/rpc/shared_workout': null });
  assert.equal((await share(get(TOKEN), ENV, { fetchFn: gone.fetchFn })).status, 404);
  const bad = stub({});
  assert.equal((await share(get('not-a-token'), ENV, { fetchFn: bad.fetchFn })).status, 404);
  assert.equal(bad.calls.length, 0);
});

const post = (body) => new Request('https://x.supabase.co/functions/v1/signin', { method: 'POST', body: JSON.stringify(body) });

function signinWorld({ failures = 0, password = 'right-password' } = {}) {
  const inserted = [];
  const s = stub({
    'GET /rest/v1/signin_failures': Array.from({ length: failures }, () => ({ at: new Date().toISOString() })),
    'POST /rest/v1/signin_failures': (u, init) => { inserted.push(JSON.parse(init.body)); return [201, null]; },
    'DELETE /rest/v1/signin_failures': [204],
    'POST /rest/v1/rpc/email_for_username': (u, init) => (JSON.parse(init.body).name === 'harsh' ? 'h@example.com' : null),
    'POST /auth/v1/token': (u, init) => {
      const b = JSON.parse(init.body);
      return b.email === 'h@example.com' && b.password === password
        ? { access_token: 'at', refresh_token: 'rt', expires_in: 3600, user: { id: 'u1', email: b.email } }
        : [400, { error_code: 'invalid_credentials', msg: 'Invalid login credentials' }];
    },
  });
  return { ...s, inserted };
}

test('signin: a username and its password give the session, as an email sign-in would', async () => {
  const w = signinWorld();
  const res = await signin(post({ username: 'Harsh', password: 'right-password' }), ENV, { fetchFn: w.fetchFn });
  assert.equal(res.status, 200);
  assert.equal((await res.json()).access_token, 'at');
  // The email is looked up with the service key and never sent back on its own.
  assert.equal(w.calls.find((c) => c.key === 'POST /rest/v1/rpc/email_for_username').init.headers.Authorization, 'Bearer service');
  assert.ok(w.calls.some((c) => c.key === 'DELETE /rest/v1/signin_failures'));
});

test('signin: a wrong password and an unknown username get the same answer, and both count', async () => {
  const w = signinWorld();
  const wrong = await signin(post({ username: 'harsh', password: 'nope' }), ENV, { fetchFn: w.fetchFn });
  const unknown = await signin(post({ username: 'nobody', password: 'nope' }), ENV, { fetchFn: w.fetchFn });
  assert.equal(wrong.status, 400);
  assert.equal(unknown.status, 400);
  assert.deepEqual(await wrong.json(), NO_MATCH);
  assert.deepEqual(await unknown.json(), NO_MATCH);
  assert.deepEqual(w.inserted, [[{ name: 'harsh' }], [{ name: 'nobody' }]]);
});

test('signin: after too many wrong passwords the username waits, even with the right one', async () => {
  const w = signinWorld({ failures: MAX_FAILURES });
  const res = await signin(post({ username: 'harsh', password: 'right-password' }), ENV, { fetchFn: w.fetchFn });
  assert.equal(res.status, 429);
  assert.ok(!w.calls.some((c) => c.key === 'POST /auth/v1/token'));
});
