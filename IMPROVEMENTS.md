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
- **Try it:** as above, with `origin/improve/history-select`, then Home, See all workouts.
- **Checked:** `npm test` (50 pass); desktop Chrome (pick, search plus select all, clear, delete)
  and the iPhone simulator (select, tick, bar above the tab bar, cancel).

### Fix on the design branch: Stats tiles cut off on phones
- **Branch:** `design/aesthetic-overhaul`, commit 23ecfcd
- "Since first" showed "+45.8%" cut off on an iPhone. Percentages from 10% up are now whole
  numbers ("+46%", as the big number above already was), and tile numbers shrink a little on phones.

### Checked: Android
Stats in the Pixel 8 emulator's Chrome looks right. Its header leaves out the "Workout log" line
because the emulator's display size makes the screen 360 points wide; under 380 the app hides it
on purpose.

### Dropped: signed-out public home page
The old app never had one: its `/` sent signed-out people to sign in, which the new app already
does. The empty branch `improve/public-home` is left as it is (branches are never deleted).

## Ideas queued (next ones first)
- Go through every old Settings row and list anything the new Settings still lacks.
- A "Delete several workouts" row in Settings that opens All workouts ready to select, as before.
- Sign-up "Confirm password" box: left out on purpose (the eye button shows what you typed).

## Open questions for you
- "Keep me signed in" (old sign-in page): the offline app always stays signed in on that device,
  so I left it out. Say if you want it back, for shared computers.
