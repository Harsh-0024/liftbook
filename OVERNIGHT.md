# Overnight work log (branch `improve/round-3`)

Started 17 Nov 2026 from `rewrite/offline-app` (ef5ac4c). Nothing here touched `main`,
`rewrite/offline-app`, beta.liftbook.in, app.liftbook.in, Supabase or any live data. Cloudflare
only builds `rewrite/offline-app`, so this branch is not live anywhere. You choose what to keep.

To look at it (signs in to the real Supabase project, so use your own test account):

```bash
cd ~/Desktop/Projects/liftbook-overnight/web && python3 -m http.server 8080
```

Then open [localhost:8080](http://localhost:8080/).

## Done

1. **The three "small leftovers" from To Be Done**
   - **All workouts:** a title written as "Session 2 - Legs" shows as "Legs", with "Session 2 ·"
     in front of its exercises, as the old list did. Search still matches the full title.
   - **Log page check list:** rows are numbered 1, 2, 3 and say "3 sets" (or "New") on the right,
     as the old check did. Tapping a row puts the cursor on that exercise's line in the box.
   - **Settings, Exercises:** plan exercises you haven't logged yet are listed too ("In your
     plan"), so one can be set as timed or bodyweight before its first workout. Rename only
     shows for exercises with logs.
2. **Log page message:** an exercise name with nothing under it said `couldn't read its sets ("")`.
   It now says `no sets under it`.

Checked: `npm test`, desktop browser against the local stand-in server (made-up data).

3. **Home: the last 7 days.** A strip of the last
   7 days with a gold tick on each day trained (a tap opens that workout), the middle tile now
   says "Week streak" (weeks in a row with a workout), and Recent shows "Session 2 - Legs" as Legs with the session under it.
   The logic (`web/core/week.js`) has tests. Checked on desktop (dark) and the iPhone simulator (light).

4. **Personal bests page** (Stats, "Personal bests", or `#/stats/bests`). Every exercise with its
   best estimated max, the day it was first reached, its top set, and whether you are at that
   best now or how far under. "New" marks a best from the last 30 days. Search, and sort by
   latest, highest or A to Z. A row opens that exercise's chart. Logic in `web/core/bests.js`
   with tests. Checked on desktop (dark) and the iPhone simulator (light).

5. **Workout page: older and newer.** Under a workout, two links go to the workout before it
   and the one after it (name and date), so you can walk through them without returning to
   the list. On a computer the ← and → keys do the same (listed under "?"). Checked on desktop.

6. **Stats: bodyweight.** A card at the bottom of Stats charts your bodyweight over the chosen
   range, with what it is now, the change, and the lowest to highest. It reads the bodyweight
   already saved with every workout, so there is nothing new to enter, and it only appears
   once two different weights exist. Logic in `web/core/weight_trend.js` with tests.
   Checked on desktop (the made-up data has a single change, so the line is one step).

7. **Home: up next.** When your plan has sessions and the last workout named one, Home shows
   the session that comes next ("Back & Triceps · Session 3 · 8 exercises"); a tap opens its
   targets in Retrieve. It hides once today's workout is logged. Retrieve's own "Next" mark
   now uses the same logic (`nextSessionId` in `web/core/sessions.js`, tested).
   Checked on desktop and the iPhone simulator.

8. **Custom workout: arrange a group yourself** (idea 9 in "Ideas for later"). An opened
   muscle group has an "Arrange" button: tap an exercise to move it between "On top" and
   "Less often". Your placing wins over what your history says, shows as "placed by you",
   and "Back to automatic" undoes a group. It is saved with your other settings
   (`often_pins`), so it follows you to every device; no database change was needed.
   Checked on desktop against the stand-in server.

9. **Stats: an exercise's sessions.** Under the chosen exercise's chart and tiles, a list of
   every time you trained it, newest first: the day, the sets as you logged them, and a tap
   to open that workout. The day your best was set wears a "Best" mark. Five show at first;
   "Show all" opens the rest. Checked on desktop.

10. **Stats: muscle balance.** A card showing the average sets a week each muscle group got
    (Chest, Back, Shoulders, Biceps, Triceps, Forearms, Legs, Abs) over the range chosen at
    the top of Stats, as bars, so a skipped group stands out. Groups come from the exercise
    name, the same way the custom workout picker sorts them. Logic in `web/core/balance.js`
    with tests. Checked on desktop and the iPhone simulator (sessions list and bodyweight card too).

11. **All workouts: search by date as you would type it.** The search matched a day only as
    `2026-11-09`. It now also finds "9 nov", "mon 9 nov", "october" or "2026". Checked on desktop.

12. **Workout page: weight lifted.** The line under a workout's title now also says how much
    was lifted in all ("2,340 kg lifted"): weight times reps over every set, bodyweight
    counted where the exercise uses it, timed holds left out. Checked on desktop (added up by
    hand for one workout).

13. **Log: start from your next session.** An empty Log box now has a row above it, "Start
    from Session 3 · Back & Triceps", that fills the box with that session from your plan and
    your last numbers (what Retrieve's "Log" button does, without going through Retrieve). It
    hides as soon as there is text, comes back after Clear, and is not shown on a day that
    already has a workout. Checked on desktop and the iPhone simulator.

14. **Workout page: Repeat.** A "Repeat" button beside Edit opens the Custom workout page
    with that workout's exercises and set counts already picked and its title filled in
    ("Session 2 - Shoulders & Forearms" stays a Session 2). "Get workout" then gives today's
    date and targets from your latest numbers, ready to copy or log. Checked on desktop and the
    iPhone simulator.

15. **Log: a date after today is pointed out.** A typo in the date line ("17/11/27" for
    "17/11/26") used to file the workout a year ahead without a word, out of this week and
    the streak. The check now says "This is dated Wed 17 Nov 2027, after today. Check the year
    on the first line." It doesn't stop the save (Bulk import already refused future days).
    Test added. Checked on desktop and the iPhone simulator (with a little space added under the
    note there).

16. **Retrieve: a day that isn't in the plan.** Opening a Retrieve day that no longer exists (a
    session removed since, an old link) showed the error text as the workout, and its Copy and
    Log buttons passed "Day 'Session 99' not found in plan." on to Notes or the Log box. It now
    says "Session 99 isn't in your plan", with links to pick a day or change the plan.
    Found by opening every screen (and missing-workout, bad-date and unknown-page links): no other
    errors. Checked on desktop and the iPhone simulator.

17. **Custom workout: the title box has a name for screen readers.** A sweep of every screen for
    buttons, links and boxes a screen reader can't name found only this one (VoiceOver read it as
    "text field"). It now reads "Workout title", as on Retrieve days. Muhurta's pages had none.
    Checked on desktop; nothing changes on screen.

