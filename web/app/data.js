// Liftbook's data on this device: the screens ask here, and every answer comes from the local
// store through the workout logic in web/core/. Changes are written to the store (which syncs
// them); nothing here waits for the network except the shared plan and feedback.

import { workoutParser } from '../core/parser.js';
import { handleWorkoutLog, formatSetsDisplay } from '../core/logging.js';
import { effectivePlanText, effectiveRepRangesText, getWorkoutDays, ownPlanText } from '../core/plans.js';
import { retrieveDay, retrieveCustom, describeRetrieveOutput } from '../core/retrieve.js';
import {
  getChartData, getOverallProgressData, statsExerciseOptions, getAllExercisesSummary, bodyweightWarningExercises,
} from '../core/stats.js';
import { normalizeExerciseName, exerciseKey, statsExerciseKey, statsVocabulary } from '../core/names.js';
import {
  validateRename, renamedName, renameInExerciseString, renameInPlanText, renameInRepText,
} from '../core/renames.js';
import { parseDate, formatDateTime, localDay } from '../core/dates.js';
import { timeKey } from './tables.js';

export const FEEDBACK_KINDS = ['like', 'dislike', 'improve', 'idea'];

const uuid = () => globalThis.crypto.randomUUID();

/** "2026-10-31T09:00:00" -> "2026-10-31" (workout dates are the person's own clock, no zone). */
export const dayOf = (date) => String(date || '').slice(0, 10);

export class Liftbook {
  constructor(store, client, userId) {
    this.store = store;
    this.client = client;
    this.userId = userId;
  }

  /* ---------------- profile and settings ---------------- */

  profile() {
    return this.store.get('profiles');
  }

  async saveProfile(fields) {
    return this.store.change('profiles', fields);
  }

  settings() {
    return { ...(this.store.get('app_settings')?.json || {}) };
  }

  async setSetting(key, value) {
    return this.store.change('app_settings', { json: { ...this.settings(), [key]: value } });
  }

  text(kind) {
    return this.store.get('user_texts', kind)?.text || '';
  }

  async setText(kind, text) {
    return this.store.change('user_texts', { kind, text: String(text ?? '') });
  }

  /** The shared plan (the main admin's), kept on the device for offline use. */
  sharedPlan() {
    return this.store.getMeta('shared_plan', { plan: null, rep_ranges: null });
  }

  isAdmin() {
    return Boolean(this.store.getMeta('is_admin', false));
  }

  /** Ask the server for the shared plan and whether this person is an admin. Quiet offline. */
  async refreshShared() {
    try {
      const [shared, admin] = await Promise.all([this.client.db.rpc('shared_plan'), this.client.db.rpc('is_admin')]);
      await this.store.setMeta('shared_plan', shared || {});
      await this.store.setMeta('is_admin', Boolean(admin));
      return true;
    } catch {
      return false;
    }
  }

  /** The plan owner is the main admin; an admin follows their own plan. */
  planText() {
    const s = this.settings();
    return effectivePlanText({
      ownPlan: this.text('plan'), followOwner: Boolean(s.follow_shared_plan), isOwner: this.isAdmin(),
      ownerPlan: this.sharedPlan().plan || '',
    });
  }

  repRangesText() {
    const s = this.settings();
    return effectiveRepRangesText({
      ownRepRanges: this.text('rep_ranges'), followOwner: Boolean(s.follow_shared_exercises), isOwner: this.isAdmin(),
      ownerRepRanges: this.sharedPlan().rep_ranges || '',
    });
  }

  ownPlan() {
    return ownPlanText(this.text('plan'));
  }

  /* ---------------- workouts ---------------- */

  /** Every logged exercise, oldest first as created: imported logs by their old id, then new ones. */
  history() {
    return this.store.all('workout_logs').sort((a, b) => {
      const la = a.legacy_id ?? Infinity;
      const lb = b.legacy_id ?? Infinity;
      if (la !== lb) return la < lb ? -1 : 1;
      return timeKey(a.created_at) - timeKey(b.created_at) || String(a.id).localeCompare(String(b.id));
    });
  }

