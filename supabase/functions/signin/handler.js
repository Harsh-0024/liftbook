// Sign in with a username: POST /signin {username, password}. The username's email is looked up
// here, on the server, and the sign-in goes to Supabase Auth as usual; the reply is Auth's own
// (the session), so the app keeps it the same way as an email sign-in. Someone who only knows a
// username learns nothing more: a wrong password and an unknown username get the same answer.

import { json, preflight } from '../_shared/http.js';
import { supabaseFor } from '../_shared/supabase.js';

const NAME = /^[A-Za-z0-9_.-]{3,50}$/;
export const MAX_FAILURES = 10;
export const WINDOW_MINUTES = 15;
export const NO_MATCH = { error_code: 'invalid_credentials', msg: 'That username and password don’t match.' };

export async function handle(req, env, { fetchFn = (...a) => globalThis.fetch(...a), now = () => Date.now() } = {}) {
  if (req.method === 'OPTIONS') return preflight();
  if (req.method !== 'POST') return json({ msg: 'Use POST.' }, 405);
  let body;
  try {
    body = await req.json();
  } catch {
    return json({ msg: 'Send the username and password.' }, 400);
  }
  const username = String(body?.username || '').trim();
  const password = String(body?.password || '');
  if (!NAME.test(username) || !password) return json(NO_MATCH, 400);
  const name = username.toLowerCase();
  const sb = supabaseFor(env, fetchFn);
  const svc = sb.asService();

  const since = new Date(now() - WINDOW_MINUTES * 60000).toISOString();
  const recent = await svc.get(`signin_failures?select=at&name=eq.${encodeURIComponent(name)}&at=gt.${encodeURIComponent(since)}`) || [];
  if (recent.length >= MAX_FAILURES) {
    return json({ error_code: 'over_request_rate_limit', msg: `Too many wrong passwords for this username. Wait ${WINDOW_MINUTES} minutes, or sign in with your email.` }, 429);
  }
  const failed = async () => {
    await svc.insert('signin_failures', [{ name }]).catch(() => {});
    return json(NO_MATCH, 400);
  };

  const email = await svc.rpc('email_for_username', { name });
  if (!email) return failed();
  const res = await fetchFn(`${sb.url}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: env.SUPABASE_ANON_KEY, Authorization: `Bearer ${env.SUPABASE_ANON_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const payload = await res.json().catch(() => null);
  if (res.ok && payload?.access_token) {
    await fetchFn(`${sb.url}/rest/v1/signin_failures?name=eq.${encodeURIComponent(name)}`, {
      method: 'DELETE', headers: { apikey: env.SUPABASE_SERVICE_ROLE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}` },
    }).catch(() => {});
    return json(payload);
  }
  if (payload?.error_code === 'invalid_credentials' || res.status === 400) {
    if (payload?.error_code === 'email_not_confirmed') return json(payload, 400);
    return failed();
  }
  return json(payload || { msg: 'Couldn’t sign in just now.' }, res.status || 500);
}
