// The device's own copy of the person's data: every table in memory, kept in IndexedDB.
//
// Every change is written here first, with a fresh updated_at; sync.js copies it to the
// server later. A row is "pending" while its updated_at differs from `synced`, the version
// the server last confirmed. Deletes are soft: deleted_at is set and the row stays, so the
// delete reaches the other devices; the screens never show deleted rows.
//
// The storage underneath is swappable: idbBackend() in a browser, memoryBackend() in tests.

import { TABLES, TABLE_NAMES, localKey, freshStamp, timeKey } from './tables.js';

const META = '_meta';

export class Store {
  constructor(backend, { now = () => Date.now() } = {}) {
    this.backend = backend;
    this.now = now;
    this.rows = Object.fromEntries(TABLE_NAMES.map((t) => [t, new Map()]));
    this.meta = new Map();
    this.listeners = new Set();
  }

  static async open(backend, options) {
    const store = new Store(backend, options);
    const loaded = await backend.load();
    for (const t of TABLE_NAMES) for (const r of loaded[t] || []) store.rows[t].set(r._k, r);
    for (const [k, v] of Object.entries(loaded[META] || {})) store.meta.set(k, v);
    return store;
  }

  /** Called with {table, local} after every change; local is true for this device's own edits. */
  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  emit(table, local) {
    for (const fn of this.listeners) {
      try {
        fn({ table, local });
      } catch (err) {
        console.error(err);
      }
    }
  }

  /** The rows of a table, without deleted ones unless asked. */
  all(table, { deleted = false } = {}) {
    const out = [];
    for (const r of this.rows[table].values()) if (deleted || !r.deleted_at) out.push(r);
    return out;
  }

  get(table, key = 'me', { deleted = false } = {}) {
    const r = this.rows[table].get(key);
    return r && (deleted || !r.deleted_at) ? r : null;
  }

  /**
   * This device's changes: each is merged into the row with that key (or makes it), stamped
   * with a fresh updated_at and left pending. One write to storage for all of them.
   */
  async change(table, changes) {
    const list = Array.isArray(changes) ? changes : [changes];
    const now = this.now();
    const saved = [];
    for (const c of list) {
      const key = localKey(table, c);
      const before = this.rows[table].get(key);
      const row = { ...(before || {}), ...c, _k: key, updated_at: freshStamp(before && before.updated_at, now) };
      if (!before) {
        row.synced = null;
        if (TABLES[table].cols.includes('created_at') && !row.created_at) row.created_at = row.updated_at;
      }
      // A change brings a deleted row back unless it is the delete itself.
      if (!('deleted_at' in c)) row.deleted_at = null;
      this.rows[table].set(key, row);
      saved.push(row);
    }
    await this.backend.put(table, saved);
    this.emit(table, true);
    return Array.isArray(changes) ? saved : saved[0];
  }

  /** Soft delete: the row stays, marked deleted, and the delete goes up like any change. */
  async remove(table, keys) {
    const list = (Array.isArray(keys) ? keys : [keys]).map((k) => this.rows[table].get(k)).filter((r) => r && !r.deleted_at);
    if (!list.length) return [];
    const stamp = new Date(this.now()).toISOString();
    return this.change(table, list.map((r) => ({ ...keyOf(table, r), deleted_at: stamp })));
  }

  /** Rows waiting to go up. */
  pending(table) {
    const out = [];
    for (const r of this.rows[table].values()) if (r.synced !== r.updated_at) out.push(r);
    return out;
  }

  pendingCount() {
    return TABLE_NAMES.reduce((n, t) => n + this.pending(t).length, 0);
  }

  /** After an upload: rows not changed again meanwhile are no longer pending. */
  async markSynced(table, uploaded) {
    const done = [];
    for (const u of uploaded) {
      const now = this.rows[table].get(u._k);
      if (now && now.updated_at === u.updated_at && now.synced !== now.updated_at) {
        const row = { ...now, synced: now.updated_at };
        this.rows[table].set(row._k, row);
        done.push(row);
      }
    }
    if (done.length) await this.backend.put(table, done);
    return done.length;
  }