18. **Reduce Motion: no slide-ins.** With the phone's Reduce Motion on, screens already stopped
    rising into place, but the toast, the two dialogs, the pick lists and an opened workout's text
    still slid in. The two slide-ins now become plain fades whenever Reduce Motion is on, wherever
    they're used. (Muhurta's leftovers only fade or glow, which Reduce Motion allows.) Checked
    that the browser reads the new rules; the movement itself can't be seen in a screenshot.

19. **Keyboard focus on Home's week strip.** Tabbing to a day in "Last 7 days" only gave it
    hover's faint ring, the same ring today already wears, so on today or a gold (trained) day
    you couldn't see it. Keyboard focus now draws a clear gold ring. A check that focuses every
    control on ten main screens and compares its look found nothing else. Checked with real
    Tab presses on the computer.

20. **Easier to tap on a phone: Stats' chips and the Log check line.** Measuring every button
    and link on the main screens found two that were small for a finger: the chips on Stats
    (Strength / Rate / Consistency, 1M to All, Estimated max / Top weight / Volume, and the
    sorting on Personal bests) were 30 points tall, and the "Nothing to check yet" line under the
    Log box, which opens the check, only 16. On touch screens both are now 40 points tall; on a
    computer nothing changes. Checked on the iPhone simulator.

21. **Editing your plan on an iPhone no longer zooms the page in.** iPhone Safari zooms in on a
    text box smaller than 16px. Phones already got 16px boxes, but the plan editor's own smaller
    size won, so tapping into the plan zoomed in. It is now 16px on phones too (other boxes were
    already fine). Checked on the iPhone simulator.

22. **Usernames and the sign-in email aren't autocorrected on a phone.** The username boxes
    (sign-up, finishing sign-up, Profile) and the sign-in email box skipped capitals but still let
    the phone's autocorrect change what you typed. It's off on them now. Every other box
    already brought up the right keyboard.

