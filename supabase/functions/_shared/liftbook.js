// One person's Liftbook, on the server: their rows from Supabase in the same Store the app keeps
// on a device, and the app's own Liftbook class over it. A change made here (a workout from a
// Shortcut) goes up exactly as a device's change does, so every device picks it up on its next
// sync. legacy_id is never written (toServer leaves it out).

import { Store, memoryBackend } from '../../../web/app/store.js';
import { Liftbook } from '../../../web/app/data.js';
import { TABLE_NAMES, conflictColumns, toServer } from '../../../web/app/tables.js';
import { formatDateTime, localDay } from '../../../web/core/dates.js';

// Retrieve counts are only for sorting the app's own exercise list; nothing here needs them.
const LOADED = TABLE_NAMES.filter((t) => t !== 'retrieval_events');

/** The people Liftbook is used by are in India; the app's default too (web/core/stats.js). */
export const DEFAULT_TZ_OFFSET_MINUTES = 330;

/** The person's own clock time now, "YYYY-MM-DDTHH:MM:SS", for an offset from UTC in minutes. */
export function localNow(offsetMinutes = DEFAULT_TZ_OFFSET_MINUTES, now = Date.now()) {
  const d = new Date(now + offsetMinutes * 60000);
  return formatDateTime({
    year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate(),
    hour: d.getUTCHours(), minute: d.getUTCMinutes(), second: d.getUTCSeconds(), micro: 0,
  });
}

export const localToday = (offsetMinutes, now) => localDay(localNow(offsetMinutes, now));

/** An offset a client sent (minutes east of UTC), or the default. */
export function tzOffset(value) {
  const n = Number(value);
  return Number.isInteger(n) && n >= -720 && n <= 840 ? n : DEFAULT_TZ_OFFSET_MINUTES;
}

/**
 * db:      a REST client (supabase.js) for this person: their own sign-in, or the service key
 * userId:  whose rows
 * admin:   whether they are an admin (the shared plan is their own then)
 */
export async function loadLiftbook(db, userId, { admin = null } = {}) {
  const store = await Store.open(memoryBackend());
  const mine = `user_id=eq.${encodeURIComponent(userId)}`;
  const tables = await Promise.all(LOADED.map((t) => db.all(`${t}?select=*&${mine}&deleted_at=is.null&order=server_updated_at.asc`)));
  for (const [i, t] of LOADED.entries()) await store.applyRemote(t, tables[i]);
  const [shared, isAdmin] = await Promise.all([
    db.rpc('shared_plan').catch(() => null),
    admin === null ? db.rpc('is_admin').catch(() => false) : admin,
  ]);
  await store.setMeta('shared_plan', shared || {});
  await store.setMeta('is_admin', Boolean(isAdmin));
  return { store, lb: new Liftbook(store, null, userId) };
}

/** Send this Liftbook's changes up, as a device's sync would. Returns how many rows went. */
export async function saveChanges(db, store, userId) {
  let sent = 0;
  for (const t of TABLE_NAMES) {
    const rows = store.pending(t);
    if (!rows.length) continue;
    await db.upsert(t, conflictColumns(t), rows.map((r) => toServer(t, r, userId)));
    await store.markSynced(t, rows);
    sent += rows.length;
  }
  return sent;
}
