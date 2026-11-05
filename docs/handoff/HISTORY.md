# History book: improvements work

Newest at the bottom. Each entry: what was done, the branch and commit, what's next.
Read `CONTEXT.md` (same folder) first.

## Branches of this work
| Item | Branch | Started from | State |
| --- | --- | --- | --- |
| 1. Today / time zone | `improve/one-clock` | `design/aesthetic-overhaul` @ 9076371 | in progress |
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
