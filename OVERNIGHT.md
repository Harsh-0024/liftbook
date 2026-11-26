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
70. **Bulk import says the date is day first.** Its hint said "a date like 03/02", which reads as
    2 March to many people; the app reads it as 3 February, and "02/13" isn't a date it takes. The
    hint and the "No days found" message now say "a date, day first: 03/02 or 3 Feb". Checked on
    desktop (8791): both show the new words.
71. **A month-first date says how to fix it.** "02/13" on the Log page gave only "isn't a date
    this app can read". It now adds "Write the day first: “13/02”." when the numbers make the swap
    clear, and "Write the day first, as 13/02 or 13 Feb." otherwise. Tested (data.test.js) and
    checked on desktop (8791).
72. **The bodyweight message says the unit and what was kept.** Typing 900 in Settings said
    "Bodyweight should be between 1 and 500." and quietly put the old number back. It now says
    "Bodyweight should be 1–500 kg. Kept 79.5 kg." Checked on desktop (8791): nothing is saved and
    the box shows 79.5 again.

Checked and clean (no change needed): zoom isn't blocked and the page language is set; an
unknown address goes back to Home; nothing sticks out sideways or is cut off on any screen
(desktop); sign-in on the iPhone in light mode shows the new outlines; Coach (the key box keeps
password managers and spellcheck off; a question with no key brings the key form up) and Retrieve
(the next session stands out) look right on desktop; the training calendar already reads well in
both themes (more = stronger gold, future days and today marked).

## Checked in the real apps (19 Nov)

- **Android app:** built from this branch (debug build) and installed on a Pixel 8 emulator,
  which still had an earlier "Testing" sign-in. Only read, nothing saved. Seen working there:
  Retrieve's spoken labels ("Session 2, Shoulders & Forearms, 7 exercises, last done 1 Nov"),
  Home's "Today: no workout yet", the Log check's "“02/13” isn’t a date this app can read. Write
  the day first: “13/02”." and "Too short for a name: is this a set line?" (the Log box was put
  back as it was), and the sets list on Stats ("30×6 · 27.5×7 · 25×8"). Phones get no hover
  effects (checked: no mouse).
- **On start-up the Android app logs one error that isn't ours:** "Error injecting safe area
  CSS: TypeError: Cannot read properties of null (reading 'style')", from a Capacitor plugin
  running before the page has a body. The app looks right anyway. Worth a look when Capacitor
  is next updated. (The other start-up errors were only the emulator being offline.)
- **iPhone (Safari), signed in to the local stand-in server, no real data:** Home, Log, Retrieve
  and Stats look right; today shows as an open ring on the week strip; the month-first date
  message shows under the Log box; a tapped row doesn't stay grey. The draft I typed was
  cleared.

## Round 4 (branch `improve/round-4`, from 24 Nov 2026)

Started from `improve/round-3`. Nothing here touched `main`, `rewrite/offline-app` or live data.
Focus: the app looking as good as the old website, or better. Compared side by side with the old
site (local copy of `main`, demo data) in the iPhone simulator and on desktop.

1. **Week streak counts calendar weeks.** It counted 7-day stretches back from today, with the
   current one excused, so 13 days without a workout could keep a streak. Now Monday-to-Sunday
   weeks, this week excused until Sunday ends. Tests updated (`web/core/test/week.test.js`).
2. **No white flash while the app starts.** `index.html` paints the theme's background itself
   until `styles.css` arrives (a dark-theme start was a bright white screen first).
3. **Log box on phones as the old site had it.** 14px mono with 1.6 spacing (was 16px / 1.75),
   so "24/11/26 - Session 1 - Chest & Biceps" fits on one line. iPhone Safari is told not to zoom
   into small boxes (`maximum-scale=1`, set on iOS only: iOS still allows pinch-zoom; Android is
   left alone, as there it would block pinch-zoom). Checked in the simulator: no zoom on tap.
4. **The tab bar steps aside while typing on a phone's browser**, as it already did in the Android
   app, and the Save bar sits just above Safari's floating form bar instead of under it.
5. **Charts like the old Stats page, a little better.** Dates every so often along the bottom
   (was only first and last), the part under "Start" tinted red, a faint guide at the latest value,
   and points as small beads whenever they have room (they vanished past 60 points before).
   Checked on desktop, light and dark. Not yet on the iPhone (the simulator shut down).
6. **Workout page: the session as a small gold label over the title.** "Session 2 - Shoulders &
   Forearms" reads as Shoulders & Forearms with SESSION 2 above it, as Home and All workouts show it.
7. **Saving a workout with new bests says so.** The note after Save reads "Saved · a new best"
   (or "2 new bests") naming the exercises, on a soft gold card with the medal, which settles in
   with a small turn (held still for Reduce Motion). Checked light and dark.
8. **Personal bests: timed holds.** A bodyweight plank's top set read "79.5 × 60s" (the bodyweight's
   number); it now reads "BW × 60s" as logged. Its best showed a bare "616" beside rows in kg; it
   now says "616 score". Tests added.
9. **Timed exercise charts.** A plank's chart labelled its score in seconds ("614s", "615.8s").
   No unit on the axis now, the first tab reads "Score" for timed exercises (as the tile does), and a
   chart with a single session puts its point in the middle.
10. **Stats charts fill their card on a computer.** Charts were drawn 640 wide inside a 786px card,
   so they sat in the middle with blank space either side and looked small next to the old Stats
   page. They are now drawn at the wide column's width (phones unchanged), and the gridlines are
   solid hairlines, as on the old site, instead of near-invisible dashes. The Retrieve day page
   was compared too: it already matches the old one (and adds Log and "View as text").
11. **Exercise card leads with the number.** As on the old exercise page, the card now opens with
   the latest value in large serif ("70 kg", estimated max, latest session) and how far it has come
   over the range ("↓ 2 kg less than in Aug 2026"), following the Est. max / Top weight / Volume tabs.
   The "Current est. max" tile repeated it, so the tiles are now Best, Since first and Sessions
   (with the last date), which replaces the line of text under them.
12. **Personal bests: one date per row.** Each row read "Top set 40 × 6 · 16 Nov" with "16 Nov"
   again under the number. The top set's day now shows only when it differs from the best's day.
13. **Personal bests: resting exercises.** An exercise not done for two months said "at your best
   now" or "now 20% under", as if it were current. It now says "last done 23 Aug". (None in the
   demo data is that old, so this was checked by reading, not on screen.)
14. **Workout page: Delete stays on the row.** Edit, Repeat, Copy as text, Share link and Delete
   didn't fit one line on a computer, so Delete sat alone on a second one. It is now a red trash
   button at the row's far end (named "Delete workout" for screen readers), apart from the others.
15. **Retrieve: cycle rows line up.** A session done recently shows its date under the name, which
   made that cycle's row taller than the rest (90px against 68px). Once any session has a date, the
   others keep that line empty, so every row is the same height. With no dates at all, nothing changes.
16. **Exercise headline, tested.** The big number's maths (item 11) moved from the Stats screen into
   `core/bests.js` (`exerciseHeadline`) with two tests: gaps in the data, one session, timed holds,
   and a change under half a unit now reading "Level with …" rather than "↑ 0 kg more".
17. **Stats charts follow the window.** Charts are drawn for the window's width when Stats opens, so
   a window made narrower left them too wide for their cards (and wider, too small). Stats now
   redraws once the window settles, for a change of 40px or more. Checked at 700px: 788 → 628 wide.
18. **Consistency year grid fits its card on a computer.** It was sized for a 1040px column, so on a
   computer it came out 898px wide in a 756px card and scrolled sideways. It is now sized for the
   card's real inner width (the 860px column less its and the card's padding, less the day names):
   739px of squares in 756px at 1024px, 11px each, no sideways scroll. On a phone the squares are
   too small to fit either way, so it scrolls at 12px as before (still to see on an iPhone).
19. **Charts show a session when you point at them (from the old Stats page).** The old charts had a
   hover box; the new ones were pictures. Now, on the exercise and overall-strength charts, the
   nearest point gets a gold guide line and ring, and a box with its day, workout, value and top
   set ("Thu 22 Oct 2026 · Push · 102 kg · Top set 85 × 6"). A click opens that workout. On a
   touch screen a tap moves the box and tapping the box opens the workout, as on the old site
   (the touch part is on the waiting list for the iPhone check).
20. **Serif numbers use lining figures (branch `design/lining-figures`).** Cormorant Garamond
   defaults to old-style figures, so the Stats headline "+10%" read as "+IO%". Headings, the Stats
   hero, the workout-title field and the avatar now use lining figures (full-height digits).
   Checked on the iPhone with the demo data; 115 tests pass.
20. **Exercise stats: every tile has a second line (branch `design/exercise-tiles`).** Only
   Sessions had one ("last 25 Nov"), so Best and Since first sat over empty space. Best now says
   when it was set ("on 8 Nov", the same session the Best badge marks) and Since first where it
   started ("from 32 kg"), like the Bodyweight tiles. Timed exercises keep "weight × √seconds".
   Checked on the iPhone with the demo data; 115 tests pass.
   Same branch: the Bodyweight Range tile's note "kg, low to high" wrapped onto two lines on a
   phone, making that tile taller than Now and Change; it reads "kg, low–high" now, one line.
   Same branch, Personal bests: the Exercises tile gets a note too ("in 40 workouts"), and the
   "22 exercises" count beside the sort buttons, which sat 9px high (it kept the footnote margins),
   is level with them.

### Branch `design/exercise-options` (from `improve/round-4`)

