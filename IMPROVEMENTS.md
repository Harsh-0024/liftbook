# Improvements log

Work done overnight on the new offline app (`web/`), on branches only. Nothing here touched `main`,
`rewrite/offline-app`, app.liftbook.in, beta.liftbook.in or any live data. You choose what to keep.

## How to try a branch

1. Get the branch into a folder:

   ```bash
   git -C ~/Desktop/Projects/Workout_Logger fetch origin
   ```

   ```bash
   git -C ~/Desktop/Projects/Workout_Logger worktree add ../liftbook-try origin/design/aesthetic-overhaul
   ```

2. Serve `web/` and open it:

   ```bash
   cd ~/Desktop/Projects/liftbook-try/web && python3 -m http.server 8080
   ```

   Then open [localhost:8080](http://localhost:8080/). It signs in to the real Supabase project,
   so use your own test account.

Preview links: Cloudflare Pages doesn't build these branches (a branch address such as
`design-aesthetic-overhaul.liftbook-beta.pages.dev` gives 404), so there are no preview links yet.
Turning on branch previews in the Cloudflare Pages project would give one per branch.

## Done

### 1. Design pass: the new app looks and feels like the old one
- **Branch:** `design/aesthetic-overhaul` (from `feature/phase-6-android`)
- **What:** the old app's black and gold look, fonts, header, phone tab bar, grouped rows and
  editors on every screen: Home, Log, Retrieve, custom workout, Stats, All workouts, Workout,
  Settings and its pages, plan, feedback, sign in and create account. Charts are drawn at the
  screen's width so their labels stay readable on phones.
- **Proof:** side-by-side screenshots of every screen, desktop and iPhone, in
  [docs/design-compare/](docs/design-compare/README.md).
- **Checked:** `npm test` (50 pass), desktop Chrome, iPhone 18 Pro simulator (light mode),
  `npm run android:sync` and a debug build (`./gradlew assembleDebug` with Java 21; the APK builds).
  Dark mode checked on the iPhone too ([picture](docs/design-compare/iphone/dark-mode-new.jpg)).
  Installed on the Pixel 8 emulator too; sign-in, Home and Retrieve look right
  ([picture](docs/design-compare/android/new-app.jpg)). No real account was used.

### 2. Plan page extras from the old app
- **Branch:** `improve/plan-extras` (from `design/aesthetic-overhaul`), commit 6c6adb5
- **What:** a "Copy and edit" row that makes the shared plan (or the built-in one) your own and
  stops following, asking first if it would replace a plan you wrote. A "Format" link beside the
  Plan label opens a short guide on how to write the plan. While you follow the shared plan, the
  editor is replaced by a note saying so.
- **Also (commit 6d374ca):** the same "Copy and edit" for rep ranges, and a note in place of the
  rep ranges box while you follow the shared ones. Each Copy row sits under its own switch.
- **Try it:** as above, with `origin/improve/plan-extras`, then Settings, Workout plan.
- **Checked:** `npm test` (50 pass); desktop Chrome and the iPhone simulator (switch, copy, format,
  rep ranges copy).

### 3. Small polish
- **Branch:** `improve/polish` (from `design/aesthetic-overhaul`), commit af2fa73
- **What:** Sync and data is now grouped rows like the rest of Settings (sync status with "Sync now",
  backup file, spreadsheet with dates). Create account shows a "8+ characters" check that turns
  gold as you type; only that rule, since it's the only one the server enforces.
- **Try it:** as above, with `origin/improve/polish`, then Settings, Sync and data, or Create account.
- **Checked:** `npm test` (50 pass); desktop Chrome and the iPhone simulator.

### 4. Search an exercise on Stats
- **Branch:** `improve/stats-search` (from `design/aesthetic-overhaul`), commit 2961601
- **What:** a "Search an exercise" box at the top of Stats, as the old page had. Pick a suggestion
  or type part of a name and press return: the Exercise card switches to it and scrolls into view.
  An unknown name says so.
