// The link preview page for share links (web/_worker.js, run by Cloudflare Pages for /s/*).
import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { preview, page, SUPABASE_URL, SUPABASE_ANON_KEY } from '../../_worker.js';
import * as config from '../../config.js';

const TOKEN = 'b'.repeat(32);
const W = {
  day: '2026-11-09', username: 'harsh', workout_name: 'Push <Day>', avatar_url: 'https://x/photo.jpg',
  exercises: [
    { exercise: 'Bench Press', sets: { weights: [60, 60], reps: [8, 8] }, best: true },
    { exercise: 'Dips', sets: { weights: [0], reps: [10] }, best: false },
  ],
};

test('the worker uses the same Supabase project as the app', () => {
  assert.equal(SUPABASE_URL, config.SUPABASE_URL);
  assert.equal(SUPABASE_ANON_KEY, config.SUPABASE_ANON_KEY);
});

test('a preview names the workout, the day, who shared it, and shows their photo', () => {
  const p = preview(W, 'https://beta.liftbook.in');
  assert.equal(p.title, 'Push <Day> · 9 Nov 2026');
  assert.match(p.description, /^harsh shared a workout on Liftbook: 2 exercises · 3 sets · 1 new best/);
  assert.equal(p.image, 'https://x/photo.jpg');
  assert.equal(preview({ ...W, avatar_url: null }, 'https://o').image, 'https://o/icons/icon-512.png');
  assert.match(preview(null, 'https://o').description, /isn’t available/);
});

test('the page escapes what people typed and sends a person on to the app', () => {
  const html = page(preview(W, 'https://o'), `https://o/#/s/${TOKEN}`);
  assert.ok(html.includes('Push &lt;Day&gt;'));
  assert.ok(!html.includes('Push <Day>'));
  assert.ok(html.includes(`content="0; url=https://o/#/s/${TOKEN}"`));
  assert.ok(html.includes('og:image" content="https://x/photo.jpg"'));
});

test('only /s/<token> is answered here; everything else is the app\'s own files', async () => {
  const assets = [];
  const env = { ASSETS: { fetch: (req) => { assets.push(new URL(req.url).pathname); return new Response('asset'); } } };
  await worker.fetch(new Request('https://o/s/not-a-token'), env, {});
  await worker.fetch(new Request('https://o/styles.css'), env, {});
  assert.deepEqual(assets, ['/s/not-a-token', '/styles.css']);
  const res = await worker.fetch(new Request(`https://o/s/${TOKEN}`), env, {}, {
    fetchFn: async (url) => {
      assert.equal(url, `${SUPABASE_URL}/functions/v1/share/${TOKEN}`);
      return new Response(JSON.stringify(W));
    },
  });
  assert.equal(res.headers.get('Content-Type'), 'text/html; charset=utf-8');
  assert.match(await res.text(), /og:title" content="Push &lt;Day&gt; · 9 Nov 2026"/);
  const down = await worker.fetch(new Request(`https://o/s/${TOKEN}`), env, {}, { fetchFn: async () => { throw new Error('offline'); } });
  assert.match(await down.text(), /isn’t available/);
});
