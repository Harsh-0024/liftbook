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

test('Retrieve’s placeholder sets are told apart from real ones', async () => {
  const { isRetrievePlaceholder } = await import('../retrieve.js');
  const { equal } = await import('node:assert');
  for (const s of ['Dips\n1, 1', 'Row - [2]\n1 1, 1 1', 'Hyper Extension - [2, 12–20]\nbw/4 bw/4, 1 1', 'Pull Ups\nbw/4, 1', 'Curl\n1 1 1, 1 1 1']) {
    equal(isRetrievePlaceholder(s), true, s);
  }
  for (const s of ['Curl\n1, 10', 'Press\n10, 1', 'Pull Ups\nbw, 1', 'Dips\nbw/4, 8', 'Row\n1 2, 1 1', 'Dips', '']) {
    equal(isRetrievePlaceholder(s), false, s);
  }
});
