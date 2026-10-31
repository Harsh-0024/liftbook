import test from 'node:test';
import { load, check } from './helpers.js';
import { describeRetrieveOutput, retrieveDay, retrieveForExercises } from '../retrieve.js';

const context = (state) => ({ history: state.history, settings: state.settings, repRangesText: state.rep_ranges, bodyweight: state.bodyweight });

test('Retrieve for picked exercises matches Python', (t) => {
  check(t, load('retrieve'), ({ exercises, header_line: headerLine, set_overrides: setOverrides, state }) =>
    retrieveForExercises(exercises, { headerLine, setOverrides, ...context(state) }));
});
test('Retrieve for a plan day matches Python', (t) => {
  check(t, load('retrieve_day'), ({ category, day_id: dayId, today, state }) =>
    retrieveDay(category, dayId, { planText: state.plan, today, ...context(state) }), (c) => `${c.input.category} ${c.input.day_id}`);
});
test('describing Retrieve text matches Python', (t) => check(t, load('describe'), ({ output }) => describeRetrieveOutput(output)));