23. **All workouts, for a new account.** With nothing logged, the page said "0 workouts logged."
    and then "No workouts yet." beside a search icon, under a search box with nothing to search.
    It now says "Nothing logged yet.", explains the list will fill in, and offers a "Log workout"
    button (as Retrieve does for an empty plan); the search box appears with the first workout.
    Found by signing in to a second, empty stand-in server and reading every screen: Home, Log,
    Stats and Personal bests already read well with no data. Checked on desktop, empty and with
    data.

24. **Home moves on to the new day.** The phone app comes back on the screen it was left on, and
    only redrew it when a sync brought changes. So Home seen last night still marked yesterday
    as "Today" in the week strip the next morning. Now, when the day has turned, a screen that
    only shows data (never one you're typing in) redraws as you come back to the app, or within a
    minute if it stays open past midnight. Checked on the computer by moving the page's clock a
    day ahead: the strip moved on, and nothing redraws on the same day.
25. **Plan and rep-range edits are kept until saved.** Unsaved changes in the two editors were
    lost by a tap on another tab, or when the website reloaded itself for an update while you
    were away copying something. Now they're kept on the device like the Log box's draft, and come
    back with a note and a **Discard** button. A draft only comes back if the saved plan hasn't
    changed since (from another device, or Copy), so it can't undo newer changes. Saving clears
    it, and sign-out now clears every draft on the device (the Custom workout drafts were left
    behind before). Checked on the computer: kept after leaving the screen and after a reload,
    Discard puts the saved plan back, saving clears it, an out-of-date draft is dropped.
26. **Workout edits and feedback are kept until saved too.** The Edit workout screen (title, date
    and the exercises) and the Feedback box now keep unsaved typing on the device the same way.
    An edit comes back with the same note and Discard button, only if the workout hasn't changed
    since; Cancel and Save clear it. Feedback comes back with the kind you picked, and Send clears
    it. The draft code is now one small helper in `ui.js`, shared with the plan editors. Checked
    on the computer: kept after leaving each screen, Discard and Cancel clear it, a stale edit
    draft is dropped, and the plan editors still behave as in item 25.
27. **The "changes are back" note, checked on the iPhone.** On the phone it sat inside the white
    editor card (a box in a box) and Discard wrapped to a second line. It now sits above the card,
    in one line ("Your unsaved changes are back." and Discard), like the admin note above it.
    Discard also put the cursor in the plan, which on a phone opened the keyboard and jumped to
    the plan's last line; it now leaves the box at the top, and only puts the cursor there on a
    computer. Checked on the iPhone simulator (an edit kept through a reload, the note, Discard)
    and on the computer.
28. **Checked: keyboard focus and text contrast (no change needed).** On 11 screens (Home, Log,
    Retrieve, Stats, History, Settings, Plan, Exercises, Feedback, a workout and its Edit), every
    link, button and field shows a focus ring, and all text measures at least 4.5:1 against its
    background (3:1 when large) in both light and dark. Only the words on gold gradient buttons
    couldn't be measured; they're dark on gold. The same sweep found real gaps in Muhurta (its
    items 33 and 34).
29. **The red Delete button in dark mode is readable.** Measured the confirm dialog and the toast
    too (they're only on screen when open): all fine except the filled red button (Delete a
    workout, and others that ask first) in dark mode, white on a light red at 2.8:1. Dark now
    fills it with a deeper red (#dc2626, 4.8:1); light keeps its red (6.5:1).
30. **Checked: every control has a name for screen readers (no change needed).** On 13 screens
    (History in Select mode and the profile page included), every link, button and field has a
    name a screen reader can say, the icon-only buttons through their aria-labels.
31. **Small links are easier to tap.** Measured every tap target at phone width against the
    24px minimum. Under it: "See all workouts" (23px tall), "Full progress →" (22), the Last /
    Best links over a workout's table (14) and Format on the plan page (20). On touch screens each
    now has an invisible area around it, about 40px tall, without anything moving. Checked on the
    iPhone: a tap just below "Format" opens and closes it. The link inside the Stats sentence is
    left as is (links in running text are exempt), and the Log check line already had its 40px
    (item 20).
32. **Checked: every screen fits 320px wide (no change needed).** A small phone, or a computer
    zoomed to 400%: none of the 13 screens scrolls sideways.
33. **Reduce Motion stops the scripted scrolling.** The CSS already calmed its animations when
    Reduce Motion is on, but ten smooth scrolls started by the app's scripts still glided (to the
    Log check, an exercise on Stats, a Retrieve result, the newest coach reply, a field above the
    phone keyboard, the top after a paste): browsers don't apply the setting to those. A small
    helper (`app/motion.js`) now makes each one jump when it's on. Tested both ways; every screen
    still loads.
34. **Section labels are headings for screen readers.** Every screen had a good title and one
    main heading, but the section labels under it ("Up next", "Last 7 days", "Plan", each month in
    History, the Stats sections) were plain text, so a screen reader couldn't jump between them.
    The `h()` helper in `app/ui.js` now marks each label as a level-2 heading; when a label also
    holds a link or button (Recent's "See all", Plan's "Format"), only its words become the
    heading. Checked on Home, Log, History, Stats, Settings, Plan and Coach.
35. **Field hints are read with their fields.** Checked every text box, number, search and list
    on 10 screens for the right phone keyboard and autofill. Most were already right (decimal pad
    for bodyweight, password and email hints on sign-in). Two fixes: the small hint under a field
    (bodyweight's "Used for bodyweight exercises", the sign-up hints) is now tied to that field, so
    a screen reader reads it when the field gets focus (`describe()` in `app/ui.js`, used by both
    `field()` helpers); and the name box on Profile and on the first-run screen now offers your
    name from autofill, as the sign-up page already did.
36. **Keyboard focus stays on a button after it saves.** Checked how messages reach a screen
    reader: the toast, sign-in errors, the Log check and the coach thread were already announced.
    One gap: every button that shows "Working…" (Save, Send, Rename, sign out and the rest, all
    through `busy()` in `app/ui.js`) is switched off while it works, and switching off a focused
    button drops keyboard focus to the top of the page, so the next Tab started over. Focus now
    comes back to the button when it's done, unless the work moved it somewhere else on purpose.
37. **Save stays off once saved.** On Workout plan, Save turns itself off when there's nothing new
    to save, but the "Working…" helper switched every button back on when it finished, so after
    saving it read "Saved" next to a Save button that was on (the same could happen to Delete in
    History and Import). `busy()` now keeps whatever the work decided: Save is off after saving,
    and on again as soon as you type. Tested: save, type, undo the typing.
38. **Checked: extra text spacing fits (no change needed).** With the spacing some readers and
    reading tools add (line height 1.5, wider letters and words, more room after paragraphs), no
    text on 12 screens was cut off or spilled over anything, and no page grew sideways. Checked at
    computer width; the phone build couldn't be checked this way (the simulator's Safari can't
    take the test styles).
39. **Checked: no errors in the console (no change needed).** Opened 24 screens, including a
    workout, its edit page, a plan session, a share link that doesn't exist and an unknown page,
    and watched for script errors, failed promises and console errors: none.
40. **App icons are 36 KB smaller, same pixels.** Measured what the app keeps on the phone for
    offline use: 66 files, 1.16 MB, the largest being the app icons. They had an unused
    see-through layer and light compression; saved again without it they are pixel-for-pixel
    identical (checked) and 15% smaller (icon-512 115 KB to 97 KB, maskable 83 KB to 70 KB, the
    two small ones too). `liftbook/app_icons.py` now saves them that way, so making new icons
    keeps them small; its tests pass.
41. **The browser's bars follow the light theme.** Checked the page basics (language set, pinch
    zoom allowed, install manifest): all fine, except the bar colour given to browsers was always
    black, so on the light theme Chrome on Android (and Safari on older iPhones) drew a black bar
    over a white page. There are now two, black for dark and warm white (`#fbf9f6`, the top bar's
    colour) for light, and a theme picked in Settings sets both (`index.html`). The phone app's
    own status bar already followed the theme. Tested light, dark and automatic. Today's iPhone
    Safari colours its bars from the page itself, so it looked right there before as well.
