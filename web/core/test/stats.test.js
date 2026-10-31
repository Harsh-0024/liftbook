import test from 'node:test';
import { load, check, tally } from './helpers.js';
import { getAllExercisesSummary, getAverageGrowthData, getChartData, getExerciseSummary, getOverallProgressData } from '../stats.js';

const context = (state) => ({ history: state.history, settings: state.settings, ownRepRanges: state.own_rep_ranges });

test('exercise charts match Python', (t) => check(t, load('chart'), ({ exercise, state }) => getChartData(exercise, context(state)), (c) => c.input.exercise));
test('exercise summaries match Python', (t) => check(t, load('summary'), ({ exercise, state }) => getExerciseSummary(exercise, context(state)), (c) => c.input.exercise));
test('all-exercise summaries match Python', (t) => {
  // Python leaves the order of exercises last trained at the same time to the database.
  const sorted = (rows) => [...rows].sort((a, b) => (a.exercise < b.exercise ? -1 : a.exercise > b.exercise ? 1 : 0));
  check(t, load('all_summary').map((c) => ({ ...c, output: sorted(c.output) })), ({ state }) => sorted(getAllExercisesSummary(context(state))));
});
test('average growth matches Python', (t) => check(t, load('growth'), ({ state }) => getAverageGrowthData(context(state))));
test('overall progress matches Python', (t) => {
  check(t, load('overall'), ({ state, mode, baseline_sessions_target: b, min_sessions: m, fade_start_days: fs, fade_end_days: fe }) =>
    getOverallProgressData({
      ...context(state), mode, baselineSessionsTarget: b ?? 5, minSessions: m ?? 3, fadeStartDays: fs ?? 60, fadeEndDays: fe ?? 90,
    }));
});
test.after(() => console.log(`# ${tally.compared} numbers compared, ${tally.inexact} equal only to within 1e-9`));
