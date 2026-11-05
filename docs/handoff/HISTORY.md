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