- **Try it:** as above, with `origin/improve/stats-search`, then Stats.
- **Checked:** desktop Chrome (full name, part of a name, unknown name) and the iPhone simulator
  (typed "row", return, Barbell Row opened).

### 5. Select several workouts to delete
- **Branch:** `improve/history-select` (from `design/aesthetic-overhaul`), commit a9995e1
- **What:** a "Select" button on All workouts, as the old list had. Tap workouts to tick them; a
  bar shows how many, "Select all" (or "Clear") for what the search shows, and Delete, which asks
  first. Cancel or Escape leaves without changes.
- **Also (commit 3963caa):** a "Delete several workouts" row in Settings, under Data and connections,
  opens the list ready to pick, with Back going to Settings. On phones the bar stays on one line.
- **Also (commit a8b5569):** after deleting one workout or several, the message at the bottom has
  an Undo button for 8 seconds; it brings the same workouts back on every device.
- **Also (commit 0de8d99):** a long history is drawn 60 workouts at a time, with "Show 60 more"
  at the bottom (and "Show the last N" at the end). Month counts, search and Select all still cover
  every workout. See "Checked: speed with a long history" below.
- **Try it:** as above, with `origin/improve/history-select`, then Home, See all workouts, or
  Settings, Delete several workouts.
- **Checked:** `npm test` (50 pass); desktop Chrome (pick, search plus select all, clear, delete)
  and the iPhone simulator (select, tick, bar above the tab bar, cancel).

### Fix on the design branch: Stats tiles cut off on phones
- **Branch:** `design/aesthetic-overhaul`, commit 23ecfcd
- "Since first" showed "+45.8%" cut off on an iPhone. Percentages from 10% up are now whole
  numbers ("+46%", as the big number above already was), and tile numbers shrink a little on phones.

### 6. Remove your profile photo
- **Branch:** `improve/profile-photo` (from `design/aesthetic-overhaul`), commit 279e584
- **What:** a "Remove" button beside "Change photo", shown only when you have a photo, as the old
  Account page had. It asks first, takes the photo off your profile, then deletes the file.
- **Try it:** as above, with `origin/improve/profile-photo`, then Settings, your name at the top.
- **Checked:** `npm test` (50 pass); desktop Chrome against the local stand-in (upload, remove: the
  file is gone from storage and the letter comes back) and the iPhone simulator (both buttons).

### 7. Bulk import: paste many workout days at once
- **Branch:** `improve/bulk-import` (from `design/aesthetic-overhaul`), commits 7e29a5c, b8aef70
- **What:** Settings, Bulk import, as the old Data page had. Paste days that each start with a date
  ("03/02 Back", "Monday 28/9 Push", "2025-02-03 Legs"). A check under the box shows each day as
  Ready, Already in or Failed, with how many exercises and sets, and "year guessed" where you didn't
  write one; "Import N days" saves the ready ones. A missing year is worked out the way the old page
  did (`web/core/bulk.js`, checked against the old Python code on the same inputs).
- **Decided:** one change from the old page: a day that would land in the future (for example
  "1/9" after "6/9/26" rolls to next year) is marked Failed instead of imported.
- **Try it:** as above, with `origin/improve/bulk-import`, then Settings, Bulk import.
- **Checked:** `npm test` (54 pass, 4 new); desktop Chrome against the local stand-in (check, import,
  the workout opens) and the iPhone simulator (typing, the check list).

### 8. Turning bodyweight off asks about old logs
- **Branch:** `improve/bodyweight-off` (from `design/aesthetic-overhaul`), commit cb02ab4
- **What:** as on the old page, turning Bodyweight off for an exercise that has logs counting it
  opens a question in place: "Only from now on", "Keep old logs as BW + number" or "Read old logs
  as plain weight", with Apply and Cancel. The logs' best-set numbers are worked out again.
