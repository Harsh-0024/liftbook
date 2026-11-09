// Liftbook's data on this device: the screens ask here, and every answer comes from the local
// store through the workout logic in web/core/. Changes are written to the store (which syncs
// them); nothing here waits for the network except the shared plan and feedback.

import { workoutParser, parsePlanExerciseLine, isTimeOnlyExercise } from '../core/parser.js';
import {
  handleWorkoutLog, formatSetsDisplay, resolveTimedStatus, hasTimeHint, classifyPerformance, getBestLog, comparisonSetCount, logMetrics,
} from '../core/logging.js';
import { makeSettings, hasBodyweightToken, isBodyweightEnabled, inferLogUsesBodyweight, effectiveSetsForLog } from '../core/bodyweight.js';
import {
  effectivePlanText, effectiveRepRangesText, getWorkoutDays, ownPlanText, parseRepTargetSets, parsePlanTargetSets, resolveTargetSets,
  parseRepRangesText, lookupRepTarget,
} from '../core/plans.js';
import {
  SPARKLINE_SESSIONS, MEDAL_KEYS, rankedSets, sessionScore, displaySets, trend, bestSummary, compareColumns, sparkline,
  shortDate, longDate, formatSetsLine,
} from '../core/insights.js';
import { formatG as fmtG } from '../core/py.js';
import { retrieveDay, retrieveCustom, describeRetrieveOutput, picksForPlanLines, oftenTrainedKeys } from '../core/retrieve.js';
import {
  getChartData, getOverallProgressData, statsExerciseOptions, getAllExercisesSummary, bodyweightWarningExercises,
} from '../core/stats.js';
import { normalizeExerciseName, exerciseKey, statsExerciseKey, statsVocabulary, buildNameIndex, namesFor } from '../core/names.js';
import {
  validateRename, renamedName, renameInExerciseString, renameInPlanText, renameInRepText,
} from '../core/renames.js';
import { parseDate, formatDateTime, localDay } from '../core/dates.js';
import { timeKey } from './tables.js';

export const FEEDBACK_KINDS = ['like', 'dislike', 'improve', 'idea'];