42. **Settings shows the keyboard shortcuts.** On a computer, Liftbook has a full set of keys
    (H home, L log, G stats, / search, the arrows between workouts...), but the only way to find
    them was to press "?" without knowing it. Settings now has a "Keyboard shortcuts" row (under
    Help make it better, with a small keyboard icon) that opens the same list, and says "Or press
    ? on any page". Shown only with a mouse and keyboard, not on phones. Tested: it opens the
    list, and focus returns to the row when it closes.
43. **"Copied" is readable.** The earlier contrast check couldn't measure text on a gradient, so
    the gradient buttons were checked by hand: the gold ones already use dark text (about 6-9:1),
    but the green "Copied" that the Copy button shows for two seconds on a plan had white words
    on bright green, 2.3-3.3:1. They are now near-black green, 5.5-8:1 (`styles.css`). Checked in
    the browser after a real tap.
44. **Boxes you type into have a clear, warm outline.** Switches, the theme picker and the chosen
    choices already stood out at 3:1 or more. The boxes you type into (search, profile, account,
    coach key, bodyweight, the Stats lists) had outlines of about 1.2:1, hard to find for anyone
    who sees less well. You asked for both looks and use, so they now have a thin warm line in
    the app's own tones, not a grey one: bronze `#6e6452` on dark (3:1 or more on every dark
    surface), taupe `#8f826b` on light (3.2:1 or more), one variable, `--field-line`. Typing in
    one still turns it gold. The big writing boxes on Log and Feedback keep their card. Looked
    at in both themes.