- **Try it:** as above, with `origin/improve/bodyweight-off`, then Settings, Exercises, Pull Ups.
- **Checked:** `npm test` (51 pass, 1 new covering all three answers); desktop Chrome against the
  local stand-in (cancel, then "plain weight": all 12 Pull Ups logs changed and synced) and the
  iPhone simulator (the question).

### Fix on the design branch: Pull Ups showed "Weight and reps"
- **Branch:** `design/aesthetic-overhaul`, commit f97c1cc
- Built-in bodyweight exercises (pull-ups, dips…) showed the Bodyweight switch off on the
  Exercises page, though the app counts them. The switch and the line under the name now say what
  the app really does.

### Fix on the design branch: messages at the bottom sat off-centre
- **Branch:** `design/aesthetic-overhaul`, commit 6eab8d0
- The short messages ("Workout saved.") started at the middle of the screen and ran to the right,
  wrapping early on phones: their slide-in animation cancelled the centring. They're centred now.

### Fix on the design branch: iPhone zoomed in when you tapped a text box
- **Branch:** `design/aesthetic-overhaul`, commit c81a927
- Log, plan, feedback and other big boxes used 15px text, so iPhone Safari zoomed the page in on
  tap. On phones they're 16px now and the page stays put.

### Exercises and Profile pages in grouped rows
- **Branch:** `design/aesthetic-overhaul`, commit 026f5cf
- **What:** these two pages were still plain cards. Exercises now lists one row per exercise with
  its kind ("Weight and reps", "Timed", "Bodyweight added") and how often it's logged; tap a row to
  open its Timed and Bodyweight switches and a rename box in place. Renames show as a list with
  Undo. Profile has a photo row and an "About you" group with a Save bar.
- **Checked:** `npm test` (50 pass); desktop Chrome (open a row, switch on and back off, save the
  profile) and the iPhone simulator (both pages).

### Checked: dark mode on tonight's pages
On the iPhone simulator in dark mode: Exercises (an open row with its switches), the
"Turning off Pull Ups" question, and Bulk import. Text, borders, the picked answer and the dimmed
Import button all read clearly; nothing needed changing.

### 9. Exercise name suggestions while you type
- **Branch:** `improve/log-suggest` (from `design/aesthetic-overhaul`), commit d309797
- **What:** as on the old Log page: type two or more letters at the start of a line (not the
  title, not a sets line) and up to six names you've logged or have in your plan appear under that
  line, those starting with what you typed first. Arrow keys move, Tab or a tap picks, Escape
  closes; a rep range after the name stays. On Log and Edit workout.
