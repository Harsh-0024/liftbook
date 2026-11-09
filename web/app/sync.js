// Copying changes between this device and the server, the way Muhurta Pomodoro does
// (mobile/web/account.js there):
//
//   1. Upload: every pending row (updated_at differs from the version the server last
//      confirmed), deletes included, as an upsert. The server's keep_newest() trigger ignores
//      an upload older than what it has and stamps server_updated_at on the rest.
//   2. Download: every row the server stamped since the last download, a few minutes of
//      overlap included (two writes can commit out of order), applied newest-change-wins.
//
// It runs when the app opens, when the device comes back online or the app comes back to the
// front, every few minutes, and a few seconds after a change here. Failures are remembered and
// retried; the app keeps working on its own copy meanwhile.

import { TABLE_NAMES, conflictColumns, toServer, timeKey } from './tables.js';

export const DEBOUNCE_MS = 3000;
export const INTERVAL_MS = 5 * 60 * 1000;
export const PULL_OVERLAP_MS = 5 * 60 * 1000;
export const PAGE = 1000;
export const PUSH_CHUNK = 500;

/**
 * store:  a Store (store.js)
 * db:     {upsert(table, onConflict, rows), pullPage(table, since, offset, limit)} (supabase.js db)
 * userId: the signed-in person's id
 */
export function createSync({ store, db, userId, debounceMs = DEBOUNCE_MS, overlapMs = PULL_OVERLAP_MS, page = PAGE, now = () => Date.now() }) {
  let running = null;
  let again = false;
  let timer = null;
  let state = { running: false, last_sync: store.getMeta('last_sync'), error: null };
  const listeners = new Set();

  const notify = () => {
    const st = status();
    for (const fn of listeners) fn(st);
  };

  function status() {
    return { ...state, pending: store.pendingCount() };
  }

  async function push(table) {
    const rows = store.pending(table);
    for (let i = 0; i < rows.length; i += PUSH_CHUNK) {
      const chunk = rows.slice(i, i + PUSH_CHUNK);
      await db.upsert(table, conflictColumns(table), chunk.map((r) => toServer(table, r, userId)));
      await store.markSynced(table, chunk);
    }
    return rows.length;
  }

  /** Everything changed on the server since this table's cursor (all of it the first time). */
  async function fetchChanges(table) {
    const cursor = store.getMeta(`cursor:${table}`);
    const since = cursor ? new Date(Math.floor(timeKey(cursor) / 1000) - overlapMs).toISOString() : null;
    const all = [];
    for (let offset = 0; ; offset += page) {
      const rows = (await db.pullPage(table, since, offset, page)) || [];
      all.push(...rows);
      if (rows.length < page) break;
    }
    return { cursor, rows: all };
  }

  async function apply(table, { cursor, rows }) {
    const changed = await store.applyRemote(table, rows);
    let newest = cursor;
    for (const r of rows) if (!newest || timeKey(r.server_updated_at) > timeKey(newest)) newest = r.server_updated_at;
    if (newest !== cursor) await store.setMeta(`cursor:${table}`, newest);
    return changed;
  }

  async function syncOnce() {
    let up = 0;
    let down = 0;
    for (const t of TABLE_NAMES) up += await push(t);
    // The tables download at the same time (one wait instead of seven), then go in one by one.
    const fetched = await Promise.all(TABLE_NAMES.map(fetchChanges));
    for (const [i, t] of TABLE_NAMES.entries()) down += await apply(t, fetched[i]);
    return { up, down };
  }

  /** One full sync (or joins the one running; a change meanwhile queues one more). Never throws. */
  function runOnce() {
    if (running) {
      again = true;
      return running;
    }
    clearTimeout(timer);
    state = { ...state, running: true };
    notify();
    running = (async () => {
      let result = { up: 0, down: 0 };
      try {
        do {
          again = false;
          const r = await syncOnce();
          result = { up: result.up + r.up, down: result.down + r.down };
        } while (again);
        const at = new Date(now()).toISOString();
        await store.setMeta('last_sync', at);
        state = { running: false, last_sync: at, error: null };
      } catch (err) {
        state = { ...state, running: false, error: describe(err) };
        if (!(err && 'status' in err)) console.error('sync failed', err);
        result.error = state.error;
      } finally {
        running = null;
        notify();
      }
      return result;
    })();
    return running;
  }

  /** A change was made here: sync a moment later (many quick changes make one sync). */
  function nudge() {
    clearTimeout(timer);
    timer = setTimeout(runOnce, debounceMs);
    notify();
  }

  function onStatus(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function stop() {
    clearTimeout(timer);
  }

  return { runOnce, nudge, status, onStatus, stop };
}

function describe(err) {
  if (!err) return 'Something went wrong while syncing.';
  if (err.status === 0) return 'offline';
  if (err.status === 401 || err.status === 403) return 'Your sign-in needs renewing. Sign in again if this stays.';
  return err.message || 'Something went wrong while syncing. It will try again.';
}

/**
 * Wire a sync to the browser: when the app opens, comes online, comes to the front, every few
 * minutes, and shortly after every change made on this device.
 */
export function startAutoSync(sync, store, { win = globalThis.window, doc = globalThis.document, intervalMs = INTERVAL_MS } = {}) {
  const unsubscribe = store.subscribe(({ local }) => {
    if (local) sync.nudge();
  });
  const online = () => sync.runOnce();
  const visible = () => {
    if (doc.visibilityState === 'visible') sync.runOnce();
  };
  win.addEventListener('online', online);
  doc.addEventListener('visibilitychange', visible);
  const interval = setInterval(() => sync.runOnce(), intervalMs);
  sync.runOnce();
  return () => {
    unsubscribe();
    win.removeEventListener('online', online);
    doc.removeEventListener('visibilitychange', visible);
    clearInterval(interval);
    sync.stop();
  };
}