45. **Keyboard focus shows in the light theme.** The ring that marks where Tab has landed used the
    pale gold `#c9a961`, about 2:1 against the light page, and a focused text box turned that same
    pale gold, so it looked lighter than a box you weren't in. Every focus mark (the ring, a focused
    box's edge, the week-strip days, opened exercises, the Log check rows, switches) now uses the gold
    the app already uses for gold text: deep gold `#8a6512` on light (4.8:1), and the same bright gold
    as before on dark, so the dark theme looks unchanged. Looked at with Tab on Profile.
46. **The Log check line is easier to click.** A sweep of every screen for click targets under
    24px found one: the line under the Log box ("Nothing to check yet", which opens the check) was a
    16px-tall button on a computer. It's now 24px, with the same look; on touch it was already 40px.
47. **Focus shows in Windows high-contrast mode.** That mode removes shadows and custom colours, so
    the focus marks drawn as a shadow or gold edge (text boxes, opened exercises, the Log check rows,
    the week-strip days) showed nothing there. In that mode only, every keyboard focus now gets a
    ring in the system's highlight colour; the normal look is untouched. Checked that the rule is
    served and off in normal mode (the browser here can't turn that mode on).
48. **Charts are marked on round numbers.** Every chart's side labels split the range into four
    equal parts, so an exercise read 67, 77, 88, 98, 109 and bodyweight 77.9, 78.3… Lines now sit
    on round steps (1, 2, 2.5 or 5 times a power of ten) with four or five lines: the exercise
    chart reads 60, 80, 100, 120, bodyweight 77, 78, 79, 80 kg, and Overall strength −10%, Start,
    +10%, +20% (so "Start" is now a gridline of its own). One change in `lineChart` (ui.js), so
    every chart gets it. Checked on Stats, and over 20,000 random ranges (always 4–5 lines, always
    covering the data). The scale itself now lives in `web/core/axis.js` (`chartScale`), with tests
    in `web/core/test/axis.test.js`: the exercise, bodyweight and percent examples above, decimals,
    a single value, and 5,000 random ranges. Tests: 110 pass.
49. **Retrieve: when each session was last done.** Each session in the plan now shows the day you
    last trained it under its name ("Today", "Monday", "28 Oct"), so a session skipped for weeks
    stands out when you choose. A session never done shows nothing extra; the cells in a row keep
    one height. The dates come from workout titles ("Session 2 - …"), the same way "Next" is
    worked out (`lastDoneBySession` in `web/core/sessions.js`, tested). Checked on desktop against
    the stand-in server. Tests: 111 pass.
50. **Stats: weights say kg.** An exercise's tiles read "Current est. max 70" and "Best 105", and its
    chart's end label "70", while bodyweight and "kg lifted" carried their unit. They now read
    "70 kg", "105 kg" (estimates in whole kilos, which also keeps them inside a phone-width tile);
    a timed hold like Plank keeps its unitless score and seconds. Bodyweight's Range tile says "kg,
    low to high" underneath, since "78–79.5 kg" would not fit a phone-width tile. Checked on desktop
    (bench, squat, pull-ups, plank).
51. **Screen readers hear what a chart shows.** Every chart was announced as "Progress chart". Each
    now says what it is and how it went: "Flat Barbell Press, estimated max, 23 Aug to 16 Nov: from
    72 kg to 70 kg; lowest 70 kg, highest 105 kg", and the same for Overall strength (against your
    start), the Rate view and Bodyweight. One helper (`chartSummary` in `web/app/ui.js`) builds it
    for every chart. Checked on desktop against the stand-in server.