- **Also (commit 5c8a1e3):** the check under the Log box says which names are new ("New
  exercise"), and for a typo of a name you know, "Did you mean Flat Barbell Press?" with a Use it
  button that fixes that line; "A1 Zercher Squat" is read as Zercher Squat. An exercise typed twice
  ("Also at no. 1") or already in that day's workout says so. Same rules as the old check
  (`services/log_check.py`), and its own test cases give the same answers.
- **Try it:** as above, with `origin/improve/log-suggest`, then Log, a new line under the title.
- **Checked:** `npm test` (55 pass, 4 new); desktop Chrome (title and sets lines get none, arrows,
  Tab, tap; Use it with blank lines above the title) and the iPhone simulator (the list under the
  line, tapping a name keeps the keyboard up; the "Did you mean" note and Use it).

### Faster pages with a long history
- **Branch:** `design/aesthetic-overhaul`, commit 64ab6e2 (also merged into `improve/history-select`)
- **What:** each page asked for the whole sorted history 3 to 5 times, and with 3,000 logs each
  ask cost about 15 ms. The app now keeps the sorted history and the list of workouts until a log
  changes, here or from another device. On the 600-workout stand-in: a workout opens in 28 ms
  (was 83), Retrieve 19 (41), All workouts 19 (40), Coach 16 (56). Stats stays near 100 ms: most of
  that is working out overall strength, which is needed each time.
- **Checked:** `npm test` (51 pass on design, 52 on history-select; a new test checks the kept list
  follows changes made here, synced in, and deletes) and the iPhone simulator (a workout page).

### Fix on the design branch: a synced change no longer clears your search
- **Branch:** `design/aesthetic-overhaul`, commits 61b52f1, 7a9ce68; and `improve/history-select`,
  commit c6940eb
- When another device's changes arrived, All workouts and Retrieve were drawn again from scratch:
  the search box emptied and the cursor left it mid-word. Now what you typed, and the cursor, stay.
  On `improve/history-select`, All workouts also keeps the pages you opened with "Show more", and
  Select mode with what you ticked. Opening the page fresh still starts empty.
- **Checked:** `npm test` (50 and 51 pass); desktop Chrome on the 600-workout stand-in (search,
  cursor, 120 rows open, 2 ticked: all kept through a redraw; a fresh visit starts at 60) and the
  iPhone simulator (typing a search).

### Keyboard and screen readers
- **Branch:** `design/aesthetic-overhaul`, commit bee5c26
- **Checked first:** on every page, all buttons, links and fields have names; switches are real
  switches; focus rings show for the keyboard; messages and the check under the Log box are read out;
  charts have a label. Nothing to fix there.
- **Fixed:** every page was titled "Liftbook"; now each has its own ("Stats · Liftbook"), which
  also shows in the browser's tabs and history. Moving to a new page puts focus on its heading, so a
  screen reader says where you are, as it would on a full page load. The tab bar marks the page
  you're on. A "Skip to content" link appears when you press Tab first.
- **Checked:** `npm test` (50 pass); desktop Chrome (titles, focus after each tab, a redraw keeps
  focus, typing in a search box keeps focus, skip link) and the iPhone simulator (no ring on the
  heading, the page doesn't move).

### Checked: speed with a long history
A stand-in account with 600 workouts (3,000 logs, three years). On this Mac every data step
(history, stats, charts, retrieve, the spreadsheet) takes under 25 ms, and Home, Stats, Exercises
and Retrieve open in under 100 ms. All workouts was the one page that grew with the history: it
built all 600 rows (6,200 elements). Now it opens with 60, in 40 ms, on `improve/history-select`.

### Checked: Android
Stats in the Pixel 8 emulator's Chrome looks right. Its header leaves out the "Workout log" line
because the emulator's display size makes the screen 360 points wide; under 380 the app hides it
on purpose.

### Dropped: signed-out public home page
The old app never had one: its `/` sent signed-out people to sign in, which the new app already
does. The empty branch `improve/public-home` is left as it is (branches are never deleted).

### Checked: old Settings rows against the new Settings
Every row of the old Settings, Account, Data, Integrations and bodyweight pages. Already in the new
app: profile, bodyweight, appearance, plan, rep ranges, bodyweight and timed exercises, renames,
spreadsheet export with dates, a backup file, AI keys (on Coach), Apple Shortcuts, feedback, admin,
email, password, sign out, delete account. Still missing, now queued below:
- "Delete several workouts" (old Data page).
- "Bulk import: paste many workout days at once" (old Data page).
- "Remove photo" on the profile (the new app can only change it).
- When you turn bodyweight off for an exercise that already has logs, the old app asked how to read
  the old numbers; the new one doesn't ask.
- The Exercises and Profile pages still use the plain cards, not the grouped rows.
Left out on purpose: "current password" to change the password (Supabase signs you in already)
and JSON export with dates (the backup file keeps everything).

## Ideas queued (next ones first)
- Log page: tidying pasted text, as the old page did.
- Sign-up "Confirm password" box: left out on purpose (the eye button shows what you typed).

## Open questions for you
- Public share links for a workout (the old `share_workout` page): the new app shares a workout as
  text through the phone's share sheet. A link anyone can open needs a new Supabase table and
  access rules, which I won't add to the live project without you. Say if you want it.
- "Keep me signed in" (old sign-in page): the offline app always stays signed in on that device,
  so I left it out. Say if you want it back, for shared computers.
