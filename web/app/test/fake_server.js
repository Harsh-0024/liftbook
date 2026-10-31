// A stand-in for Liftbook's Supabase tables, with the same rules as supabase/schema.sql:
// newest change wins (keep_newest), the server stamps server_updated_at, user_id is pinned,
// legacy_id can't be written, and each person only sees their own rows.

import { TABLES, timeKey } from '../tables.js';

export function fakeServer() {
  const tables = Object.fromEntries(Object.keys(TABLES).map((t) => [t, new Map()]));
  let clock = Date.parse('2026-11-01T00:00:00Z');
  const log = [];
  let online = true;

  const stamp = () => {
    clock += 1;
    return new Date(clock).toISOString().replace('Z', '000+00:00'); // microseconds, as Postgres writes them
  };
  const keyOf = (table, row) => [row.user_id, ...TABLES[table].key.map((c) => row[c])].join('|');
  const offlineError = () => Object.assign(new Error('offline'), { status: 0 });

  /** The db half of supabase.js, signed in as `userId`. */
  function clientFor(userId) {
    return {
      async upsert(table, onConflict, rows) {
        if (!online) throw offlineError();
        log.push({ op: 'upsert', table, userId, rows: structuredClone(rows) });
        const expected = ['user_id', ...TABLES[table].key].join(',');
        if (onConflict !== expected) throw Object.assign(new Error(`bad on_conflict ${onConflict}`), { status: 400 });
        for (const r of rows) {
          if ('legacy_id' in r) throw Object.assign(new Error('permission denied for column legacy_id'), { status: 401 });
          if ('server_updated_at' in r) throw Object.assign(new Error('server_updated_at sent'), { status: 400 });
          if (r.user_id !== userId) throw Object.assign(new Error('row-level security'), { status: 403 });
          const k = keyOf(table, r);
          const old = tables[table].get(k);
          if (old && timeKey(r.updated_at) <= timeKey(old.updated_at)) continue; // keep_newest: skipped
          tables[table].set(k, { ...(old || {}), ...structuredClone(r), user_id: old ? old.user_id : r.user_id, server_updated_at: stamp() });
        }
        return null;
      },
      async pullPage(table, since, offset, limit) {
        if (!online) throw offlineError();
        const entry = { op: 'pull', table, userId, since, offset };
        log.push(entry);
        const rows = [...tables[table].values()]
          .filter((r) => r.user_id === userId && (!since || timeKey(r.server_updated_at) > timeKey(since)))
          .sort((a, b) => timeKey(a.server_updated_at) - timeKey(b.server_updated_at))
          .slice(offset, offset + limit)
          .map((r) => structuredClone(r));
        entry.ids = rows.map((r) => r.id ?? r.kind ?? r.exercise_key ?? 'me');
        return rows;
      },
    };
  }

  return {
    tables,
    log,
    clientFor,
    advance(ms) {
      clock += ms;
    },
    setOnline(v) {
      online = v;
    },
    /** A row put there directly (as the import did), stamped now. */
    seed(table, row) {
      tables[table].set(keyOf(table, row), { ...structuredClone(row), server_updated_at: stamp() });
    },
    row(table, userId, ...key) {
      return tables[table].get([userId, ...key].join('|')) || null;
    },
  };
}
