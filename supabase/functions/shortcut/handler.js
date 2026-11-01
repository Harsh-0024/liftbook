// Apple Shortcuts: log a workout from a note, and get a plan day's targets as a note
// (the old app's /shortcut/log and /shortcut/pick).
//
//   POST /functions/v1/shortcut/log/<key>     the note as form field workout_text (or text, note,
//                                              JSON, a file, or the raw body)
//   GET  /functions/v1/shortcut/pick/<key>?list=1              {ok, sessions: [...]}
//   GET  /functions/v1/shortcut/pick/<key>?key=<session>&format=json   {ok, text}
//
// <key> is the person's Shortcut key ("lbk_..."); an X-Liftbook-Key header works too. Only a
// SHA-256 of each key is stored (shortcut_keys table), so a copy of the database can't be used to
// log for anyone. Every JSON reply has "server", so a Shortcut can tell this app's reply from an
// error page.

import { supabaseFor } from '../_shared/supabase.js';
import { json, text, preflight } from '../_shared/http.js';
import { loadLiftbook, saveChanges, localNow, tzOffset } from '../_shared/liftbook.js';
import { toPlainText } from '../../../web/core/rich_text.js';
import { workoutParser } from '../../../web/core/parser.js';
import { normalizeExerciseName } from '../../../web/core/names.js';
import { hasBodyweightToken } from '../../../web/core/bodyweight.js';
import { resolveDay, sessionLabels } from './sessions.js';

export const SERVER = 'Supabase';
export const KEY_HELP = 'Copy your Shortcut key again from Liftbook > Settings > Apple Shortcuts. '
  + 'Then open this shortcut in the Shortcuts app and paste the key into the first box.';
export const KEY_INVALID = `Your shortcut key isn't valid. ${KEY_HELP}`;
export const KEY_MISSING = `Your shortcut key is missing. ${KEY_HELP}`;
export const DAY_TAKEN = 'That day already has a workout, so nothing was saved. '
  + 'To add these exercises to it, paste them on the Log page and choose Add to that day.';
export const SAVE_FAILED = 'Error saving workout. Please try again.';
const MAX_TEXT = 60000;

export async function sha256Hex(value) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** ".../shortcut/log/<key>" -> {action: "log", key}; the key may also come in a header. */
export function route(req) {
  const url = new URL(req.url);
  const m = /\/(log|pick|recommend)(?:\/([^/]+))?\/?$/.exec(url.pathname);
  const header = (req.headers.get('x-liftbook-key') || '').trim();
  return { action: m ? m[1] : null, key: header || (m && m[2] ? decodeURIComponent(m[2]).trim() : ''), url };
}

/** The workout text from whatever a Shortcut (or another app) sent, and where it was found. */
export async function workoutTextOf(req, url) {
  if (req.method !== 'POST') {
    const q = url.searchParams;
    const t = String(q.get('workout_text') || q.get('text') || q.get('note') || '').trim();
    return { raw: t, source: t ? 'query' : 'none' };
  }
  const type = (req.headers.get('content-type') || '').toLowerCase();
  try {
    if (type.includes('application/x-www-form-urlencoded') || type.includes('multipart/form-data')) {
      const form = await req.formData();
      const named = String(form.get('workout_text') || '').trim();
      if (named && typeof form.get('workout_text') === 'string') return { raw: named, source: 'form.workout_text' };
      const other = String((typeof form.get('text') === 'string' && form.get('text')) || (typeof form.get('note') === 'string' && form.get('note')) || '').trim();
      if (other) return { raw: other, source: 'form.text_or_note' };
      const values = [];
      const files = [];
      for (const [, v] of form.entries()) {
        if (typeof v === 'string') {
          if (v.trim()) values.push(v.trim());
        } else {
          files.push(v);
        }
      }
      if (values.length) return { raw: longest(values), source: 'form.any' };
      // Rich-text notes can arrive as an uploaded file (RTF/HTML).
      const uploads = [];
      for (const f of files) {
        const bytes = new Uint8Array(await f.slice(0, 200000).arrayBuffer());
        if (new TextDecoder().decode(bytes).trim()) uploads.push(bytes);
      }
      if (uploads.length) return { raw: toPlainText(uploads.reduce((a, b) => (b.length > a.length ? b : a))), source: 'file' };
      return { raw: '', source: 'none' };
    }
    const bytes = new Uint8Array(await req.arrayBuffer());
    if (type.includes('json')) {
      let body = null;
      try {
        body = JSON.parse(new TextDecoder().decode(bytes));
      } catch {
        body = null;
      }
      if (body && typeof body === 'object' && !Array.isArray(body)) {
        const named = String(body.workout_text || body.text || body.note || '').trim();
        if (named) return { raw: named, source: 'json.named' };
        const values = Object.values(body).filter((v) => ['string', 'number'].includes(typeof v)).map((v) => String(v).trim()).filter(Boolean);
        if (values.length) return { raw: longest(values), source: 'json.any' };
      }
      return { raw: '', source: 'none' };
    }
    const raw = toPlainText(bytes);
    return { raw, source: raw ? 'raw.body' : 'none' };
  } catch {
    return { raw: '', source: 'error' };
  }
}

// Python's max(values, key=len): the first of the longest.
const longest = (values) => values.reduce((a, b) => ([...b].length > [...a].length ? b : a));

/** True when the day's workout already holds every exercise in the text: an upload that got
 * through before the phone gave up waiting. */
