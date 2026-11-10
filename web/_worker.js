// Cloudflare Pages runs this only for /s/<token> (_routes.json); every other address is the
// app's own files, as before. A share link pasted into WhatsApp or iMessage is read by their
// preview robot, which never runs the app, so this page carries the preview itself: the
// workout's name and day, who shared it, and their photo. A person opening it goes straight on
// to the app's share page (#/s/<token>). The workout comes from the "share" Edge Function.

// Public values, the same as web/config.js (a test checks they match).
export const SUPABASE_URL = 'https://qjlmxlnmfowqsunpzvac.supabase.co';
export const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFqbG14bG5tZm93cXN1bnB6dmFjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTM0MjIwODQsImV4cCI6MjEwODk5ODA4NH0.w1CiMM2N21lUujwztzcrf69r7TO6Depg5tBkzvHMD0Y';

const TOKEN_PATH = /^\/s\/([0-9a-f]{32})\/?$/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function niceDay(day) {
  const [y, m, d] = String(day || '').split('-').map(Number);
  return y && m && d ? `${d} ${MONTHS[m - 1]} ${y}` : '';
}

/** The preview's words and picture for a shared workout (null: the link doesn't work). */
export function preview(w, origin) {
  if (!w) {
    return { title: 'Liftbook', description: 'This shared workout isn’t available any more.', image: `${origin}/icons/icon-512.png`, small: true };
  }
  const ex = w.exercises || [];
  const sets = ex.reduce((n, e) => n + (Array.isArray(e.sets?.reps) ? e.sets.reps.length : 0), 0);
  const bests = ex.filter((e) => e.best).length;
  const who = w.username || 'Someone';
  const parts = [plural(ex.length, 'exercise'), plural(sets, 'set')];
  if (bests) parts.push(`${plural(bests, 'new best')} 🏅`);
  const names = ex.slice(0, 4).map((e) => e.exercise).join(', ') + (ex.length > 4 ? '…' : '');
  return {
    title: `${w.workout_name || 'Workout'} · ${niceDay(w.day)}`,
    description: `${who} shared a workout on Liftbook: ${parts.join(' · ')}.${names ? ` ${names}` : ''}`,
    image: w.avatar_url || `${origin}/icons/icon-512.png`,
    small: true,
  };
}

export function page(p, appUrl) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(p.title)}</title>
<meta name="description" content="${esc(p.description)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Liftbook">
<meta property="og:title" content="${esc(p.title)}">
<meta property="og:description" content="${esc(p.description)}">
<meta property="og:image" content="${esc(p.image)}">
<meta property="og:url" content="${esc(appUrl)}">
<meta name="twitter:card" content="${p.small ? 'summary' : 'summary_large_image'}">
<meta name="theme-color" content="#000000">
<meta http-equiv="refresh" content="0; url=${esc(appUrl)}">
<script>location.replace(${JSON.stringify(appUrl).replace(/</g, '\\u003c')});</script>
</head>
<body style="background:#000;color:#ddd;font-family:system-ui,sans-serif;padding:24px">
<p><a href="${esc(appUrl)}" style="color:#c9a961">Open the shared workout</a></p>
</body>
</html>`;
}

export default {
  async fetch(req, env, _ctx, { fetchFn = (...a) => globalThis.fetch(...a) } = {}) {
    const url = new URL(req.url);
    const m = TOKEN_PATH.exec(url.pathname);
    if (!m) return env.ASSETS.fetch(req);
    let w = null;
    try {
      const res = await fetchFn(`${SUPABASE_URL}/functions/v1/share/${m[1]}`, {
        headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${SUPABASE_ANON_KEY}` },
      });
      if (res.ok) w = await res.json();
    } catch {
      // The preview falls back to Liftbook's own; the link still opens.
    }
    const html = page(preview(w, url.origin), `${url.origin}/#/s/${m[1]}`);
    return new Response(html, {
      headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'public, max-age=300', 'X-Content-Type-Options': 'nosniff' },
    });
  },
};
