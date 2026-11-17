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
    Test added. Checked on desktop.

## Next when resumed

## Ideas not done yet