  /**
   * Rows from the server. Newest change wins: a row is taken when it is newer than the copy
   * here (deletes included); the same version just stops being pending; an older one is
   * ignored (the copy here goes up on the next upload). Returns how many rows changed here.
   */
  async applyRemote(table, serverRows) {
    const saved = [];
    let changed = 0;
    for (const s of serverRows) {
      const key = localKey(table, s);
      const local = this.rows[table].get(key);
      const theirs = timeKey(s.updated_at);
      const mine = local ? timeKey(local.updated_at) : -Infinity;
      if (!local || theirs > mine) {
        const row = { ...s, _k: key, synced: s.updated_at };
        delete row.user_id;
        this.rows[table].set(key, row);
        saved.push(row);
        changed++;
      } else if (theirs === mine && local.synced !== local.updated_at) {
        const row = { ...local, synced: local.updated_at };
        this.rows[table].set(key, row);
        saved.push(row);
      }
    }
    if (saved.length) await this.backend.put(table, saved);
    if (changed) this.emit(table, false);
    return changed;
  }

  getMeta(key, fallback = null) {
    return this.meta.has(key) ? this.meta.get(key) : fallback;
  }

  async setMeta(key, value) {
    this.meta.set(key, value);
    await this.backend.putMeta(key, value);
  }

  /** Everything on this device, for a backup file. */
  snapshot() {
    return Object.fromEntries(TABLE_NAMES.map((t) => [t, this.all(t)]));
  }
}

function keyOf(table, row) {
  return Object.fromEntries(TABLES[table].key.map((c) => [c, row[c]]));
}

/* ------------------------------------------------------------------ */
/* storage underneath                                                  */
/* ------------------------------------------------------------------ */

/** In memory only (tests). `data` can be shared between two opens to act like a reload. */
export function memoryBackend(data = {}) {
  for (const t of [...TABLE_NAMES, META]) data[t] ??= {};
  return {
    data,
    async load() {
      const out = {};
      for (const t of TABLE_NAMES) out[t] = Object.values(data[t]).map((r) => structuredClone(r));
      out[META] = structuredClone(data[META]);
      return out;
    },
    async put(table, rows) {
      for (const r of rows) data[table][r._k] = structuredClone(r);
    },
    async putMeta(key, value) {
      data[META][key] = structuredClone(value);
    },
  };
}

const DB_VERSION = 1;

/** IndexedDB: one database per account ("liftbook-<user id>"), one object store per table. */
export function idbBackend(name, idb = globalThis.indexedDB) {
  let dbp = null;
  const open = () => (dbp ??= new Promise((resolve, reject) => {
    const req = idb.open(name, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const t of TABLE_NAMES) if (!db.objectStoreNames.contains(t)) db.createObjectStore(t, { keyPath: '_k' });
      if (!db.objectStoreNames.contains(META)) db.createObjectStore(META);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(new Error('The app is open in another tab with an older version. Close it and reload.'));
  }));
  const done = (tx) => new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error('storage write aborted'));
  });
  return {
    async load() {
      const db = await open();
      const tx = db.transaction([...TABLE_NAMES, META], 'readonly');
      const out = {};
      const reads = TABLE_NAMES.map((t) => new Promise((resolve, reject) => {
        const req = tx.objectStore(t).getAll();
        req.onsuccess = () => resolve((out[t] = req.result));
        req.onerror = () => reject(req.error);
      }));
      out[META] = {};
      reads.push(new Promise((resolve, reject) => {
        const req = tx.objectStore(META).openCursor();
        req.onsuccess = () => {
          const c = req.result;
          if (!c) return resolve();
          out[META][c.key] = c.value;
          c.continue();
        };
        req.onerror = () => reject(req.error);
      }));
      await Promise.all(reads);
      return out;
    },
    async put(table, rows) {
      if (!rows.length) return;
      const db = await open();
      const tx = db.transaction(table, 'readwrite');
      const os = tx.objectStore(table);
      for (const r of rows) os.put(r);
      await done(tx);
    },
    async putMeta(key, value) {
      const db = await open();
      const tx = db.transaction(META, 'readwrite');
      tx.objectStore(META).put(value, key);
      await done(tx);
    },
    async close() {
      if (dbp) (await dbp).close();
      dbp = null;
    },
  };
}

/** Remove an account's database from this device (signing out). */
export function deleteDatabase(name, idb = globalThis.indexedDB) {
  return new Promise((resolve, reject) => {
    const req = idb.deleteDatabase(name);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
    req.onblocked = () => resolve();
  });
}
