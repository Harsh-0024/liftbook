// The seven tables a device keeps and syncs (supabase/schema.sql).
//
// key:  the columns that pick out one row of a person's (user_id is the rest of the primary key).
// defaults: what a missing value is sent as, for columns the server requires.
// cols: what the app uploads. Never legacy_id (the column grants refuse it) and never
//       server_updated_at (the server stamps it on every write).

export const TABLES = {
  profiles: {
    key: [],
    defaults: { full_name: '' },
    cols: ['username', 'full_name', 'bodyweight', 'avatar_path', 'created_at', 'updated_at', 'deleted_at'],
  },
  workout_logs: {
    key: ['id'],
    cols: ['id', 'date', 'workout_name', 'exercise', 'exercise_string', 'sets', 'bodyweight', 'uses_bodyweight',
      'top_weight', 'top_reps', 'estimated_1rm', 'created_at', 'updated_at', 'deleted_at'],
  },
  user_texts: {
    key: ['kind'],
    defaults: { text: '' },
    cols: ['kind', 'text', 'updated_at', 'deleted_at'],
  },
  exercise_settings: {
    key: ['exercise_key'],
    defaults: { view_count: 0 },
    cols: ['exercise_key', 'exercise_name', 'is_timed', 'is_bodyweight', 'bodyweight_source', 'group_name',
      'view_count', 'last_viewed_at', 'updated_at', 'deleted_at'],
  },
  retrieval_events: {
    key: ['id'],
    cols: ['id', 'exercise_key', 'retrieved_at', 'updated_at', 'deleted_at'],
  },
  exercise_renames: {
    key: ['id'],
    defaults: { log_ids: [] },
    cols: ['id', 'old_key', 'old_name', 'new_name', 'log_ids', 'created_at', 'updated_at', 'deleted_at'],
  },
  app_settings: {
    key: [],
    defaults: { json: {} },
    cols: ['json', 'updated_at', 'deleted_at'],
  },
};

export const TABLE_NAMES = Object.keys(TABLES);

/** The row's key on this device: its key columns joined, or "me" for one-row-per-person tables. */
export function localKey(table, row) {
  const { key } = TABLES[table];
  if (!key.length) return 'me';
  return key.map((c) => String(row[c] ?? '')).join('|');
}

/** The on_conflict columns for an upload. */
export function conflictColumns(table) {
  return ['user_id', ...TABLES[table].key].join(',');
}

/** A local row -> what goes to the server: only the uploadable columns, plus user_id. */
export function toServer(table, row, userId) {
  const { cols, defaults = {} } = TABLES[table];
  const out = { user_id: userId };
  for (const c of cols) out[c] = row[c] ?? defaults[c] ?? null;
  return out;
}

/**
 * A timestamp -> one number that sorts like the time itself, to the microsecond. The server
 * writes "2026-10-31T12:00:00.123456+00:00", a device "2026-10-31T12:00:00.123Z": the two
 * can't be compared as text.
 */
export function timeKey(value) {
  if (!value) return -Infinity;
  const s = String(value);
  const frac = /\.(\d+)/.exec(s);
  const whole = Date.parse(frac ? s.replace(/\.\d+/, '') : s);
  if (Number.isNaN(whole)) return -Infinity;
  const micro = frac ? Number(frac[1].slice(0, 6).padEnd(6, '0')) : 0;
  return whole * 1000 + micro;
}

/** A change time for a row: now, but always later than its previous change (a clock may be behind). */
export function freshStamp(previous, now = Date.now()) {
  const prevMs = previous ? Math.floor(timeKey(previous) / 1000) : -Infinity;
  return new Date(Math.max(now, prevMs + 1)).toISOString();
}