1. **An exercise's switches no longer look switched off.** In Settings > Exercises, opening an
   exercise shows "Timed" and "Bodyweight" switches; their names were grey (a style meant for
   Retrieve's tucked-away groups, which this list shares) while "Rename" below was dark, so the
   switches read as unavailable. Their names are now in full ink there; Retrieve keeps its grey.
   Checked both pages; 115 tests pass.
### Branch `fix/busy-icon-button` (from `improve/round-4`)

1. **The trash button no longer swells while you're asked.** Tapping the trash on a workout
   turned the small icon button into a wide "Working…" pill behind the "Delete this workout?"
   question, shifting the row. Buttons with only an icon now keep their icon and just dim while
   working (and tell screen readers they're busy); text buttons still say "Working…". Found while
   saving and deleting a test workout end to end on the mock server (both worked). 115 tests pass.
### Branch `improve/workout-not-found` (from `improve/round-4`)

1. **A day with no workout says so.** Opening a workout's address for a day with nothing logged
   said "Workout not found. It may have been deleted on another device." It now reads "No workout
   that day: Nothing is logged on Wed 1 Jan 2020", keeps the deleted-elsewhere note as a maybe,
   and offers Log workout beside All workouts.
### Branch `feature/chart-hover` (from `improve/round-4`)

From here on each kind of work has its own branch (design/, fix/, feature/, improve/ + topic),
as asked on 24 Nov; `improve/round-4` above holds everything before that.

1. **Bodyweight chart: hover box too.** Pointing at it shows the day, the workout the weight was
   saved with, and the weight; a click opens that workout.
2. **Workout names in the hover boxes** read "Session 2 · Shoulders & Forearms" (not " - "), and a
   bare "Workout" is left out.
3. **Charts from the keyboard.** Tab reaches a chart (a rounded gold focus ring); the arrows step
   through its sessions with the box following, Home and End jump to the first and latest, Enter
   opens that workout, Escape closes the box. The box is read out by screen readers as it changes.

### Branch `feature/log-for-day` (from `improve/workout-not-found`)

1. **Log a workout for a given day.** The no-workout page's button now reads "Log a workout that
   day" and opens Log with that day's date line ready ("20/11/26 - ").
   (`#/log?day=2026-11-20`.) An unsaved workout already in the box is never replaced; a note says
   to change its first line to that date instead.
2. **No complaints while only the first line is written.** A box with just the date and title
   showed a red "No exercises found" and a red count before anything else was typed. Those wait
   now until there is a second line; saving still checks everything as before.
3. **Cursor ready, and no false warning.** The cursor now waits after the date line for the title.
   Found while doing it: the page is drawn a second time once the data loads, and that second
   drawing took its own date line for someone's unsaved work and showed "Your unsaved workout is
   still here". A box already on the asked day is now recognised as such; the note only shows for a
   draft dated otherwise (checked both).
4. **A bare date line isn't kept as a draft.** Opening "Log a workout that day" and leaving without
   typing left "10/11/26 - " saved as unsaved work; the next "Log a workout that day" for another
   day then kept that line and said "Your unsaved workout is still here". A box holding only a date
   line is no longer saved, and one already saved that way switches to the day asked for. A real
   unsaved workout is still kept, with its note (checked both; 115 tests pass).
### Branch `improve/keyboard-parity` (from `improve/round-4`)

1. **Keys the old site had.** Two shortcuts were missing against the old Flask pages:
   - **AI coach:** Enter sends the question again, and Shift+Enter starts a new line (before,
     only Cmd/Ctrl+Enter sent). On a touch screen the return key still adds a line, since
     there's no Shift there and Send sits beside the box.
   - **Edit workout:** Cmd+Enter (Ctrl+Enter elsewhere) saves from anywhere on the page, as the
     old edit page did. The key stops listening once you leave the page.
   Checked in the browser: Cmd+Enter saved an edit and went back to the workout; Enter sent a
   coach question, Shift+Enter didn't. 115 tests pass.
2. **The workout page's "i" notes close like before.** On the old page only one could be open,
   and Escape or a tap anywhere else closed it. In the new app they stayed open until their "i"
   was tapped again, and several could pile up. Now opening one closes the others, and Escape or a
   tap away closes it. Checked in the browser; 115 tests pass.
3. **Enter in a search box puts the keyboard away.** The old site's search boxes (All workouts,
   Exercises, Retrieve) dropped the keyboard on Enter or a phone's "Search" key, so the filtered
   list could be seen; the new ones kept it up. Now every search box does this, except Stats,
   where Enter still jumps to the exercise typed. Checked in All workouts and Stats; 115 tests pass.
4. **Reorder a custom workout from the keyboard.** The picked exercises could only be dragged
   by their handle with a mouse or finger. The handle can now take keyboard focus (it turns gold),
   and the up and down arrows move the exercise; focus stays with it, and a screen reader hears
   where it is ("2 of 3"). Checked in the browser; 115 tests pass.
5. **The plan's Format note closes the same way.** Settings > Workout plan's "Format" opens a note
   over the plan text, and it stayed open until "Format" was tapped again. It now shares the "i"
   notes' behaviour (item 2): Escape or a tap elsewhere closes it, one note open at a time. The
   closing code moved into one helper (`popover` in `web/app/ui.js`) used by both. Checked both
   pages; 115 tests pass.
## design/footer (25 Nov)

- The footer read "2026 Liftbook", a bare year that looks like a slip (the old site had the same).
  It now reads "© 2026 Liftbook". Checked on the iPhone.
## Log's "How to write sets" (branch `design/log-guide`, 25 Nov 2026)

- The guide's examples ("100 x 5, 5, 4", "bw+10 x 6", "Bodyweight - 72") were grey monospace text
  running straight into grey explanations. Each example now sits on a soft chip in the text colour,
  so it reads apart from what it means. Checked on the iPhone 18 Pro in dark and light. 115 tests pass.
## fix/bodyweight-notice (from improve/round-4)

- Stats, with no bodyweight set: the notice read "so Hyper Extension, Pull Ups, Pull-Ups count your
  bodyweight": one lift logged under two spellings, named twice. It now names each exercise once
  (matched the way Stats matches names), keeping the first spelling. New test; 116 pass. Checked on
  iPhone 18 Pro: "so Hyper Extension, Pull Ups count your bodyweight."
### Branch `fix/row-card-surface` (from `improve/round-4`)

- **Row cards keep their card colour.** Settings' profile card and Stats' Personal bests link are a
  row that is its own card; .rowi's transparent background overrode the card surface, so in light
  mode they showed the darker page and looked greyed out. They now have the surface like every other
  card, and still change on hover. Checked in light mode.
## fix/stats-numbers (25 Nov)

- Stats > exercise: the big number said "25 kg" but the chart's end tag right under it said
  "25.3 kg". The tag now rounds as the big number does; pointing at a session still shows the
  exact value. Checked on the iPhone.
## improve/coach (25 Nov)

- With no AI key turned on, the Coach page hid its Ask box but still showed six starter questions;
  tapping one only gave an error, since the built-in answers can't handle any of them. They now
  appear once a key is on, like the Ask box. Checked on the iPhone without a key.
### Branch `design/settings` (from `improve/round-4`)

- **Settings' Preferences card lines up and reads right.** The Bodyweight row's text is a `<label>`
  (so tapping it focuses the kg box), and it took label's bold type into its note: "Used for
  bodyweight exercises" was bold where every other row's note is plain. Appearance's moon icon had
  no fixed slot, so its title sat 4pt left of Bodyweight's. Both now match the rows around them.
  Checked on the iPhone simulator.
- **Sign out's icon points out.** It was the "sign in" picture (an arrow going into a door on the
  right); now the arrow leaves a door on the left, as sign-out icons usually do. Only Sign out uses
  it. Checked on the iPhone simulator. The rest of Settings on the phone looked right.