// randomUUID only exists on https pages (and localhost); getRandomValues works everywhere.
const uuid = () => {
  if (globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID();
  const b = globalThis.crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hex = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

/** "2026-10-31T09:00:00" -> "2026-10-31" (workout dates are the person's own clock, no zone). */
export const dayOf = (date) => String(date || '').slice(0, 10);

export class Liftbook {
  constructor(store, client, userId) {
    this.store = store;
    this.client = client;
    this.userId = userId;
    this.kept = new Map();
  }

  /** fn's answer, worked out again only after the table changes. Callers get their own copy of the list. */
  keep(name, table, fn) {
    const v = this.store.version[table];
    let k = this.kept.get(name);
    if (!k || k.v !== v) this.kept.set(name, (k = { v, value: fn() }));
    return k.value.slice();
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
    return this.keep('history', 'workout_logs', () => this.store.all('workout_logs').sort((a, b) => {
      const la = a.legacy_id ?? Infinity;
      const lb = b.legacy_id ?? Infinity;
      if (la !== lb) return la < lb ? -1 : 1;
      return timeKey(a.created_at) - timeKey(b.created_at) || String(a.id).localeCompare(String(b.id));
    }));
  }

  exerciseSettings() {
    return this.store.all('exercise_settings');
  }

  renames() {
    return this.store.all('exercise_renames');
  }

  /** Workouts, newest first: one per day, its exercises in logged order. */
  workouts() {
    return this.keep('workouts', 'workout_logs', () => {
      const byDay = new Map();
      for (const log of this.history()) {
        const day = dayOf(log.date);
        if (!byDay.has(day)) byDay.set(day, { day, date: log.date, title: log.workout_name || 'Workout', logs: [] });
        byDay.get(day).logs.push(log);
      }
      return [...byDay.values()].sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
    });
  }

  workout(day) {
    return this.workouts().find((w) => w.day === day) || null;
  }

  /**
   * Each exercise of a day's workout against its earlier sessions, as the old workout page showed
   * it (routes/workouts.py view_workout): the trend vs the average of the last 3 sessions, the
   * medal or gap vs the best, the sets matched strongest to strongest with the last session and
   * the best, and the points of the last 8 sessions for a small chart.
   */
  compareWorkout(day) {
    const w = this.workout(day);
    if (!w) return [];
    const settings = makeSettings(this.exerciseSettings());
    const all = this.history();
    const order = new Map(all.map((l, i) => [l, i]));
    const before = all.filter((l) => dayOf(l.date) < day);
    const nameIndex = buildNameIndex([...new Set(all.map((l) => l.exercise))]);
    const repTargetSets = parseRepTargetSets(this.text('rep_ranges'));
    const planTargetSets = parsePlanTargetSets(this.planText());
    const refYear = Number(day.slice(0, 4));
    return w.logs.map((log) => {
      const str = String(log.exercise_string || '');
      const [targetSets, strict] = resolveTargetSets({
        exerciseName: log.exercise, exerciseString: str, repTargetSets, planTargetSets,
        inferredSetCount: comparisonSetCount(log.sets, str), defaultSets: 3,
      });
      const isTimed = Boolean(resolveTimedStatus({ exerciseName: log.exercise, exerciseString: str, settings, history: all, nameIndex }).is_timed);
      const usesBw = inferLogUsesBodyweight(settings, log);
      const names = new Set(namesFor(log.exercise, nameIndex));
      const prevAll = before.filter((l) => names.has(l.exercise))
        .sort((a, b) => (dayOf(a.date) < dayOf(b.date) ? 1 : dayOf(a.date) > dayOf(b.date) ? -1 : order.get(b) - order.get(a)));
      const comparable = prevAll.filter((l) => !strict || comparisonSetCount(l.sets, l.exercise_string || '') >= targetSets);
      const prev = comparable[0] || null;
      let perf = classifyPerformance({
        history: before, settings, exerciseName: log.exercise, currentSets: effectiveSetsForLog(settings, log),
        targetSets, strictTargetSets: strict, nameIndex, isTimed, currentLogId: log.id, currentExerciseString: str,
      });
      if (!prev) perf = { ...perf, key: 'first_log' };
      let best = null;
      if (prev) {
        best = (perf.reference_log_id != null && before.find((l) => l.id === perf.reference_log_id))
          || getBestLog({ history: before, settings, exerciseName: log.exercise, targetSets, strictTargetSets: strict, nameIndex, isTimed });
      }
      const opts = { usesBodyweight: usesBw, isTimed };
      const ranked = (l) => {
        const eff = effectiveSetsForLog(settings, l);
        return rankedSets(displaySets(l, eff, usesBw), eff, opts);
      };
      const score = (l) => sessionScore(effectiveSetsForLog(settings, l), { topN: targetSets, isTimed });
      const todayRanked = ranked(log);
      const todayScore = score(log);
      const past = comparable.slice(0, SPARKLINE_SESSIONS - 1).map((l) => ({ log: l, day: dayOf(l.date), score: score(l) }));
      const tr = trend(todayScore, past);
      const side = (l) => (l ? { day: dayOf(l.date), date_text: shortDate(dayOf(l.date), refYear), ranked: ranked(l), bodyweight: l.bodyweight ?? null } : null);
      const last = side(prev);
      const bestSide = side(best);
      const bestIsLast = Boolean(best && prev && best === prev);
      const point = (l, extra) => ({ day: dayOf(l.date), date_text: longDate(dayOf(l.date)), sets: ranked(l).map((x) => x.label).join(' · '), ...extra });
      const spark = sparkline([
        ...past.slice().reverse().map((p) => point(p.log, { score: p.score, is_best: p.log === best })),
        point(log, { score: todayScore, is_today: true }),
      ], { average: tr?.average ?? null });
      let bodyweightNote = null;
      if (usesBw && last && log.bodyweight && last.bodyweight && Math.abs(Number(log.bodyweight) - Number(last.bodyweight)) >= 0.1) {
        bodyweightNote = `Bodyweight ${fmtG(Number(log.bodyweight))} kg today vs ${fmtG(Number(last.bodyweight))} kg last time, which is included in the comparison.`;
      }
      return {
        log, isTimed, usesBw, perf,
        medal: MEDAL_KEYS.has(perf.key),
        first: !prevAll.length,
        setsRanked: todayRanked.map((x) => x.label),
        setsLine: formatSetsLine(displaySets(log, effectiveSetsForLog(settings, log), usesBw), opts),
        trend: tr,
        trendDates: (tr?.days || []).map((d) => shortDate(d, refYear)).join(', '),
        best: bestSummary(perf, { hasHistory: prevAll.length > 0 }),
        last, bestCmp: bestSide, bestIsLast,
        table: last ? compareColumns(todayRanked, last.ranked, bestIsLast ? null : bestSide?.ranked) : [],
        bodyweightNote,
        spark,
        sparkFirst: spark ? shortDate(spark.dots[0].day, refYear) : '',
      };
    });
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
      // As the Python log route: bodyweight sets stay as offsets ("BW+20" is 20), flagged as
      // bodyweight; stats add the bodyweight once. Without this they were stored as 98 and
      // counted 78 kg twice.
      parsed = workoutParser(clean, { bodyweight: this.profile()?.bodyweight ?? null, preserveBodyweightOffsets: true, now });
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
    // Each exercise's sets as the old check wrote them: "BW+20×6" for bodyweight, "60×1s" or "45s"
    // for timed (your answer, the known timed list, or a time written in the text).
    const settings = makeSettings(this.exerciseSettings());
    const num = (v) => fmtG(Number(v) || 0);
    for (const e of exercises) {
      if (e.valid === false || e.missing_name) continue;
      const str = String(e.exercise_string || '');
      const bw = Boolean(isBodyweightEnabled(settings, e.name, str) || isTimeOnlyExercise(str, e.source_name || e.name));
      const secs = Boolean(resolveTimedStatus({ exerciseName: e.name, exerciseString: str, settings }).is_timed);
      e.sets_label = (e.reps || []).map((r, k) => {
        const w = Number(e.weights?.[k]) || 0;
        if (bw) return `${w ? `BW${w > 0 ? '+' : '−'}${num(Math.abs(w))}` : 'BW'}×${r}${secs ? 's' : ''}`;
        if (secs && !w) return `${r}s`;
        return `${num(w)}×${r}${secs ? 's' : ''}`;
      }).join(' · ');
    }
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
    const needsBodyweight = !this.profile()?.bodyweight && rows.some((l) => l.uses_bodyweight);
    return { summary: result.summary, day: dayOf(parsed.date), appended: Boolean(existing), timedPrompts, skipped: check.errors, needsBodyweight };
  }

  async deleteWorkout(day) {
    const w = this.workout(day);
    if (w) await this.store.remove('workout_logs', w.logs.map((l) => l._k));
  }

  /** Several days' workouts at once (the history's Select). */
  async deleteWorkouts(days) {
    const keys = days.flatMap((d) => this.workout(d)?.logs.map((l) => l._k) || []);
    if (keys.length) await this.store.remove('workout_logs', keys);
  }

  /* ---------------- exercise settings ---------------- */

  async setExerciseSetting(name, fields) {
    const key = exerciseKey(name);
    if (!key) return null;
    const before = this.store.get('exercise_settings', key, { deleted: true }) || {};
    return this.store.change('exercise_settings', { ...before, exercise_key: key, exercise_name: before.exercise_name || name, ...fields });
  }

  /** Whether an exercise counts bodyweight: your choice, or the built-in list (pull-ups, dips…). */
  bodyweightOn(name) {
    return isBodyweightEnabled(makeSettings(this.exerciseSettings()), name, '');
  }

  /**
   * Before bodyweight is turned off for an exercise: its logs, and how many count bodyweight now
   * (services.bodyweight.get_bodyweight_conflict_info). With any, the old page asked what to do.
   */
  bodyweightConflict(name) {
    const key = exerciseKey(name);
    const logs = key ? this.history().filter((l) => exerciseKey(l.exercise) === key) : [];
    const bodyweightLogs = logs.filter((l) => hasBodyweightToken(l.exercise_string) || l.uses_bodyweight === true).length;
    const wasSelected = this.exerciseSetting(name)?.is_bodyweight === true;
    return { total: logs.length, bodyweight_logs: bodyweightLogs, has_conflict: Boolean(bodyweightLogs || wasSelected) };
  }

  /**
   * Turn bodyweight off for an exercise, and say what its old logs mean:
   * 'future_only' (each keeps what it meant), 'keep_offsets' (a past "10" stays bodyweight + 10)
   * or 'literal' (a past "10" becomes 10 kg). Their best-set numbers are worked out again.
   */
  async turnOffBodyweight(name, resolution = 'future_only') {
    const key = exerciseKey(name);
    if (!key) return null;
    const settings = makeSettings(this.exerciseSettings());
    const history = this.history();
    const logs = history.filter((l) => exerciseKey(l.exercise) === key);
    const isTimed = Boolean(resolveTimedStatus({ exerciseName: name, settings, history }).is_timed);
    const changes = [];
    for (const log of logs) {
      // Saved with the meaning it has today, so turning the setting off doesn't change it.
      const uses = resolution === 'keep_offsets' ? true : resolution === 'literal' ? false : inferLogUsesBodyweight(settings, log);
      if (log.uses_bodyweight === uses) continue;
      const next = { ...log, uses_bodyweight: uses };
      changes.push({ ...next, ...logMetrics(next, { settings, isTimed: isTimed || hasTimeHint(log.exercise_string || '') }) });
    }
    if (changes.length) await this.store.change('workout_logs', changes);
    return this.setExerciseSetting(name, { is_bodyweight: false, bodyweight_source: 'manual' });
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

  retrieveCustom(exerciseLines, title, setOverrides = null) {
    const [text, exercises, sets] = retrieveCustom(exerciseLines, { title, setOverrides, ...this.retrieveContext() });
    return { text, exercises, sets, described: describeRetrieveOutput(text) };
  }

  /** Every exercise ever logged or in the plan, for picking by hand; most retrieved first. */
  /**
   * Every exercise in the plan or the history, for picking by hand, as the old picker had it:
   * the sets and reps a plan retrieve would give it, and whether it's trained often (in the
   * plan you follow, or part of your routine) or goes under "Less often". Most retrieved first.
   */
  exerciseCatalog() {
    const counts = new Map();
    for (const e of this.store.all('retrieval_events')) counts.set(e.exercise_key, (counts.get(e.exercise_key) || 0) + 1);
    const items = new Map();
    const days = this.planDays().workout || {};
    for (const cat of Object.values(days)) {
      for (const lines of Object.values(cat)) {
        for (const line of lines) {
          const parsed = parsePlanExerciseLine(String(line));
          const name = String(parsed.name || line).trim();
          const key = normalizeExerciseName(name);
          if (key && !items.has(key)) items.set(key, { key, name, line: String(line), inPlan: true });
        }
      }
    }
    const byDay = new Map();
    for (const log of this.history()) {
      const key = normalizeExerciseName(log.exercise);
      if (!key) continue;
      if (!items.has(key)) items.set(key, { key, name: log.exercise, line: log.exercise, inPlan: false });
      const day = String(log.date || '').slice(0, 10);
      if (day) (byDay.get(day) || byDay.set(day, new Set()).get(day)).add(key);
    }
    // null: too little history to tell, so nothing folds away.
    const often = oftenTrainedKeys([...byDay].sort(), [...items.values()].filter((i) => i.inPlan).map((i) => i.key));
    const repText = this.repRangesText();
    const [ranges, setsBy] = parseRepRangesText(repText);
    return [...items.values()]
      .map((it) => {
        const [, sets] = picksForPlanLines([it.line], repText)[0] || [null, 3];
        const range = lookupRepTarget(it.name, ranges, setsBy)[0] || parsePlanExerciseLine(it.line).inline_range || '';
        return { key: it.key, name: it.name, count: counts.get(it.key) || 0, sets, reps: String(range),
          often: often === null || often.has(it.key) };
      })
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }

  /** The exercises of a plan day with their sets ([[name, sets]]), for Edit. */
  planDayPicks(category, dayId) {
    const lines = this.planDays().workout?.[category]?.[`${category} ${dayId}`] || [];
    const byKey = new Map(picksForPlanLines(lines, this.repRangesText()));
    const out = [];
    for (const line of lines) {
      const name = String(parsePlanExerciseLine(String(line)).name || line).trim();
      const key = normalizeExerciseName(name);
      if (byKey.has(key)) {
        out.push([name, byKey.get(key)]);
        byKey.delete(key);
      }
    }
    return out;
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

  /**
   * Every exercise logged, newest day first, as a spreadsheet (the old app's /export_csv columns).
   * from/to: "YYYY-MM-DD" or "" for no limit.
   */
  csv({ from = '', to = '' } = {}) {
    const history = this.history();
    const settings = makeSettings(this.exerciseSettings());
    const timed = new Map();
    const isTimed = (l) => {
      if (hasTimeHint(l.exercise_string || '')) return true;
      if (!timed.has(l.exercise)) timed.set(l.exercise, resolveTimedStatus({ exerciseName: l.exercise, settings, history }).is_timed);
      return timed.get(l.exercise);
    };
    const cell = (v) => {
      const t = v === null || v === undefined ? '' : String(v);
      return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
    };
    const list = (xs) => (Array.isArray(xs) ? xs.filter((x) => x !== null && x !== undefined).join(',') : '');
    const rows = [['Date', 'Workout Name', 'Exercise', 'Exercise String', 'Weights', 'Reps', 'Sets JSON', 'Top Weight (kg)',
      'Top Reps', 'Estimated 1RM (kg)', 'Uses Bodyweight', 'Bodyweight (kg)', 'Timed']];
    const logs = history.filter((l) => (!from || dayOf(l.date) >= from) && (!to || dayOf(l.date) <= to))
      .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)); // a day's exercises stay in logged order
    for (const l of logs) {
      const sets = l.sets && typeof l.sets === 'object' ? l.sets : {};
      rows.push([String(l.date || '').replace(' ', 'T'), l.workout_name || '', l.exercise || '', l.exercise_string || '',
        list(sets.weights), list(sets.reps), l.sets ? JSON.stringify(l.sets) : '', l.top_weight ?? '', l.top_reps ?? '',
        l.estimated_1rm === null || l.estimated_1rm === undefined ? '' : Number(l.estimated_1rm).toFixed(2),
        l.uses_bodyweight ? 'yes' : l.uses_bodyweight === false ? 'no' : '', l.bodyweight ?? '', isTimed(l) ? 'yes' : 'no']);
    }
    return { count: logs.length, text: rows.map((r) => r.map(cell).join(',')).join('\r\n') + '\r\n' };
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

  /* Admins only (the database refuses anyone else). */

  async adminFeedback() {
    return (await this.client.db.rpc('admin_feedback', {})) || [];
  }

  async setFeedbackStatus(id, status) {
    if (!['new', 'seen', 'done'].includes(status)) throw new Error('Unknown status.');
    await this.client.db.rpc('admin_set_feedback_status', { feedback_id: id, new_status: status });
  }

  async adminUsers() {
    return (await this.client.db.rpc('admin_users', {})) || [];
  }

  async adminCoach(maxRows = 100) {
    return (await this.client.db.rpc('admin_coach_answers', { max_rows: maxRows })) || { totals: {}, answers: [] };
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

  /** Take the profile photo away: the profile forgets it first, then the file goes. */
  async removeAvatar() {
    const old = this.profile()?.avatar_path;
    if (!old) return;
    await this.saveProfile({ avatar_path: null });
    await this.store.setMeta('avatar_url', null);
    if (!old.startsWith('http')) this.client.storage.remove('avatars', [old]).catch(() => {});
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
