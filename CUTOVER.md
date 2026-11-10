# Switching app.liftbook.in to the new app

The new app (`web/`, Supabase project `qjlmxlnmfowqsunpzvac`) runs at https://beta.liftbook.in
until the switch. The old Flask app (Render/Railway, Neon) keeps running until the last step.
Do these in order, in one sitting. Nothing here has been done yet.

## Already set up (before the switch)

- `web/` deploys to Cloudflare Pages from the `rewrite/offline-app` branch (beta.liftbook.in).
- Supabase Auth sends email through Resend from a liftbook.in address; templates are in
  `supabase/templates/` (see its README).
- Edge Functions deployed: `coach`, `shortcut`, `share` (shared pages and link previews) and
  `signin` (sign in with a username). Link previews are `web/_worker.js`, which Pages runs for
  `/s/*` only.
- Supabase Auth's Site URL is https://beta.liftbook.in; app.liftbook.in is already an allowed
  redirect URL.

## The switch

1. **Tell people.** Say when it happens, and that they'll need to add their Apple Shortcuts again.
   Ask them not to log in the old app during the switch.

2. **Copy the data one last time.** From the repo root on the Mac (settings in
   `~/.liftbook-import.env`):

       .venv/bin/python scripts/import_to_supabase.py --dry-run
       .venv/bin/python scripts/import_to_supabase.py

   This run also moves old undated workouts from the old server's UTC time to India time, so a
   workout saved at 1:30 am lands on the right day (the dry run says how many move).
   After this, never run the import again: it would undo changes people make in the new app.

3. **Copy the profile photos again** (it only copies what's new or changed):

       .venv/bin/python scripts/copy_photos_to_supabase.py --dry-run
       .venv/bin/python scripts/copy_photos_to_supabase.py

4. **Point app.liftbook.in at the new app.**
   - Cloudflare Pages > the Liftbook project > Custom domains > add `app.liftbook.in`.
   - At GoDaddy (DNS for liftbook.in), change the `app` CNAME from
     `workout-tracker-62qi.onrender.com` to the Pages address (`<project>.pages.dev`).
   - Wait until https://app.liftbook.in opens the new app (sign-in page with "Liftbook").

5. **Tell Supabase the new address:**
   - `supabase/config.toml`: set `site_url = "https://app.liftbook.in"`, then
     `supabase config push --project-ref qjlmxlnmfowqsunpzvac`.
   - `supabase secrets set LIFTBOOK_APP_URL=https://app.liftbook.in/ --project-ref qjlmxlnmfowqsunpzvac`
   - `web/config.js`: set `WEB_APP_URL = 'https://app.liftbook.in/'` (where the Android app's
     emailed links and share links point), then rebuild the Android app.
   - Keep beta.liftbook.in on the same Pages project, so share links made during the beta
     (`beta.liftbook.in/s/...`) keep working.

6. **Shortcuts.** Tell everyone to open Settings > Apple Shortcuts in the new app, make their
   Shortcut key, and add both shortcuts again (the old ones call the old servers). Details:
   `supabase/functions/README.md`.

7. **Backups.** Change `.github/workflows/nightly-backup.yml` so each night it:
   - dumps the Supabase database (`pg_dump` of `SUPABASE_DB_URL`, the direct connection);
   - uploads the dump to the same Google Drive folder as now;
   - restores it into Neon, so Neon stays a standby copy.
   Add the Supabase URL as a GitHub secret first, then run the workflow by hand once and check
   the Drive file and Neon.

8. **Watch for a few days.** Sign-ups, password resets and the coach; Supabase's Logs page.

9. **Retire the old servers** (only when the new app has run well for a while):
   - Railway: first check its Postgres and any volume for data that isn't in Neon (an older
     database or uploaded photos). Download anything there before deleting.
   - Then delete the Railway and Render services.

10. **Merge `rewrite/offline-app` into `main`.** The GitHub Pages site (`site/`, the public home
    and privacy pages) deploys from `main`; check it still works after the merge. Cloudflare
    Pages can then deploy from `main` instead (Settings > Builds > Production branch).

11. **Delete the import settings file**, which holds database passwords and keys:

        rm ~/.liftbook-import.env