- **In dark mode the chosen option in a switch shows.** The chosen Dark/Light/Auto option used the
  card colour (#0f0f11), which in dark mode is darker than the switch's track, so it looked sunk in
  and only its gold text marked it. It now sits on a lifted #26262b in dark mode; light mode keeps
  its white chip. Applies to every `.seg` switch. Checked on the iPhone simulator in dark mode, and
  tapping Light then Auto still switches the theme.
- Dark-mode pass on the iPhone simulator: sign-in, Home, Settings, Stats (chart, tiles, sessions),
  Retrieve and a plan page all read well; nothing else needed changing. A plan's right-hand column
  (sets, a rep range, or nothing) follows what the plan itself declares, so it is left as is.
  Tip: Safari's cached app on 127.0.0.1 swallows `/__signin`; the Mac's address
  (http://192.168.29.209:8791/__signin?to=/) is a clean origin that works.
- Nov 25, light mode on iPhone: the Bodyweight row's description looked bold on `design/charts`, which lacks this branch's `.rowi label.main` weight fix. On this branch it is regular, like every other row. Merge this branch to fix it everywhere.

## design/settings: checked on the iPhone (25 Nov)

- Bodyweight's note is plain (not the form labels' semibold) and Appearance lines up with the rows
  above, on the iPhone too. The rest of Settings (Training, Account, Help make it better, Sign out)
  reads evenly. Nothing to change.
## design/gold-edges (25 Nov)
- Same flaw as Muhurta: gradient fills (primary buttons, active tabs, done-day dots, "Copied") have a transparent border, and the gradient repeated underneath it, leaving a faint sliver of the far-end colour at the edges.
- All four now use `background-origin: border-box`. Checked on the iPhone simulator (Home: Today's workout, the week dots).

## design/page-head (25 Nov)
- All workouts on the iPhone: the Select button beside "40 workouts logged." sat a few points higher than that line (the header bottom-aligns its children, and the button has padding).
- A page header with a button directly beside it now aligns on the last baseline. Only All workouts uses that; Coach's button row is untouched. Checked on the simulator.

### Branch `design/plan-page` (from `improve/round-4`)

- Retrieve and a plan page on the iPhone (light mode): both look good, and Copy works. But
  "Copied" turned the button into a loud lime-green slab (#16a34a to #22c55e), off the warm gold
  palette, and the wider label pushed Log to the left. Now "Copied" is a soft wash of the app's
  own green (`--good` 12% on the surface) with deeper green text and a thin green border, and Copy
  keeps one width (7.4em) in both states. Checked on the iPhone: calm, and Log stays still.
- Dark mode on the iPhone: "Copied" is a deep green chip with light green text, readable and
  calm. No other loud green fills are left in styles.css (only the `--good` tokens).

## design/retrieve-plan (from improve/round-4)

- Retrieve, a plan never logged (Session 5 in the demo): "No history yet" sat in italics under all
  eight exercises. Now the header line says it once ("8 exercises · 20 sets · Bodyweight 79.5 kg ·
  Nothing logged yet") and the rows are just the names and targets. A plan with some history
  (Session 3) is unchanged. Checked on iPhone 18 Pro; 115 tests pass.

## Merging the design branches together (checked 25 Nov)

All 31 Liftbook branches off improve/round-4 were merged into one throwaway copy (not pushed).
25 merge cleanly together (OVERNIGHT.md and web/sw.js aside: rebuild sw.js after) and 115 tests
pass on the result. Six pairs touch the same lines and need a hand merge:

- design/plan-page with design/gold-edges: web/styles.css
- design/workout-phone with design/workout-page: web/styles.css
- feature/chart-hover with design/stats-tiles: web/app/screens/stats.js
- feature/log-for-day with design/log-check: web/app/screens/log.js
- fix/first-line-exercise with design/log-check: web/app/screens/log.js
- improve/history-search with design/page-head: web/styles.css

## design/selects (25 Nov)

- Every picker (Stats: Recently trained, the exercise; Settings and elsewhere) drew a small filled
  triangle, which read as a plain OS default. It is now a thin chevron, like the old site's
  Bootstrap pickers, in each theme's quiet grey. Checked on the iPhone in dark and light.

### Branch `feature/search-short-names` (from `improve/round-4`)

- Searching "rdl" found nothing, though Romanian Deadlift is logged most Legs days. The exercise
  searches (All workouts, Retrieve, Settings > Exercises, Stats, Personal bests) now know gym short
  names (web/core/search.js): rdl, sldl, ohp, bp, dl, bss, lpd, pullups/chinups/pushups for a whole
  lift; db, bb, kb, ez, bw, ext, tri, bi, incl, decl for one word. Words typed may come in any
  order ("press incl db"), and a short word matches from the start of a word in the name, so "bb"
  doesn't find Dumbbell. Plain text still matches as before. New test file search.test.js (3
  tests); 118 pass. Checked on iPhone 18 Pro: "rdl" on All workouts lists the Legs days;
  "db press" in Retrieve > Custom workout lists Incline, Flat and Seated Dumbbell (Overhead) Press.

### Branch `fix/added-day-bests` (from `improve/round-4`)

- Adding exercises to a day that already had a workout ("Add to that day") opened the day with
  "Added to this day · a new best — Pull-Ups. Well lifted.", though Pull-Ups was logged earlier
  and only Flat Barbell Press was added. The note now names only bests among the exercises just
  added (`saveWorkout` returns `added`); a plain save is unchanged. Checked in the browser:
  adding Barbell Curl to that day now says just "Added to this day".
- Log screen on the iPhone (light mode): looks right, the check updates as you type, and Save →
  "That day already has a workout" → Add to that day works. Just after the keyboard closes, Safari
  briefly leaves the floating Save bar where it sat above the keyboard, over the check card; the
  next scroll puts it back. A Safari quirk, left as is.
- Test: joining a day returns `added` with only the new exercise (data.test.js).
- Day page lower half on the iPhone: the uneven Edit/Repeat/Copy/Share buttons and the clipped
  lone "previous workout" link are both already fixed on `design/workout-page`.

## A name over sets, with no date line (branch `fix/first-line-exercise`, 25 Nov 2026)

- Typing just "Squat" then "60 70 80, 8 6 5" on Log was refused: with no date, the first line was always taken as the title, so the sets had "no exercise name above them" while the check line said "Squat · adds to …".
- Now, on the app's Log screen, a dateless first line with sets right under it is the exercise. The workout takes the day's existing title, or "Workout". A title over an exercise name ("Leg day" / "Squat" / sets) is unchanged.
- The parser keeps its Python behaviour by default (option `exerciseFirst`, which only `Liftbook.check` turns on), so the 3411 parity cases still match. New test in data.test.js; 116 tests pass.
- Checked on the iPhone 18 Pro: "1 exercise · 3 sets", Squat 60×8 · 70×6 · 80×5. Draft cleared afterwards, nothing saved.
- Then: with no title typed and a workout already on that day, the check line no longer says "Workout" (a title that wouldn't be used). It reads "Wed 25 Nov 2026 · adds to Session 3 - Back & Triceps if you choose". Checked on the iPhone.

### Branch `fix/phone-autocorrect` (from `improve/round-4`)

- On an iPhone, typing "bw/4" in Log became "Be/4 be/4": iOS autocorrect still ran in the workout
  box (only spell-check and, elsewhere, capitals were off), and Liftbook then could not read the
  line ("“Hyper Extension”: no sets under it."). Autocorrect is now off in every box that takes
  workout text: Log, a workout's Edit, Bulk import, and the plan and rep-range boxes in Settings.
  Log keeps its capital at the start of a line (exercise names), which reads fine ("Bw" works).
  Checked on iPhone 18 Pro: "bw bw, 30 30" stays as typed and is read without an error. Tests: 115
  pass.
- The same for the boxes that take an exercise name: the searches on All workouts, Retrieve,
  Settings > Exercises, Stats and Personal bests, and the Rename box. Autocorrect and spell-check
  are off there too; All workouts' search also stops capitalising the first letter, as the others
  already did. Checked on iPhone 18 Pro: "bw rdl" stays "bw rdl". Tests: 115 pass.

## improve/search-hits (25 Nov)

1. **Search shows what matched.** In All workouts, searching "curl" found the right workouts, but
   a row like "Session 3 · Pull-Ups · Incline EZ-Bar Sku…" cut off before the curl, so you could
   not see why it matched. While searching, matching exercises now come first in each row and in
   the text colour: "Session 3 · **Barbell Curl** · Pull-Ups · Incli…". No search: unchanged.
   Checked on the iPhone.
2. **No autocorrect in exercise searches.** On the iPhone, typing "curl" in All workouts became
   "Curl" with a "Curls" suggestion; names like "RDL" or "EZ-Bar" could be "corrected" away. The
   four exercise searches (All workouts, Retrieve, Stats, Settings → Exercises) now turn off
   autocorrect, spell check and capitals. Checked on the iPhone in All workouts.

## design/bests (25 Nov)

- Personal bests: the "22 exercises" count beside Latest / Highest / A to Z sat about 9px above the
  buttons' middle (the quiet-note style's own margins pulled it up). In a card head it now has none,
  so it sits level with them. Checked on the iPhone.
- The line beside the sort buttons said "22 exercises", right under the Exercises 22 tile. It now
  reads "Sort by", and "3 of 22" while a search narrows the list. Checked on the iPhone.

## design/log-check (25 Nov)

- The line over the Log page's check ("Wed 25 Nov 2026 · Legs · adds to ... if you choose") named
  the day's workout by its full title, "Session 3 - Back & Triceps", and on a phone broke it after
  "Back". It now says "Back & Triceps", as Home and All workouts name it, and each fact wraps whole.
  Checked on the iPhone.
- The check line said "· adds to Back & Triceps if you choose", which was hard to follow. It now
  says "· also on this day: Back & Triceps"; Save still asks whether to add to it or open it.
  Checked on the iPhone.
20. **Log help examples are code chips (branch `design/log-help`, a567b57).** Under "How to write
   sets" the examples to type (`100 x 5, 5, 4`, `bw+10 x 6`...) were loose grey monospace inside the
   sentence. They now sit in small gold-tinted chips with dark text, so what to type stands apart
   from what it means. Checked on the iPhone in light and dark; 115 tests pass.

## design/custom-picker (25 Nov)
- Custom workout picker on the iPhone: unpicked exercises had nothing on the right, so a row didn't look tappable; the tick only appeared after picking.
- Now every row ends in an empty ring (the field-line colour, 3:1 contrast) that fills gold with a check when picked. Checked in light and dark on the simulator.
- Then matched it to the ring All workouts already uses when picking workouts (24px, the soft line colour, 14px check), so the app has one selection ring, not two.

### Branch `design/workout-page` (from `improve/round-4`)

- c54c39b: the link to the older/newer workout at the foot of a workout page always took half the row, so on the newest (or oldest) workout, with only one neighbour, "Shoulders & Forearms" was cut to "Shoulders & For…" beside an empty half. A lone neighbour now spans the row; with both, they still sit side by side. Checked on the iPhone (dark); tapping it still opens that workout.
- a6d566a: on a phone the workout's buttons wrap onto two rows (Edit, Repeat / Copy as text, Share link, trash) that ended at different points. Under 560px the buttons grow to fill their row, so both rows line up edge to edge; the trash button stays square. Checked on the iPhone; Copy as text still says "Copied". Tests: 115 pass.
- The line under a workout's title (date · exercises · sets · kg lifted · bodyweight) wrapped on the phone inside "3,693 kg lifted", leaving "lifted" alone at the start of the second line; kept whole, the second line then began with a dot. Now each item stays whole, lines break only between items, and no line starts with a dot (each item carries its dot; the first one on a line is clipped). Checked on iPhone 18 Pro. Tests: 115 pass.

## improve/settings-copy (25 Nov)

- Settings > Sync and data: the status line always ended "· 0 changes waiting to upload". It now
  just says "Last synced just now"; the waiting count appears only when something is waiting.
  Checked on the iPhone.
- Settings > Account: the subtitle said "Password, theme, sign out, delete" but the first card on
  the page is Email. It now reads "Email, password, theme, sign out, delete". Checked on the iPhone.

## design/stats-consistency (25 Nov)

- Stats, Consistency: the year switch showed as a lone gold "2026" button on its own line when
  there is only one year to pick. It now appears once there are two years.
- The card's heading repeated the chosen tab ("Consistency" over the Consistency tab). It now reads
  "Training days", the way the Strength tab is headed "Overall strength".
- Checked on the iPhone.
- On a phone the year grid scrolls sideways and opened cut mid-word ("De" for Dec) and mid-square
  at its edge. The side with more weeks past it now fades out over 28px, so the cut reads as "more
  this way"; at either end that side is sharp. Checked on the iPhone, both scrolled in and at the end.

### Branch `design/workout-phone` (from `improve/round-4`)

- **Workout buttons fill their rows on a phone.** On an iPhone the action row wraps to Edit + Repeat
  and Copy as text + Share link + trash, and the first row stopped short with a gap. Under 560px the
  buttons now share each row's width (the trash stays a square at the end). Checked on the iPhone
  18 Pro simulator.
- **iPhone checks done (simulator, mock data, light mode):** tapping a chart moves the box to the
  tapped point and tapping the box opens that workout; the exercise card's big number ("70 kg",
  "↓ 2 kg less than in Aug 2026") fits; the trash button sits at the end of the action row.

## design/workout-phone: the facts under a workout's title (25 Nov)

- On a phone, the line under the title (day · exercises · sets · kg lifted · bodyweight) broke inside a
  fact ("3,693 kg" / "lifted"). Each fact now wraps whole, and the separating dot sits in the gap, so
  a wrapped line never starts with a dot. Checked on the iPhone.
- Also checked on the iPhone from the Waiting list's round-4 items: tapping a chart moves the box to
  the tapped point, the Retrieve rows sit two to a row, the Consistency year grid scrolls sideways
  ending near today, and a plan's "SESSION 3 · CYCLE 1" kicker shows. All fine.

- The links to the workout before and after: the first or the latest workout has only one, which
  now takes the whole row instead of cutting "Shoulders & Forearms" to "Shoulders & For..." beside
  an empty half. With both, a long name wraps to two lines before it is cut. Checked on the iPhone
  (25 Nov: one link; 16 Nov: both).

### Branch `design/stats-tiles` (from `improve/round-4`)

- **Every Stats tile has its caption.** Under an exercise's chart, Best and Since first had no line
  underneath while Sessions did, so the three tiles sat uneven and the Overall tiles above all had
  one. Best now gives the day of the best ("28 Oct"; a timed hold keeps "weight × √seconds"), and
  Since first the day it counts from ("from 23 Aug"). Checked on the mock data.
- **Bodyweight axis without "kg".** Its axis read "77 kg … 80 kg" while the exercise chart's reads
  bare numbers; it now matches, and the tag at the line's end still says "79.5 kg" (as does the
  chart's spoken summary).
- **Personal bests: status lines.** "at your best now" reads in green, as other good news does;
  "first session" reads "one session so far", the words the exercise tile already uses.
- Checked in dark mode too: the green is the dark theme's brighter one, and the Stats tiles and
  captions read cleanly on the dark cards.
- **Tile numbers line up on a phone.** On the iPhone "MOST IMPROVED" wraps to two lines and pushed
  its number below Best's and New bests'. Each row of tiles now shares its label, number and
  caption lines (CSS subgrid), so the numbers sit level whatever wraps. Desktop is unchanged (all
  tiles 108px, numbers level). Checked on the iPhone 18 Pro simulator.
- **More iPhone checks passed (from the waiting list):** Retrieve on two columns, the "SESSION 2"
  kicker, the Consistency year grid (scrolls sideways, opens on recent months), and the Overall
  chart's red stretch under the start line with its guide line. Still to see on a phone: the gold
  "a new best" note after saving, and a timed exercise's best and chart.

## Muscle balance numbers (branch `design/stats-tiles`, 25 Nov 2026)

- Every muscle's sets-a-week figure now shows one decimal (6.0, 9.0, 2.9, 10.6), so the column lines up instead of mixing whole numbers and decimals.
- A card header's small note (Muscle balance's "sets a week") sits on the title's baseline, with no stray margin below it.
- Checked on the iPhone 18 Pro (light): Stats > Muscle balance, and the Personal bests header (unchanged look). 115 tests pass.

### Branch `design/home` (from `improve/round-4`)

- **Avatar initial in Inter, as on the old site.** Home's big avatar (and the small ones in
  Settings) set the initial in Cormorant, whose thin strokes read faint inside the gold ring; the
  old site and the "LB" mark use Inter 600. Now the same. One line in styles.css (`.avatar`) if the
  serif is wanted back. Checked in dark mode next to the old site.
