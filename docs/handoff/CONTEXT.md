# Context book: improvements work (for picking up in another chat)

Paste this file and `HISTORY.md` (same folder) into a new chat to carry on. Everything a new
helper needs is here; the history says what's done and what's next.

## The owner's instructions (keep to these)
- Look first, plan in simple words, wait for "go" before building. (Given for items 1-4 below.)
- Never work on `main` (it's the old website, going away). Start each new branch from the top of
  the newest app branch: **`design/aesthetic-overhaul`** (check with `git fetch` and
  `git log origin/design/aesthetic-overhaul -1` that it's still the newest main line).
- Commit in sensible steps and push after each commit. Never delete branches.
- Test what's built, show it working, say plainly what couldn't be checked.
- Simple language, no jargon. Update this book and `HISTORY.md` after every step, and push.
- Don't touch live data (Supabase project, app.liftbook.in, beta.liftbook.in): write scripts/SQL
  for the owner to run.

## What the app is
- **New app (the one being worked on):** `web/` — an offline-first app in plain JavaScript (no
  framework, no build step). It keeps your data on the device and syncs with **Supabase**.
  The same files run as the website and inside the **Android app** (Capacitor 8, `android/`,
  `web/app/native.js`). Planned next: Mac and Windows apps and the Android web app.
  - `web/core/` — the workout logic (parser, plans, stats, retrieve...), ported from Python;
    tests compare it with the Python app (`web/core/test`, fixtures from `scripts/make_core_fixtures.py`).
  - `web/app/` — screens (`screens/*.js`), data layer (`data.js`), device store and sync
    (`store.js`, `sync.js`), Supabase client, `ui.js` helpers. `web/styles.css` — all styles.
  - `supabase/schema.sql` — tables. `workout_logs.date` is "the person's own clock time, no time
    zone". `supabase/functions/` — AI coach and Apple Shortcut server functions (Deno).
  - `scripts/import_to_supabase.py` — copies the old database (Neon) into Supabase. Rerun until
    the switch to the new app; not after.
  - `IMPROVEMENTS.md` — the owner's log of earlier overnight work.
- **Old app:** Flask (`app.py`, `liftbook/`, `templates/`, `services/`) on `main`, live at
  app.liftbook.in. Still in the folder; not to be changed.
- Tests: `npm test` (Node 20+). Was 63 passing at the start.
- Serve locally: `python3 web/tools/serve.py` (port 8765). A local stand-in for Supabase is used
  by the tests: `web/app/test/fake_server.js`.

## The four improvements asked for
1. **"Today" / time zone.** Rule: a workout's saved time is the phone's clock time.
2. **Gold text in light mode** readable (4.5:1), keep the look; fix other inconsistencies.
3. **Reminders**: after the usual number of days without training, and for a planned workout at a
   day and time. Off by default, one switch, quiet hours in Settings.
4. **Home-screen widget**: today's planned session, what to aim for, quick Log.

## Decisions so far
- Items 3 and 4 on the **Android app** first (phone's own notifications, a native Android widget).
  Android web app: no widget (long-press icon shortcuts instead); web notifications later.
  Mac widgets need a native Swift app (not possible with a web-based desktop app); Windows widgets
  not practical. Told to the owner.
- Order: 1, then 2, then 3, then 4. One branch per item, each from `design/aesthetic-overhaul`
  (item 4 builds on item 3's "planned workouts", so it starts from item 3's branch).
- An earlier branch, `harsh024/affectionate-brown-l39qhv`, changed the **old Flask app** by
  mistake (time zone, gold contrast). Not to be used; left in place (never delete branches).

## Open questions for the owner (not answered yet)
- How will the Mac and Windows apps be made (Electron, Tauri, or the web app installed from
  Chrome/Edge)? Decides what reminders can do there.
- Is an iPhone version still planned?

## Findings that the work is based on
- **Item 1:** Stats (`web/core/stats.js`, `DEFAULT_TZ_OFFSET_MINUTES = 330`) adds 5h30 to every
  saved time, though new workouts are already saved in phone time. So an undated workout saved
  after 6:30 pm shows on the right day in History but the next day in Stats. Old website workouts
  copied from Neon kept the old server's UTC time: one saved between midnight and 5:30 am (India)
  sits on the previous day. Home's "this week" (`data.js overview()`) and Stats' 1M/3M start
  (`screens/stats.js since()`) use UTC days. The Shortcut function already uses India time.
- **Item 2:** `web/styles.css` already has `--gold-text: #8a6512` in light mode (passes). Still
  failing: white text on gold buttons (`--on-gold: #fff`, ~3.2:1), `--subtle: #737373` on page
  backgrounds (4.1-4.3:1), zero counts at opacity 0.55. The light colours are written twice
  (`@media (prefers-color-scheme: light)` and `:root[data-theme="light"]`); both must change together.
- This cloud machine has no Android SDK: Android parts can be written here but must be built and
  tried on the owner's Mac (`npm run android:debug`, see `android/README.md` on `feature/phase-6-android`).