  exerciseSettings() {
    return this.store.all('exercise_settings');
  }

  renames() {
    return this.store.all('exercise_renames');
  }

  /** Workouts, newest first: one per day, its exercises in logged order. */
  workouts() {
    const byDay = new Map();
    for (const log of this.history()) {
      const day = dayOf(log.date);
      if (!byDay.has(day)) byDay.set(day, { day, date: log.date, title: log.workout_name || 'Workout', logs: [] });
      byDay.get(day).logs.push(log);
    }
    return [...byDay.values()].sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
  }

  workout(day) {
    return this.workouts().find((w) => w.day === day) || null;
  }

  /** The workout as text again, as it would be typed (editing, copying). */
  workoutText(workout) {
    const p = parseDate(workout.date);
    const lines = [`${p.day}/${p.month}/${String(p.year % 100).padStart(2, '0')} ${workout.title}`];
    lines.push('');
    for (const log of workout.logs) {
      lines.push(String(log.exercise_string || `${log.exercise}\n${formatSetsDisplay(log.sets)}`).trim(), '');
    }
    return lines.join('\n').trim();
  }

  /** Read typed text without saving: what would be saved, and what's wrong with it. */
  check(text, { now = new Date() } = {}) {
    const clean = String(text || '').replace(/\r\n?/g, '\n').trim();
    if (!clean) return { ok: false, errors: ['Type your workout first.'], parsed: null };
    let parsed;
    try {
      parsed = workoutParser(clean, { bodyweight: this.profile()?.bodyweight ?? null, now });
    } catch (err) {
      return { ok: false, errors: [`Couldn’t read this: ${err.message}`], parsed: null };
    }
    const exercises = parsed.exercises || [];
    const errors = [];
    if (!exercises.length) errors.push('No exercises found. Put each exercise on its own line, its sets on the next.');
    for (const e of exercises.filter((x) => x.missing_name && x.valid !== false)) {
      errors.push(`Line ${e.line}: sets without an exercise name above them (\u201c${e.exercise_string}\u201d).`);
    }
    if (parsed.invalid_date_text) errors.push(`\u201c${parsed.invalid_date_text}\u201d isn\u2019t a date this app can read.`);
    const invalid = exercises.filter((e) => e.valid === false || e.missing_name);
    for (const e of invalid.filter((x) => x.valid === false)) errors.push(`“${e.name}”: couldn’t read its sets (“${String(e.exercise_string || '').split('\n').slice(1).join(' ')}”).`);
    const day = dayOf(parsed.date);
    const existing = this.workout(day);
    return {
      // Sets without a name and unreadable dates stop the save; an unreadable exercise is
      // shown as an error in the summary and the rest is saved.
      ok: exercises.length > 0 && invalid.length < exercises.length && !parsed.invalid_date_text
        && !exercises.some((e) => e.missing_name),
      errors, parsed, day,
      exercise_count: exercises.length - invalid.length,
      set_count: exercises.reduce((n, e) => n + (e.valid === false ? 0 : (e.reps || []).length), 0),
      existing: existing ? { day, title: existing.title } : null,
    };
  }

