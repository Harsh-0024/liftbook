// What a share link shows, for anyone: GET /share/<token>. The same as the shared_workout
// function the app can call itself, plus `avatar_url`, a link to the owner's profile photo that
// works for 7 days (the photos are private, so only the service key can make one). The website's
// link previews (web/_worker.js) read it too.

import { json, preflight } from '../_shared/http.js';
import { supabaseFor } from '../_shared/supabase.js';

const TOKEN = /^[0-9a-f]{32}$/;
export const PHOTO_SECONDS = 7 * 86400;

export async function handle(req, env, { fetchFn = (...a) => globalThis.fetch(...a) } = {}) {
  if (req.method === 'OPTIONS') return preflight();
  if (req.method !== 'GET') return json({ error: 'Use GET.' }, 405);
  const url = new URL(req.url);
  const token = url.pathname.split('/').filter(Boolean).pop() || url.searchParams.get('token') || '';
  if (!TOKEN.test(token)) return json({ error: 'Not a share link.' }, 404);
  const sb = supabaseFor(env, fetchFn);
  const svc = sb.asService();
  const w = await svc.rpc('shared_workout', { share_token: token });
  if (!w) return json(null, 404, { 'Cache-Control': 'no-store' });
  let avatar_url = null;
  try {
    const [link] = await svc.get(`share_links?select=user_id&token=eq.${token}`) || [];
    const [p] = link ? await svc.get(`profiles?select=avatar_path&user_id=eq.${link.user_id}`) || [] : [];
    const path = p?.avatar_path;
    if (path && /^https?:\/\//.test(path)) avatar_url = path;
    else if (path) {
      const res = await fetchFn(`${sb.url}/storage/v1/object/sign/avatars/${path.split('/').map(encodeURIComponent).join('/')}`, {
        method: 'POST',
        headers: { apikey: env.SUPABASE_SERVICE_ROLE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ expiresIn: PHOTO_SECONDS }),
      });
      const signed = res.ok ? await res.json() : null;
      if (signed?.signedURL) avatar_url = `${sb.url}/storage/v1${signed.signedURL}`;
    }
  } catch {
    // No photo is fine: the page shows the first letter instead.
  }
  return json({ ...w, avatar_url }, 200, { 'Cache-Control': 'public, max-age=60' });
}
