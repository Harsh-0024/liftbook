import test from 'node:test';
import { load, check } from './helpers.js';
import { handleWorkoutLog } from '../logging.js';

test('saving a workout matches Python', (t) => {
  check(t, load('log'), ({ parsed, state, logged_bodyweight: loggedBodyweight }) => {
    let nextId = Math.max(0, ...state.history.map((log) => log.id));
    const before = new Set(state.settings.filter((row) => row.is_bodyweight !== undefined).map((row) => row.exercise_key));
    const result = handleWorkoutLog(parsed, {
      history: state.history, settings: state.settings, renames: state.renames, ownRepRanges: state.own_rep_ranges,
      planText: state.plan, bodyweight: state.bodyweight, loggedBodyweight, newId: () => (nextId += 1),
    });
    const keys = [...new Set(result.bodyweightSettings.map((row) => row.exercise_key))].filter((k) => !before.has(k)).sort();
    return { summary: result.summary, logs: result.logs, bodyweight: result.bodyweight ?? state.bodyweight, bodyweight_keys: keys };
  }, (c) => JSON.stringify(c.input.parsed).slice(0, 300));
});