52. **Workout page: bodyweight in kg.** The line under a workout's title read "1,965 kg lifted ·
    bodyweight 79.5"; it now says "bodyweight 79.5 kg", like the rest of the app. Looked at adding a
    "First" count beside New bests / Improving / Dipping / Steady (three of four exercises in the
    demo's latest workout are firsts) but left it: five columns would cut those labels short on a
    phone. Checked on desktop.
53. **Home: when the next session was last done.** Home's Up next row now ends with it, as Retrieve
    shows it (item 49): "Session 3 · 8 exercises · last done 28 Oct" ("last done yesterday",
    "last done Monday"). A session never done shows nothing extra. Checked on desktop (the demo's
    next session has never been done, so it shows no date; the date itself is the tested
    `lastDoneBySession`).
54. **"Click" with a mouse, "Tap" on a phone.** Three hints named the touch gesture on the computer
    too: the training calendar ("Tap a day to see it"), Arrange in the custom workout ("Tap an
    exercise to move it") and the wrong-password message ("tap “Forgot password?”"). With a mouse or
    trackpad they now say "Click"; touch screens keep "Tap" (`tapWord` in `web/app/ui.js`). The
    Apple Shortcuts page, which is about the iPhone, keeps "tap". Checked on desktop (the calendar
    reads "Click a day to see it."); the same check shows "Tap" on the iPhone in Muhurta (its item 69).
55. **Stats: a timed hold's score says what it is.** Plank showed "Current score 615.8", a number
    with no meaning on its own (it is weight × √seconds: 79.5 kg held 60 s). The tile now reads
    "616" with "weight × √seconds" under it; Best is a whole number too. Lifts are unchanged.
    Checked on desktop (plank and squat).
56. **Stats: "Since first" waits for a second session.** An exercise logged once showed "Since first
    0%", as if it had been tried and stayed flat. With one session the tile now reads "–" and "one
    session so far"; from the second session on it shows the change as before. Checked on desktop
    (plank: one session; squat: +34%).
57. **Personal bests: the right-hand number says kg.** Each exercise's best read "125.4" or "615.8".
    It now matches the exercise tiles on Stats (item 50): "125 kg" for a lift, a whole score ("616")
    for a timed hold. Checked on desktop.
58. **Consistency: dates read day first.** The Consistency view said "workouts a week since Aug 23"
    while every other date in the app reads "23 Aug". It now says "since 23 Aug" (`core/consistency.js`,
    its test updated). Checked on desktop.
59. **Stats' choice rows have names a screen reader can say.** The rows of choices on Stats (the
    overall view, the time range, the measure, the year, how bests are sorted) had no name, and the
    range buttons were read as "1 M", "3 M". Each row now has one ("Time range", "Measure"…) and
    the ranges say "1 month", "3 months", "6 months", "1 year", "All time"; the chosen one was
    already marked. Checked on desktop.
60. **Stats' choice rows are buttons, not "tabs".** They were marked as tabs, which tells a screen
    reader to expect the arrow keys to move between them and a panel to switch; neither is true
    (Tab moves between them and they redraw the page). They are now a named group of buttons, the
    chosen one "pressed". Looks the same. Checked on desktop: choosing 3M marks only 3M pressed.
61. **Appearance answers the arrow keys.** Settings' Dark / Light / Auto is a set of radio buttons,
    but each was its own Tab stop and ← → did nothing. It is now one Tab stop (the chosen theme),
    the arrows move the choice, and the focus stays on it as the theme changes. Checked on desktop
    with real key presses: → from Auto goes round to Dark, ← back to Auto (left on Auto).
62. **Messages are read out.** The small message at the bottom ("Bodyweight saved: 79.5 kg.",
    "Copied") is a live region, but its words went in at the same moment it appeared, which screen
    readers often skip. It now appears empty and gets its words a moment later, so each message is
    said; while empty it stays unseen, and its rise plays when the words arrive. Checked on desktop:
    the box shows empty, then the words; with the animation run to its end it is fully visible.
    (Saved the same bodyweight, 79.5, to see it.)
63. **The same message twice is said twice.** If a message was still up ("Copied") and the same
    words came again, nothing in the region changed, so nothing was read out. Now the same words
    while it is up also empty first and come back a moment later; a different message still goes
    straight in. Checked on desktop: "Saved", "Saved", "Other" logs "Saved", "", "Saved", "Other".
64. **A set typed wrong isn't quietly a new exercise.** A half-typed set line such as "60 x" lost
    its number (read as a list number) and became an exercise called "X", shown only as "New". A
    name with under two letters now gets a warning on the Log check: "Too short for a name: is this
    a set line?", in the warning colour. Tested (name_check.test.js) and checked on desktop.
    Left as it is on purpose: two sets written ("60x10, 65x8") are saved as three with the last
    copied. That is the parser's rule (three sets unless the plan says otherwise) and the check
    shows "3 sets", so it is not hidden.
65. **Retrieve's sessions say what the date means.** A screen reader heard "Session 2 Shoulders &
    Forearms Monday": the date's meaning came only from where it sits. Each session now has a
    full spoken name ("Next: Session 3, Back & Triceps, 8 exercises"; "Session 2, Shoulders &
    Forearms, 7 exercises, last done Monday"), and the hover text ends with "last done Monday" too.
    The card looks the same. Checked on desktop (8791).
66. **Today isn't over yet.** Home's Last 7 days read "Today: no workout" to a screen reader, as if
    the day were done. Today now says "no workout yet"; past days keep "no workout". Checked on
    desktop (8791).
67. **Stats writes sets the way the workout page does.** An exercise's Sessions list showed the
    saved text ("60 x 5, 60 x 5, 60 x 5"; for bodyweight whatever was typed), while the workout
    page and the Log check write "60×5 · 60×5 · 60×5". Stats now uses the same form, in the order
    lifted: "BW+20×6 · BW×8 · BW×8" for Pull Ups, "BW×60s · BW×45s" for Plank. The saved text is
    still used if the sets can't be read. Checked on desktop (8791) for a weighted, a bodyweight
    and a timed exercise.
68. **No stuck highlights after a tap on the phone.** On an iPhone a tapped button, row or link
    keeps its hover look until you tap somewhere else (a lifted primary button, a grey row, an
    underline). All 28 hover effects now apply only where there is a mouse; the chosen state
    (.active, an open info pop, keyboard focus) is untouched and still shows on the phone. Done by
    a small script that kept each rule in its place, so nothing else changes order. Checked on
    desktop (8791): all 29 mouse-only blocks load and hovering a link still underlines it.
69. **The spinner keeps turning with Reduce Motion.** With the device set to reduce motion, the
    "Opening…" spinner stopped dead, which looks like the app froze. It now turns slowly (2.4 s a
    turn, as Muhurta's sync spinner does); the sync dot's pulse and the page slide still stop.
    Checked on desktop (8791): 0.9 s a turn normally, 2.4 s with the reduce-motion rule applied.
    Also checked and clean: every other animation already stops or fades under Reduce Motion.
    Also checked and clean for contrast: every piece of visible text on Home, Log, Retrieve,
    Stats, Settings and a workout page, in dark and light, measured against what is really
    behind it, is at least 4.5:1 (3:1 for large text). Lowest colour token: light --good, 4.5:1.

Checked and clean (no change needed): zoom isn't blocked and the page language is set; an
unknown address goes back to Home; nothing sticks out sideways or is cut off on any screen
(desktop); sign-in on the iPhone in light mode shows the new outlines; Coach (the key box keeps
password managers and spellcheck off; a question with no key brings the key form up) and Retrieve
(the next session stands out) look right on desktop; the training calendar already reads well in
both themes (more = stronger gold, future days and today marked).

## Next when resumed

- Your "Suggestions/Workout Logger/To Be Done" list, section 7 ("Small leftovers"), is already
  built in this app: unlogged plan exercises in Settings > Exercises, the session name before the
  exercises in History, and row numbers with "3 sets" on the Log check. Idea 8 (darker gold links in
  light mode) is also in. Those lines can move to "Done".

## Ideas not done yet
