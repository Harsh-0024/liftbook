# History book: improvements work

Newest at the bottom. Each entry: what was done, the branch and commit, what's next.
Read `CONTEXT.md` (same folder) first.

## Branches of this work
| Item | Branch | Started from | State |
| --- | --- | --- | --- |
| 1. Today / time zone | `improve/one-clock` | `design/aesthetic-overhaul` @ 9076371 | done |
| 2. Light-mode gold | `improve/light-contrast` | `design/aesthetic-overhaul` @ 9076371 | done |
| 3. Reminders | `feature/reminders` | `design/aesthetic-overhaul` @ 9076371 | done (phone check pending) |
| 4. Widget | `feature/widget` | `feature/reminders` @ b8e1872 | in progress |

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

### 2026-11-05 — Item 2: light mode readable everywhere (branch `improve/light-contrast`)
- New branch `improve/light-contrast` from `design/aesthetic-overhaul` @ 9076371 (books copied in).
- `web/styles.css` (both copies of the light colours, `@media (prefers-color-scheme: light)` and
  `:root[data-theme="light"]`): `--on-gold` #fff -> #1a1a1a (dark text on gold buttons and the
  on/off tabs, as dark mode does; white was 2.3-3.2:1), `--subtle` #737373 -> #6b6b6b (4.5:1+ on
  every light surface). Zero counts (`.nums .zero b`) opacity 0.55 -> 0.8, both themes (3:1+).
  `--gold-text` (#8a6512) already passed: no change.
- New `web/tools/contrast_check.cjs`: opens every screen against an in-browser stand-in for
  Supabase (made-up workouts), lists text below the guideline, saves screenshots. Needs
  Playwright. Before: 8 kinds of faint text in light mode, 1 in dark. After: 0 and 0. Dark-mode
  screenshots identical except the zero count. Picture:
  `docs/design-compare/light-contrast-before-after.jpg`. `npm test`: 63 pass.
- Not checked: real phones; the charts' lines (drawn shapes, not text).
- **Next:** item 3, reminders, on a new branch `feature/reminders` from `design/aesthetic-overhaul`.
  First look at how to add the Capacitor Local Notifications plugin and where a "planned
  workouts" table fits (schema, tables.js, sync).

### 2026-11-05 — Item 3, step 1: the reminder rules (branch `feature/reminders`)
- New branch `feature/reminders` from `design/aesthetic-overhaul` @ 9076371 (books copied in).
- **Decided:** reminder settings and planned workouts are kept in the synced `app_settings` row
  (`json.reminders`, `json.planned_workouts`), like `stats_range`: no Supabase change for the
  owner to run, no new sync code, and they follow the person to every device.
- `web/core/reminders.js` (no device parts): `upcomingReminders({ now, workoutDays, settings,
  planned })` gives every notification to schedule for the next 14 days.
  - Gap: the usual gap = median days between workouts in the last 8 weeks (needs 3 gaps; else
    3 days; or a number set by hand). Reminder at 09:00 the morning after the usual gap has
    passed; if still nothing, once more the next morning, then quiet (no nagging).
  - Planned: once on a date or weekly on a weekday, 30 min before; skipped if that day already
    has a workout.
  - Quiet hours (default 22:00-07:00, may run past midnight): a reminder inside them moves to
    when they end, or is dropped if that would be after the workout starts.
  - `notificationId(key)`: a stable whole number per reminder (Android needs one).
- `web/core/test/reminders.test.js`: 8 tests. `npm test`: 71 pass.
- **Next (step 2):** add `@capacitor/local-notifications@8.3.1`; in `web/app/native.js` a
  `scheduleReminders(list)` that asks permission and replaces Liftbook's pending notifications;
  call it on start, resume, after sync and after saving a workout or settings; tapping a planned
  reminder opens Retrieve for that session. Then step 3: Settings > Reminders page.

### 2026-11-05 — Item 3, step 2: the Android app sets the reminders on the phone
- `@capacitor/local-notifications` ^8.3.1 added (package.json; lockfile: only the plugin's 10
  lines, kept in the owner's npm format; `npx cap sync android` updated
  `android/capacitor.settings.gradle` and `android/app/capacitor.build.gradle`). The plugin
  brings the Android permissions itself (post notifications, exact alarms, restore after a restart).
- Notification icon `android/app/src/main/res/drawable/ic_stat_liftbook.xml` (a one-colour
  dumbbell) and gold accent, set in `capacitor.config.json` (`plugins.LocalNotifications`).
- `web/app/data.js`: `reminders()`, `setReminders(fields)`, `plannedWorkouts()`,
  `savePlannedWorkouts(list)`, `upcomingReminders(now)`.
- `web/app/native.js`: `remindersSupported` (Android app only), `reminderPermission({ ask })`,
  `scheduleReminders(list, idOf)` (cancels Liftbook's pending ones, sets the new list; other
  apps' untouched; nothing without permission), `onReminderTap(open)`.
- `web/app/main.js`: reminders worked out again 1.5 s after any data change (here or synced),
  at start and when the app comes back to the front; cleared on sign-out; a tapped reminder
  opens Retrieve (planned) or Log (gap).
- Tests: `web/app/test/reminders_native.test.js` (stand-in plugin), `reminders_data.test.js`.
  `npm test`: 75 pass. **Not checked: a real phone** (no Android SDK here).
- **Next (step 3):** Settings > Reminders page: the switch (asks Android's permission when turned
  on; on the website says it works in the Android app), quiet hours, usual gap (Auto shows the
  worked-out number), and planned workouts (add: once on a date or weekly; time; session from the
  plan; delete). Add the row in Settings under Training.

### 2026-11-05 — Item 3, step 3: Settings > Reminders page
- `web/app/screens/settings.js`: new section `reminders` (row "Reminders · On/Off" under
  Training). The switch (on the Android app it asks Android's permission first; if refused it
  stays off and says where to allow it; on the website it saves and says reminders show in the
  Android app), a "Next: Fri 6 Nov, 09:00 · ..." line, "Remind me after" (Usual (N days) or 1-14),
  quiet hours (two time boxes), planned workouts (list with remove; add: workout from the plan or
  "Any workout", Once on a date / Every week on a weekday, time).
- A tapped planned reminder opens that session's targets (`retrieve/day/<category>/<id>`).
- `web/styles.css`: time boxes get the same style as other inputs. Bell icon in `ui.js`.
- **Decided:** this branch doesn't depend on `improve/one-clock`; a small `todayHere()` in
  settings.js instead of `deviceDay()`. When both are merged, `todayHere` can become `deviceDay`.
- Checked in Chromium (phone size, light and dark) against the stand-in: switch on, add a weekly
  plan, the list, the Next line, Settings row "On", no errors. Picture:
  `docs/design-compare/reminders-page.jpg`. `npm test`: 75 pass.
- **Not checked:** on a real Android phone (permission prompt, notifications arriving, tap
  opening the page). To try: `npm run android:debug`, install, Settings > Reminders, switch on,
  plan a workout ~35 minutes ahead, lock the phone.
- **Next:** item 3 is done apart from that phone check. Item 4: widget on a new branch
  `feature/widget` from `feature/reminders` (it shows the planned workout).

### 2026-11-05 — Item 4, step 1: what the widget shows (branch `feature/widget`)
- New branch `feature/widget` from `feature/reminders` @ b8e1872.
- `web/app/data.js`: `widgetSummary(now)` -> `{ heading, title, lines: [{ name, aim }], more,
  route, updated }`. Today's planned workout ("Today · 18:30", "Today · logged" once a workout is
  saved that day) or else the next session ("Next"); up to 4 exercises with the last sets to
  beat (`sets_label` from Retrieve) or the target for a new one ("2 × 6–10"); route opens that
  session's targets, or Log when there's no plan.
- The "next session" rule moved from `screens/retrieve.js` into `data.js` (`nextSessionId()`,
  `sessionIds()`): Retrieve and the widget use one copy.
- `web/app/test/widget_data.test.js` (3 tests). `npm test`: 78 pass.
- **Next (step 2):** the native Android part: a small Capacitor plugin in `android/app/src/main/java/in/liftbook/app/`
  (`WidgetBridge`, saves the summary as JSON in SharedPreferences and refreshes the widget),
  `LiftbookWidget` (AppWidgetProvider + RemoteViews layout `res/layout/widget_liftbook.xml`,
  info `res/xml/liftbook_widget_info.xml`), registered in `MainActivity` and the manifest. Taps
  open `in.liftbook.app://open#/<route>`; "Log" opens `#/log`. Then `native.js` `updateWidget()`
  called with the reminders refresh.
