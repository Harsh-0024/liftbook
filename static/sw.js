importScripts('/static/offline-workouts.js');

const VERSION = 'v6';
// Files that are the same for everyone (styles, icons, the offline page).
const SHARED_CACHE = `liftbook-shared-${VERSION}`;
// The signed-in person's pages and data; emptied when nobody is signed in.
const USER_CACHE = `liftbook-user-${VERSION}`;
const OFFLINE_URL = '/static/offline.html';
// Who is signed in, and where '/' sends them so the installed app can open offline.
const SIGNED_IN_KEY = '/__sw/signed-in';
// A save that gets no answer in this long is kept on the device instead.
const SAVE_TIMEOUT_MS = 20000;

const CORE_PAGES = ['/log', '/stats', '/retrieve/categories'];

function cacheNameFor(url) {
  const { origin, pathname } = new URL(url, self.location.origin);
  if (origin !== self.location.origin) return SHARED_CACHE;
  if (pathname.startsWith('/static/') || pathname.startsWith('/app-icon/')) return SHARED_CACHE;
  return USER_CACHE;
}

// Only keep real answers: a redirect (e.g. to /login) can't be replayed for a
// navigation, and error pages shouldn't stand in for the page offline.
// Cross-origin CDN files load as opaque responses, which are fine to keep.
function cacheable(response) {
  if (!response || response.redirected) return false;
  if (/no-store/.test(response.headers.get('Cache-Control') || '')) return false;
  return response.ok || response.type === 'opaque';
}

function remember(request, response) {
  if (!cacheable(response)) return Promise.resolve();
  const copy = response.clone();
  return caches.open(cacheNameFor(request.url))
    .then((cache) => cache.put(request, copy))
    .catch(() => {});
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    Promise.all([
      caches.open(SHARED_CACHE).then((cache) => cache.addAll([OFFLINE_URL, '/static/manifest.json'])),
      ...CORE_PAGES.map((url) =>
        fetch(url).then((response) => remember(new Request(url), response)).catch(() => null)
      ),
    ])
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  const keep = [SHARED_CACHE, USER_CACHE];
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((key) => (keep.includes(key) ? null : caches.delete(key))))
    )
  );
  self.clients.claim();
});

// Every page tells the worker who is signed in (see base.html).
self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'signed-in' && typeof data.home === 'string' && typeof data.user === 'string') {
    // The account id too: a username can change while a workout waits to upload.
    const who = JSON.stringify({ home: data.home, user: data.user, userId: data.userId ?? null });
    event.waitUntil(
      caches.open(USER_CACHE).then((cache) => cache.put(SIGNED_IN_KEY, new Response(who)))
    );
  } else if (data.type === 'signed-out') {
    event.waitUntil(caches.delete(USER_CACHE));
  }
});

function signedIn() {
  return caches.open(USER_CACHE)
    .then((cache) => cache.match(SIGNED_IN_KEY))
    .then((response) => (response ? response.json() : null))
    .catch(() => null);
}

function offlineNavigation(request) {
  return caches.match(request).then((cached) => {
    if (cached) return cached;
    if (new URL(request.url).pathname === '/') {
      return signedIn().then((who) =>
        who ? Response.redirect(who.home, 302) : caches.match(OFFLINE_URL)
      );
    }
    return caches.match(OFFLINE_URL);
  });
}

function newId() {
  if (self.crypto && self.crypto.randomUUID) return self.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// "Analyze & Save" on /log. Online it goes through untouched; if the server
// can't be reached (or doesn't answer), the workout is kept on the device and
// uploaded later by the pages (see offline-sync.js).
async function saveWorkout(request) {
  const form = await request.clone().formData();
  const text = String(form.get('workout_text') || '').trim();
  const fixingId = String(form.get('offline_id') || '');

  let timer;
  const timeout = new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('no answer')), SAVE_TIMEOUT_MS);
  });
  try {
    const response = await Promise.race([fetch(request), timeout]);
    clearTimeout(timer);
    // 400: the page's security token went stale (it was opened offline);
    // keep the workout and upload it with a fresh one.
    if (response.status === 400) throw new Error('stale page');
    if (fixingId) {
      // Fixing a kept workout: keep the latest edit for the next try. Once it's
      // in, the server sends the browser on to the workout page, which forgets
      // the kept copy (offline_saved in its address; see offline-sync.js).
      const kept = await offlineWorkouts.get(fixingId).catch(() => null);
      if (kept && text) await offlineWorkouts.put({ ...kept, text }).catch(() => {});
    }
    return response;
  } catch (err) {
    clearTimeout(timer);
    const who = await signedIn();
    if (!text) return Response.redirect('/log', 303);
    if (!who) return caches.match(OFFLINE_URL);
    const kept = fixingId ? await offlineWorkouts.get(fixingId).catch(() => null) : null;
    await offlineWorkouts.put({
      id: kept ? kept.id : newId(),
      user: who.user,
      userId: who.userId ?? null,
      text,
      savedAt: kept ? kept.savedAt : Date.now(),
      status: 'pending',
      error: '',
    });
    return Response.redirect('/log#saved-offline', 303);
  }
}

// Network first for everything, so pages and data are never stale while
// online; the cache only answers when the network can't.
self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method === 'POST' && request.mode === 'navigate'
      && new URL(request.url).pathname === '/log') {
    event.respondWith(saveWorkout(request));
    return;
  }
  if (request.method !== 'GET' || !request.url.startsWith('http')) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        event.waitUntil(remember(request, response));
        return response;
      })
      .catch(() => {
        if (request.mode === 'navigate') return offlineNavigation(request);
        return caches.match(request).then((cached) => cached || Response.error());
      })
  );
});