  /**
   * Save typed text as a workout. append: add to the day's workout that is already there.
   * Returns {summary, day, appended} or {error}, or {existing} when the day already has one.
   */
  async log(text, { append = false, replaceDay = null, now = new Date() } = {}) {
    const check = this.check(text, { now });
    if (!check.ok) return { error: check.errors[0] || 'Nothing to save.', errors: check.errors };
    const parsed = check.parsed;
    const existing = check.existing && check.existing.day !== replaceDay ? this.workout(check.day) : null;
    if (existing && !append) return { existing: check.existing };
    if (existing && append) {
      parsed.date = existing.date;
      parsed.workout_name = existing.title;
    }
    let loggedBodyweight = null;
    let history = this.history();
    if (replaceDay) {
      const old = this.workout(replaceDay);
      loggedBodyweight = old?.logs.find((l) => l.bodyweight)?.bodyweight ?? null;
      history = history.filter((l) => dayOf(l.date) !== replaceDay);
    }
    const result = handleWorkoutLog(parsed, {
      history, settings: this.exerciseSettings(), renames: this.renames(), ownRepRanges: this.text('rep_ranges'),
      planText: this.planText(), bodyweight: this.profile()?.bodyweight ?? null, loggedBodyweight, newId: uuid,
    });
    if (replaceDay) {
      const old = this.workout(replaceDay);
      if (old) await this.store.remove('workout_logs', old.logs.map((l) => l._k));
    }
    // created_at keeps the logged order (history() sorts by it), a millisecond apart.
    const base = Date.now();
    const rows = result.logs.map((l, i) => ({ ...l, created_at: new Date(base + i).toISOString() }));
    if (rows.length) await this.store.change('workout_logs', rows);
    if (result.bodyweight !== null && result.bodyweight !== undefined && this.profile()) {
      await this.saveProfile({ bodyweight: result.bodyweight });
    }
    const flags = result.bodyweightSettings.filter((s) => this.store.get('exercise_settings', s.exercise_key)?.is_bodyweight !== true);
    if (flags.length) {
      await this.store.change('exercise_settings', flags.map((s) => ({
        ...(this.store.get('exercise_settings', s.exercise_key, { deleted: true }) || {}),
        exercise_key: s.exercise_key, exercise_name: s.exercise_name, is_bodyweight: true, bodyweight_source: s.source,
      })));
    }
    const timedPrompts = [...new Set(result.summary.filter((r) => r.timed_prompt_needed).map((r) => r.timed_prompt_exercise))];
    return { summary: result.summary, day: dayOf(parsed.date), appended: Boolean(existing), timedPrompts, skipped: check.errors };
  }

  async deleteWorkout(day) {
    const w = this.workout(day);
    if (w) await this.store.remove('workout_logs', w.logs.map((l) => l._k));
  }

  /* ---------------- exercise settings ---------------- */

  async setExerciseSetting(name, fields) {
    const key = exerciseKey(name);
    if (!key) return null;
    const before = this.store.get('exercise_settings', key, { deleted: true }) || {};
    return this.store.change('exercise_settings', { ...before, exercise_key: key, exercise_name: before.exercise_name || name, ...fields });
  }

  exerciseSetting(name) {
    return this.store.get('exercise_settings', exerciseKey(name)) || null;
  }

  /* ---------------- retrieve ---------------- */

  planDays() {
    return getWorkoutDays(this.planText());
  }

  retrieveContext() {
    return {
      history: this.history(), settings: this.exerciseSettings(), repRangesText: this.repRangesText(),
      bodyweight: this.profile()?.bodyweight ?? null,
    };
  }

  retrieveDay(category, dayId) {
    const [text, exercises, sets] = retrieveDay(category, dayId, { planText: this.planText(), ...this.retrieveContext() });
    return { text, exercises, sets, described: describeRetrieveOutput(text) };
  }

  retrieveCustom(exerciseLines, title) {
    const [text, exercises, sets] = retrieveCustom(exerciseLines, { title, ...this.retrieveContext() });
    return { text, exercises, sets, described: describeRetrieveOutput(text) };
  }

