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
- **Try it:** as above, with `origin/improve/plan-extras`, then Settings, Workout plan.
- **Checked:** `npm test` (50 pass); desktop Chrome and the iPhone simulator (switch, copy, format).

### 3. Small polish
- **Branch:** `improve/polish` (from `design/aesthetic-overhaul`), commit af2fa73
- **What:** Sync and data is now grouped rows like the rest of Settings (sync status with "Sync now",
  backup file, spreadsheet with dates). Create account shows a "8+ characters" check that turns
  gold as you type; only that rule, since it's the only one the server enforces.
- **Try it:** as above, with `origin/improve/polish`, then Settings, Sync and data, or Create account.
- **Checked:** `npm test` (50 pass); desktop Chrome and the iPhone simulator.

### Dropped: signed-out public home page
The old app never had one: its `/` sent signed-out people to sign in, which the new app already
does. The empty branch `improve/public-home` is left as it is (branches are never deleted).

## Ideas queued (next ones first)
- "Keep me signed in" choice on sign-in, as the old one had (decide if the offline app needs it).
- Stats on Android in the emulator, checked properly (it was still loading in the last check).
- Exercise search inside the overall Stats card, as the old Stats page had.
