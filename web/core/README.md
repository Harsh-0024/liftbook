# Liftbook core (JavaScript)

The app's workout logic, ported from the Python app to plain JavaScript modules. No build step and
no framework: the same files run in a browser, in Capacitor on Android and in Node.

| Module | What it does | Python it comes from |
| --- | --- | --- |
| `parser.js` | Reads a typed workout: date, title, bodyweight, each exercise's sets | `parsers/workout.py` |
| `plans.js` | Plan days, rep ranges, how many sets an exercise should have | `list_of_exercise.py`, `services/rep_ranges.py`, `services/retrieve.py` |
| `names.js` | Exercise names: normalising, "same exercise" matching, stats keys | `services/exercise_matching.py`, `services/stats.py` |
| `renames.js` | Renamed exercises, in logs, plans and rep ranges | `services/exercise_rename.py` |
| `bodyweight.js` | Bodyweight exercises and the weight they count | `services/bodyweight.py` |
| `scoring.js` | Estimated 1RM, workout scores, comparing two workouts | `services/helpers.py`, `services/best_scoring.py`, `services/workout_quality.py` |
| `logging.js` | Saving a workout: the rows to store and the summary shown | `services/logging.py` |
| `retrieve.js` | Retrieve: the next workout's targets, as text | `services/retrieve.py` |
| `stats.js` | Stats page: charts, summaries, growth, overall progress | `services/stats.py` |
| `dates.js`, `html.js`, `py.js` | Dates, HTML entities, and helpers that make JavaScript behave like Python | |
| `defaults.js`, `html_entities.js` | Generated data (`scripts/make_js_core_data.py`) | `list_of_exercise.py`, Python's `html.entities` |

The functions take plain data, the rows as Supabase stores them (`workout_logs`, `exercise_settings`,
`exercise_renames`), and return plain data. They never read or write a database themselves.

## Tests

From the repo root (Node 20 or newer):

```bash
node --test web/core/test/*.test.js
```

The tests compare every function with what the Python app gives, over about 5,500 cases: all the
inputs the Python test suite uses, hand-written odd ones, and seeded random workouts and training
histories. The expected answers (`test/fixtures/`) are made by the Python app itself:

```bash
.venv/bin/python scripts/make_core_fixtures.py
```

Run it again after changing the Python logic, then make the JavaScript match. Where the two
are allowed to differ, see [DIFFERENCES.md](DIFFERENCES.md).