  /** Every exercise ever logged or in the plan, for picking by hand; most retrieved first. */
  exerciseCatalog() {
    const counts = new Map();
    for (const e of this.store.all('retrieval_events')) counts.set(e.exercise_key, (counts.get(e.exercise_key) || 0) + 1);
    const names = new Map();
    const days = this.planDays().workout || {};
    for (const cat of Object.values(days)) {
      for (const lines of Object.values(cat)) {
        for (const line of lines) {
          const name = String(line).replace(/\s*-\s*\[.*$/, '').trim();
          const key = normalizeExerciseName(name);
          if (key && !names.has(key)) names.set(key, name);
        }
      }
    }
    for (const log of this.history()) {
      const key = normalizeExerciseName(log.exercise);
      if (key && !names.has(key)) names.set(key, log.exercise);
    }
    return [...names.entries()]
      .map(([key, name]) => ({ key, name, count: counts.get(key) || 0 }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }

  async recordRetrievals(names) {
    const at = new Date().toISOString();
    const rows = names.map((n) => ({ id: uuid(), exercise_key: normalizeExerciseName(n), retrieved_at: at })).filter((r) => r.exercise_key);
    if (rows.length) await this.store.change('retrieval_events', rows);
  }

  /* ---------------- stats ---------------- */

  statsOptions() {
    const history = this.history();
    const vocabulary = statsVocabulary(new Set(history.map((l) => l.exercise)));
    const views = {};
    for (const s of this.exerciseSettings()) {
      const k = statsExerciseKey(s.exercise_name || s.exercise_key, vocabulary);
      if (k && s.view_count) views[k] = (views[k] || 0) + s.view_count;
    }
    return statsExerciseOptions({ history, views });
  }

  chart(exercise) {
    return getChartData(exercise, { history: this.history(), settings: this.exerciseSettings(), ownRepRanges: this.text('rep_ranges') });
  }

  overall(mode = 'index') {
    return getOverallProgressData({ history: this.history(), settings: this.exerciseSettings(), mode });
  }

  summaries() {
    return getAllExercisesSummary({ history: this.history(), settings: this.exerciseSettings() });
  }

  bodyweightWarnings() {
    return bodyweightWarningExercises({ history: this.history(), bodyweight: this.profile()?.bodyweight ?? null });
  }

  async countView(exercise) {
    const s = this.exerciseSetting(exercise);
    await this.setExerciseSetting(exercise, { view_count: (s?.view_count || 0) + 1, last_viewed_at: new Date().toISOString() });
  }

  /** Workouts per week and the current streak (Home). */
  overview() {
    const workouts = this.workouts();
    const today = localDay(formatDateTime(parseDate(new Date())));
    const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    return {
      total: workouts.length,
      thisWeek: workouts.filter((w) => w.day > weekAgo && w.day <= today).length,
      exercises: new Set(this.history().map((l) => normalizeExerciseName(l.exercise))).size,
      last: workouts[0] || null,
    };
  }

  /* ---------------- renames ---------------- */

  /** Logged names a rename would move: the exercise and its gym-tagged versions. */
  renamePairs(oldName, newName) {
    const oldKey = normalizeExerciseName(oldName);
    const pairs = new Map();
    for (const log of this.history()) {
      const to = renamedName(log.exercise, oldKey, newName);
      if (to && to !== log.exercise) pairs.set(log.exercise, to);
    }
    return [...pairs.entries()];
  }

  renamePreview(oldName, newName) {
    const error = validateRename(oldName, newName);
    if (error) return { error };
    const pairs = this.renamePairs(oldName.trim(), newName.trim());
    const names = new Set(pairs.map(([o]) => o));
    return { pairs, logs: this.history().filter((l) => names.has(l.exercise)).length };
  }

  /** Rename an exercise everywhere in this person's data (logs, plan, rep ranges, settings). */
  async rename(oldName, newName) {
    const error = validateRename(oldName, newName);
    if (error) throw new Error(error);
    oldName = oldName.trim();
    newName = newName.trim();
    const oldKey = normalizeExerciseName(oldName);
    const newKey = normalizeExerciseName(newName);
    const pairs = new Map(this.renamePairs(oldName, newName));
    const moved = [];
    const changes = [];
    for (const log of this.history()) {
      const to = pairs.get(log.exercise);
      if (!to) continue;
      changes.push({ id: log.id, exercise: to, exercise_string: renameInExerciseString(log.exercise_string || '', log.exercise, to) });
      moved.push(log.id);
    }
    if (changes.length) await this.store.change('workout_logs', changes);
    for (const [from, to] of pairs) {
      const s = this.store.get('exercise_settings', exerciseKey(from));
      if (!s) continue;
      const target = this.store.get('exercise_settings', exerciseKey(to));
      await this.store.change('exercise_settings', {
        ...s, ...(target || {}), exercise_key: exerciseKey(to), exercise_name: to,
        view_count: (s.view_count || 0) + (target?.view_count || 0),
      });
      if (exerciseKey(from) !== exerciseKey(to)) await this.store.remove('exercise_settings', exerciseKey(from));
    }
    const plan = this.text('plan');
    if (plan) await this.setText('plan', renameInPlanText(plan, oldKey, newName));
    const reps = this.text('rep_ranges');
    if (reps) await this.setText('rep_ranges', renameInRepText(reps, oldKey, newName));

    // Remember it, so logs typed with the old name land under the new one.
    const rows = this.renames();
    for (const r of rows) {
      if (normalizeExerciseName(r.new_name) === oldKey) await this.store.change('exercise_renames', { id: r.id, new_name: newName });
      if (normalizeExerciseName(newName) === r.old_key) await this.store.remove('exercise_renames', r._k);
    }
    if (oldKey !== newKey) {
      const existing = this.renames().find((r) => r.old_key === oldKey);
      if (existing) {
        await this.store.change('exercise_renames', { id: existing.id, new_name: newName, log_ids: [...new Set([...(existing.log_ids || []), ...moved])] });
      } else {
        await this.store.change('exercise_renames', { id: uuid(), old_key: oldKey, old_name: oldName, new_name: newName, log_ids: moved });
      }
    }
    return { logs: moved.length };
  }

  /** Put a rename back: its logs return to the old name, and the redirect goes. */
  async undoRename(id) {
    const r = this.store.get('exercise_renames', id);
    if (!r) return;
    const ids = new Set(r.log_ids || []);
    const changes = this.history().filter((l) => ids.has(l.id)).map((l) => ({
      id: l.id, exercise: r.old_name, exercise_string: renameInExerciseString(l.exercise_string || '', l.exercise, r.old_name),
    }));
    if (changes.length) await this.store.change('workout_logs', changes);
    await this.store.remove('exercise_renames', r._k);
  }

  /* ---------------- online-only ---------------- */

  async sendFeedback(kind, message, page = '') {
    if (!FEEDBACK_KINDS.includes(kind)) throw new Error('Pick what kind of feedback this is.');
    const text = String(message || '').trim();
    if (!text) throw new Error('Write something first.');
    if (text.length > 2000) throw new Error('Keep it under 2,000 characters.');
    await this.client.db.insert('feedback', { kind, message: text, page: String(page).slice(0, 200) });
  }

  async myFeedback() {
    return this.client.db.select('feedback?select=id,kind,message,status,created_at&order=created_at.desc&limit=50');
  }

  async usernameAvailable(name) {
    return Boolean(await this.client.db.rpc('username_available', { name }));
  }

  /** A new profile photo: into the private avatars bucket, under the person's own folder. */
  async uploadAvatar(file) {
    const ext = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' }[file.type];
    if (!ext) throw new Error('Choose a PNG, JPEG or WebP picture.');
    if (file.size > 2 * 1024 * 1024) throw new Error('Choose a picture under 2 MB.');
    const path = `${this.userId}/avatar-${Date.now()}.${ext}`;
    const old = this.profile()?.avatar_path;
    await this.client.storage.upload('avatars', path, file);
    await this.saveProfile({ avatar_path: path });
    if (old && old !== path) this.client.storage.remove('avatars', [old]).catch(() => {});
    return path;
  }

  async avatarUrl() {
    const path = this.profile()?.avatar_path;
    if (!path || path.startsWith('http')) return path || null;
    const cached = this.store.getMeta('avatar_url');
    if (cached && cached.path === path && cached.expires > Date.now() + 60000) return cached.url;
    try {
      const url = await this.client.storage.signedUrl('avatars', path, 7 * 86400);
      await this.store.setMeta('avatar_url', { path, url, expires: Date.now() + 7 * 86400000 });
      return url;
    } catch {
      return cached?.url || null;
    }
  }

  /** Delete the account: photo first (storage can't cascade), then everything else. */
  async deleteAccount() {
    const path = this.profile()?.avatar_path;
    if (path && !path.startsWith('http')) await this.client.storage.remove('avatars', [path]).catch(() => {});
    await this.client.db.rpc('delete_my_account');
  }
}