- **The week row reads in light mode.** Home's Last 7 days rings used the divider line (8% black on
  cream) and today's a pale gold, so in light mode the row looked empty. Day rings now come from
  the muted ink at 30% and today's ring is full gold. Checked in light and dark.

## design/home: See all workouts (25 Nov)

- "See all workouts" sat under the three totals (Workouts, Week streak, Exercises), apart from the
  Recent list it continues. It now comes right under that list, as on the old site's home page, and
  the totals follow with a little more room above them. Checked on the iPhone.
- Home totals: "Workouts 40", "Week streak 15", "Exercises 22" were bare numbers over an empty
  line, unlike the Stats tiles. Each now says what it counts: "since 23 Aug" (with the year when
  the first workout was in another year), "weeks in a row" ("none this week yet" at 0),
  "different lifts". Checked on iPhone 18 Pro.
- Home before the first workout: a greeting, two buttons, then empty page. Now a short "How it
  works" list under the buttons: Set up your plan, Retrieve a session, Log what you lifted (each a
  link, one line each on the phone), and "Have old workouts? Bulk import them". Gone once a
  workout is logged. Checked on iPhone 18 Pro with an empty demo account.
- Stats before the first workout showed the search box, Personal bests, the Strength / Rate /
  Consistency and 1M–All pills over an empty chart ("Nothing to chart yet"), and an empty Exercise
  card. Now one card: "Your charts start here", a line on what Stats will show, and two buttons,
  Log a workout and Import old workouts. Everything comes back with the first workout. Checked on
  iPhone 18 Pro with the empty account, and with the demo data (unchanged). Retrieve needed nothing:
  a new account already sees the default plan to pick from.
- Personal bests before the first workout said "0 exercises" beside Latest / Highest / A to Z
  buttons over an empty list. Now the same kind of card as Stats: "No bests yet", what will land
  there, and a Log a workout button. Checked on iPhone 18 Pro with the empty account.
- Those cards' two buttons, stacked on the phone, were each as wide as their words. They now
  share one width (up to 230 px, side by side on wider screens). Checked in dark mode too.

### Branch `design/bests-icon` (26 Nov)

- **Stats: Personal bests has its own icon.** The Personal bests row used the chart icon, the same
  one as the Stats tab right below it, so it didn't say "bests". It now uses the medal icon that
  already marks a new personal best on shared workouts. Checked on the iPhone in dark mode;
  115 tests pass.

### Branch `design/curly-apostrophes` (26 Nov)

- Stats → Muscle balance note: "exercise's" now uses the curly apostrophe (’) like the rest of the app. Checked in the page.
- Left as they are: the rename message ("That's already its name.") and the coach's built-in answers. They are checked against fixtures from the Python site, so changing them needs both sides changed.

### Branch `design/home-all-time` (26 Nov)

- Home: the three totals (Workouts, Week streak, Exercises) sat unlabelled under "Recent", just
  below "Last 7 days · 1 workout", so "40 workouts" could read as this week's. They are a section of
  their own now, "Overall", and "See all workouts" sits right under the Recent list it belongs to.
  Checked on the iPhone.

### Branch `design/light-tabbar` (26 Nov)

- The bottom tab bar's shadow was 25% black in both themes. On the light theme that showed as a grey
  band over the page above the bar, heaviest on the "Opening…" screen. It is now a theme token
  (`--tab-shadow`): unchanged on dark, a light 5% on light, in step with the light theme's other shadows
  (8%). Checked on the iPhone in light mode.

### Branch `design/log-check-messages` (26 Nov)

- **Log check: a problem reads as a sentence, not as sets.** Under an exercise with a red info
  icon, "No sets under it" / "Couldn't read these sets" used the spaced monospace font meant for
  sets ("120×10 · 120×10"), so it looked like data. It is now in the normal font, in the same red
  as the icon; real sets keep the monospace look. Checked on the iPhone in dark mode; 115 tests
  pass.

### Branch `design/serif-numbers` (26 Nov)

- Numbers in the serif (Cormorant) used its old-style figures: Stats' big "+10%" read as "+IO%",
  the 1 and 0 at letter height. Headings, the Stats hero number and the editable plan title now use
  lining figures. Checked on the iPhone.

### Branch `design/session-dot` (26 Nov)

- **Workout titles in sentences take the app's dot.** Saved titles are "Session 3 - Back &
  Triceps"; Home splits them, but sentences printed them raw with the hyphen, beside the app's own
  "Session 4 · Legs". A new `sessionTitleText()` in core/sessions.js (with a test) gives
  "Session 3 · Back & Triceps", used by the Log check heading ("adds to …"), the "already logged"
  box, the delete question, the Stats calendar tip and Bulk import's "already logged" reason.
  Shares and saved text keep the title as written. Checked in the page ("adds to Session 3 · Back
  & Triceps") and on the iPhone; 116 tests pass.

### Branch `design/settings-rows` (26 Nov)

- Settings → Preferences: the Bodyweight note ("Used for bodyweight exercises") was semi-bold, because it sits
  inside a label. It is now regular, like every other note. "Appearance" was a bold `<b>` 4px left
  of "Bodyweight". It now uses the same title style and icon column, so both titles line up and match.
  Checked on the iPhone.

### Branch `design/settings-sync-status` (26 Nov)

- Settings, "Sync and data": the sync status ("Synced just now", "3 to sync") sat beside the row
  and squeezed the description onto two lines on a phone. It is now a line of its own under the
  description, with a dot: green when synced, amber when changes are waiting. rowItem() takes
  `status` (and `warn`) for this. Checked on the iPhone.

### Branch `design/shortcut-links` (26 Nov)

- **Apple Shortcuts, "Links for your own shortcut": the bits of code stay whole.** The help line
  broke "?key=" across two lines, leaving "?" alone at the end of one. `workout_text`, `?key=`
  and `?list=1` are now small monospace chips on a soft gold ground that never break (a new
  `code` style in styles.css; nothing else in the app used `<code>`). Checked on the iPhone;
  115 tests pass.

### Branch `design/shortcuts-layout` (26 Nov)

- **Apple Shortcuts: Session names joins step 2.** The Session names link had a card of its own
  between steps 2 and 3, tall and unbalanced (card padding plus row padding) and breaking the
  1-2-3 flow. It is now the third row in step 2's list, under Get Workout, which it belongs
  with. Checked on the iPhone; 115 tests pass.

### Branch `design/stat-tiles` (26 Nov)

- A row of three number tiles (Stats, Home, Personal bests, Bulk import) shares its rows now: label,
  number, note. On a phone "Most improved" took two lines and dropped its number and note below the
  other two tiles'; now all three numbers sit on one line. CSS subgrid, behind @supports. Checked on
  the iPhone.

### Branch `fix/autocorrect-off` (26 Nov)

- **Workout boxes no longer let the iPhone autocorrect sets.** The Log box, the workout edit box,
  the plan and rep-range boxes and Bulk import turned spellcheck off but left iOS autocorrect on,
  so "bw" could become "be" or "by" as you type (the demo draft held a "Be/4 be/4" line, which
  the check read as a new exercise). They now also have `autocorrect="off"`, as the sign-in and
  username boxes already did. Seen in the page (all five boxes carry it) and the Log page loads
  on the iPhone; the keyboard's own behaviour can't be tested in the simulator, since its
  typing skips autocorrect. 115 tests pass.

## fix/chart-tip-scroll (26 Nov)

1. **Chart boxes on a phone.** A swipe that started on a chart opened its box and left it riding up
   the screen as the page scrolled; now the box closes when the touch turns into a scroll. And a
   first tap where the box opens (below the point, near the top of the chart) used to land on the
   box and jump straight into that workout; now the first tap only opens the box, and a second tap
   on it opens the workout. Checked both on the iPhone.

### Branch `improve/exercise-search-count` (26 Nov)

- Settings, Exercises: searching left the count at "65 exercises" over a list of four. It now says
  "4 of 65" while a search is on (and "0 of 65" with no match), and goes back to "65 exercises" when
  the search is cleared. Checked on the iPhone.

### Branch `improve/session-names` (26 Nov)

- **Session names: labels and examples fit each session.** The page showed "Session 1 - Chest &
  Biceps" with a plain hyphen, and every box suggested "e.g. push", even Legs. It now shows
  "Session 1 · Chest & Biceps" like the rest of the app, and each box suggests that session's
  first word ("e.g. chest", "e.g. legs"; "e.g. push" when a session has no title). The label
  Get Workout lists is unchanged. Checked on the iPhone; 115 tests pass.

### Branch `improve/shortcuts-copy` (26 Nov)

- **Apple Shortcuts: the Log Workout line fits on one line.** "Pick one of your newest workout
  notes and log it" left "it" alone on a second line on an iPhone. It now reads "Log one of your
  newest workout notes", one line like Get Workout's. Checked on the iPhone; 115 tests pass.
  Also looked at: Bulk import (fine), the "1." / "3." step numbers (old-style figures, already
  fixed on `design/lining-figures`) and the footer (same "2026 Liftbook" as the old site).

### Branch `design/coach` (from `improve/round-4`)

- **Coach replies have even padding.** A reply card ended with its last paragraph's (or error's)
  12px bottom margin, so it had more room under the text than above. Whatever ends a reply, or ends
  the answer inside it, now adds no gap. Checked on the iPhone simulator with the "local coach is
  not running" error (the mock has no coach); the rest of Coach on the phone looked right.

