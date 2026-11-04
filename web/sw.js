// Liftbook's service worker: keeps every file of the app on the device, so after the first
// visit it opens with no connection. Only signing in and syncing (Supabase, another address)
// use the network; this worker never touches those.
//
// VERSION and FILES are filled in by web/tools/build_sw.js. A new version installs next to the
// old one, takes over, and the old copy is removed.
'use strict';

const VERSION = '63eaf55561f9';
const FILES = [
  './',
  'app/data.js',
  'app/main.js',
  'app/native.js',
  'app/online.js',
  'app/screens/auth.js',
  'app/screens/coach.js',
  'app/screens/home.js',
  'app/screens/log.js',
  'app/screens/retrieve.js',
  'app/screens/settings.js',
  'app/screens/stats.js',
  'app/store.js',
  'app/supabase.js',
  'app/sync.js',
  'app/tables.js',
  'app/ui.js',
  'config.js',
  'core/bodyweight.js',
  'core/coach_tools.js',
  'core/dates.js',
  'core/defaults.js',
  'core/history_qa.js',
  'core/html.js',
  'core/html_entities.js',
  'core/insights.js',
  'core/logging.js',
  'core/names.js',
  'core/parser.js',
  'core/plans.js',
  'core/py.js',
  'core/renames.js',
  'core/retrieve.js',
  'core/rich_text.js',
  'core/scoring.js',
  'core/sessions.js',
  'core/stats.js',
  'fonts/LICENSE-cormorant.md',
  'fonts/LICENSE-inter.md',
  'fonts/cormorant-garamond-latin-500-normal.woff2',
  'fonts/cormorant-garamond-latin-600-normal.woff2',
  'fonts/cormorant-garamond-latin-700-normal.woff2',
  'fonts/inter.woff2',
  'icons/favicon-32.png',
  'icons/icon-180.png',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/maskable-512.png',
  'index.html',
  'manifest.webmanifest',
  'shortcuts/Get Workout.shortcut',
  'shortcuts/Log Workout.shortcut',
  'styles.css'
];
const CACHE = `liftbook-${VERSION}`;

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // "reload": straight from the site, not an older copy the browser kept.
    await cache.addAll(FILES.map((f) => new Request(f, { cache: 'reload' })));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name !== CACHE && name.startsWith('liftbook-')) await caches.delete(name);
    await self.clients.claim();
  })());
});

const scope = new URL(self.registration.scope);

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    if (req.mode === 'navigate') {
      const home = await cache.match('./');
      if (home) return home;
    }
    return fetch(req);
  })());
});
