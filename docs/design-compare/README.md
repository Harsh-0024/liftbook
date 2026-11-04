# Old app vs new app, screen by screen

Each picture shows the **old** Flask app (app.liftbook.in, left) beside the **new** offline app on
the `design/aesthetic-overhaul` branch (right), with the same 36 made-up workouts in both.

- `desktop/`: a 1280 px wide browser window in dark mode.
- `iphone/`: an iPhone 18 Pro simulator in Safari, light mode.

How they were taken: the old app ran locally with a demo SQLite database; the new app ran against a
local stand-in for Supabase. Neither touched the live site or real accounts.

## What the design pass brought over from the old app

- **Colours and type:** black with gold (`#D4AF37`) and the gold gradient on main buttons, the warm
  linen light theme, Inter for text and Cormorant Garamond for page titles, the soft gold glow
  behind the page. Fonts ship with the app, so it looks right offline too.
- **Header:** uppercase, letter-spaced links with icons and a gold underline on the current page.
  On phones: the "LB" mark, "Liftbook / Workout log", and round gold-ringed buttons.
- **Phone tab bar:** four uppercase tabs, Home, Log, Retrieve, Stats, as before.
- **Grouped rows:** settings, lists and pickers use the old rounded groups with icon, title, grey
  line, value and chevron, and small uppercase section labels.
- **Editors:** Log, plan and feedback have the big text box with a bar under it that says what's
  in the box and holds the main button. On phones the bar stays above the tab bar.

## Screen by screen

| Screen | Desktop | iPhone | What changed in the new app |
| --- | --- | --- | --- |
| Home | [desktop](desktop/home.jpg) | [iphone](iphone/home.jpg) | Same greeting, name, Log / Retrieve buttons, recent workouts and three number tiles. Adds "Today's workout" when today is already logged. |
| Log | [desktop](desktop/log.jpg) | [iphone](iphone/log.jpg) | Same editor and save bar. Adds a live "Check" list of what it read, a warning when that day already has a workout, and a "How to write sets" guide. |
| Retrieve | [desktop](desktop/retrieve.jpg) | [iphone](iphone/retrieve.jpg) | Same cycle tiles, four to a row (two on phones). The session after your last one is marked "Next". |
| Custom workout | [desktop](desktop/retrieve-custom.jpg) | – | Same muscle-group list and "Your workout" panel. Groups open in place; a phone gets a sticky "Get targets" bar. |
| Stats | [desktop](desktop/stats.jpg) | [iphone](iphone/stats.jpg) | Same "+X% stronger" hero and gold line chart. Charts are drawn at the screen's width, so the labels stay readable on phones. |
| All workouts | [desktop](desktop/history.jpg) | [iphone](iphone/history.jpg) | Same list by month with date and weekday. Shows how many workouts each month has; search also finds exercises. |
| Workout | [desktop](desktop/workout.jpg) | [iphone](iphone/workout.jpg) | Same layout. Each exercise is compared with last time and with your best, with a medal for a new best. |
| Settings | [desktop](desktop/settings.jpg) | [iphone](iphone/settings.jpg) | Same profile row and grouped sections. Adds bodyweight and appearance right on the page. |
| Account | [desktop](desktop/settings-account.jpg) | [iphone](iphone/settings-account.jpg) | Email, password, a Dark / Light / Auto switch, sign out and delete. |
| Sync and data (old: Integrations / Data) | [desktop](desktop/settings-sync.jpg) | [iphone](iphone/settings-sync.jpg) | New: sync status, backup file, spreadsheet export. AI keys moved to the Coach page. |
| Shortcuts (old: Data) | [desktop](desktop/settings-shortcuts.jpg) | – | Apple Shortcuts set-up. |
| Workout plan | [desktop](desktop/plan.jpg) | [iphone](iphone/plan.jpg) | Same switch rows and plan editor with "Saved" / "Not saved yet". Rep ranges sit on the same page. |
| Feedback | [desktop](desktop/feedback.jpg) | [iphone](iphone/feedback.jpg) | Same four tiles (like, don't like, could be better, idea) and send bar. Adds a list of what you sent and its status. |
| Sign in | [desktop](desktop/signin.jpg) | – | Same single card with the logo, show / hide password, and "Forgot password?" beside the label. |
| Create account | [desktop](desktop/signup.jpg) | – | Same card, fewer fields: no "confirm password" (the eye button shows what you typed). |

## Dark mode on iPhone

[iphone/dark-mode-new.jpg](iphone/dark-mode-new.jpg): ten screens of the new app in dark mode (Home, Log,
Retrieve, Stats, Workout, Settings, plan, Feedback, Coach, custom workout).

## Android

[android/new-app.jpg](android/new-app.jpg): the redesigned debug app on a Pixel 8 emulator (sign-in), then
Home and Retrieve in the emulator's Chrome against the local stand-in server.

## Still different on purpose

- The old phone header had a **Log out** button; the new one has a sync dot, Coach and Settings.
  Sign out is at the bottom of Settings.
- The new app has a **Coach** page (AI answers about your training) that the old app did not.
- The old public home page for signed-out visitors isn't in the new app yet; it opens on sign-in.