- Coach, Earlier answers: the date no longer wraps ("9 Nov / 2026" on long questions). The year is left off for this year's answers and the date stays on one line. Checked on the phone.

## design/key-field (26 Nov)

1. **"AIza", not "Alza".** In Inter a capital I looks like a lowercase l, so the AI key field's hint
   read "Alza… or gsk_…" (Gemini keys start "AIza") and the coach's button read "Al keys". The key
   field is now in the app's monospace, where I and l differ, and the button says "Your keys" (the
   page is already titled AI coach). Inter's serifed-I option isn't in the bundled font, so a
   wider fix wasn't possible. Checked on the iPhone.

### Branch `design/settings-bodyweight` (26 Nov)
- Settings: the Bodyweight box was meant to be narrow, but the general `input[type=number] { width: 100% }` rule further down won, so the box took 92 px and pushed "Used for bodyweight exercises" onto two lines. The box's own rule now carries `[type]` and wins (72 px, its own padding), and the line reads "For bodyweight exercises". One line on the iPhone simulator.
- Settings: "For bodyweight exercises" was set heavier than every other row's description, because that row is a <label> and the app's label style is semibold. `.rowi .desc` now sets its own regular weight, so no wrapper can make a description heavy. Checked on the iPhone (light mode); 115/115 tests pass.

### Branch `design/settings-icons` (26 Nov)

- "Sign out of this device" drew a sign-in icon: the arrow went into the door. It now leaves it
  (the door on the left, the arrow pointing out).
- The clipboard icon (Bulk import, Spreadsheet export, the Log page's Paste button, the share page)
  had a 1px clip that didn't show at 18px, so it looked the same as the plan sheet beside it in
  Settings. It has a real clip now. Checked both on the iPhone.
- Stats, "Personal bests": its icon was the Stats tab's chart, twice on one screen. It is the medal
  now, the app's sign for a best everywhere else. Checked on the iPhone.
- Settings, Exercises: every row had the same dumbbell. The icon now says the kind, as the line
  under the name does: a dumbbell for weight and reps, a stopwatch (new "timer" icon) for timed, the
  bodyweight figure for bodyweight. It changes with the switches. Checked in the browser, with the
  demo user's Barbell Curl switched to Timed and back.

## fix/retrieve-placeholders (from improve/round-4)

- Retrieve writes "1, 1" (or "bw/4, 1") under an exercise with no history, for you to fill in.
  Logged unchanged, the offline app saved them as real 1 kg × 1 sets, and they turned up as
  personal bests (the demo had "Chest-Supported Machine High Row: 1 kg"). The old site's check
  (services/log_check.py) skipped them; the offline app didn't. Now the Log check marks such an
  exercise "Still Retrieve's 1, 1: fill in your sets, or it won't be saved" and saving leaves it
  out. It also catches the per-set form Retrieve writes for a plan's set count ("1 1, 1 1",
  "bw/4 bw/4, 1 1"), which the old exact-match list missed. New test; 116 pass. Checked on
  iPhone 18 Pro.
- Not done: the two placeholder logs already in the demo data stay; delete them from History
  if wanted.

- Log, status line: with only Retrieve's 1, 1 left to fill in, it reads "1 of 8 filled in" in amber instead of a red "1 exercise · 2 sets" that looked like an error. Real problems still turn it red. Checked on the phone.

- Log, check list: exercises still on Retrieve's 1, 1 show a quiet dash, "Left out when you save" and an amber "To fill in" tag, not a red ⓘ with a long warning each. The red list above it becomes one muted note ("7 exercises still have Retrieve's 1, 1…"); real errors stay red. Checked on the phone.

### Branch `improve/history-search` (from `improve/round-4`)

- All workouts, searching "curl": Back & Triceps matched, but its row read "Session 3 · Pull-Ups ·
  Incline EZ-Bar Sku…", cutting off the Barbell Curl it matched on. While searching, the exercises
  that match now come first in each row, in the ink colour (`mark.hit`), so every result shows
  why it is there. Checked on the iPhone and in the browser (no console errors).
- Also on the iPhone: Home (light mode) looks right; Week streak 15 checked against the dates
  (weeks run Monday to Sunday, and 9, 16 and 25 Nov fall in three weeks in a row).
- All workouts' "Select" sat about 6pt above "40 workouts logged." beside it (the header lined up
  box bottoms, and the button's padding lifted its text). A page head with a text button now
  lines up on the text baseline: both end at the same line (measured in the browser, seen on the
  iPhone). A search with no match shows a calm "Nothing matches …" card: fine as it is.

