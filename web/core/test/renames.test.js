import test from 'node:test';
import { load, check } from './helpers.js';
import { planExerciseNames, renameInExerciseString, renameInPlanText, renameInRepText, validateRename } from '../renames.js';

test('renaming in a plan matches Python', (t) => check(t, load('rename_plan'), ({ text, old_key: k, new_name: n }) => renameInPlanText(text, k, n)));
test('renaming in rep ranges matches Python', (t) => check(t, load('rename_rep'), ({ text, old_key: k, new_name: n }) => renameInRepText(text, k, n)));
test('renaming in logged text matches Python', (t) => check(t, load('rename_string'), ({ text, old, new: n }) => renameInExerciseString(text, old, n)));
test('rename checks match Python', (t) => check(t, load('validate_rename'), ({ old, new: n }) => validateRename(old, n)));
test('plan exercise names match Python', (t) => check(t, load('plan_names'), ({ text }) => planExerciseNames(text)));