export function sameWorkoutAlreadySaved(lb, rawText, day) {
  let parsed;
  try {
    parsed = workoutParser(toPlainText(rawText), { bodyweight: lb.profile()?.bodyweight ?? null, preserveBodyweightOffsets: true });
  } catch {
    return false;
  }
  const names = new Set((parsed?.exercises || []).map((e) => normalizeExerciseName(e.name || '')).filter(Boolean));
  if (!names.size) return false;
  const logged = new Set((lb.workout(day)?.logs || []).map((l) => normalizeExerciseName(l.exercise || '')));
  return [...names].every((n) => logged.has(n));
}

/** Never a bare 500: the app (and a Shortcut) always gets a reply it can read. */
export async function handle(req, env, options = {}) {
  try {
    return await serve(req, env, options);
  } catch (err) {
    console.error('failed', err);
    return json({ ok: false, error: 'Liftbook hit an error. Try again in a minute.', server: SERVER }, 500);
  }
}

async function serve(req, env, { fetchFn = (...a) => globalThis.fetch(...a), now = () => Date.now() } = {}) {
  if (req.method === 'OPTIONS') return preflight();
  const { action, key, url } = route(req);
  const asJson = action === 'log' || url.searchParams.get('format') === 'json' || Boolean(url.searchParams.get('list'));
  const reply = (body, status = 200) => json({ ...body, server: SERVER }, status);
  const say = (message, status) => (asJson ? reply({ ok: status === 200, [status === 200 ? 'text' : 'error']: message }, status) : text(message, status));

  if (!action) return reply({ ok: false, error: 'Unknown Shortcut address. Use .../shortcut/log/<key> or .../shortcut/pick/<key>.' }, 404);
  if (action === 'recommend') {
    return say('This Shortcut is from the old app. Add Get Workout again from Liftbook > Settings > Apple Shortcuts.', 410);
  }
  if (!key) return action === 'log' ? reply({ ok: false, error: KEY_MISSING }) : say(KEY_MISSING, 401);

  const sb = supabaseFor(env, fetchFn);
  const db = sb.asService();
  const [owner] = (await db.get(`shortcut_keys?select=user_id&key_hash=eq.${await sha256Hex(key)}`)) || [];
  if (!owner) return action === 'log' ? reply({ ok: false, error: KEY_INVALID }) : say(KEY_INVALID, 401);
  const userId = owner.user_id;
  db.update(`shortcut_keys?user_id=eq.${userId}`, { last_used_at: new Date(now()).toISOString() }).catch(() => {});

  const admin = ((await db.get(`admins?select=user_id&user_id=eq.${userId}`)) || []).length > 0;
  const { lb, store } = await loadLiftbook(db, userId, { admin });
  const appUrl = String(env.LIFTBOOK_APP_URL || 'https://app.liftbook.in/').replace(/#.*$/, '');
  const dayUrl = (day) => `${appUrl}#/workout/${day}`;

  if (action === 'pick') {
    if (url.searchParams.get('list')) {
      const sessions = sessionLabels(lb.planText());
      return sessions.length ? reply({ ok: true, sessions }) : reply({ ok: false, error: 'No workout plan yet. Add one in Settings first.' });
    }
    const rawKey = String(url.searchParams.get('key') || url.searchParams.get('session') || url.searchParams.get('word') || '').trim().slice(0, 140);
    if (!rawKey) return say('Missing key. Pass ?key=<session-name-or-day>.', 400);
    const picked = resolveDay(lb.planText(), rawKey, lb.text('shortcut_keys'));
    if (picked.error) return say(picked.error, 400);
    return say(lb.retrieveDay(picked.day.category, picked.day.day_id).text, 200);
  }

  // log
  const { raw, source } = await workoutTextOf(req, url);
  const textIn = toPlainText(Array.from(raw).slice(0, MAX_TEXT).join(''));
  if (!textIn) return reply({ ok: false, error: 'Please enter workout data.', received_chars: 0, input_source: source });
  const at = localNow(tzOffset(url.searchParams.get('tz_offset_minutes') ?? env.LIFTBOOK_TZ_OFFSET_MINUTES), now());
  const check = lb.check(textIn, { now: at });
  const result = await lb.log(textIn, { now: at });
  if (result.error) {
    const errors = result.errors || [result.error];
    const error = errors.length > 1 ? `${errors[0]} (${errors.length - 1} more like this.)` : errors[0];
    console.info(`shortcut log refused: ${error} (source=${source}, chars=${textIn.length})`);
    return reply({ ok: false, error, received_chars: textIn.length, input_source: source });
  }
  if (result.existing) {
    const day = result.existing.day;
    if (!sameWorkoutAlreadySaved(lb, textIn, day)) {
      // A different workout for a day that has one: nothing was saved, so don't say it was.
      return reply({ ok: false, error: DAY_TAKEN, date: day, result_url: dayUrl(day), already_exists: true, input_source: source });
    }
    return reply({
      ok: true, date: day, exercise_count: 0, set_count: 0, result_url: dayUrl(day), input_source: source,
      bodyweight_hint: false, already_exists: true, message: 'Workout already there.',
    });
  }
  try {
    await saveChanges(db, store, userId);
  } catch (err) {
    console.error('shortcut save failed', err.message);
    return reply({ ok: false, error: SAVE_FAILED, input_source: source });
  }
  const skipped = result.skipped || [];
  return reply({
    ok: true,
    date: result.day,
    exercise_count: check.exercise_count || 0,
    set_count: check.set_count || 0,
    result_url: dayUrl(result.day),
    bodyweight_hint: Boolean(lb.profile()?.bodyweight == null && hasBodyweightToken(textIn)),
    input_source: source,
    already_exists: false,
    message: skipped.length ? `Workout logged. Not saved: ${skipped.join(' ')}` : 'Workout logged.',
  });
}
