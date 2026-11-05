# History book: improvements work

Newest at the bottom. Each entry: what was done, the branch and commit, what's next.
Read `CONTEXT.md` (same folder) first.

## Branches of this work
| Item | Branch | Started from | State |
| --- | --- | --- | --- |
| 1. Today / time zone | `improve/one-clock` | `design/aesthetic-overhaul` @ 9076371 | done |
| 2. Light-mode gold | `improve/light-contrast` | `design/aesthetic-overhaul` | not started |
| 3. Reminders | `feature/reminders` | `design/aesthetic-overhaul` | not started |
| 4. Widget | `feature/widget` | `feature/reminders` | not started |

The newest copy of these two books is on the branch that is "in progress".

## Log

### 2026-11-05 — Looked at the whole app, plan agreed
- Found the newest app on `design/aesthetic-overhaul`, read `IMPROVEMENTS.md`, the Android
  README, the schema, the import script; ran `npm test` (63 pass). Plan given and the owner
  said "start".
- Created `improve/one-clock` from `design/aesthetic-overhaul` @ 9076371 and these two books.
- **Next:** item 1, step by step:
  1. Stats uses the saved date as it is (no 5h30 shift).
  2. Home "this week" and Stats ranges use the phone's day, not UTC.
  3. `scripts/import_to_supabase.py` moves old undated website workouts (time not exactly
     midnight) forward to India time while copying.
  4. SQL preview + one-time fix for rows already in Supabase, for the owner to run.
  5. Tests at 7:15 pm and 1:30 am.

### 2026-11-05 — Item 1, steps 1-2 and 5: Stats and "today" use the phone's day
- `web/app/data.js`: `LOCAL_TIMES = { tzOffsetMinutes: 0 }` passed to every Stats call (chart,
  overall, exercise list); `web/core/history_qa.js` (coach) does the same. The core keeps its
  +5:30 default only so its tests still match the Python app.
- New `deviceDay()` in `web/core/dates.js`: the calendar day on the device's clock. Used for
  Home's "this week", Stats' 1M/3M/6M/1Y start, the "last synced" day and file names (all used
  the UTC day before).
- New tests `web/app/test/days.test.js` (7:15 pm, 1:30 am, every hour of the day). They fail on
  the old code and pass now. `npm test`: 67 pass with the computer set to India and to UTC.
- `web/sw.js` version refreshed (`node web/tools/build_sw.js`, needed after any web/ change).
- **Next:** step 3, the import script (`scripts/import_to_supabase.py`) moves old undated website
  workouts to India time while copying; step 4, SQL for rows already in Supabase.

### 2026-11-05 — Item 1, steps 3-4: old website workouts land on the right day
- `scripts/import_to_supabase.py`: `local_workout_time()` moves an old workout whose time isn't
  exactly midnight (undated, stamped by the UTC server) to `LIFTBOOK_TIME_ZONE` (default
  Asia/Kolkata) while copying. Dated ones (midnight) stay. `--dry-run` now reports how many move
  and how many land on a different day.
- **Decided: no separate SQL fix for Supabase.** The import always reads from the old database,
  so rerunning it can't move a workout twice, and it also corrects rows an earlier run copied
  (their `server_updated_at` is bumped, so phones pull the fix on the next sync). A SQL fix run
  on Supabase alone could move rows twice after the switch.
- **Owner's step (not done by me):** before the switch to the new app, run the import once more:
  `python scripts/import_to_supabase.py --dry-run` to see the numbers, then without `--dry-run`.
- Checked on a throwaway local Postgres 16 (one database as the old app, built from `models.py`;
  one as Supabase: `supabase/schema.sql` on top of small stand-ins for `auth.users`,
  `auth.identities`, `auth.uid()`, `storage.*` and the three roles). Dry run, real run, second run
  (nothing moves again), and a row copied by the old script (fixed). New `tests/test_import_times.py`
  (4 pass).
- **Next:** item 1 is done. Item 2 on a new branch `improve/light-contrast` from
  `design/aesthetic-overhaul`.