- All workouts search: a gold "Clear" now sits inside the box while it has text (the same on every
  browser; Safari's own small x is hidden), and the line under the title reads "14 of 40 workouts
  match." while searching. Clear empties the box, brings back the full list and keeps the
  keyboard up. Checked on the iPhone.

## improve/log-messages (26 Nov)

1. Log: typing an exercise and its sets with no title line first ("Back Squat", then "100 100, 5 5")
   made the exercise the workout's title and said only "Line 2: sets without an exercise name above
   them". It now says line 1 was read as the date and title and to put a title such as "Legs" first.
   Sets further down keep the plain message. New test; 116 tests pass. Checked on the iPhone.

### Branch `design/charts` (from `improve/round-4`)

- Chart end tags: the chart kept a fixed 54px on its right for the pill that labels the last point, enough for "+11%" but not "79.5 kg", which ran past the chart into the card's padding on a phone (the bodyweight chart). The right margin now grows with the tag (short tags keep 54px), so the pill ends inside the chart and lines up with the stat cards below. The narrower plot then dropped the middle date ("3 Oct"), so dates are now spaced at 100px instead of 110px and it's back. Checked on the iPhone in light mode, and on the computer (pill ends 4px inside the chart).
- Bodyweight stat tiles: the Range tile's "kg, low to high" wrapped onto two lines on a phone, so it stood taller than Now and Change. It reads "kg, low–high" now; all three tiles are one height. Checked on the iPhone (light).
- Serif numbers: Cormorant's default old-style "1" looks like a capital I, so the Stats headline "+11%" read "+II%". The headline and h1–h3 now use lining figures (font-variant-numeric: lining-nums); "+11%" reads plainly. Checked on the iPhone (light).
- Light mode: the charts' line and dots were --gold (#c9a961), which faded into the cream cards. A new --chart-line token keeps the gold in dark mode and uses a deeper gold (#a37b2c) in light mode, for the line, the dots and the guide. Checked on the iPhone in light mode; 115/115 tests pass.

## fix/stats-rounding (25 Nov)

1. Stats, Exercise card: the big number and the chart's end tag now agree. An estimated max showed
   "25 kg" above a chart tagged "25.3 kg"; both now say 25 kg. The Top weight view no longer rounds a
   real plate load: 107.5 kg showed as "108 kg" and now stays 107.5 kg, with the change ("↑ 27.5 kg")
   kept to the half kilo too. Checked with the demo data in the browser; 115 tests pass.
2. Charts: the end tag ("107.5 kg") ran into the card's right edge, since the chart kept a fixed
   54 px for it. The room on the right now grows with the tag's text. Checked on the iPhone, along
   with entry 1 (125 kg headline and tag agree; Back Squat top weight shows 107.5 kg).

### Branch `design/log-bar` (26 Nov)
- Log: the floating Save bar lay over the bottom of the text box, and the box's rounded edge showed through as a second outline. The bar now has a raised face, a gold-tinted rim and a shadow cast upward, so it reads as floating above what scrolls under it. Checked on the iPhone simulator.
- Light mode: the same upward shadow was a heavy grey smear and the raised face came out grey. Two tokens (`--bar-face`, `--bar-lift`) now give light mode a light face and a faint warm shade. Checked in both modes on the simulator.
- The plan page's Edit / Log / Copy bar and the plan-picker bar get the same raised face, gold rim and upward shade, so every floating bar in the app looks alike. Checked on the simulator.

- Log bar after Clear: "Cleared", Undo, Paste and Save stay on one row on a phone. The count's 160px minimum pushed the three buttons onto a second row; it now gives way down to 60px. Checked on the phone.
20. **Workout page: back arrow level with the buttons (branch `design/workout-head`).** The back
   arrow's usual 10px bottom margin, meant for pages where it sits over a title, lifted it 5px above
   the edit and share buttons in the workout header row. It is now centred with them. Checked on the
   iPhone; 115 tests pass.
21. **Workout page: action buttons fill each row on a phone (same branch).** "Edit · Repeat" wrapped
   onto a row with a gap after them, and "Copy as text · Share link" left a different gap below.
   Under 600px the labelled buttons now grow to fill their row; the trash button keeps its size.
   Checked on the iPhone with the demo data; 115 tests pass.

### Branch `design/workout-head`, more (26 Nov)

- Workout page: the Share icon was 15px beside Edit's 18px. Icons size to the text, and a `<button>`
  (Share) has a smaller font than a link (Edit). Icon buttons now draw their icon at 18px, so both
  match. Measured in the browser (Edit 18, Share 18); no other page shows these buttons apart from the
  coach's reply row (34px buttons). Checked on the iPhone: equal, and level with the back arrow.
- The line under the title (date · exercises · sets · kg lifted · bodyweight) keeps each item whole
  when it wraps. On the iPhone "3,693 kg" ended one line and "lifted" started the next. A wrapped
  line also no longer starts with a "·" (each item's dot is clipped when it starts a line). Checked
  on the iPhone: "Wed 25 Nov 2026 · 10 exercises · 25 sets" then "3,693 kg lifted · bodyweight 79.5 kg".

## Waiting list

Tasks skipped because something they need isn't there yet. Each says what it waits on; the work
moved on to something else meanwhile.

- ~~**iPhone checks**~~ **Done 25 Nov** (the last one, the gold "a new best" note after saving, was checked on the iPhone in dark mode: Pull-Ups 9 reps gave "Saved · a new best" and a 🥇 +8.3% chip; nothing to change. The colour medal emoji stays on purpose: gold/silver/bronze say which set beat the best). Original note: (waits on: the iOS Simulator working again). Everything in round 4 was checked
  on a computer only. To see on an iPhone: the charts' red stretch under the start line and the
  guide line, the gold "a new best" note after saving, the "SESSION 2" kicker on a workout, timed
  exercises' bests and charts, the exercise card's big number, the trash button at the end of a
  workout's action row (it wraps with the others on a narrow screen), the Retrieve rows on two
  columns, the Consistency year grid (should scroll sideways at 12px squares, as before), and
  tapping a chart (the box should move to the tapped point; tapping the box opens the workout).
- **iPhone check of `improve/keyboard-parity`** (waits on: the iOS Simulator): the keyboard's
  "Search" key should close the keyboard in All workouts, Exercises and Retrieve; in the coach
  box, return should add a line; a workout's "i" notes should close on a tap elsewhere.

- **Merging this branch: keep the light-mode bar tokens** (waits on: the merge). The light theme
  sets `--bar-face` and `--bar-lift` on the line after `--gold-fill`, in both the
  `prefers-color-scheme: light` block and `[data-theme="light"]`. Branches that change `--gold-fill`
  (it gained `border-box` elsewhere) conflict on that spot; an automatic "theirs" merge dropped
  both lines in the all-branches preview, and light mode got the dark mode's black 50% shade over
  the editor again. Keep the two lines when resolving.

- **Estimated max of a single rep** (waits on: your call, since it moves every number). Epley,
  weight × (1 + reps / 30), is used for every set, single reps too, so a 1-rep set scores 3.3% above
  its own weight: Hyper Extension BW × 1 at 79.5 kg shows a best of 82 kg. The usual fix is to score
  a 1-rep set as its weight. It isn't done because the same formula is in web/core/scoring.js,
  web/core/coach_tools.js and the Flask services (helpers.py, parsing.py, workout_quality.py,
  coach_tools.py), and the tests check the two sides agree: changing it shifts estimated maxes,
  medals and charts for every past single, on both sides at once. The Personal bests row now says
  "with BW" under such numbers (design/bests-with-bw), which explains the bodyweight but not the 3%.

## Next when resumed

- Your "Suggestions/Workout Logger/To Be Done" list, section 7 ("Small leftovers"), is already
  built in this app: unlogged plan exercises in Settings > Exercises, the session name before the
  exercises in History, and row numbers with "3 sets" on the Log check. Idea 8 (darker gold links in
  light mode) is also in. Those lines can move to "Done".

## Ideas not done yet

### Branch `design/edit-page` (from improve/round-4)

- **Edit workout on a phone: the title was cut off.** Title and date shared one row, the date taking
  150px, so "Session 2 - Shoulders & Forearms" showed as "Session 2 - Shoulders &". Up to 480px wide
  the title now has the whole line and the date sits under it, with the same 18px between them as
  between other fields. Wider screens keep the two side by side. Checked on the iPhone 18 Pro
  simulator; 115 tests pass.
### Branch `fix/edit-check` (from improve/round-4)

- **Edit workout's Check list wrote sets its own way.** A plank showed as "0×60 · 0×45" and a
  bodyweight set had no "BW". It now uses the same set text as the Log page and the workout page
  (`BW×60s`), and shows the Log page's name notes with "Use it" for a close misspelling of a known
  name.
- Showing those notes showed a second bug: every row said "Already in that day's workout", because
  the check compared the workout with itself. `lb.check()` takes `replaceDay`, and Edit passes the
  day it is editing. Test added (116 pass); checked on the iPhone 18 Pro simulator.
- Limit: a misspelling that is already saved in your history ("Lateral Raize" in the demo data)
  counts as a known name, so Edit doesn't flag it. Rename it in Settings → Exercises to fix it
  everywhere.
## fix/exercise-label (from improve/round-4)
- Stats lists named an exercise typed two ways by whichever spelling sorted first, so Personal bests said "Pull Ups" while workouts say "Pull-Ups". Now the spelling used most recently names it (list still A–Z). New test; 116 pass. Checked on the iPhone.
### Branch `fix/log-sets-typo` (from improve/round-4)

- **A typo in a sets line saved a junk exercise.** "Hyper Extension" followed by "Be/4 be/4, 1 1" (iOS had turned "bw" into "Be") was read as two exercises: Hyper Extension with "no sets under it", and a new exercise called "Be/4 Be/4" with sets 1 1, which Save kept. Now that line counts as Hyper Extension's sets: the error reads `"Hyper Extension": couldn't read its sets ("Be/4 be/4, 1 1").`, the count leaves it out, and nothing is saved under the typo's name. A name with truly nothing under it still says "no sets under it". Test added (116 pass); checked on the iPhone 18 Pro simulator.
## Page not found (branch `fix/unknown-route`)
- A link to a page Liftbook doesn't have (old bookmark, typo) used to quietly show Home, as if it had worked.
- It now shows "Page not found" with a "Go to Home" button, in the same style as "Workout not found". No tab is highlighted.
- Checked on the iPhone 18 Pro simulator (#/nope, then the button back to Home).
## improve/bests-jump (from improve/round-4)
- Opening an exercise from Personal bests (or a workout's Full progress) centred the exercise picker, leaving the chart half off a phone screen. Now the Exercise card's top lands under the header, so picker, headline and chart are all in view. Checked on the iPhone.
## improve/home-stat-links (from improve/round-4)
- Home: the three number tiles now open where the number comes from: Workouts → All workouts, Week streak → Stats, Exercises → Personal bests (same 22). Gold border on hover, gold tint on tap. Checked on the iPhone.
- Settings → Exercises: every row said "Weight and reps" under the name, which hid the few that are
  timed or have bodyweight added. Now only those say what they are ("Timed", "Bodyweight added");
  plain lifts show just the name, and the list is shorter to scroll. Checked on the iPhone.
- Settings → Exercises read only the saved timed choice, so Plank (timed by the built-in list, and
  logged in seconds) showed its Timed switch off and no "Timed" line. Before the change above it even
  said "Weight and reps". New `lb.timedOn(name)` uses the same rule as logging (your choice, the
  built-in list, or times in its logs), as `bodyweightOn` already did for bodyweight. Plank now says
  "Timed" with its switch on. Test added (116 pass); checked on the iPhone.
- Profile: Name, Username and Bodyweight sat with each box right on the next field's label. A rule
  for a lone field in a card (`.group > .blk .field { margin: 0 }`) also removed the space between
  stacked fields. Neighbouring fields in a card now have 16px between them; a card with one field
  is unchanged. Checked on the iPhone.
## design/exercise-headline (from improve/round-4)
- Stats → Exercise: the big headline rounded to whole kilos ("82 kg") while the chart's tag for the same session said "82.2 kg". Now both say 82.2 kg; volume stays whole. Checked on the iPhone.
- The Best tile under the chart rounded to whole kilos too ("82 kg"); now 82.2 kg like the headline and chart tag. Checked on the iPhone.
## design/settings-align (from improve/round-4)
- Settings → Preferences: the Appearance icon now sits in the same 22px column as the row icons, so "Appearance" lines up with "Bodyweight" (it was 4px left) and its moon is the same 20px size. Checked on the iPhone.
- Settings → Preferences: the Bodyweight note "Used for bodyweight exercises" was bold, because the row text is a <label> and took the form-label weight; it is plain now like every other row note. Checked on the iPhone with the demo data; 115 tests pass.
## Even line breaks (branch `design/text-wrap`)
- Headings use `text-wrap: balance`; paragraphs, row descriptions and muted notes use `text-wrap: pretty`.
- No more single short word alone on the last line (Apple Shortcuts: "…paste your key when asked" used to leave "it" by itself).
- Checked on the iPhone 18 Pro simulator. Browsers without support just wrap as before.
- Note: the mock server on 8791 stopped answering the phone (white page; it still answers curl). A second copy runs on 8793 for phone checks.

- Workout page meta line: each item ("3,693 kg lifted", "bodyweight 79.5 kg") now stays whole on a phone; when the line wraps, the dot ends the line above. Checked on the iPhone.
- Older/newer workout links under a workout: a lone link (newest or oldest workout) now takes the whole row instead of half, and long names wrap to two lines before being cut ("Shoulders & For…" → "Shoulders & Forearms"). Checked on the iPhone.
- Sync and data: the backup line said "22 exercises" while Settings → Exercises lists 65 (that list
  also has the lifts only in your plan). The 22 are the different lifts you have logged, so it now
  says "22 different lifts", the words Home uses for the same count. Checked on the iPhone.
- Apple Shortcuts: step 2 told you to "Open this page on your iPhone" even when you already had. On
  an iPhone or iPad (an iPad that reports itself as a Mac counts, by its touch screen) it now just
  says "Tap a shortcut to add it, and paste your key when asked."; a computer keeps the full
  sentence. Checked on the iPhone.
## Stats range row on a phone (branch `design/stats-consistency`)
- The 1M…All (and year) row under the Stats chart sat at the right, while on a phone the Strength / Rate / Consistency tabs wrap under the heading at the left: two rows of pills that didn't line up.
- On screens up to 560px wide it now starts at the left, in line with the tabs and the big number; wider screens keep it at the right. The inline style became a `range-row` class.
- Checked on the iPhone 18 Pro simulator and at 1024px on the Mac.

## Muscle balance numbers (branch `design/stats-consistency`)
- The sets-a-week column mixed "6" and "9" with "2.9" and "10.6". When any row has tenths, every row now shows one decimal ("6.0", "2.9"), so the figures line up.
- The "sets a week" note sits on the heading's baseline instead of floating above it.
- Checked on the iPhone 18 Pro simulator.

## Bodyweight Range tile (branch `design/stats-consistency`)
- The Range tile's note "kg, low to high" wrapped to two lines on a phone, making it taller than Now and Change. It now says "kg" (the label already says Range), so the three tiles match.
- Checked on the iPhone 18 Pro simulator.
## design/bests-count-align (26 Nov)

1. Personal bests: the "22 exercises" count sat about 9pt above the middle of the Latest / Highest / A to Z pills, because `.foot` kept its own 14px bottom margin inside the header row. `.card-head .foot { margin: 0; }` centres it and lines its left edge up with the search box and list. The same rule fixes "sets a week" beside the Muscle balance heading. Checked on the iPhone 18 Pro simulator.
## design/exercise-icons (26 Nov)

1. Settings → Exercises: every row had the same dumbbell icon, even "Crunches A — Bodyweight added". Timed exercises now show a stopwatch (a new `timer` icon in web/app/ui.js), bodyweight ones the standing figure Settings uses for Bodyweight, and the rest keep the dumbbell. Switching Timed or Bodyweight on a row changes its icon at once. Checked on the iPhone 18 Pro simulator: Crunches A (figure), Rope Crunches (dumbbell), and Plank switched to Timed and back on the mock demo user (stopwatch, then dumbbell; left as it was).
## design/gold-edge (26 Nov)

1. Gold fills (chosen tab pills such as Latest / Highest / A to Z, primary buttons, the chosen weekday dot) had a faint pale rim on their left and top edges: the border is transparent, the gradient was painted inside the padding and tiled under the border, so its light far end showed in the border strip. `--gold-fill` (all three themes) now paints at `border-box`. Same flaw and fix as Muhurta's design/gold-edge. Checked on the iPhone 18 Pro simulator (Personal bests).
## design/plan-label (26 Nov)

1. Workout plan: the "Plan" label (the one with the Format link beside it) showed in small sentence case, while "REP RANGES" below it showed as an uppercase section label. ui.js wraps a label's leading words in `<span role="heading">` when the label also holds a link, and the broad `.label span` rule (meant for counts like "1 workout") then un-capitalised it. A new rule, `.label > span[role="heading"]`, gives that span the label's own look back. Checked on the iPhone 18 Pro simulator. On Home, Stats, Retrieve, Settings, Sync and data, Shortcuts, Personal bests and Log no label gets such a span, so they don't change.
## design/signout-icon (26 Nov)

1. "Sign out of this device" in Settings used an arrow pointing into a door frame on the right, the usual sign-in symbol. The `logout` icon in web/app/ui.js is mirrored: frame on the left, arrow leaving it. Only that row uses the icon. Checked on the iPhone 18 Pro simulator in dark mode.
## fix/sync-status (26 Nov)

1. Sync and data: the status title said "Up to date" whenever sync wasn't running and had no error, even with changes still waiting to upload. It now says "Changes waiting to upload" then. The line under it dropped "· 0 changes waiting to upload" when nothing waits (it only made the line wrap); with changes waiting it still shows "· N changes waiting to upload". Checked on the iPhone 18 Pro simulator with nothing waiting. Not seen with changes waiting (the mock syncs straight away).
## improve/account-subtitle (26 Nov)

1. The Account page's subtitle said "Password, theme, sign out, delete". The page opens with an Email card, and its theme card is headed "Appearance", so the subtitle now reads "Email, password, appearance, sign out, delete" (fits one line on the iPhone 18 Pro). The Settings row that opens it already started with "Email".
## improve/coach-no-key (26 Nov)

1. AI coach with no key turned on: the question box was hidden, but the six suggested questions still showed, and each tap only failed. The "AI keys" button did nothing either, since the key card was already showing. A new `canAsk(on)` in web/app/screens/coach.js now shows or hides the question box, the suggested questions and the "AI keys" button together, so the screen shows only the key card and Earlier answers until a key is on. Checked on the iPhone 18 Pro simulator with no key. Not checked with a key on, because the mock's coach bridge isn't running; that path calls the same `canAsk(true)`.
## improve/csv-dates (26 Nov)

1. Sync and data: the From / To dates sit under both Backup file and Spreadsheet, but only the spreadsheet uses them. The hint "Leave the dates empty for all of it." is now "Spreadsheet only. Leave empty for everything." (one line on the iPhone 18 Pro). Checked on the simulator.
## improve/delete-confirm (26 Nov)

1. Delete my account: the confirm box had the username as its placeholder, so it read "demo" in grey, which looks already typed, and the faded Delete button then seemed broken. The placeholder is gone; the label above still says which username to type. Checked on the iPhone 18 Pro simulator. Nothing was typed in or deleted.
## improve/exercise-counts (26 Nov)

1. Settings → Exercises: each row said "12 logged" without saying 12 of what. The number counts the workouts that include the exercise, which Stats calls "Sessions", so the rows now say "12 sessions" ("1 session" for one). Checked on the iPhone 18 Pro simulator.
- Log parser: "120, 10x" reads as 3 sets of 120 × 1 (the trailing "x" makes 10 drop to 1), where
  "120, 10" reads as 120 × 10. Seen 26 Nov. Checked: the Python parser on main reads it the same
  way (and "120, 10x 8x" as 10 × 8 in both), so this is how Liftbook has always read it. Changing it
  means changing both parsers and their tests; your call. (A short list filling up to 3 sets is on purpose.)

## Merge of the run's branches (26 Nov, approved by you)

All 84 topic branches of this run are now merged into `improve/round-4` (never `main`; every
branch is kept). Left out as older work: `claude/workouts-per-week-stat-ultwmn`,
`harsh024/redesign-work`, `harsh024/affectionate-brown-l39qhv`, `feature/reminders`, `feature/widget`.
Many conflicts were two branches making the same fix; there the base's version stayed. Where they differed:
- design/plan-page: Copied button kept plan-page's soft green over the solid green
- design/log-check: check headline combines both: whole-word spans and 'also on this day' (log-check) with no 'Workout' when joining a day and errors only once a second line is typed (base)
- design/log-help: same job as design/log-guide; kept log-guide's neutral chips (gold reads as 'chosen' here), dropped the .howto rule
- design/workout-page: meta line kept the base's simpler fix (dot ends the line above) over the clip-path one
- design/stats-tiles: bodyweight chart keeps the hover tip and gets bare axis numbers
- design/home: Home totals stay links and gain their caption lines; avatar initial in Inter (old site); Bests empty state kept with the base's search matcher
- design/home-all-time: totals under their own 'Overall' label, still links with caption lines
- fix/retrieve-placeholders: combined with the log-check work (placeholders quiet, real problems red, 'also on this day')
- improve/history-search: Clear button and match count kept; the base's exerciseLine highlight kept over its own exerciseList
- fix/stats-rounding: its rounding (places) for the exercise headline and end tag
- improve/log-messages + fix/first-line-exercise: a lone first line over sets is now read as the
  exercise, so the test for the "Line 1 is read as the title" message now checks that instead.
- `web/sw.js` was rebuilt once at the end.
Tests: 127 of 127 pass. Checked on the iPhone 18 Pro simulator: Home (avatar, Recent, See all,
Overall tiles), Log check (typo in red, Retrieve's 1, 1 as a quiet note, "also on this day"),
Settings and Stats (headline and end tag agree, tile lines).

## fix/log-typo-row (26 Nov)

1. Log's check list: a sets line with a typo under an exercise ("Hyper Extension" then "be/4, 12")
   was already reported right in the red box, but the list showed two rows: "Hyper Extension · No
   sets under it" and "Be/4 · No sets under it". Now there is one row, "Hyper Extension ·
   Couldn't read "Be/4, 12"", and the typo line gets no row of its own. Test added; 127 pass.
   Checked on the iPhone 18 Pro simulator. Merged back into `improve/round-4` once checked.

## design/plan-targets (26 Nov)

1. A Retrieve plan page's right-hand column said "10–20 reps" on one row, "2 sets" on the next and
   nothing on others: only a "[2]" in the plan was ever shown, while every other line quietly
   meant 3 sets (as the "20 sets" in the header counts them). Now every row says its sets:
   "3 sets", "2 sets", or "3 × 10–20" with a rep range. Only the page's display changed; the
   Retrieve text and its match with the old Python site are as before. 127 tests pass. Checked on
   the iPhone 18 Pro simulator (Session 4 · Legs). Merged back into `improve/round-4`.

## design/gold-card (26 Nov)

- Highlighted cards (`.card.gold`, `.group.gold`: Home's "Up next", the coach's keys card) had a
  hard 4px ring outside their gold border, which read as a second outline on the dark theme.
  Now: one gold edge, a faint gold wash from the top-left corner, and a soft gold glow.
- Checked on the iPhone 18 Pro simulator (demo user, http://127.0.0.1:8794/). sw.js rebuilt,
  127/127 tests pass, `git diff --check` clean.

## design/stat-numbers (26 Nov)

- Home's three totals (Workouts, Week streak, Exercises) now look like the old site's
  `.stat-value`: large Cormorant Garamond figures in a gold gradient (dark: #d4af37 → #f4d03f;
  light: a deeper #8a6512 → #b08a2e so they stay readable on cream), matching the serif "+10%"
  on Stats. New token `--num-grad`.
- Only Home: the Stats tiles hold words and units ("Wednesday", "34.8 kg") that would overflow
  at that size, so they keep the smaller face.
- Checked on the iPhone 18 Pro simulator (demo user): Home totals and the Stats tiles. sw.js
  rebuilt, 127/127 tests pass, `git diff --check` clean.

## design/serif-counts (26 Nov)

- A workout's summary counts (New best · Improving · Dipping · Steady) and the share card's
  counts (Exercises · Sets · New bests) now use the serif display face at 1.85rem, in their
  existing colours, so they match the workout's serif title, Home's totals and the Stats
  headline. They are always whole counts, so the larger face fits the four columns.
- Looked over Retrieve, Log, Home and a workout in dark and light mode on the iPhone 18 Pro
  simulator (demo user); nothing else stood out. sw.js rebuilt, 127/127 tests pass,
  `git diff --check` clean.

## design/history-list (26 Nov)

- All workouts: each row's day number (25, 16, 9…) is now a serif figure, like the page title,
  Home's totals and a workout's counts, with the weekday under it as before.
- The first month label ("November 2026") sat 8px under the search field, because the first
  section drops its top margin. A list right under a search now starts 24px down.
- Checked on the iPhone 18 Pro simulator (demo user). sw.js rebuilt, 127/127 tests pass,
  `git diff --check` clean.

## design/retrieve-tiles (26 Nov)
- Retrieve's session names now use the serif (Cormorant), like the page titles and the old
  site's headings, instead of small sans text. Long names wrap to two lines, which reads fine.
- The "Next" tile lost its hard 2px gold bar along the top (it sat on the tile above). It is now
  a soft gold wash like the gold cards. A 1px gold outline was tried, but it ran square over the
  group's rounded corner, so it was dropped.
- Checked on the iPhone simulator; sw.js rebuilt; tests 127/127.

## design/up-next-serif (26 Nov)
- Home's "Up next" card names the session in the serif ("Legs"), as the Retrieve tiles now do,
  so the next session reads the same on both pages. Only that row (cls next-row); other list rows
  keep Inter.
- Also looked over Retrieve (light), a plan page and Stats (light): no change needed. The search
  box's darker border is the 3:1 field line on purpose; the avatar initial stays Inter on purpose.
- Checked on the iPhone simulator (light); sw.js rebuilt; tests 127/127.

## design/log-start-gold (26 Nov)
- Log's "Start from Session 4 · Legs" card is the same suggestion as Home's "Up next", but it
  was a plain grey card. It now uses the gold card (gold edge, soft wash and glow) so the next
  session looks the same wherever it is offered.
- Checked on the iPhone simulator (dark); sw.js rebuilt; tests 127/127.

## design/profile-name-serif (26 Nov)
- Settings' profile card shows your name in the serif (1.45rem), as Home's greeting does, so
  the name reads the same on both pages; @username and email stay in Inter.
- Checked on the iPhone simulator (dark); sw.js rebuilt; tests 127/127.

## design/bests-tiles (26 Nov)
- Personal bests' three tiles (Exercises, New bests, Latest best) hold short figures, so they now
  use the serif like Home's totals (class bests-stats; colours unchanged, New bests stays gold).
  The main Stats tiles keep Inter: they hold words like "Wednesday".
- Checked on the iPhone simulator (dark): "25 Nov" fits its tile. sw.js rebuilt; tests 127/127.

## design/workout-steps-serif (26 Nov)
- The older / newer links at the foot of a workout ("← Push, 9 Nov" and "Back & Triceps,
  25 Nov →") name the session in the serif, as Retrieve, Home's Up next and the page title do.
  Still clamped to two lines; dates stay Inter.
- Also reviewed the 25 Nov workout page top to bottom on the phone: no other change needed.
- Checked on the iPhone simulator (dark); sw.js rebuilt; tests 127/127.

## improve/coach-back (26 Nov)
- The AI coach page had no way back on a phone, while Settings (the other header button) has a
  back arrow. The coach now uses the shared pageHead with a back link to Home; its "New chat" and
  "Your keys" buttons stay on the right (as the heading's aside).
- Checked on the iPhone simulator (dark): arrow shows, tap goes Home. sw.js rebuilt; tests 127/127.

## design/workout-list-serif (26 Nov)
- Home's "Recent" list and All workouts now name each session in the serif (class w-row, 1.2rem),
  matching the serif day numbers beside them in All workouts and the session names on Retrieve,
  Up next, the workout page and its older/newer links. Session label and exercise line stay Inter.
  Select mode keeps the same rows (the class is on the button too).
- Checked All workouts on the iPhone simulator (dark). sw.js rebuilt; tests 127/127.

## design/bests-with-bw
- Personal bests showed "82 kg" beside "Top set BW × 1" for Hyper Extension, which read as an 82 kg load. The estimated max of a bodyweight set counts the bodyweight (as Stats does), so the row now says so: a small "with BW" under the number, above the date.
- core/bests.js: rows get withBw (the best set had a bodyweight offset). New test in core/test/bests.test.js.
- Also checked this round: Liftbook's text fields are already 16px on phones (no iOS zoom, unlike payment-tracker had); the Stats chart curve can't overshoot its points.
- sw.js rebuilt; npm test 128 pass. Checked on the iPhone.

## design/title-ampersand
- Retrieve's session tiles broke "Shoulders & Forearms" as "Shoulders &" / "Forearms", leaving the ampersand hanging at the line's end. A no-break space after "&" now carries it down with the next word: "Shoulders" / "& Forearms". One-line titles are unchanged.
- Also looked at this round: Log (Save dimmed while empty, today's date in the example) and the rest of Retrieve; nothing else to change.
- sw.js rebuilt; npm test 128 pass. Checked on the iPhone.

## improve/waiting-single-rep
- Workout page check (Back & Triceps, 25 Nov) and Settings on the iPhone: nothing to change; the
  "vs best" column's "−52%" already uses a true minus.
- Found that a 1-rep set's estimated max is 3.3% over its weight (Epley at reps = 1). Put on the
  Waiting list rather than changed: the formula is shared with the Flask services and every past
  number would move.

## design/coach-earlier-answers (27 Nov)
- Coach → "Earlier answers": the card's title was plain sans while every other card title is serif, and the questions under it were as large as the title.
- The title now uses the serif card-title style; questions are 0.95rem, and the open question turns gold so you can see which answer you're reading.
- Checked on the iPhone (closed and open). npm test 128 pass.

## design/settings-account-row (27 Nov)
- Settings: the ACCOUNT section's first row was titled "Account" too, which said nothing.
- The row and its page are now "Email and password". The row's line reads "Change them, sign out, delete the account". The page's line no longer lists "appearance" first, and it says "sign out" (that button signs out of this device only).
- Checked on the iPhone (the row and the page). npm test 128 pass.

## design/workout-rows-even (27 Nov)
- Home → Recent (and All workouts): a workout with no session line ("Push") made a shorter row than its neighbours (about 62 vs 72 px).
- Workout rows now share a 72px minimum height, so the list reads as even rows.
- Checked on the iPhone (Back & Triceps, Shoulders & Forearms, Push all the same height). npm test 128 pass.

## design/plan-meta-case (27 Nov)
- Retrieve → a session's plan: the line under the title read "8 exercises · 20 sets · Bodyweight 79.5 kg", with a capital B mid-line. The workout page writes the same thing as "· bodyweight 79.5 kg".
- The plan line now uses "bodyweight" in lower case, like the workout page.
- Looked at, left alone: the 🥇🥈🥉 medals on a workout's "vs best" pill are colour emoji among line icons, but each tier has its own meaning (explained in the help), so they stay.
- Checked on the iPhone (Session 4 · Legs). npm test 128 pass.

## fix/short-page-footer (27 Nov)
- On a short page (Page not found, and any page shorter than the screen), the footer's "© 2026 Liftbook" was hidden under the tab bar on the iPhone: only its gold line showed.
- The cause: the page's minimum height was 100vh, which in Safari counts the toolbar's hidden height too. It now uses 100dvh (the visible height), with 100vh kept as a fallback.
- Checked on the iPhone (Page not found: footer fully above the tab bar). npm test 128 pass.

### design/appearance-icon-follows
- Settings → Appearance: the row's icon was always a moon, even with Light or Auto picked. It now shows the chosen theme's icon (moon, sun or monitor) and changes when you pick another.
- Light mode checked on the iPhone (Home, Stats, chart, Settings): reads well. The darker search-box border is kept on purpose (3:1 contrast for boxes you type into).
- Checks: diff --check, marker grep, sw.js rebuilt, npm test 128 pass.

### design/tabbar-fade
- Log: in the thin gap between the floating Save bar and the tab bar, the workout text showed
  through sliced in half (a stray "1, 1" cut by the tab bar's top edge). The tab bar now has a
  16px fade above it in its own colour, so text scrolling into it fades out. The same softer
  edge applies on every page. The floating bar itself stays as designed on 26 Nov.
- The "1, 1" rows in "Start from Session 4 · Legs" are right for the demo: it has never logged
  those Legs exercises, so there are no last numbers to fill in.
- Seen again: after the keyboard closes, Safari leaves the Save bar higher for a moment; one scroll
  puts it back (noted before, Safari's viewport, not the app).
- Checked on the iPhone in dark mode. Checks: diff --check, marker grep, sw.js rebuilt, npm test 128 pass.

### design/plan-dock-labels
- A plan page's floating bar (Edit · Share · Log · Copy) showed Share and Log as bare icons on
  phones. The share arrow is well known; a bare ⊕ doesn't say "open this on the Log page". On
  screens up to 430px the Log button now keeps its word and only Share falls back to its icon;
  below 380px both are icons as before (each keeps its name for screen readers).
- Tried showing both words first: on the 402pt iPhone Copy then touched the bar's edge, so Share
  stays an icon.
- Checked on the iPhone 18 Pro (402pt): Edit, share icon, "⊕ Log", Copy fit with even padding.
  Not checked on a 380-400pt screen; by the widths measured it should fit.
- Checks: diff --check, marker grep, sw.js rebuilt, npm test 128 pass.
